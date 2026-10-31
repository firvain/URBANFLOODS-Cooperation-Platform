"""Increment 5a: full-text search across blog posts and forum threads (``GET /search/``).

Every test tags its rows with a fresh nonsense token (``_token()``) and searches for it, so rows
committed by other tests never leak into exact assertions. Posts live in a blog category and
threads in a forum category, both registered with ``cleanup_forum_categories`` (threads go
first, then posts and the categories through ``cleanup_categories``).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from app.core import rate_limit
from app.core.config import settings
from app.crud.user import anonymise_user
from app.db.enums import CategoryKind, ContentStatus
from app.db.models import Category, Post, Thread, User
from tests.factories import (
    create_admin,
    create_category,
    create_post,
    create_thread,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
SEARCH = f"{API}/search/"

ITEM_FIELDS = {
    "type",
    "id",
    "slug",
    "title",
    "snippet",
    "locale",
    "author",
    "category",
    "published_at",
    "rank",
}
HIDDEN_STATUSES = (ContentStatus.PENDING, ContentStatus.HIDDEN, ContentStatus.DELETED)


# --- helpers ----------------------------------------------------------------------------------


@pytest.fixture
def limits(monkeypatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    rate_limit.reset()
    yield
    rate_limit.reset()


def _token() -> str:
    """A word no other row contains (letters first, so Postgres parses it as one word)."""
    return f"zq{uuid.uuid4().hex[:10]}"


async def _committed(db, cleanup_users, factory=create_verified_user, **kwargs) -> User:
    user = await factory(db, **kwargs)
    cleanup_users.add(user.email)
    await db.commit()
    return user


async def _categories(db, cleanup: set[int]) -> tuple[Category, Category]:
    blog = await create_category(db, kind=CategoryKind.BLOG)
    forum = await create_category(db, kind=CategoryKind.FORUM)
    cleanup.update({blog.id, forum.id})
    await db.commit()
    return blog, forum


async def _post(db, category: Category, *, body: str | None = None, **kwargs) -> Post:
    post = await create_post(db, category_id=category.id, **kwargs)
    if body is not None:
        post.body_html = f"<p>{body}</p>"
        post.body_text = body
    await db.commit()
    return post


async def _thread(db, category: Category, *, body: str | None = None, **kwargs) -> Thread:
    thread = await create_thread(db, category_id=category.id, body_text=body, **kwargs)
    if body is not None:
        thread.body_text = body
    await db.commit()
    return thread


async def _search(client, q: str, **params):
    response = await client.get(SEARCH, params={"q": q, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _keys(data: dict) -> list[tuple[str, int]]:
    return [(item["type"], item["id"]) for item in data["items"]]


def _assert_field(response, field: str) -> None:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "validation.failed"
    assert f"query.{field}" in detail["fields"], detail["fields"]


# --- matching and ranking ---------------------------------------------------------------------


async def test_title_hit_ranks_above_body_only_hit(client, db_session, cleanup_forum_categories):
    blog, _ = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    in_body = await _post(db_session, blog, title="Rainwater harvesting", body=f"About {tok}.")
    in_title = await _post(db_session, blog, title=f"Guide to {tok}", body="Nothing here.")

    data = await _search(client, tok)

    assert _keys(data) == [("post", in_title.id), ("post", in_body.id)]
    assert data["items"][0]["rank"] > data["items"][1]["rank"]


async def test_title_hit_ranks_above_body_hit_for_threads(
    client, db_session, cleanup_forum_categories
):
    _, forum = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    in_body = await _thread(db_session, forum, title="Pond sizing", body=f"Ask about {tok} here")
    in_title = await _thread(db_session, forum, title=f"Sizing {tok}", body="Plain words only")

    data = await _search(client, tok, type="threads")

    assert _keys(data) == [("thread", in_title.id), ("thread", in_body.id)]


async def test_stemming_flooding_finds_floods(client, db_session, cleanup_forum_categories):
    blog, forum = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    post = await _post(db_session, blog, title=f"Post {tok}", body="Floods hit the old town.")
    thread = await _thread(db_session, forum, title=f"Thread {tok}", body="Recent floods nearby")
    await _post(db_session, blog, title=f"Other {tok}", body="Drought and heat waves.")

    data = await _search(client, f"flooding {tok}")

    assert set(_keys(data)) == {("post", post.id), ("thread", thread.id)}


async def test_trigram_typo_on_title_when_fts_misses(client, db_session, cleanup_forum_categories):
    blog, forum = await _categories(db_session, cleanup_forum_categories)
    post = await _post(db_session, blog, title="Urban Resilience Toolkit", body="Nothing else.")
    thread = await _thread(db_session, forum, title="Coastal resilience plans", body="Ideas?")

    data = await _search(client, "resilence")

    keys = _keys(data)
    assert ("post", post.id) in keys
    assert ("thread", thread.id) in keys


async def test_trigram_typo_needs_every_word_in_the_title(
    client, db_session, cleanup_forum_categories
):
    blog, _ = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    both = await _post(db_session, blog, title=f"Urban Resilience {tok}", body="Nothing else.")
    one = await _post(db_session, blog, title=f"Coastal Resilience {tok}", body="Nothing else.")

    keys = _keys(await _search(client, f"urban resilence {tok}"))

    assert ("post", both.id) in keys
    assert ("post", one.id) not in keys


async def test_title_substring_matches_when_fts_misses(
    client, db_session, cleanup_forum_categories
):
    blog, _ = await _categories(db_session, cleanup_forum_categories)
    post = await _post(db_session, blog, title=f"Floodwall retrofits {_token()}")

    data = await _search(client, "wall retro")

    assert ("post", post.id) in _keys(data)


async def test_like_wildcards_in_query_are_literal(client, db_session, cleanup_forum_categories):
    blog, _ = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    post = await _post(db_session, blog, title=f"{tok} plain title")

    data = await _search(client, f"{tok[:4]}%_")

    assert ("post", post.id) not in _keys(data)


async def test_no_match_returns_empty_page(client, db_session, cleanup_forum_categories):
    data = await _search(client, _token())

    assert data == {"total": 0, "items": []}


async def test_stopword_only_query_returns_200(client):
    response = await client.get(SEARCH, params={"q": "the"})

    assert response.status_code == 200, response.text


# --- snippets ---------------------------------------------------------------------------------


async def test_snippet_marks_the_match(client, db_session, cleanup_forum_categories):
    blog, _ = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    await _post(
        db_session,
        blog,
        title="Retention basins",
        body=f"Cities across the region built retention basins and {tok} schemes last year.",
    )

    item = (await _search(client, tok))["items"][0]

    assert f"<mark>{tok}</mark>" in item["snippet"]


async def test_snippet_has_no_html_but_mark(client, db_session, cleanup_forum_categories):
    blog, forum = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    body = f'Compare 1 < 2 & <script>alert(1)</script> <b onclick="x">bold</b> {tok} words.'
    await _post(db_session, blog, title="Escaping", body=body)
    await _thread(db_session, forum, title="Escaping too", body=body)

    data = await _search(client, tok)

    assert data["total"] == 2
    for item in data["items"]:
        tags = set(re.findall(r"<[^>]*>", item["snippet"]))
        assert tags <= {"<mark>", "</mark>"}, item["snippet"]
        assert "<script" not in item["snippet"]
        assert "1 &lt; 2 &amp;" in item["snippet"]
        assert "<mark>" in item["snippet"]


async def test_snippet_for_title_only_hit_is_start_of_body(
    client, db_session, cleanup_forum_categories
):
    blog, _ = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    await _post(db_session, blog, title=f"Title {tok}", body="Opening words of the body text.")

    item = (await _search(client, tok))["items"][0]

    assert item["snippet"].startswith("Opening words")
    assert "<mark>" not in item["snippet"]


# --- response shape ---------------------------------------------------------------------------


async def test_item_shape(client, db_session, cleanup_users, cleanup_forum_categories):
    author = await _committed(db_session, cleanup_users, display_name="Maria P.")
    blog, forum = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    post = await _post(db_session, blog, title=f"Post {tok}", author_id=author.id, locale="el")
    thread = await _thread(db_session, forum, title=f"Thread {tok}", author_id=author.id)

    data = await _search(client, tok)

    assert data["total"] == 2
    by_type = {item["type"]: item for item in data["items"]}
    assert set(by_type) == {"post", "thread"}
    for item in data["items"]:
        assert set(item) == ITEM_FIELDS
        assert item["author"] == {"id": author.id, "display_name": "Maria P."}
        assert isinstance(item["rank"], float)
        assert item["published_at"] is not None
    assert by_type["post"]["id"] == post.id
    assert by_type["post"]["slug"] == post.slug
    assert by_type["post"]["locale"] == "el"
    assert by_type["post"]["category"] == {"id": blog.id, "slug": blog.slug, "name": blog.name}
    assert by_type["thread"]["id"] == thread.id
    assert by_type["thread"]["title"] == thread.title
    assert by_type["thread"]["category"] == {
        "id": forum.id,
        "slug": forum.slug,
        "name": forum.name,
    }


async def test_author_null_when_author_removed(client, db_session, cleanup_forum_categories):
    blog, forum = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    await _post(db_session, blog, title=f"Orphan {tok}", author_id=None)
    await _thread(db_session, forum, title=f"Orphan {tok}", author_id=None)

    data = await _search(client, tok)

    assert data["total"] == 2
    assert [item["author"] for item in data["items"]] == [None, None]


async def test_anonymised_author_shown_as_deleted_user(
    client, db_session, cleanup_user_ids, cleanup_forum_categories
):
    author = await create_verified_user(db_session)
    cleanup_user_ids.add(author.id)
    blog, _ = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    await _post(db_session, blog, title=f"Legacy {tok}", author_id=author.id)
    await anonymise_user(db_session, user=author)
    await db_session.commit()

    item = (await _search(client, tok))["items"][0]

    assert item["author"] == {"id": author.id, "display_name": "Deleted user"}


# --- visibility -------------------------------------------------------------------------------


async def _every_status(db, blog, forum, tok: str, author_id: int) -> dict:
    rows: dict = {}
    for status in (ContentStatus.PUBLISHED, *HIDDEN_STATUSES):
        rows[("post", status)] = await _post(
            db, blog, title=f"Post {status.value} {tok}", status=status, author_id=author_id
        )
        rows[("thread", status)] = await _thread(
            db, forum, title=f"Thread {status.value} {tok}", status=status, author_id=author_id
        )
    return rows


async def test_anonymous_sees_only_published(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    author = await _committed(db_session, cleanup_users)
    blog, forum = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    rows = await _every_status(db_session, blog, forum, tok, author.id)

    data = await _search(client, tok)

    expected = {
        ("post", rows[("post", ContentStatus.PUBLISHED)].id),
        ("thread", rows[("thread", ContentStatus.PUBLISHED)].id),
    }
    assert set(_keys(data)) == expected
    assert data["total"] == 2


async def test_author_sees_own_pending_and_hidden_not_deleted(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    author = await _committed(db_session, cleanup_users)
    blog, forum = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    rows = await _every_status(db_session, blog, forum, tok, author.id)
    await login_as(client, author)

    data = await _search(client, tok)

    expected = {
        (kind, rows[(kind, status)].id)
        for kind in ("post", "thread")
        for status in (ContentStatus.PUBLISHED, ContentStatus.PENDING, ContentStatus.HIDDEN)
    }
    assert set(_keys(data)) == expected


async def test_other_member_does_not_see_someone_elses_pending(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    author = await _committed(db_session, cleanup_users)
    other = await _committed(db_session, cleanup_users)
    blog, forum = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    rows = await _every_status(db_session, blog, forum, tok, author.id)
    await login_as(client, other)

    data = await _search(client, tok)

    assert set(_keys(data)) == {
        ("post", rows[("post", ContentStatus.PUBLISHED)].id),
        ("thread", rows[("thread", ContentStatus.PUBLISHED)].id),
    }


async def test_admin_sees_hidden_and_pending_but_not_deleted(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    author = await _committed(db_session, cleanup_users)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    blog, forum = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    rows = await _every_status(db_session, blog, forum, tok, author.id)
    await login_as(client, admin)

    data = await _search(client, tok)

    expected = {
        (kind, rows[(kind, status)].id)
        for kind in ("post", "thread")
        for status in (ContentStatus.PUBLISHED, ContentStatus.PENDING, ContentStatus.HIDDEN)
    }
    assert set(_keys(data)) == expected
    assert data["total"] == 6


# --- filters ----------------------------------------------------------------------------------


async def test_type_filter(client, db_session, cleanup_forum_categories):
    blog, forum = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    post = await _post(db_session, blog, title=f"Post {tok}")
    thread = await _thread(db_session, forum, title=f"Thread {tok}")

    assert _keys(await _search(client, tok, type="posts")) == [("post", post.id)]
    assert _keys(await _search(client, tok, type="threads")) == [("thread", thread.id)]
    assert set(_keys(await _search(client, tok, type="all"))) == {
        ("post", post.id),
        ("thread", thread.id),
    }
    assert set(_keys(await _search(client, tok))) == {("post", post.id), ("thread", thread.id)}


async def test_locale_filter(client, db_session, cleanup_forum_categories):
    blog, forum = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    el_post = await _post(db_session, blog, title=f"Post el {tok}", locale="el")
    await _post(db_session, blog, title=f"Post en {tok}", locale="en")
    el_thread = await _thread(db_session, forum, title=f"Thread el {tok}", locale="el")
    await _thread(db_session, forum, title=f"Thread en {tok}", locale="en")

    data = await _search(client, tok, locale="el")

    assert set(_keys(data)) == {("post", el_post.id), ("thread", el_thread.id)}
    assert data["total"] == 2
    assert {item["locale"] for item in data["items"]} == {"el"}


# --- pagination and cross-type order ----------------------------------------------------------


async def test_mixed_types_ordered_by_rank_and_paginated(
    client, db_session, cleanup_forum_categories
):
    blog, forum = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    now = datetime.now(UTC)
    title_post = await _post(db_session, blog, title=f"Post {tok}", body="Unrelated words.")
    title_thread = await _thread(db_session, forum, title=f"Thread {tok}", body="Unrelated words")
    body_post = await _post(db_session, blog, title="Post body", body=f"Mentions {tok} once.")
    body_thread = await _thread(db_session, forum, title="Thread body", body=f"Mentions {tok}")
    # Equal ranks fall back to newest published first.
    title_post.published_at = now - timedelta(hours=1)
    title_thread.published_at = now
    await db_session.commit()

    full = await _search(client, tok)
    first = await _search(client, tok, skip=0, limit=2)
    second = await _search(client, tok, skip=2, limit=2)
    beyond = await _search(client, tok, skip=4, limit=2)

    assert full["total"] == first["total"] == second["total"] == beyond["total"] == 4
    keys = _keys(full)
    assert keys[:2] == [("thread", title_thread.id), ("post", title_post.id)]
    assert set(keys[2:]) == {("post", body_post.id), ("thread", body_thread.id)}
    ranks = [item["rank"] for item in full["items"]]
    assert ranks == sorted(ranks, reverse=True)
    assert _keys(first) + _keys(second) == keys
    assert len(first["items"]) == len(second["items"]) == 2
    assert beyond["items"] == []


async def test_type_filter_counts_only_that_type(client, db_session, cleanup_forum_categories):
    blog, forum = await _categories(db_session, cleanup_forum_categories)
    tok = _token()
    for i in range(3):
        await _post(db_session, blog, title=f"Post {i} {tok}")
    await _thread(db_session, forum, title=f"Thread {tok}")

    data = await _search(client, tok, type="posts", limit=1)

    assert data["total"] == 3
    assert len(data["items"]) == 1


# --- validation -------------------------------------------------------------------------------


@pytest.mark.parametrize("q", ["", "a", "   ", "  a  ", "x" * 201])
async def test_q_length_validated(client, q):
    _assert_field(await client.get(SEARCH, params={"q": q}), "q")


async def test_q_required(client):
    _assert_field(await client.get(SEARCH), "q")


async def test_q_is_stripped_before_length_check(client):
    response = await client.get(SEARCH, params={"q": "  ab  "})

    assert response.status_code == 200, response.text


async def test_q_of_200_characters_accepted(client):
    response = await client.get(SEARCH, params={"q": "x" * 200})

    assert response.status_code == 200, response.text


async def test_unknown_type_rejected(client):
    _assert_field(await client.get(SEARCH, params={"q": "floods", "type": "replies"}), "type")


@pytest.mark.parametrize(("param", "value"), [("limit", 0), ("limit", 51), ("skip", -1)])
async def test_paging_params_validated(client, param, value):
    _assert_field(await client.get(SEARCH, params={"q": "floods", param: value}), param)


# --- rate limit -------------------------------------------------------------------------------


async def test_rate_limited_after_60_requests(client, limits):
    # Rejected requests count too.
    statuses = [(await client.get(SEARCH, params={"q": "a"})).status_code for _ in range(60)]
    assert statuses == [422] * 60

    response = await client.get(SEARCH, params={"q": "floods"})

    assert response.status_code == 429, response.text
    assert response.json()["detail"]["code"] == "rate.limited"
    assert "Retry-After" in response.headers


# --- query count ------------------------------------------------------------------------------


async def _count_statements(client, q: str) -> int:
    from sqlalchemy import event

    from app.db.session import engine

    statements: list[str] = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    sync_engine = engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", record)
    try:
        await _search(client, q)
    finally:
        event.remove(sync_engine, "before_cursor_execute", record)
    return len(statements)


async def test_no_n_plus_one(client, db_session, cleanup_users, cleanup_forum_categories):
    blog, forum = await _categories(db_session, cleanup_forum_categories)
    small, large = _token(), _token()
    for tok, n in ((small, 1), (large, 5)):
        for _ in range(n):
            author = await _committed(db_session, cleanup_users)
            await _post(db_session, blog, title=f"Post {tok}", author_id=author.id)
            await _thread(db_session, forum, title=f"Thread {tok}", author_id=author.id)

    few = await _count_statements(client, small)
    many = await _count_statements(client, large)

    assert few == many
    # count + page + one load per type
    assert many <= 4

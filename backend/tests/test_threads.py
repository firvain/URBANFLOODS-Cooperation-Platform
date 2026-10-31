"""Increment 3b: forum threads - list (visibility, pinned first, activity/newest sort, filters,
search, pagination), detail, create (trust -> status, forum categories only, sanitising, slugs,
tags, KNOWBASE links), update (locked threads: author 423, admin allowed), soft delete, admin
pin/unpin/lock/unlock, and ``/threads/mentions/{kb_type}/{kb_id}/``.

Every test works in its own fresh forum category, so rows committed by other tests never leak
into the assertions. ``cleanup_forum_categories`` removes the categories and every thread in them
(with their KNOWBASE links and audit rows); ``cleanup_users`` / ``cleanup_tags`` the rest. The
KNOWBASE is mocked with respx.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import select

from app.core import rate_limit
from app.core.config import settings
from app.crud.tag import recount_tag_usage
from app.db.enums import CategoryKind, ContentStatus, ContentType, HiddenReason, KbType
from app.db.models import AuditLog, Category, KnowbaseLink, Tag, Thread, User
from tests.factories import (
    create_admin,
    create_category,
    create_post,
    create_tag,
    create_thread,
    create_thread_knowbase_link,
    create_user,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
THREADS = f"{API}/threads/"
KB_BASE = "https://knowbase.test"
KB_API = f"{KB_BASE}/api/v1"
MEASURE_7 = {"id": 7, "title_en": "Retention basin", "title_local": "Λεκάνη ανάσχεσης"}

SUMMARY_FIELDS = {
    "id",
    "slug",
    "title",
    "excerpt",
    "locale",
    "status",
    "category",
    "author",
    "tags",
    "is_pinned",
    "is_locked",
    "reply_count",
    "last_activity_at",
    "published_at",
    "created_at",
    "updated_at",
}
DETAIL_FIELDS = SUMMARY_FIELDS | {
    "body_html",
    "knowbase_links",
    "approved_at",
    "hidden_reason",
    "deleted_at",
}


# --- helpers ----------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def kb_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "KNOWBASE_BASE_URL", KB_BASE)


@pytest.fixture(autouse=True)
def upstream(kb_settings) -> Iterator[respx.MockRouter]:
    """Every request to the (test) KNOWBASE goes through this router; anything unmocked fails."""
    with respx.mock(base_url=KB_API, assert_all_called=False, assert_all_mocked=True) as router:
        yield router


@pytest.fixture
def limits(monkeypatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    rate_limit.reset()
    yield
    rate_limit.reset()


async def _committed(db, cleanup_users, factory=create_verified_user, **kwargs) -> User:
    user = await factory(db, **kwargs)
    cleanup_users.add(user.email)
    await db.commit()
    return user


async def _trusted(db, cleanup_users, **kwargs) -> User:
    return await _committed(db, cleanup_users, trusted_at=datetime.now(UTC), **kwargs)


async def _forum(db, cleanup, **kwargs) -> Category:
    kwargs.setdefault("kind", CategoryKind.FORUM)
    category = await create_category(db, **kwargs)
    cleanup.add(category.id)
    await db.commit()
    return category


async def _thread(db, category: Category, **kwargs) -> Thread:
    """A committed thread (removed with its category by ``cleanup_forum_categories``)."""
    thread = await create_thread(db, category_id=category.id, **kwargs)
    await db.commit()
    return thread


async def _set_body(db, thread: Thread, text: str) -> None:
    thread.body_html = f"<p>{text}</p>"
    thread.body_text = text
    await db.commit()


def _ids(response) -> list[int]:
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


def _assert_field(response, field: str, code: str | None = None) -> None:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "validation.failed"
    fields = detail["fields"]
    matching = {k: v for k, v in fields.items() if k == field or k.startswith(f"{field}.")}
    assert matching, fields
    if code is not None:
        assert code in matching.values(), fields


def _body(category: Category, **overrides) -> dict:
    body = {
        "title": "Sizing retention ponds",
        "body_html": "<p>How do you size retention ponds for a 50-year storm?</p>",
        "category_id": category.id,
        "locale": "en",
        "tags": [],
        "knowbase_links": [],
    }
    body.update(overrides)
    return body


async def _create(client, category: Category, cleanup_tags=None, **overrides):
    response = await client.post(THREADS, json=_body(category, **overrides))
    if response.status_code == 201 and cleanup_tags is not None:
        cleanup_tags.update(tag["id"] for tag in response.json()["tags"])
    return response


async def _audit(db, thread_id: int, action: str) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.target_type == "thread",
            AuditLog.target_id == thread_id,
            AuditLog.action == action,
        )
        .order_by(AuditLog.id)
    )
    return list((await db.scalars(stmt)).all())


# --- list: visibility -------------------------------------------------------------------------


async def test_anon_sees_only_published(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    author = await _committed(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    published = await _thread(db_session, category, author_id=author.id)
    for status in (ContentStatus.PENDING, ContentStatus.HIDDEN, ContentStatus.DELETED):
        await _thread(db_session, category, author_id=author.id, status=status)

    response = await client.get(THREADS, params={"category": category.slug})

    assert _ids(response) == [published.id]
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert set(item) == SUMMARY_FIELDS
    assert item["status"] == "published"
    assert item["category"] == {
        "id": category.id,
        "kind": "forum",
        "slug": category.slug,
        "name": category.name,
    }
    assert item["author"]["id"] == author.id
    assert set(item["author"]) == {"id", "display_name", "organisation", "avatar_url"}
    assert item["excerpt"] == "How do you size retention ponds?"
    assert item["is_pinned"] is False
    assert item["is_locked"] is False
    assert item["reply_count"] == 0
    assert "body_html" not in item


async def test_author_sees_own_pending_in_list_and_detail(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    author = await _committed(db_session, cleanup_users)
    other = await _committed(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    published = await _thread(db_session, category, author_id=other.id)
    mine = await _thread(db_session, category, author_id=author.id, status=ContentStatus.PENDING)
    await _thread(db_session, category, author_id=other.id, status=ContentStatus.PENDING)
    deleted = await _thread(db_session, category, author_id=author.id, status=ContentStatus.DELETED)
    hidden = await _thread(
        db_session,
        category,
        author_id=author.id,
        status=ContentStatus.HIDDEN,
        hidden_reason=HiddenReason.REJECTED,
    )

    await login_as(client, author)
    response = await client.get(THREADS, params={"category": category.slug})

    assert set(_ids(response)) == {published.id, mine.id, hidden.id}
    detail = await client.get(f"{THREADS}{mine.slug}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "pending"
    assert (await client.get(f"{THREADS}{hidden.slug}")).json()["hidden_reason"] == "rejected"
    _assert_error(await client.get(f"{THREADS}{deleted.slug}"), 404, "threads.not_found")


async def _deleted_thread(db, category: Category, **kwargs) -> Thread:
    return await _thread(
        db, category, status=ContentStatus.DELETED, deleted_at=datetime.now(UTC), **kwargs
    )


async def test_admin_sees_hidden_and_pending_in_list_and_deleted_only_in_detail(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    author = await _committed(db_session, cleanup_users)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    member = await _committed(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    published = await _thread(db_session, category, author_id=author.id)
    pending = await _thread(db_session, category, author_id=author.id, status=ContentStatus.PENDING)
    hidden = await _thread(db_session, category, author_id=author.id, status=ContentStatus.HIDDEN)
    deleted = await _deleted_thread(db_session, category, author_id=author.id)

    await login_as(client, admin)
    listed = await client.get(THREADS, params={"category": category.slug})
    assert set(_ids(listed)) == {published.id, pending.id, hidden.id}
    only_hidden = await client.get(THREADS, params={"category": category.slug, "status": "hidden"})
    assert _ids(only_hidden) == [hidden.id]
    only_deleted = await client.get(
        THREADS, params={"category": category.slug, "status": "deleted"}
    )
    assert deleted.id not in _ids(only_deleted)
    hidden_detail = await client.get(f"{THREADS}{hidden.slug}")
    assert hidden_detail.status_code == 200
    assert hidden_detail.json()["deleted_at"] is None

    # Admins can still open a deleted thread (to restore or purge it from the Moderate menu).
    detail = await client.get(f"{THREADS}{deleted.slug}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "deleted"
    assert datetime.fromisoformat(body["deleted_at"]) == deleted.deleted_at
    replies = await client.get(f"{THREADS}{deleted.id}/replies/")
    assert replies.status_code == 200, replies.text
    assert replies.json() == {"total": 0, "items": []}

    # The status filter is ignored for members.
    await login_as(client, member)
    as_member = await client.get(THREADS, params={"category": category.slug, "status": "hidden"})
    assert _ids(as_member) == [published.id]


async def test_deleted_thread_detail_404_for_author_member_and_anon(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    author = await _committed(db_session, cleanup_users)
    member = await _committed(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    deleted = await _deleted_thread(db_session, category, author_id=author.id)

    _assert_error(await client.get(f"{THREADS}{deleted.slug}"), 404, "threads.not_found")
    _assert_error(await client.get(f"{THREADS}{deleted.id}/replies/"), 404, "threads.not_found")
    for user in (author, member):
        await login_as(client, user)
        _assert_error(await client.get(f"{THREADS}{deleted.slug}"), 404, "threads.not_found")
        _assert_error(await client.get(f"{THREADS}{deleted.id}/replies/"), 404, "threads.not_found")


async def test_admin_cannot_edit_or_delete_a_deleted_thread(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    category = await _forum(db_session, cleanup_forum_categories)
    deleted = await _deleted_thread(db_session, category)

    await login_as(client, admin)
    _assert_error(
        await client.patch(f"{THREADS}{deleted.id}", json={"title": "Back again"}),
        404,
        "threads.not_found",
    )
    _assert_error(await client.delete(f"{THREADS}{deleted.id}"), 404, "threads.not_found")


async def test_detail_shape_and_unknown_slug(
    client, db_session, cleanup_users, cleanup_forum_categories, cleanup_tags
):
    author = await _committed(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    tag = await create_tag(db_session)
    cleanup_tags.add(tag.id)
    thread = await _thread(db_session, category, author_id=author.id, tags=[tag])
    await create_thread_knowbase_link(db_session, thread_id=thread.id, title_en="Basin")
    await db_session.commit()

    response = await client.get(f"{THREADS}{thread.slug}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["body_html"] == thread.body_html
    assert body["tags"] == [
        {"id": tag.id, "slug": tag.slug, "name": tag.name, "usage_count": tag.usage_count}
    ]
    assert body["knowbase_links"] == [
        {
            "kb_type": "measure",
            "kb_id": 7,
            "title_en": "Basin",
            "title_local": None,
            "url": "/knowbase/measures/7",
        }
    ]
    _assert_error(await client.get(f"{THREADS}no-such-thread-anywhere"), 404, "threads.not_found")


async def test_excerpt_is_first_200_chars_of_body_text(
    client, db_session, cleanup_forum_categories
):
    category = await _forum(db_session, cleanup_forum_categories)
    long_text = " ".join(["pond"] * 100)
    await _thread(db_session, category, body_text=long_text)

    item = (await client.get(THREADS, params={"category": category.slug})).json()["items"][0]

    assert len(item["excerpt"]) <= 200
    assert item["excerpt"].endswith("…")
    assert item["excerpt"].startswith("pond pond")


# --- list: order, filters, search, pagination -------------------------------------------------


async def test_pinned_first_then_latest_activity(client, db_session, cleanup_forum_categories):
    category = await _forum(db_session, cleanup_forum_categories)
    now = datetime.now(UTC)
    old = await _thread(db_session, category, last_activity_at=now - timedelta(days=3))
    pinned_old = await _thread(
        db_session, category, is_pinned=True, last_activity_at=now - timedelta(days=5)
    )
    recent = await _thread(db_session, category, last_activity_at=now - timedelta(hours=1))
    pinned_new = await _thread(
        db_session, category, is_pinned=True, last_activity_at=now - timedelta(days=1)
    )

    default = await client.get(THREADS, params={"category": category.slug})
    explicit = await client.get(THREADS, params={"category": category.slug, "sort": "activity"})

    expected = [pinned_new.id, pinned_old.id, recent.id, old.id]
    assert _ids(default) == expected
    assert _ids(explicit) == expected


async def test_sort_newest_by_creation_still_pinned_first(
    client, db_session, cleanup_forum_categories
):
    category = await _forum(db_session, cleanup_forum_categories)
    now = datetime.now(UTC)
    first = await _thread(db_session, category, last_activity_at=now)
    second = await _thread(db_session, category, last_activity_at=now - timedelta(days=2))
    pinned = await _thread(db_session, category, is_pinned=True)
    for thread, days in ((first, 3), (second, 1), (pinned, 9)):
        thread.created_at = now - timedelta(days=days)
    await db_session.commit()

    response = await client.get(THREADS, params={"category": category.slug, "sort": "newest"})

    assert _ids(response) == [pinned.id, second.id, first.id]
    bad = await client.get(THREADS, params={"sort": "oldest"})
    assert bad.status_code == 422


async def test_filters_by_tag_author_and_locale(
    client, db_session, cleanup_users, cleanup_forum_categories, cleanup_tags
):
    alice = await _committed(db_session, cleanup_users)
    bob = await _committed(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    tag = await create_tag(db_session)
    cleanup_tags.add(tag.id)
    tagged = await _thread(db_session, category, author_id=alice.id, tags=[tag])
    greek = await _thread(db_session, category, author_id=bob.id, locale="el")
    plain = await _thread(db_session, category, author_id=alice.id)

    params = {"category": category.slug}
    assert _ids(await client.get(THREADS, params={**params, "tag": tag.slug})) == [tagged.id]
    assert set(_ids(await client.get(THREADS, params={**params, "author_id": alice.id}))) == {
        tagged.id,
        plain.id,
    }
    assert _ids(await client.get(THREADS, params={**params, "locale": "el"})) == [greek.id]
    assert _ids(await client.get(THREADS, params={"tag": "no-such-tag-xyz"})) == []
    assert _ids(await client.get(THREADS, params={"category": "no-such-category-xyz"})) == []


async def test_blog_category_slug_does_not_match(client, db_session, cleanup_forum_categories):
    blog = await _forum(db_session, cleanup_forum_categories, kind=CategoryKind.BLOG)
    response = await client.get(THREADS, params={"category": blog.slug})
    assert _ids(response) == []


async def test_q_ranks_title_match_above_body_match(client, db_session, cleanup_forum_categories):
    category = await _forum(db_session, cleanup_forum_categories)
    now = datetime.now(UTC)
    in_body = await _thread(
        db_session, category, title="Rainwater at schools", last_activity_at=now
    )
    await _set_body(db_session, in_body, "A small detention pond near the school yard.")
    in_title = await _thread(
        db_session,
        category,
        title="Detention pond design guide",
        last_activity_at=now - timedelta(days=4),
    )
    unrelated = await _thread(db_session, category, title="Early warning sirens")
    await _set_body(db_session, unrelated, "Sirens and text messages.")

    response = await client.get(THREADS, params={"category": category.slug, "q": "detention pond"})

    assert _ids(response) == [in_title.id, in_body.id]


async def test_q_matches_title_substring(client, db_session, cleanup_forum_categories):
    category = await _forum(db_session, cleanup_forum_categories)
    thread = await _thread(db_session, category, title="Floodwall retrofits")

    response = await client.get(THREADS, params={"category": category.slug, "q": "wall retro"})

    assert _ids(response) == [thread.id]


async def test_pagination_and_limit_cap(client, db_session, cleanup_forum_categories):
    category = await _forum(db_session, cleanup_forum_categories)
    for _ in range(3):
        await _thread(db_session, category)

    first = await client.get(THREADS, params={"category": category.slug, "limit": 2})
    second = await client.get(THREADS, params={"category": category.slug, "limit": 2, "skip": 2})

    assert first.json()["total"] == 3
    assert len(first.json()["items"]) == 2
    assert second.json()["total"] == 3
    assert len(second.json()["items"]) == 1
    assert not set(_ids(first)) & set(_ids(second))
    assert (await client.get(THREADS, params={"limit": 51})).status_code == 422


# --- create -----------------------------------------------------------------------------------


async def test_create_requires_verified_user(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    category = await _forum(db_session, cleanup_forum_categories)
    _assert_error(await _create(client, category), 401, "auth.not_authenticated")

    unverified = await _committed(db_session, cleanup_users, factory=create_user)
    await login_as(client, unverified)
    _assert_error(await _create(client, category), 403, "auth.email_not_verified")


async def test_trusted_user_publishes_immediately(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, user)

    response = await _create(client, category)

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["status"] == "published"
    assert body["published_at"] is not None
    assert body["last_activity_at"] is not None
    assert body["author"]["id"] == user.id
    assert body["category"]["id"] == category.id
    assert body["is_pinned"] is False
    assert body["is_locked"] is False
    assert body["reply_count"] == 0
    assert body["slug"].startswith("sizing-retention-ponds")
    client.cookies.clear()
    assert (await client.get(f"{THREADS}{body['slug']}")).status_code == 200


async def test_untrusted_user_thread_is_pending(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user = await _committed(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, user)

    response = await _create(client, category)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["published_at"] is None
    assert (await client.get(f"{THREADS}{body['slug']}")).status_code == 200
    client.cookies.clear()
    _assert_error(await client.get(f"{THREADS}{body['slug']}"), 404, "threads.not_found")


async def test_admin_thread_is_published_and_audited(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, admin)

    response = await _create(client, category)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "published"
    rows = await _audit(db_session, body["id"], "thread.created")
    assert len(rows) == 1
    assert rows[0].actor_id == admin.id
    assert rows[0].metadata_ == {
        "thread_id": body["id"],
        "status": "published",
        "category_id": category.id,
    }


async def test_body_is_sanitised(client, db_session, cleanup_users, cleanup_forum_categories):
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, user)

    response = await _create(
        client,
        category,
        body_html=(
            '<p onclick="x()">See <a href="https://example.org" rel="opener">this</a></p>'
            "<script>alert(1)</script>"
        ),
    )

    assert response.status_code == 201, response.text
    html = response.json()["body_html"]
    assert "<script" not in html
    assert "alert" not in html
    assert "onclick" not in html
    assert 'rel="nofollow noopener noreferrer"' in html
    assert response.json()["excerpt"] == "See this"
    stored = await db_session.scalar(select(Thread).where(Thread.id == response.json()["id"]))
    assert stored.body_text == "See this"


@pytest.mark.parametrize("html", ["", "<script>alert(1)</script>", "<p> </p>"])
async def test_empty_body_is_rejected(
    client, db_session, cleanup_users, cleanup_forum_categories, html
):
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, user)

    _assert_field(await _create(client, category, body_html=html), "body_html", "empty")


@pytest.mark.parametrize("title", ["ab", "x" * 201, "   "])
async def test_title_length_validated(
    client, db_session, cleanup_users, cleanup_forum_categories, title
):
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, user)

    _assert_field(await _create(client, category, title=title), "title")


async def test_slug_from_title_is_unique_and_transliterated(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    token = category.slug[-12:]
    base = f"swales-or-basins-{token}"
    await _thread(db_session, category, slug=base)
    await login_as(client, user)

    first = await _create(client, category, title=f"Swales or basins {token}")
    second = await _create(client, category, title=f"Swales or Basins {token}?")
    greek = await _create(client, category, title="Πλημμύρες στην Κοζάνη")

    assert first.json()["slug"] == f"{base}-2"
    assert second.json()["slug"] == f"{base}-3"
    assert greek.json()["slug"].startswith("plemmures-sten-kozane")
    assert greek.json()["title"] == "Πλημμύρες στην Κοζάνη"


async def test_locale_must_be_supported(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, user)

    assert (await _create(client, category, locale="el")).json()["locale"] == "el"
    _assert_field(await _create(client, category, locale="de"), "locale")


async def test_category_must_exist_be_active_and_forum(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user = await _trusted(db_session, cleanup_users)
    archived = await _forum(db_session, cleanup_forum_categories, is_archived=True)
    blog = await _forum(db_session, cleanup_forum_categories, kind=CategoryKind.BLOG)
    await login_as(client, user)

    _assert_field(await _create(client, archived), "category_id", "archived")
    _assert_field(await _create(client, blog), "category_id", "invalid")
    missing = await client.post(THREADS, json={**_body(blog), "category_id": 2_000_000_000})
    _assert_field(missing, "category_id", "not_found")


async def test_admin_only_forum_category(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    member = await _trusted(db_session, cleanup_users)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    category = await _forum(db_session, cleanup_forum_categories, admin_only=True)

    await login_as(client, member)
    _assert_error(await _create(client, category), 403, "threads.category_admin_only")

    await login_as(client, admin)
    assert (await _create(client, category)).status_code == 201


async def test_tags_created_reused_and_counted(
    client, db_session, cleanup_users, cleanup_forum_categories, cleanup_tags
):
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    token = category.slug[-12:]
    existing = await create_tag(db_session, name=f"Existing {token}", slug=f"existing-{token}")
    cleanup_tags.add(existing.id)
    await db_session.commit()
    await login_as(client, user)

    response = await _create(
        client,
        category,
        cleanup_tags,
        tags=[f"existing {token}", f"Brand New {token}", f"brand new {token}"],
    )

    assert response.status_code == 201, response.text
    tags = response.json()["tags"]
    assert len(tags) == 2
    by_slug = {t["slug"]: t for t in tags}
    assert by_slug[f"existing-{token}"]["id"] == existing.id
    assert by_slug[f"existing-{token}"]["usage_count"] == 1
    assert by_slug[f"brand-new-{token}"]["usage_count"] == 1

    too_many = await _create(client, category, tags=[f"tag {i}" for i in range(11)])
    _assert_field(too_many, "tags")


async def test_pending_thread_does_not_count_towards_tag_usage(
    client, db_session, cleanup_users, cleanup_forum_categories, cleanup_tags
):
    user = await _committed(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, user)

    response = await _create(client, category, cleanup_tags, tags=[f"t {category.slug}"])

    assert response.status_code == 201, response.text
    assert response.json()["tags"][0]["usage_count"] == 0


async def test_tag_usage_counts_posts_and_threads(
    db_session, cleanup_forum_categories, cleanup_tags
):
    forum = await _forum(db_session, cleanup_forum_categories)
    blog = await _forum(db_session, cleanup_forum_categories, kind=CategoryKind.BLOG)
    tag = await create_tag(db_session)
    cleanup_tags.add(tag.id)
    await create_post(db_session, category_id=blog.id, tags=[tag])
    await create_post(db_session, category_id=blog.id, tags=[tag], status=ContentStatus.PENDING)
    await create_thread(db_session, category_id=forum.id, tags=[tag])
    await create_thread(db_session, category_id=forum.id, tags=[tag])
    await create_thread(db_session, category_id=forum.id, tags=[tag], status=ContentStatus.HIDDEN)
    await create_thread(
        db_session,
        category_id=forum.id,
        tags=[tag],
        status=ContentStatus.DELETED,
        deleted_at=datetime.now(UTC),
    )

    try:
        await recount_tag_usage(db_session, tag_ids=[tag.id])
        await db_session.refresh(tag)
        assert tag.usage_count == 3  # one published post + two published threads
    finally:
        # Release the row locks before the cleanup fixtures delete the categories.
        await db_session.rollback()


async def test_create_rate_limited(
    client, db_session, cleanup_users, cleanup_forum_categories, limits
):
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, user)

    statuses = [(await client.post(THREADS, json={})).status_code for _ in range(20)]
    assert statuses == [422] * 20

    _assert_error(await _create(client, category), 429, "rate.limited")


# --- create: KNOWBASE links -------------------------------------------------------------------


async def test_links_resolved_and_titles_cached(
    client, db_session, upstream, cleanup_users, cleanup_forum_categories
):
    upstream.get("/measures/7").respond(json=MEASURE_7)
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, user)

    response = await _create(
        client,
        category,
        knowbase_links=[{"kb_type": "measure", "kb_id": 7}, {"kb_type": "measure", "kb_id": 7}],
    )

    assert response.status_code == 201, response.text
    expected = [
        {
            "kb_type": "measure",
            "kb_id": 7,
            "title_en": "Retention basin",
            "title_local": "Λεκάνη ανάσχεσης",
            "url": "/knowbase/measures/7",
        }
    ]
    assert response.json()["knowbase_links"] == expected
    stored = list(
        (
            await db_session.scalars(
                select(KnowbaseLink).where(
                    KnowbaseLink.content_type == ContentType.THREAD,
                    KnowbaseLink.content_id == response.json()["id"],
                )
            )
        ).all()
    )
    assert [(link.kb_type, link.kb_id) for link in stored] == [(KbType.MEASURE, 7)]

    upstream.reset()
    detail = await client.get(f"{THREADS}{response.json()['slug']}")
    assert detail.json()["knowbase_links"] == expected


async def test_unknown_link_is_422_and_nothing_created(
    client, db_session, upstream, cleanup_users, cleanup_forum_categories
):
    upstream.get("/measures/999").respond(404, json={"detail": "Not found"})
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, user)

    links = [{"kb_type": "measure", "kb_id": 999}]
    response = await _create(client, category, knowbase_links=links)

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["fields"] == {"knowbase_links": "not_found"}
    created = await db_session.scalar(select(Thread.id).where(Thread.category_id == category.id))
    assert created is None


async def test_knowbase_down_is_503(
    client, db_session, upstream, cleanup_users, cleanup_forum_categories
):
    upstream.get("/measures/7").mock(side_effect=httpx.ConnectError("down"))
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, user)

    response = await _create(client, category, knowbase_links=[{"kb_type": "measure", "kb_id": 7}])

    _assert_error(response, 503, "knowbase.unavailable")


async def test_too_many_links_rejected(client, db_session, cleanup_users, cleanup_forum_categories):
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, user)

    eleven = [{"kb_type": "measure", "kb_id": i} for i in range(1, 12)]
    _assert_field(await _create(client, category, knowbase_links=eleven), "knowbase_links")


# --- update -----------------------------------------------------------------------------------


async def test_author_edits_title_body_and_links(
    client, db_session, upstream, cleanup_users, cleanup_forum_categories
):
    upstream.get("/measures/7").respond(json=MEASURE_7)
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, user)
    created = (await _create(client, category)).json()

    response = await client.patch(
        f"{THREADS}{created['id']}",
        json={
            "title": "Sizing swales",
            "body_html": "<p>New</p><script>x()</script>",
            "knowbase_links": [{"kb_type": "measure", "kb_id": 7}],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Sizing swales"
    assert body["body_html"] == "<p>New</p>"
    assert body["excerpt"] == "New"
    assert body["slug"] == created["slug"]
    assert body["status"] == "published"
    assert [link["kb_id"] for link in body["knowbase_links"]] == [7]
    rows = await _audit(db_session, created["id"], "thread.updated")
    assert len(rows) == 1
    assert rows[0].actor_id == user.id
    assert rows[0].metadata_ == {"fields": ["body_html", "knowbase_links", "title"]}

    # Unchanged update: no audit row.
    same = await client.patch(f"{THREADS}{created['id']}", json={"title": "Sizing swales"})
    assert same.status_code == 200
    assert len(await _audit(db_session, created["id"], "thread.updated")) == 1

    null_title = await client.patch(f"{THREADS}{created['id']}", json={"title": None})
    _assert_field(null_title, "title")
    empty = await client.patch(f"{THREADS}{created['id']}", json={"body_html": "<script/>"})
    _assert_field(empty, "body_html", "empty")


async def test_update_category_must_be_forum(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    target = await _forum(db_session, cleanup_forum_categories)
    blog = await _forum(db_session, cleanup_forum_categories, kind=CategoryKind.BLOG)
    admin_only = await _forum(db_session, cleanup_forum_categories, admin_only=True)
    thread = await _thread(db_session, category, author_id=user.id)
    await login_as(client, user)
    url = f"{THREADS}{thread.id}"

    _assert_field(await client.patch(url, json={"category_id": blog.id}), "category_id", "invalid")
    _assert_error(
        await client.patch(url, json={"category_id": admin_only.id}),
        403,
        "threads.category_admin_only",
    )
    moved = await client.patch(url, json={"category_id": target.id})
    assert moved.status_code == 200, moved.text
    assert moved.json()["category"]["id"] == target.id


async def test_other_member_cannot_edit_or_delete(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    author = await _committed(db_session, cleanup_users)
    other = await _committed(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    thread = await _thread(db_session, category, author_id=author.id)
    pending = await _thread(db_session, category, author_id=author.id, status=ContentStatus.PENDING)

    _assert_error(
        await client.patch(f"{THREADS}{thread.id}", json={"title": "Mine now"}),
        401,
        "auth.not_authenticated",
    )
    await login_as(client, other)
    _assert_error(
        await client.patch(f"{THREADS}{thread.id}", json={"title": "Mine now"}),
        403,
        "threads.forbidden",
    )
    _assert_error(await client.delete(f"{THREADS}{thread.id}"), 403, "threads.forbidden")
    _assert_error(
        await client.patch(f"{THREADS}{pending.id}", json={"title": "Hello"}),
        404,
        "threads.not_found",
    )
    _assert_error(
        await client.patch(f"{THREADS}2000000000", json={"title": "Nope"}),
        404,
        "threads.not_found",
    )


async def test_locked_thread_author_gets_423_admin_can_edit(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    author = await _trusted(db_session, cleanup_users)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    category = await _forum(db_session, cleanup_forum_categories)
    thread = await _thread(db_session, category, author_id=author.id, is_locked=True)

    await login_as(client, author)
    _assert_error(
        await client.patch(f"{THREADS}{thread.id}", json={"title": "Reopened"}),
        423,
        "threads.locked",
    )

    await login_as(client, admin)
    response = await client.patch(f"{THREADS}{thread.id}", json={"title": "Edited by admin"})
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Edited by admin"
    assert response.json()["is_locked"] is True
    assert response.json()["author"]["id"] == author.id


async def test_member_cannot_set_slug_admin_can(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    author = await _trusted(db_session, cleanup_users)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    category = await _forum(db_session, cleanup_forum_categories)
    taken = await _thread(db_session, category)
    thread = await _thread(db_session, category, author_id=author.id)
    new_slug = f"renamed-{thread.slug}"

    await login_as(client, author)
    _assert_error(
        await client.patch(f"{THREADS}{thread.id}", json={"slug": new_slug}),
        403,
        "threads.forbidden",
    )

    await login_as(client, admin)
    response = await client.patch(f"{THREADS}{thread.id}", json={"slug": new_slug})
    assert response.status_code == 200, response.text
    assert response.json()["slug"] == new_slug
    assert (await client.get(f"{THREADS}{new_slug}")).status_code == 200
    rows = await _audit(db_session, thread.id, "thread.updated")
    assert rows[-1].actor_id == admin.id
    assert rows[-1].metadata_ == {"fields": ["slug"]}

    _assert_error(
        await client.patch(f"{THREADS}{thread.id}", json={"slug": taken.slug}),
        409,
        "threads.slug_taken",
    )
    _assert_field(await client.patch(f"{THREADS}{thread.id}", json={"slug": "Bad Slug"}), "slug")


async def test_update_tags_recounts(
    client, db_session, cleanup_users, cleanup_forum_categories, cleanup_tags
):
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, user)
    token = category.slug[-12:]
    created = (await _create(client, category, cleanup_tags, tags=[f"old {token}"])).json()
    old_id = created["tags"][0]["id"]

    response = await client.patch(f"{THREADS}{created['id']}", json={"tags": [f"new {token}"]})

    assert response.status_code == 200, response.text
    new = response.json()["tags"]
    cleanup_tags.update(t["id"] for t in new)
    assert [t["slug"] for t in new] == [f"new-{token}"]
    assert new[0]["usage_count"] == 1
    old = await db_session.scalar(select(Tag).where(Tag.id == old_id))
    assert old.usage_count == 0


# --- delete -----------------------------------------------------------------------------------


async def test_author_soft_deletes(
    client, db_session, cleanup_users, cleanup_forum_categories, cleanup_tags
):
    user = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    await login_as(client, user)
    created = (await _create(client, category, cleanup_tags, tags=[f"d {category.slug}"])).json()
    tag_id = created["tags"][0]["id"]
    user_id = user.id
    assert created["tags"][0]["usage_count"] == 1

    response = await client.delete(f"{THREADS}{created['id']}")

    assert response.status_code == 204, response.text
    assert _ids(await client.get(THREADS, params={"category": category.slug})) == []
    _assert_error(await client.get(f"{THREADS}{created['slug']}"), 404, "threads.not_found")
    db_session.expire_all()
    stored = await db_session.scalar(select(Thread).where(Thread.id == created["id"]))
    assert stored.status == ContentStatus.DELETED
    assert stored.deleted_at is not None
    tag = await db_session.scalar(select(Tag).where(Tag.id == tag_id))
    assert tag.usage_count == 0
    rows = await _audit(db_session, created["id"], "thread.deleted")
    assert len(rows) == 1
    assert rows[0].actor_id == user_id
    assert rows[0].metadata_ == {"thread_id": created["id"], "previous_status": "published"}

    _assert_error(await client.delete(f"{THREADS}{created['id']}"), 404, "threads.not_found")


async def test_admin_can_delete_any_thread(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    author = await _committed(db_session, cleanup_users)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    category = await _forum(db_session, cleanup_forum_categories)
    thread = await _thread(db_session, category, author_id=author.id, status=ContentStatus.PENDING)

    await login_as(client, admin)
    assert (await client.delete(f"{THREADS}{thread.id}")).status_code == 204
    rows = await _audit(db_session, thread.id, "thread.deleted")
    assert rows[0].actor_id == admin.id


# --- admin: pin / lock ------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["pin", "unpin", "lock", "unlock"])
async def test_pin_and_lock_require_admin(
    client, db_session, cleanup_users, cleanup_forum_categories, action
):
    author = await _trusted(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    thread = await _thread(db_session, category, author_id=author.id)

    _assert_error(
        await client.post(f"{THREADS}{thread.id}/{action}"), 401, "auth.not_authenticated"
    )
    await login_as(client, author)
    _assert_error(await client.post(f"{THREADS}{thread.id}/{action}"), 403, "auth.forbidden")


@pytest.mark.parametrize(
    ("action", "undo", "field"), [("pin", "unpin", "is_pinned"), ("lock", "unlock", "is_locked")]
)
async def test_pin_and_lock_are_idempotent_and_audited(
    client, db_session, cleanup_users, cleanup_forum_categories, action, undo, field
):
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    category = await _forum(db_session, cleanup_forum_categories)
    thread = await _thread(db_session, category)
    await login_as(client, admin)

    first = await client.post(f"{THREADS}{thread.id}/{action}")
    again = await client.post(f"{THREADS}{thread.id}/{action}")

    assert first.status_code == 200, first.text
    assert set(first.json()) == DETAIL_FIELDS
    assert first.json()[field] is True
    assert again.status_code == 200
    assert again.json()[field] is True
    done = f"{action}ed" if action == "lock" else "pinned"
    rows = await _audit(db_session, thread.id, f"thread.{done}")
    assert len(rows) == 1  # the repeated call changed nothing
    assert rows[0].actor_id == admin.id

    undone = await client.post(f"{THREADS}{thread.id}/{undo}")
    assert undone.status_code == 200
    assert undone.json()[field] is False
    undone_action = "unlocked" if undo == "unlock" else "unpinned"
    assert len(await _audit(db_session, thread.id, f"thread.{undone_action}")) == 1
    thread_id = thread.id
    db_session.expire_all()
    stored = await db_session.scalar(select(Thread).where(Thread.id == thread_id))
    assert getattr(stored, field) is False


async def test_pin_unknown_or_deleted_thread_is_404(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    category = await _forum(db_session, cleanup_forum_categories)
    deleted = await _thread(db_session, category, status=ContentStatus.DELETED)
    await login_as(client, admin)

    _assert_error(await client.post(f"{THREADS}{deleted.id}/pin"), 404, "threads.not_found")
    _assert_error(await client.post(f"{THREADS}2000000000/lock"), 404, "threads.not_found")


async def test_pinned_thread_appears_first_after_pin(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    category = await _forum(db_session, cleanup_forum_categories)
    now = datetime.now(UTC)
    old = await _thread(db_session, category, last_activity_at=now - timedelta(days=9))
    new = await _thread(db_session, category, last_activity_at=now)
    await login_as(client, admin)

    assert _ids(await client.get(THREADS, params={"category": category.slug})) == [new.id, old.id]
    await client.post(f"{THREADS}{old.id}/pin")
    assert _ids(await client.get(THREADS, params={"category": category.slug})) == [old.id, new.id]


# --- mentions ---------------------------------------------------------------------------------


async def test_mentions_lists_visible_threads_linking_an_item(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    author = await _committed(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    kb_id = 1_000_000 + category.id  # unique to this test
    linked = await _thread(db_session, category, author_id=author.id)
    pending = await _thread(db_session, category, author_id=author.id, status=ContentStatus.PENDING)
    other_item = await _thread(db_session, category)
    unlinked = await _thread(db_session, category)
    for thread in (linked, pending):
        await create_thread_knowbase_link(db_session, thread_id=thread.id, kb_id=kb_id)
    await create_thread_knowbase_link(db_session, thread_id=other_item.id, kb_id=kb_id + 1)
    await create_thread_knowbase_link(
        db_session, thread_id=unlinked.id, kb_type="document", kb_id=kb_id
    )
    await db_session.commit()
    url = f"{THREADS}mentions/measure/{kb_id}/"

    anon = await client.get(url)
    assert _ids(anon) == [linked.id]
    assert anon.json()["total"] == 1
    assert set(anon.json()["items"][0]) == SUMMARY_FIELDS

    await login_as(client, author)
    assert set(_ids(await client.get(url))) == {linked.id, pending.id}

    assert (await client.get(f"{THREADS}mentions/video/1/")).status_code == 422
    assert (await client.get(f"{THREADS}mentions/measure/0/")).status_code == 422

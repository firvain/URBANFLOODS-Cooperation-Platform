"""Increment 2e: blog posts - list (visibility, filters, search, sort), detail, create (trust ->
status, sanitising, slugs, tags, categories, cover, event fields), update and soft delete.

Every test works in its own fresh category, so rows committed by other tests never leak into
the assertions. Rows the app commits are removed by ``cleanup_users`` / ``cleanup_categories``
(posts in them go too) / ``cleanup_tags``. KNOWBASE links are covered in
``test_knowbase_links.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core import rate_limit
from app.core.config import settings
from app.db.enums import CategoryKind, ContentStatus, HiddenReason
from app.db.models import AuditLog, Category, Post, Tag, User
from tests.factories import (
    create_admin,
    create_attachment,
    create_category,
    create_post,
    create_tag,
    create_user,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
POSTS = f"{API}/posts/"

SUMMARY_FIELDS = {
    "id",
    "slug",
    "title",
    "excerpt",
    "locale",
    "status",
    "category",
    "author",
    "cover",
    "tags",
    "event_at",
    "event_url",
    "comment_count",
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


async def _category(db, cleanup_categories, **kwargs) -> Category:
    category = await create_category(db, **kwargs)
    cleanup_categories.add(category.id)
    await db.commit()
    return category


async def _post(db, category: Category, **kwargs) -> Post:
    """A committed post (removed with its category by ``cleanup_categories``)."""
    post = await create_post(db, category_id=category.id, **kwargs)
    await db.commit()
    return post


async def _set_body(db, post: Post, text: str) -> None:
    post.body_html = f"<p>{text}</p>"
    post.body_text = text
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
        "title": "Green roofs in Kozani",
        "body_html": "<p>Green roofs slow down stormwater run-off.</p>",
        "category_id": category.id,
        "locale": "en",
        "tags": [],
        "knowbase_links": [],
    }
    body.update(overrides)
    return body


async def _create(client, category: Category, cleanup_tags=None, **overrides):
    response = await client.post(POSTS, json=_body(category, **overrides))
    if response.status_code == 201 and cleanup_tags is not None:
        cleanup_tags.update(tag["id"] for tag in response.json()["tags"])
    return response


async def _audit(db, post_id: int, action: str) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.target_type == "post",
            AuditLog.target_id == post_id,
            AuditLog.action == action,
        )
        .order_by(AuditLog.id)
    )
    return list((await db.scalars(stmt)).all())


# --- list: visibility -------------------------------------------------------------------------


async def test_anon_sees_only_published(client, db_session, cleanup_users, cleanup_categories):
    author = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    published = await _post(db_session, category, author_id=author.id)
    for status in (ContentStatus.PENDING, ContentStatus.HIDDEN, ContentStatus.DELETED):
        await _post(db_session, category, author_id=author.id, status=status)

    response = await client.get(POSTS, params={"category": category.slug})

    assert _ids(response) == [published.id]
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert set(item) == SUMMARY_FIELDS
    assert item["status"] == "published"
    assert item["category"] == {
        "id": category.id,
        "kind": "blog",
        "slug": category.slug,
        "name": category.name,
    }
    assert item["author"]["id"] == author.id
    assert item["author"]["display_name"] == author.display_name
    assert set(item["author"]) == {
        "id",
        "display_name",
        "organisation",
        "avatar_url",
        "has_profile",
    }
    assert item["tags"] == []
    assert item["cover"] is None
    assert "body_html" not in item


async def test_author_sees_own_pending_in_list_and_detail(
    client, db_session, cleanup_users, cleanup_categories
):
    author = await _committed(db_session, cleanup_users)
    other = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    published = await _post(db_session, category, author_id=other.id)
    mine = await _post(db_session, category, author_id=author.id, status=ContentStatus.PENDING)
    await _post(db_session, category, author_id=other.id, status=ContentStatus.PENDING)
    deleted = await _post(db_session, category, author_id=author.id, status=ContentStatus.DELETED)
    hidden = await _post(
        db_session,
        category,
        author_id=author.id,
        status=ContentStatus.HIDDEN,
        hidden_reason=HiddenReason.REJECTED,
    )

    await login_as(client, author)
    response = await client.get(POSTS, params={"category": category.slug})

    assert set(_ids(response)) == {published.id, mine.id, hidden.id}
    statuses = {i["id"]: i["status"] for i in response.json()["items"]}
    assert statuses[mine.id] == "pending"
    assert statuses[hidden.id] == "hidden"

    detail = await client.get(f"{POSTS}{mine.slug}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "pending"
    rejected = await client.get(f"{POSTS}{hidden.slug}")
    assert rejected.json()["hidden_reason"] == "rejected"
    _assert_error(await client.get(f"{POSTS}{deleted.slug}"), 404, "posts.not_found")


async def _deleted_post(db, category: Category, **kwargs) -> Post:
    return await _post(
        db, category, status=ContentStatus.DELETED, deleted_at=datetime.now(UTC), **kwargs
    )


async def test_admin_sees_hidden_and_pending_in_list_and_deleted_only_in_detail(
    client, db_session, cleanup_users, cleanup_categories
):
    author = await _committed(db_session, cleanup_users)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    category = await _category(db_session, cleanup_categories)
    published = await _post(db_session, category, author_id=author.id)
    pending = await _post(db_session, category, author_id=author.id, status=ContentStatus.PENDING)
    hidden = await _post(db_session, category, author_id=author.id, status=ContentStatus.HIDDEN)
    deleted = await _deleted_post(db_session, category, author_id=author.id)

    await login_as(client, admin)
    listed = await client.get(POSTS, params={"category": category.slug})
    assert set(_ids(listed)) == {published.id, pending.id, hidden.id}

    only_hidden = await client.get(POSTS, params={"category": category.slug, "status": "hidden"})
    assert _ids(only_hidden) == [hidden.id]
    only_deleted = await client.get(POSTS, params={"category": category.slug, "status": "deleted"})
    assert deleted.id not in _ids(only_deleted)

    hidden_detail = await client.get(f"{POSTS}{hidden.slug}")
    assert hidden_detail.status_code == 200
    assert hidden_detail.json()["deleted_at"] is None

    # Admins can still open a deleted post (to restore or purge it from the Moderate menu).
    detail = await client.get(f"{POSTS}{deleted.slug}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "deleted"
    assert body["deleted_at"] is not None
    assert datetime.fromisoformat(body["deleted_at"]) == deleted.deleted_at


async def test_deleted_post_detail_404_for_author_member_and_anon(
    client, db_session, cleanup_users, cleanup_categories
):
    author = await _committed(db_session, cleanup_users)
    member = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    deleted = await _deleted_post(db_session, category, author_id=author.id)

    _assert_error(await client.get(f"{POSTS}{deleted.slug}"), 404, "posts.not_found")
    for user in (author, member):
        await login_as(client, user)
        _assert_error(await client.get(f"{POSTS}{deleted.slug}"), 404, "posts.not_found")


async def test_admin_cannot_edit_or_delete_a_deleted_post(
    client, db_session, cleanup_users, cleanup_categories
):
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    category = await _category(db_session, cleanup_categories)
    deleted = await _deleted_post(db_session, category)

    await login_as(client, admin)
    _assert_error(
        await client.patch(f"{POSTS}{deleted.id}", json={"title": "Back again"}),
        404,
        "posts.not_found",
    )
    _assert_error(await client.delete(f"{POSTS}{deleted.id}"), 404, "posts.not_found")


async def test_status_filter_ignored_for_members(
    client, db_session, cleanup_users, cleanup_categories
):
    member = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    published = await _post(db_session, category)
    await _post(db_session, category, status=ContentStatus.HIDDEN)

    anon = await client.get(POSTS, params={"category": category.slug, "status": "hidden"})
    assert _ids(anon) == [published.id]
    await login_as(client, member)
    as_member = await client.get(POSTS, params={"category": category.slug, "status": "hidden"})
    assert _ids(as_member) == [published.id]


async def test_detail_404_for_pending_post_to_anon_and_unknown_slug(
    client, db_session, cleanup_categories
):
    category = await _category(db_session, cleanup_categories)
    pending = await _post(db_session, category, status=ContentStatus.PENDING)

    _assert_error(await client.get(f"{POSTS}{pending.slug}"), 404, "posts.not_found")
    _assert_error(await client.get(f"{POSTS}no-such-post-anywhere"), 404, "posts.not_found")


async def test_detail_shape(client, db_session, cleanup_users, cleanup_categories, cleanup_tags):
    author = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    tag = await create_tag(db_session)
    cleanup_tags.add(tag.id)
    cover = await create_attachment(db_session, uploader_id=author.id, alt_text="A basin")
    post = await _post(db_session, category, author_id=author.id, tags=[tag], cover=cover)

    response = await client.get(f"{POSTS}{post.slug}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["body_html"] == post.body_html
    assert body["knowbase_links"] == []
    assert body["tags"] == [
        {"id": tag.id, "slug": tag.slug, "name": tag.name, "usage_count": tag.usage_count}
    ]
    assert body["cover"] == {
        "id": cover.id,
        "url": f"{settings.UPLOAD_URL_PREFIX}/{cover.storage_path}",
        "thumb_url": f"{settings.UPLOAD_URL_PREFIX}/{cover.thumb_path}",
        "width": cover.width,
        "height": cover.height,
        "alt_text": "A basin",
    }


async def test_author_has_profile_follows_directory_opt_out(
    client, db_session, cleanup_users, cleanup_categories
):
    author = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    post = await _post(db_session, category, author_id=author.id)

    detail = await client.get(f"{POSTS}{post.slug}")
    assert detail.json()["author"]["has_profile"] is True
    listing = await client.get(POSTS, params={"category": category.slug})
    assert listing.json()["items"][0]["author"]["has_profile"] is True

    author.show_in_directory = False
    await db_session.commit()

    detail = await client.get(f"{POSTS}{post.slug}")
    assert detail.json()["author"]["has_profile"] is False
    listing = await client.get(POSTS, params={"category": category.slug})
    assert listing.json()["items"][0]["author"]["has_profile"] is False


# --- list: filters, search, sort, pagination --------------------------------------------------


async def test_filters_by_tag_author_and_locale(
    client, db_session, cleanup_users, cleanup_categories, cleanup_tags
):
    alice = await _committed(db_session, cleanup_users)
    bob = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    tag = await create_tag(db_session)
    cleanup_tags.add(tag.id)
    tagged = await _post(db_session, category, author_id=alice.id, tags=[tag])
    greek = await _post(db_session, category, author_id=bob.id, locale="el")
    plain = await _post(db_session, category, author_id=alice.id)

    params = {"category": category.slug}
    assert _ids(await client.get(POSTS, params={**params, "tag": tag.slug})) == [tagged.id]
    assert set(_ids(await client.get(POSTS, params={**params, "author_id": alice.id}))) == {
        tagged.id,
        plain.id,
    }
    assert _ids(await client.get(POSTS, params={**params, "locale": "el"})) == [greek.id]
    assert _ids(await client.get(POSTS, params={"tag": "no-such-tag-xyz"})) == []
    assert _ids(await client.get(POSTS, params={"category": "no-such-category-xyz"})) == []


async def test_q_ranks_title_match_above_body_match(client, db_session, cleanup_categories):
    category = await _category(db_session, cleanup_categories)
    in_body = await _post(db_session, category, title="Rainwater harvesting at schools")
    await _set_body(db_session, in_body, "A small detention pond near the school yard.")
    in_title = await _post(db_session, category, title="Detention pond design guide")
    unrelated = await _post(db_session, category, title="Early warning sirens")
    await _set_body(db_session, unrelated, "Sirens and text messages.")

    response = await client.get(POSTS, params={"category": category.slug, "q": "detention pond"})

    assert _ids(response) == [in_title.id, in_body.id]


async def test_q_matches_title_substring(client, db_session, cleanup_categories):
    category = await _category(db_session, cleanup_categories)
    post = await _post(db_session, category, title="Floodwall retrofits")

    response = await client.get(POSTS, params={"category": category.slug, "q": "wall retro"})

    assert _ids(response) == [post.id]


async def test_default_order_is_newest_published_first(client, db_session, cleanup_categories):
    category = await _category(db_session, cleanup_categories)
    now = datetime.now(UTC)
    old, new, mid = [await _post(db_session, category) for _ in range(3)]
    for post, days in ((old, 3), (new, 1), (mid, 2)):
        post.published_at = now - timedelta(days=days)
    await db_session.commit()

    newest = await client.get(POSTS, params={"category": category.slug})
    oldest = await client.get(POSTS, params={"category": category.slug, "sort": "oldest"})

    assert _ids(newest) == [new.id, mid.id, old.id]
    assert _ids(oldest) == [old.id, mid.id, new.id]


async def test_sort_events_upcoming_only(client, db_session, cleanup_categories):
    category = await _category(db_session, cleanup_categories)
    now = datetime.now(UTC)
    await _post(db_session, category, event_at=now - timedelta(days=1))
    later = await _post(db_session, category, event_at=now + timedelta(days=2))
    sooner = await _post(db_session, category, event_at=now + timedelta(days=1))
    await _post(db_session, category)  # no event

    upcoming = await client.get(
        POSTS, params={"category": category.slug, "sort": "events", "upcoming_only": "true"}
    )
    assert _ids(upcoming) == [sooner.id, later.id]

    all_events = await client.get(POSTS, params={"category": category.slug, "sort": "events"})
    assert len(_ids(all_events)) == 3
    assert _ids(all_events)[1:] == [sooner.id, later.id]


async def test_pagination_and_limit_cap(client, db_session, cleanup_categories):
    category = await _category(db_session, cleanup_categories)
    for _ in range(3):
        await _post(db_session, category)

    first = await client.get(POSTS, params={"category": category.slug, "limit": 2})
    second = await client.get(POSTS, params={"category": category.slug, "limit": 2, "skip": 2})

    assert first.json()["total"] == 3
    assert len(first.json()["items"]) == 2
    assert second.json()["total"] == 3
    assert len(second.json()["items"]) == 1
    assert not set(_ids(first)) & set(_ids(second))
    assert (await client.get(POSTS, params={"limit": 51})).status_code == 422
    assert (await client.get(POSTS, params={"sort": "random"})).status_code == 422


# --- create -----------------------------------------------------------------------------------


async def test_create_requires_verified_user(client, db_session, cleanup_users, cleanup_categories):
    category = await _category(db_session, cleanup_categories)
    _assert_error(await _create(client, category), 401, "auth.not_authenticated")

    unverified = await _committed(db_session, cleanup_users, factory=create_user)
    await login_as(client, unverified)
    _assert_error(await _create(client, category), 403, "auth.email_not_verified")


async def test_trusted_user_publishes_immediately(
    client, db_session, cleanup_users, cleanup_categories
):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)

    response = await _create(client, category)

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body["status"] == "published"
    assert body["published_at"] is not None
    assert body["author"]["id"] == user.id
    assert body["category"]["id"] == category.id
    assert body["slug"] == "green-roofs-in-kozani" or body["slug"].startswith(
        "green-roofs-in-kozani-"
    )
    assert body["locale"] == "en"
    # Anyone can read it now.
    client.cookies.clear()
    assert (await client.get(f"{POSTS}{body['slug']}")).status_code == 200


async def test_untrusted_user_post_is_pending(
    client, db_session, cleanup_users, cleanup_categories
):
    user = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)

    response = await _create(client, category)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["published_at"] is None
    assert (await client.get(f"{POSTS}{body['slug']}")).status_code == 200
    client.cookies.clear()
    _assert_error(await client.get(f"{POSTS}{body['slug']}"), 404, "posts.not_found")


async def test_admin_post_is_published(client, db_session, cleanup_users, cleanup_categories):
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, admin)

    response = await _create(client, category)

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "published"


async def test_create_writes_audit_row(client, db_session, cleanup_users, cleanup_categories):
    user = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)

    body = (await _create(client, category)).json()

    rows = await _audit(db_session, body["id"], "post.created")
    assert len(rows) == 1
    assert rows[0].actor_id == user.id
    assert rows[0].metadata_ == {
        "post_id": body["id"],
        "status": "pending",
        "category_id": category.id,
    }


async def test_body_is_sanitised(client, db_session, cleanup_users, cleanup_categories):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
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
    stored = await db_session.scalar(select(Post).where(Post.id == response.json()["id"]))
    assert stored.body_text == "See this"


@pytest.mark.parametrize("html", ["", "   ", "<script>alert(1)</script>", "<p> </p>"])
async def test_empty_body_is_rejected(client, db_session, cleanup_users, cleanup_categories, html):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)

    _assert_field(await _create(client, category, body_html=html), "body_html", "empty")


async def test_excerpt_generated_when_omitted(
    client, db_session, cleanup_users, cleanup_categories
):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)

    short = await _create(client, category, body_html="<p>Short <b>body</b> here.</p>")
    long_text = " ".join(["word"] * 300)
    long = await _create(client, category, body_html=f"<p>{long_text}</p>")
    given = await _create(client, category, excerpt="  My own summary.  ")

    assert short.json()["excerpt"] == "Short body here."
    assert len(long.json()["excerpt"]) <= 500
    assert long.json()["excerpt"].endswith("…")
    assert given.json()["excerpt"] == "My own summary."
    too_long = await _create(client, category, excerpt="x" * 501)
    _assert_field(too_long, "excerpt")


async def test_slug_from_title_is_unique_and_transliterated(
    client, db_session, cleanup_users, cleanup_categories
):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    token = category.slug[-12:]
    base = f"sponge-city-pilot-{token}"
    await _post(db_session, category, slug=base)
    await login_as(client, user)

    first = await _create(client, category, title=f"Sponge city pilot {token}")
    second = await _create(client, category, title=f"Sponge City Pilot {token}!")
    greek = await _create(client, category, title="Πλημμύρες στην Κοζάνη")

    assert first.json()["slug"] == f"{base}-2"
    assert second.json()["slug"] == f"{base}-3"
    assert greek.json()["slug"].startswith("plemmures-sten-kozane")
    assert greek.json()["title"] == "Πλημμύρες στην Κοζάνη"


@pytest.mark.parametrize("title", ["ab", "x" * 201, "   "])
async def test_title_length_validated(client, db_session, cleanup_users, cleanup_categories, title):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)

    _assert_field(await _create(client, category, title=title), "title")


async def test_tags_created_reused_and_counted(
    client, db_session, cleanup_users, cleanup_categories, cleanup_tags
):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
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
    assert by_slug[f"brand-new-{token}"]["name"] == f"Brand New {token}"
    assert by_slug[f"brand-new-{token}"]["usage_count"] == 1


async def test_pending_post_does_not_count_towards_tag_usage(
    client, db_session, cleanup_users, cleanup_categories, cleanup_tags
):
    user = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)

    response = await _create(client, category, cleanup_tags, tags=[f"t {category.slug}"])

    assert response.status_code == 201, response.text
    assert response.json()["tags"][0]["usage_count"] == 0


async def test_too_many_tags_rejected(client, db_session, cleanup_users, cleanup_categories):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)

    response = await _create(client, category, tags=[f"tag {i}" for i in range(11)])

    _assert_field(response, "tags")


async def test_admin_only_category(client, db_session, cleanup_users, cleanup_categories):
    member = await _trusted(db_session, cleanup_users)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    category = await _category(db_session, cleanup_categories, admin_only=True)

    await login_as(client, member)
    _assert_error(await _create(client, category), 403, "posts.category_admin_only")

    await login_as(client, admin)
    assert (await _create(client, category)).status_code == 201


async def test_category_must_exist_be_active_and_blog(
    client, db_session, cleanup_users, cleanup_categories
):
    user = await _trusted(db_session, cleanup_users)
    archived = await _category(db_session, cleanup_categories, is_archived=True)
    forum = await _category(db_session, cleanup_categories, kind=CategoryKind.FORUM)
    await login_as(client, user)

    _assert_field(await _create(client, archived), "category_id", "archived")
    _assert_field(await _create(client, forum), "category_id", "invalid")
    missing = await client.post(POSTS, json={**_body(archived), "category_id": 2_000_000_000})
    _assert_field(missing, "category_id", "not_found")


async def test_cover_must_be_own_live_attachment(
    client, db_session, cleanup_users, cleanup_categories
):
    user = await _trusted(db_session, cleanup_users)
    other = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    mine = await create_attachment(db_session, uploader_id=user.id)
    theirs = await create_attachment(db_session, uploader_id=other.id)
    gone = await create_attachment(db_session, uploader_id=user.id, deleted_at=datetime.now(UTC))
    await db_session.commit()
    await login_as(client, user)

    ok = await _create(client, category, cover_attachment_id=mine.id)
    assert ok.status_code == 201, ok.text
    assert ok.json()["cover"]["id"] == mine.id

    for attachment_id in (theirs.id, gone.id, 2_000_000_000):
        response = await _create(client, category, cover_attachment_id=attachment_id)
        _assert_field(response, "cover_attachment_id", "invalid")


async def test_event_fields(client, db_session, cleanup_users, cleanup_categories):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)

    ok = await _create(
        client,
        category,
        event_at="2027-03-01T09:30:00+02:00",
        event_url="HTTPS://Example.org/Webinar",
    )
    assert ok.status_code == 201, ok.text
    assert datetime.fromisoformat(ok.json()["event_at"]) == datetime(2027, 3, 1, 7, 30, tzinfo=UTC)
    assert ok.json()["event_url"] == "https://example.org/Webinar"

    naive = await _create(client, category, event_at="2027-03-01T09:30:00")
    _assert_field(naive, "event_at")
    for url in ("javascript:alert(1)", "ftp://example.org/x", "https://user:pw@example.org/"):
        _assert_field(await _create(client, category, event_url=url), "event_url", "invalid")


async def test_locale_must_be_supported(client, db_session, cleanup_users, cleanup_categories):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)

    assert (await _create(client, category, locale="el")).json()["locale"] == "el"
    _assert_field(await _create(client, category, locale="de"), "locale")


async def test_create_rate_limited(client, db_session, cleanup_users, cleanup_categories, limits):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)

    # Rejected requests count too.
    statuses = [(await client.post(POSTS, json={})).status_code for _ in range(20)]
    assert statuses == [422] * 20

    response = await _create(client, category)
    _assert_error(response, 429, "rate.limited")


# --- update -----------------------------------------------------------------------------------


async def test_author_edits_title_and_body(client, db_session, cleanup_users, cleanup_categories):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)
    created = (await _create(client, category)).json()

    response = await client.patch(
        f"{POSTS}{created['id']}",
        json={"title": "Blue-green roofs", "body_html": "<p>New</p><script>x()</script>"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Blue-green roofs"
    assert body["body_html"] == "<p>New</p>"
    assert body["slug"] == created["slug"]  # unchanged
    assert body["status"] == "published"  # an edit keeps it published
    assert body["excerpt"] == "New"  # the auto excerpt follows the body
    rows = await _audit(db_session, created["id"], "post.updated")
    assert len(rows) == 1
    assert rows[0].actor_id == user.id
    assert rows[0].metadata_ == {"fields": ["body_html", "title"]}


async def test_update_keeps_a_custom_excerpt(client, db_session, cleanup_users, cleanup_categories):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)
    created = (await _create(client, category, excerpt="Hand-written")).json()

    response = await client.patch(f"{POSTS}{created['id']}", json={"body_html": "<p>New</p>"})

    assert response.json()["excerpt"] == "Hand-written"


async def test_update_of_pending_post_stays_pending(
    client, db_session, cleanup_users, cleanup_categories
):
    user = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)
    created = (await _create(client, category)).json()

    response = await client.patch(f"{POSTS}{created['id']}", json={"title": "Still waiting"})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"
    assert response.json()["published_at"] is None


async def test_update_empty_body_rejected(client, db_session, cleanup_users, cleanup_categories):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)
    created = (await _create(client, category)).json()

    response = await client.patch(f"{POSTS}{created['id']}", json={"body_html": "<script/>"})
    _assert_field(response, "body_html", "empty")
    null_title = await client.patch(f"{POSTS}{created['id']}", json={"title": None})
    _assert_field(null_title, "title")


async def test_other_member_cannot_edit_or_delete(
    client, db_session, cleanup_users, cleanup_categories
):
    author = await _committed(db_session, cleanup_users)
    other = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    post = await _post(db_session, category, author_id=author.id)
    pending = await _post(db_session, category, author_id=author.id, status=ContentStatus.PENDING)

    _assert_error(
        await client.patch(f"{POSTS}{post.id}", json={"title": "Mine now"}),
        401,
        "auth.not_authenticated",
    )
    await login_as(client, other)
    _assert_error(
        await client.patch(f"{POSTS}{post.id}", json={"title": "Mine now"}), 403, "posts.forbidden"
    )
    _assert_error(await client.delete(f"{POSTS}{post.id}"), 403, "posts.forbidden")
    # Someone else's pending post does not exist for this member.
    _assert_error(
        await client.patch(f"{POSTS}{pending.id}", json={"title": "x" * 5}), 404, "posts.not_found"
    )
    _assert_error(
        await client.patch(f"{POSTS}2000000000", json={"title": "Nope"}), 404, "posts.not_found"
    )


async def test_member_cannot_set_slug_admin_can(
    client, db_session, cleanup_users, cleanup_categories
):
    author = await _trusted(db_session, cleanup_users)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    category = await _category(db_session, cleanup_categories)
    taken = await _post(db_session, category)
    post = await _post(db_session, category, author_id=author.id)
    new_slug = f"renamed-{post.slug}"

    await login_as(client, author)
    _assert_error(
        await client.patch(f"{POSTS}{post.id}", json={"slug": new_slug}), 403, "posts.forbidden"
    )

    await login_as(client, admin)
    response = await client.patch(f"{POSTS}{post.id}", json={"slug": new_slug})
    assert response.status_code == 200, response.text
    assert response.json()["slug"] == new_slug
    assert (await client.get(f"{POSTS}{new_slug}")).status_code == 200
    rows = await _audit(db_session, post.id, "post.updated")
    assert rows[-1].actor_id == admin.id
    assert rows[-1].metadata_ == {"fields": ["slug"]}

    _assert_error(
        await client.patch(f"{POSTS}{post.id}", json={"slug": taken.slug}), 409, "posts.slug_taken"
    )
    _assert_field(await client.patch(f"{POSTS}{post.id}", json={"slug": "Bad Slug"}), "slug")


async def test_update_tags_recounts(
    client, db_session, cleanup_users, cleanup_categories, cleanup_tags
):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)
    token = category.slug[-12:]
    created = (await _create(client, category, cleanup_tags, tags=[f"old {token}"])).json()
    old_id = created["tags"][0]["id"]

    response = await client.patch(f"{POSTS}{created['id']}", json={"tags": [f"new {token}"]})

    assert response.status_code == 200, response.text
    new = response.json()["tags"]
    cleanup_tags.update(t["id"] for t in new)
    assert [t["slug"] for t in new] == [f"new-{token}"]
    assert new[0]["usage_count"] == 1
    old = await db_session.scalar(select(Tag).where(Tag.id == old_id))
    assert old.usage_count == 0


async def test_unchanged_update_writes_no_audit(
    client, db_session, cleanup_users, cleanup_categories
):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)
    created = (await _create(client, category)).json()

    response = await client.patch(f"{POSTS}{created['id']}", json={"title": created["title"]})

    assert response.status_code == 200
    assert await _audit(db_session, created["id"], "post.updated") == []


# --- delete -----------------------------------------------------------------------------------


async def test_author_soft_deletes(
    client, db_session, cleanup_users, cleanup_categories, cleanup_tags
):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)
    created = (await _create(client, category, cleanup_tags, tags=[f"d {category.slug}"])).json()
    tag_id = created["tags"][0]["id"]
    user_id = user.id
    assert created["tags"][0]["usage_count"] == 1

    response = await client.delete(f"{POSTS}{created['id']}")

    assert response.status_code == 204, response.text
    assert _ids(await client.get(POSTS, params={"category": category.slug})) == []
    _assert_error(await client.get(f"{POSTS}{created['slug']}"), 404, "posts.not_found")
    db_session.expire_all()
    stored = await db_session.scalar(select(Post).where(Post.id == created["id"]))
    assert stored.status == ContentStatus.DELETED
    assert stored.deleted_at is not None
    tag = await db_session.scalar(select(Tag).where(Tag.id == tag_id))
    assert tag.usage_count == 0
    rows = await _audit(db_session, created["id"], "post.deleted")
    assert len(rows) == 1
    assert rows[0].actor_id == user_id

    # Gone for the author too: no editing, no second delete.
    _assert_error(
        await client.patch(f"{POSTS}{created['id']}", json={"title": "Back again"}),
        404,
        "posts.not_found",
    )
    _assert_error(await client.delete(f"{POSTS}{created['id']}"), 404, "posts.not_found")


async def test_admin_can_edit_and_delete_any_post(
    client, db_session, cleanup_users, cleanup_categories
):
    author = await _committed(db_session, cleanup_users)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    category = await _category(db_session, cleanup_categories)
    post = await _post(db_session, category, author_id=author.id, status=ContentStatus.PENDING)

    await login_as(client, admin)
    edited = await client.patch(f"{POSTS}{post.id}", json={"title": "Edited by admin"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["status"] == "pending"  # no moderation transitions here
    assert edited.json()["author"]["id"] == author.id

    assert (await client.delete(f"{POSTS}{post.id}")).status_code == 204
    rows = await _audit(db_session, post.id, "post.deleted")
    assert rows[0].actor_id == admin.id


async def test_update_category_cover_excerpt_and_event(
    client, db_session, cleanup_users, cleanup_categories
):
    user = await _trusted(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    target = await _category(db_session, cleanup_categories)
    admin_only = await _category(db_session, cleanup_categories, admin_only=True)
    archived = await _category(db_session, cleanup_categories, is_archived=True)
    cover = await create_attachment(db_session, uploader_id=user.id)
    await db_session.commit()
    await login_as(client, user)
    created = (
        await _create(
            client,
            category,
            excerpt="Hand-written",
            event_at="2027-01-01T10:00:00Z",
            event_url="https://example.org/e",
        )
    ).json()
    url = f"{POSTS}{created['id']}"

    _assert_error(
        await client.patch(url, json={"category_id": admin_only.id}),
        403,
        "posts.category_admin_only",
    )
    _assert_field(await client.patch(url, json={"category_id": archived.id}), "category_id")
    _assert_field(await client.patch(url, json={"event_at": "2027-01-01T10:00:00"}), "event_at")

    response = await client.patch(
        url,
        json={
            "category_id": target.id,
            "cover_attachment_id": cover.id,
            "excerpt": None,
            "event_at": None,
            "event_url": None,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["category"]["id"] == target.id
    assert body["cover"]["id"] == cover.id
    assert body["excerpt"] == "Green roofs slow down stormwater run-off."  # regenerated
    assert body["event_at"] is None
    assert body["event_url"] is None
    rows = await _audit(db_session, created["id"], "post.updated")
    assert rows[-1].metadata_ == {
        "fields": ["category_id", "cover_attachment_id", "event_at", "event_url", "excerpt"]
    }

    cleared = await client.patch(url, json={"cover_attachment_id": None})
    assert cleared.json()["cover"] is None

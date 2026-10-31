"""Increment 3d: comments on blog posts - list (post visibility, comment visibility, order,
pagination), create (verified, post must be published, comment allow-list sanitising, length,
``comment_count``), update (author within 24 h or admin) and soft delete (author or admin).

Every test works in its own fresh category; its posts (and their comments, by cascade) go with
``cleanup_categories``. Audit rows by the test's users go with ``cleanup_users``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core import rate_limit
from app.core.config import settings
from app.crud.comment import sanitize_comment_html
from app.db.enums import ContentStatus, HiddenReason
from app.db.models import AuditLog, Category, Comment, Post, User
from tests.factories import (
    create_admin,
    create_category,
    create_comment,
    create_post,
    create_user,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
POSTS = f"{API}/posts/"
COMMENT_FIELDS = {
    "id",
    "post_id",
    "author",
    "body_html",
    "status",
    "created_at",
    "updated_at",
    "is_edited",
}


# --- helpers ----------------------------------------------------------------------------------


@pytest.fixture
def limits(monkeypatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    rate_limit.reset()
    yield
    rate_limit.reset()


def _comments_url(post_id: int) -> str:
    return f"{POSTS}{post_id}/comments/"


def _comment_url(comment_id: int) -> str:
    return f"{API}/comments/{comment_id}"


async def _committed(db, cleanup_users, factory=create_verified_user, **kwargs) -> User:
    user = await factory(db, **kwargs)
    cleanup_users.add(user.email)
    await db.commit()
    return user


async def _category(db, cleanup_categories) -> Category:
    category = await create_category(db)
    cleanup_categories.add(category.id)
    await db.commit()
    return category


async def _post(db, category: Category, **kwargs) -> Post:
    post = await create_post(db, category_id=category.id, **kwargs)
    await db.commit()
    return post


async def _comment(db, post: Post, **kwargs) -> Comment:
    comment = await create_comment(db, post_id=post.id, **kwargs)
    await db.commit()
    return comment


async def _setup(db, cleanup_users, cleanup_categories, **post_kwargs):
    """A committed verified member, a category and a published post by another member."""
    user = await _committed(db, cleanup_users)
    post_author = await _committed(db, cleanup_users)
    category = await _category(db, cleanup_categories)
    post = await _post(db, category, author_id=post_author.id, **post_kwargs)
    return user, post_author, category, post


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
    assert field in fields, fields
    if code is not None:
        assert fields[field] == code, fields


async def _create(client, post_id: int, body_html: str = "<p>Great work on this.</p>"):
    return await client.post(_comments_url(post_id), json={"body_html": body_html})


async def _comment_count(client, post: Post) -> int:
    response = await client.get(f"{POSTS}{post.slug}")
    assert response.status_code == 200, response.text
    return response.json()["comment_count"]


async def _backdate(db, comment_id: int, delta: timedelta) -> None:
    then = datetime.now(UTC) - delta
    await db.execute(
        update(Comment).where(Comment.id == comment_id).values(created_at=then, updated_at=then)
    )
    await db.commit()


async def _fresh(db, comment_id: int) -> Comment:
    """The comment as stored now (the test session may hold an older copy)."""
    stmt = select(Comment).where(Comment.id == comment_id)
    return await db.scalar(stmt.execution_options(populate_existing=True))


async def _audit(db, comment_id: int, action: str) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.target_type == "comment",
            AuditLog.target_id == comment_id,
            AuditLog.action == action,
        )
        .order_by(AuditLog.id)
    )
    return list((await db.scalars(stmt)).all())


# --- sanitiser --------------------------------------------------------------------------------


def test_sanitize_comment_html_restricts_tags():
    html = sanitize_comment_html(
        "<h2>Heading</h2><p>Some <strong>bold</strong> and <em>it</em></p>"
        '<img src="https://example.org/x.png" alt="x">'
        "<table><tbody><tr><td>cell</td></tr></tbody></table>"
        "<pre><code>x = 1</code></pre>"
        '<p><a href="https://example.org">link</a></p><script>alert(1)</script>'
    )
    assert "<h2" not in html
    assert "Heading" in html
    assert "<img" not in html
    assert "<table" not in html and "<td" not in html
    assert "cell" in html
    assert "<pre" not in html
    assert "<code>x = 1</code>" in html
    assert "<strong>bold</strong>" in html
    assert 'rel="nofollow noopener noreferrer"' in html
    assert "script" not in html and "alert" not in html


def test_sanitize_comment_html_empty_when_only_an_image_remains():
    assert sanitize_comment_html('<img src="https://example.org/x.png" alt="x">') == ""
    assert sanitize_comment_html("<h3> </h3>") == ""


# --- list -------------------------------------------------------------------------------------


async def test_list_on_published_post_is_public(
    client, db_session, cleanup_users, cleanup_categories
):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    comment = await _comment(db_session, post, author_id=user.id, body="Very useful.")

    response = await client.get(_comments_url(post.id))

    assert _ids(response) == [comment.id]
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert set(item) == COMMENT_FIELDS
    assert item["post_id"] == post.id
    assert item["status"] == "published"
    assert item["body_html"] == "<p>Very useful.</p>"
    assert item["is_edited"] is False
    assert item["author"]["id"] == user.id
    assert item["author"]["display_name"] == user.display_name
    assert set(item["author"]) == {
        "id",
        "display_name",
        "organisation",
        "avatar_url",
        "has_profile",
    }


async def test_author_has_profile_follows_directory_opt_out(
    client, db_session, cleanup_users, cleanup_categories
):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    await _comment(db_session, post, author_id=user.id)

    response = await client.get(_comments_url(post.id))
    assert response.json()["items"][0]["author"]["has_profile"] is True

    user.show_in_directory = False
    await db_session.commit()

    response = await client.get(_comments_url(post.id))
    assert response.json()["items"][0]["author"]["has_profile"] is False


async def test_list_hides_non_published_comments_from_others(
    client, db_session, cleanup_users, cleanup_categories
):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    published = await _comment(db_session, post, author_id=user.id)
    hidden = await _comment(
        db_session,
        post,
        author_id=user.id,
        status=ContentStatus.HIDDEN,
        hidden_reason=HiddenReason.ADMIN,
    )
    await _comment(db_session, post, author_id=user.id, status=ContentStatus.DELETED)

    assert _ids(await client.get(_comments_url(post.id))) == [published.id]
    await login_as(client, user)
    assert _ids(await client.get(_comments_url(post.id))) == [published.id, hidden.id]
    client.cookies.clear()
    await login_as(client, admin)
    # Deleted comments are never listed, not even for admins.
    assert _ids(await client.get(_comments_url(post.id))) == [published.id, hidden.id]


async def test_list_on_pending_post_404_for_anon_200_for_author(
    client, db_session, cleanup_users, cleanup_categories
):
    author = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    post = await _post(db_session, category, author_id=author.id, status=ContentStatus.PENDING)

    _assert_error(await client.get(_comments_url(post.id)), 404, "posts.not_found")
    _assert_error(await client.get(_comments_url(2_000_000_000)), 404, "posts.not_found")

    await login_as(client, author)
    response = await client.get(_comments_url(post.id))
    assert response.status_code == 200, response.text
    assert response.json() == {"total": 0, "items": []}


async def test_list_on_deleted_post_200_for_admin_only(
    client, db_session, cleanup_users, cleanup_categories
):
    user, post_author, _, post = await _setup(
        db_session,
        cleanup_users,
        cleanup_categories,
        status=ContentStatus.DELETED,
        deleted_at=datetime.now(UTC),
    )
    comment = await _comment(db_session, post, author_id=user.id)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)

    _assert_error(await client.get(_comments_url(post.id)), 404, "posts.not_found")
    for member in (user, post_author):
        await login_as(client, member)
        _assert_error(await client.get(_comments_url(post.id)), 404, "posts.not_found")

    await login_as(client, admin)
    assert _ids(await client.get(_comments_url(post.id))) == [comment.id]


async def test_list_order_oldest_first_and_pagination(
    client, db_session, cleanup_users, cleanup_categories
):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    now = datetime.now(UTC)
    third = await _comment(db_session, post, author_id=user.id, created_at=now)
    first = await _comment(db_session, post, author_id=user.id, created_at=now - timedelta(hours=2))
    second = await _comment(
        db_session, post, author_id=user.id, created_at=now - timedelta(hours=1)
    )

    assert _ids(await client.get(_comments_url(post.id))) == [first.id, second.id, third.id]

    response = await client.get(_comments_url(post.id), params={"skip": 1, "limit": 1})
    assert _ids(response) == [second.id]
    assert response.json()["total"] == 3

    assert (await client.get(_comments_url(post.id), params={"limit": 100})).status_code == 200
    _assert_field(await client.get(_comments_url(post.id), params={"limit": 101}), "query.limit")


# --- create -----------------------------------------------------------------------------------


async def test_create_requires_verified_user(client, db_session, cleanup_users, cleanup_categories):
    _, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    _assert_error(await _create(client, post.id), 401, "auth.not_authenticated")

    unverified = await _committed(db_session, cleanup_users, factory=create_user)
    await login_as(client, unverified)
    _assert_error(await _create(client, post.id), 403, "auth.email_not_verified")


async def test_create_comment(client, db_session, cleanup_users, cleanup_categories):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    await login_as(client, user)

    response = await _create(client, post.id, "<p>Great work on this.</p>")

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == COMMENT_FIELDS
    assert body["post_id"] == post.id
    assert body["status"] == "published"
    assert body["author"]["id"] == user.id
    assert body["body_html"] == "<p>Great work on this.</p>"
    assert body["is_edited"] is False
    stored = await db_session.scalar(select(Comment).where(Comment.id == body["id"]))
    assert stored.body_text == "Great work on this."

    client.cookies.clear()
    assert _ids(await client.get(_comments_url(post.id))) == [body["id"]]


async def test_create_writes_audit_row(client, db_session, cleanup_users, cleanup_categories):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    await login_as(client, user)

    body = (await _create(client, post.id)).json()

    rows = await _audit(db_session, body["id"], "comment.created")
    assert len(rows) == 1
    assert rows[0].actor_id == user.id
    assert rows[0].metadata_ == {"comment_id": body["id"], "post_id": post.id}


async def test_create_on_own_pending_post_rejected(
    client, db_session, cleanup_users, cleanup_categories
):
    author = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    post = await _post(db_session, category, author_id=author.id, status=ContentStatus.PENDING)
    await login_as(client, author)

    _assert_error(await _create(client, post.id), 422, "comments.post_not_published")


async def test_create_on_hidden_or_missing_post_404_for_member(
    client, db_session, cleanup_users, cleanup_categories
):
    user, _, _, post = await _setup(
        db_session,
        cleanup_users,
        cleanup_categories,
        status=ContentStatus.HIDDEN,
        hidden_reason=HiddenReason.ADMIN,
    )
    await login_as(client, user)

    _assert_error(await _create(client, post.id), 404, "posts.not_found")
    _assert_error(await _create(client, 2_000_000_000), 404, "posts.not_found")


async def test_nobody_can_comment_on_a_deleted_post(
    client, db_session, cleanup_users, cleanup_categories
):
    user, post_author, _, post = await _setup(
        db_session,
        cleanup_users,
        cleanup_categories,
        status=ContentStatus.DELETED,
        deleted_at=datetime.now(UTC),
    )
    admin = await _committed(db_session, cleanup_users, factory=create_admin)

    for member in (user, post_author, admin):
        await login_as(client, member)
        _assert_error(await _create(client, post.id), 404, "posts.not_found")


async def test_admin_cannot_comment_on_hidden_post(
    client, db_session, cleanup_users, cleanup_categories
):
    _, _, _, post = await _setup(
        db_session,
        cleanup_users,
        cleanup_categories,
        status=ContentStatus.HIDDEN,
        hidden_reason=HiddenReason.ADMIN,
    )
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    await login_as(client, admin)

    _assert_error(await _create(client, post.id), 422, "comments.post_not_published")


async def test_body_is_sanitised_to_comment_allow_list(
    client, db_session, cleanup_users, cleanup_categories
):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    await login_as(client, user)

    response = await _create(
        client,
        post.id,
        '<h2>Big title</h2><p onclick="x()">Body <a href="https://example.org">link</a></p>'
        '<img src="https://example.org/a.png" alt="a"><script>alert(1)</script>',
    )

    assert response.status_code == 201, response.text
    html = response.json()["body_html"]
    assert "<h2" not in html
    assert "Big title" in html
    assert "<img" not in html
    assert "<script" not in html and "alert" not in html
    assert "onclick" not in html
    assert 'rel="nofollow noopener noreferrer"' in html


@pytest.mark.parametrize(
    "html",
    ["", "   ", "<script>alert(1)</script>", "<p> </p>", '<img src="https://e.org/a.png">'],
)
async def test_empty_body_rejected(client, db_session, cleanup_users, cleanup_categories, html):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    await login_as(client, user)

    _assert_field(await _create(client, post.id, html), "body_html", "empty")


async def test_body_text_length_limit(client, db_session, cleanup_users, cleanup_categories):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    await login_as(client, user)

    ok = await _create(client, post.id, f"<p>{'a' * 5000}</p>")
    assert ok.status_code == 201, ok.text
    _assert_field(await _create(client, post.id, f"<p>{'a' * 5001}</p>"), "body_html", "too_long")
    _assert_field(await client.post(_comments_url(post.id), json={}), "body_html")


async def test_comment_count_follows_create_and_delete(
    client, db_session, cleanup_users, cleanup_categories
):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    await login_as(client, user)
    assert await _comment_count(client, post) == 0

    first = (await _create(client, post.id)).json()
    await _create(client, post.id)
    assert await _comment_count(client, post) == 2

    assert (await client.delete(_comment_url(first["id"]))).status_code == 204
    assert await _comment_count(client, post) == 1


async def test_create_rate_limited(client, db_session, cleanup_users, cleanup_categories, limits):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    await login_as(client, user)

    # Rejected requests count too.
    statuses = [(await client.post(_comments_url(post.id), json={})).status_code for _ in range(30)]
    assert statuses == [422] * 30

    _assert_error(await _create(client, post.id), 429, "rate.limited")


# --- update -----------------------------------------------------------------------------------


async def test_author_edits_within_24h(client, db_session, cleanup_users, cleanup_categories):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    await login_as(client, user)
    created = (await _create(client, post.id, "<p>First version.</p>")).json()
    await _backdate(db_session, created["id"], timedelta(hours=23))

    response = await client.patch(
        _comment_url(created["id"]), json={"body_html": "<h2>Second</h2><p>version.</p>"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == COMMENT_FIELDS
    assert "<h2" not in body["body_html"]
    assert "Second" in body["body_html"]
    assert body["is_edited"] is True
    assert body["author"]["id"] == user.id
    stored = await _fresh(db_session, created["id"])
    assert stored.body_text == "Second version."

    rows = await _audit(db_session, created["id"], "comment.updated")
    assert len(rows) == 1
    assert rows[0].actor_id == user.id
    assert rows[0].metadata_ == {"comment_id": created["id"], "post_id": post.id}


async def test_author_cannot_edit_after_24h(client, db_session, cleanup_users, cleanup_categories):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    comment = await _comment(db_session, post, author_id=user.id)
    await _backdate(db_session, comment.id, timedelta(hours=24, minutes=1))
    await login_as(client, user)

    response = await client.patch(_comment_url(comment.id), json={"body_html": "<p>Late.</p>"})

    _assert_error(response, 403, "comments.forbidden")


async def test_admin_edits_any_comment_any_time(
    client, db_session, cleanup_users, cleanup_categories
):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    comment = await _comment(db_session, post, author_id=user.id)
    await _backdate(db_session, comment.id, timedelta(days=30))
    await login_as(client, admin)

    response = await client.patch(
        _comment_url(comment.id), json={"body_html": "<p>Edited by a moderator.</p>"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["body_html"] == "<p>Edited by a moderator.</p>"
    assert response.json()["author"]["id"] == user.id
    assert response.json()["is_edited"] is True
    rows = await _audit(db_session, comment.id, "comment.updated")
    assert [row.actor_id for row in rows] == [admin.id]


async def test_other_member_cannot_edit_or_delete(
    client, db_session, cleanup_users, cleanup_categories
):
    user, post_author, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    comment = await _comment(db_session, post, author_id=user.id)
    # Even the post's author cannot touch someone else's comment.
    await login_as(client, post_author)

    response = await client.patch(_comment_url(comment.id), json={"body_html": "<p>Mine.</p>"})
    _assert_error(response, 403, "comments.forbidden")
    _assert_error(await client.delete(_comment_url(comment.id)), 403, "comments.forbidden")


async def test_update_validation(client, db_session, cleanup_users, cleanup_categories):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    comment = await _comment(db_session, post, author_id=user.id)
    await login_as(client, user)

    url = _comment_url(comment.id)
    _assert_field(await client.patch(url, json={"body_html": "<p> </p>"}), "body_html", "empty")
    _assert_field(
        await client.patch(url, json={"body_html": f"<p>{'b' * 5001}</p>"}), "body_html", "too_long"
    )
    _assert_field(await client.patch(url, json={}), "body_html")


async def test_update_and_delete_unknown_or_deleted_comment_404(
    client, db_session, cleanup_users, cleanup_categories
):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    deleted = await _comment(db_session, post, author_id=user.id, status=ContentStatus.DELETED)
    await login_as(client, user)

    for comment_id in (deleted.id, 9_000_000_000):
        url = _comment_url(comment_id)
        response = await client.patch(url, json={"body_html": "<p>x</p>"})
        _assert_error(response, 404, "comments.not_found")
        _assert_error(await client.delete(url), 404, "comments.not_found")


async def test_update_requires_verified_user(client, db_session, cleanup_users, cleanup_categories):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    comment = await _comment(db_session, post, author_id=user.id)

    response = await client.patch(_comment_url(comment.id), json={"body_html": "<p>x</p>"})
    _assert_error(response, 401, "auth.not_authenticated")
    _assert_error(await client.delete(_comment_url(comment.id)), 401, "auth.not_authenticated")


# --- delete -----------------------------------------------------------------------------------


async def test_author_soft_deletes(client, db_session, cleanup_users, cleanup_categories):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    comment = await _comment(db_session, post, author_id=user.id)
    # Deleting has no time limit.
    await _backdate(db_session, comment.id, timedelta(days=7))
    await login_as(client, user)

    response = await client.delete(_comment_url(comment.id))

    assert response.status_code == 204, response.text
    stored = await _fresh(db_session, comment.id)
    assert stored.status == ContentStatus.DELETED
    assert stored.deleted_at is not None
    assert _ids(await client.get(_comments_url(post.id))) == []

    rows = await _audit(db_session, comment.id, "comment.deleted")
    assert len(rows) == 1
    assert rows[0].actor_id == user.id
    assert rows[0].metadata_ == {"comment_id": comment.id, "post_id": post.id}


async def test_admin_deletes_any_comment(client, db_session, cleanup_users, cleanup_categories):
    user, _, _, post = await _setup(db_session, cleanup_users, cleanup_categories)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    comment = await _comment(db_session, post, author_id=user.id)
    await login_as(client, admin)

    assert (await client.delete(_comment_url(comment.id))).status_code == 204
    assert await _comment_count(client, post) == 0
    rows = await _audit(db_session, comment.id, "comment.deleted")
    assert [row.actor_id for row in rows] == [admin.id]

"""Increment 3c: replies on forum threads - list (thread visibility, one level of nesting,
ordering, placeholders for deleted parents, pagination of top-level replies), create (verified,
thread published and unlocked, parent checks, sanitising, counters, rate limit, audit), update
(author within 24 h or admin; a locked thread blocks the author) and soft delete (author or
admin; children survive).

Every test works in its own forum category; its threads (and their replies, by cascade) go with
``cleanup_forum_categories``. Audit rows by the test's users go with ``cleanup_users``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core import rate_limit
from app.core.config import settings
from app.db.enums import CategoryKind, ContentStatus, HiddenReason
from app.db.models import AuditLog, Category, Reply, Thread, User
from tests.factories import (
    create_admin,
    create_category,
    create_reply,
    create_thread,
    create_user,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
THREADS = f"{API}/threads/"
REPLY_FIELDS = {
    "id",
    "thread_id",
    "parent_reply_id",
    "author",
    "body_html",
    "status",
    "created_at",
    "updated_at",
    "is_edited",
    "children",
}


# --- helpers ----------------------------------------------------------------------------------


@pytest.fixture
def limits(monkeypatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    rate_limit.reset()
    yield
    rate_limit.reset()


def _replies_url(thread_id: int) -> str:
    return f"{THREADS}{thread_id}/replies/"


def _reply_url(reply_id: int) -> str:
    return f"{API}/replies/{reply_id}"


async def _committed(db, cleanup_users, factory=create_verified_user, **kwargs) -> User:
    user = await factory(db, **kwargs)
    cleanup_users.add(user.email)
    await db.commit()
    return user


async def _forum(db, cleanup) -> Category:
    category = await create_category(db, kind=CategoryKind.FORUM)
    cleanup.add(category.id)
    await db.commit()
    return category


async def _thread(db, category: Category, **kwargs) -> Thread:
    thread = await create_thread(db, category_id=category.id, **kwargs)
    await db.commit()
    return thread


async def _reply(db, thread: Thread, **kwargs) -> Reply:
    reply = await create_reply(db, thread_id=thread.id, **kwargs)
    await db.commit()
    return reply


async def _setup(db, cleanup_users, cleanup_forum_categories, **thread_kwargs):
    """A committed verified member, a forum category and a published thread by another member."""
    user = await _committed(db, cleanup_users)
    thread_author = await _committed(db, cleanup_users)
    category = await _forum(db, cleanup_forum_categories)
    thread = await _thread(db, category, author_id=thread_author.id, **thread_kwargs)
    return user, thread_author, category, thread


def _ids(response) -> list[int]:
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def _tree(response) -> list[tuple[int, list[int]]]:
    assert response.status_code == 200, response.text
    return [
        (item["id"], [child["id"] for child in item["children"]])
        for item in response.json()["items"]
    ]


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


async def _create(
    client, thread_id: int, body_html: str = "<p>We tried this too.</p>", parent=None
):
    payload: dict = {"body_html": body_html}
    if parent is not None:
        payload["parent_reply_id"] = parent
    return await client.post(_replies_url(thread_id), json=payload)


async def _thread_detail(client, thread: Thread) -> dict:
    response = await client.get(f"{THREADS}{thread.slug}")
    assert response.status_code == 200, response.text
    return response.json()


async def _backdate(db, reply_id: int, delta: timedelta) -> None:
    then = datetime.now(UTC) - delta
    await db.execute(
        update(Reply).where(Reply.id == reply_id).values(created_at=then, updated_at=then)
    )
    await db.commit()


async def _set_status(db, reply_id: int, status: ContentStatus) -> None:
    values: dict = {"status": status}
    if status == ContentStatus.DELETED:
        values["deleted_at"] = datetime.now(UTC)
    await db.execute(update(Reply).where(Reply.id == reply_id).values(**values))
    await db.commit()


async def _lock(db, thread: Thread) -> None:
    await db.execute(update(Thread).where(Thread.id == thread.id).values(is_locked=True))
    await db.commit()


async def _fresh(db, reply_id: int) -> Reply:
    stmt = select(Reply).where(Reply.id == reply_id)
    return await db.scalar(stmt.execution_options(populate_existing=True))


async def _audit(db, reply_id: int, action: str) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.target_type == "reply",
            AuditLog.target_id == reply_id,
            AuditLog.action == action,
        )
        .order_by(AuditLog.id)
    )
    return list((await db.scalars(stmt)).all())


# --- list -------------------------------------------------------------------------------------


async def test_list_on_published_thread_is_public(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    reply = await _reply(db_session, thread, author_id=user.id, body="Swales work well.")

    response = await client.get(_replies_url(thread.id))

    assert _ids(response) == [reply.id]
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert set(item) == REPLY_FIELDS
    assert item["thread_id"] == thread.id
    assert item["parent_reply_id"] is None
    assert item["status"] == "published"
    assert item["body_html"] == "<p>Swales work well.</p>"
    assert item["is_edited"] is False
    assert item["children"] == []
    assert item["author"]["id"] == user.id
    assert set(item["author"]) == {
        "id",
        "display_name",
        "organisation",
        "avatar_url",
        "has_profile",
    }


async def test_author_has_profile_follows_directory_opt_out(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    await _reply(db_session, thread, author_id=user.id)

    response = await client.get(_replies_url(thread.id))
    assert response.json()["items"][0]["author"]["has_profile"] is True

    user.show_in_directory = False
    await db_session.commit()

    response = await client.get(_replies_url(thread.id))
    assert response.json()["items"][0]["author"]["has_profile"] is False


async def test_list_on_pending_or_missing_thread_404(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    author = await _committed(db_session, cleanup_users)
    category = await _forum(db_session, cleanup_forum_categories)
    thread = await _thread(db_session, category, author_id=author.id, status=ContentStatus.PENDING)

    _assert_error(await client.get(_replies_url(thread.id)), 404, "threads.not_found")
    _assert_error(await client.get(_replies_url(2_000_000_000)), 404, "threads.not_found")

    await login_as(client, author)
    response = await client.get(_replies_url(thread.id))
    assert response.status_code == 200, response.text
    assert response.json() == {"total": 0, "items": []}


async def test_list_on_deleted_thread_200_for_admin_only(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, thread_author, _, thread = await _setup(
        db_session,
        cleanup_users,
        cleanup_forum_categories,
        status=ContentStatus.DELETED,
        deleted_at=datetime.now(UTC),
    )
    reply = await _reply(db_session, thread, author_id=user.id)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)

    _assert_error(await client.get(_replies_url(thread.id)), 404, "threads.not_found")
    for member in (user, thread_author):
        await login_as(client, member)
        _assert_error(await client.get(_replies_url(thread.id)), 404, "threads.not_found")

    await login_as(client, admin)
    assert _ids(await client.get(_replies_url(thread.id))) == [reply.id]


async def test_list_structure_and_ordering(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, other, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    now = datetime.now(UTC)
    second = await _reply(
        db_session, thread, author_id=user.id, created_at=now - timedelta(hours=3)
    )
    first = await _reply(
        db_session, thread, author_id=other.id, created_at=now - timedelta(hours=5)
    )
    late_child = await _reply(
        db_session, thread, author_id=user.id, parent_reply_id=first.id, created_at=now
    )
    early_child = await _reply(
        db_session,
        thread,
        author_id=other.id,
        parent_reply_id=first.id,
        created_at=now - timedelta(hours=4),
    )
    # A hidden child is invisible to the public.
    await _reply(
        db_session,
        thread,
        author_id=other.id,
        parent_reply_id=first.id,
        status=ContentStatus.HIDDEN,
        hidden_reason=HiddenReason.ADMIN,
    )

    response = await client.get(_replies_url(thread.id))

    assert _tree(response) == [(first.id, [early_child.id, late_child.id]), (second.id, [])]
    assert response.json()["total"] == 2
    child = response.json()["items"][0]["children"][0]
    assert set(child) == REPLY_FIELDS
    assert child["parent_reply_id"] == first.id
    assert child["children"] == []
    assert child["author"]["id"] == other.id


async def test_deleted_parent_with_children_is_a_placeholder(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, other, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    now = datetime.now(UTC)
    parent = await _reply(
        db_session, thread, author_id=user.id, created_at=now - timedelta(hours=2)
    )
    child = await _reply(db_session, thread, author_id=other.id, parent_reply_id=parent.id)
    lonely = await _reply(
        db_session, thread, author_id=user.id, created_at=now - timedelta(hours=1)
    )
    # Its only child is deleted too: nothing left to show.
    parent_of_deleted = await _reply(
        db_session, thread, author_id=user.id, created_at=now - timedelta(minutes=30)
    )
    dead_child = await _reply(
        db_session, thread, author_id=other.id, parent_reply_id=parent_of_deleted.id
    )
    for reply_id in (parent.id, lonely.id, parent_of_deleted.id, dead_child.id):
        await _set_status(db_session, reply_id, ContentStatus.DELETED)

    response = await client.get(_replies_url(thread.id))

    assert _tree(response) == [(parent.id, [child.id])]
    assert response.json()["total"] == 1
    placeholder = response.json()["items"][0]
    assert placeholder["status"] == "deleted"
    assert placeholder["body_html"] == ""
    assert placeholder["author"] is None
    assert placeholder["children"][0]["body_html"] != ""


async def test_list_pagination_counts_top_level_only(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    now = datetime.now(UTC)
    tops = [
        await _reply(db_session, thread, author_id=user.id, created_at=now - timedelta(hours=h))
        for h in (3, 2, 1)
    ]
    children = [
        await _reply(db_session, thread, author_id=user.id, parent_reply_id=tops[1].id)
        for _ in range(2)
    ]

    response = await client.get(_replies_url(thread.id), params={"skip": 1, "limit": 1})

    assert _tree(response) == [(tops[1].id, [c.id for c in children])]
    assert response.json()["total"] == 3
    assert (await client.get(_replies_url(thread.id), params={"limit": 50})).status_code == 200
    _assert_field(await client.get(_replies_url(thread.id), params={"limit": 51}), "query.limit")


# --- create -----------------------------------------------------------------------------------


async def test_create_requires_verified_user(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    _, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    _assert_error(await _create(client, thread.id), 401, "auth.not_authenticated")

    unverified = await _committed(db_session, cleanup_users, factory=create_user)
    await login_as(client, unverified)
    _assert_error(await _create(client, thread.id), 403, "auth.email_not_verified")


async def test_create_reply_and_nested_reply(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    await login_as(client, user)

    response = await _create(client, thread.id, "<p>Top level.</p>")
    assert response.status_code == 201, response.text
    top = response.json()
    assert set(top) == REPLY_FIELDS
    assert top["thread_id"] == thread.id
    assert top["parent_reply_id"] is None
    assert top["status"] == "published"
    assert top["author"]["id"] == user.id
    assert top["body_html"] == "<p>Top level.</p>"
    assert top["children"] == []
    assert top["is_edited"] is False
    stored = await _fresh(db_session, top["id"])
    assert stored.body_text == "Top level."

    response = await _create(client, thread.id, "<p>Nested.</p>", parent=top["id"])
    assert response.status_code == 201, response.text
    nested = response.json()
    assert nested["parent_reply_id"] == top["id"]

    client.cookies.clear()
    assert _tree(await client.get(_replies_url(thread.id))) == [(top["id"], [nested["id"]])]


async def test_create_on_pending_thread(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, thread_author, _, thread = await _setup(
        db_session, cleanup_users, cleanup_forum_categories, status=ContentStatus.PENDING
    )
    await login_as(client, user)
    _assert_error(await _create(client, thread.id), 404, "threads.not_found")
    _assert_error(await _create(client, 2_000_000_000), 404, "threads.not_found")

    client.cookies.clear()
    await login_as(client, thread_author)
    _assert_error(await _create(client, thread.id), 422, "threads.not_published")


async def test_nobody_can_reply_to_a_deleted_thread(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, thread_author, _, thread = await _setup(
        db_session,
        cleanup_users,
        cleanup_forum_categories,
        status=ContentStatus.DELETED,
        deleted_at=datetime.now(UTC),
    )
    reply = await _reply(db_session, thread, author_id=user.id)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)

    for member in (user, thread_author, admin):
        await login_as(client, member)
        _assert_error(await _create(client, thread.id), 404, "threads.not_found")
        _assert_error(await _create(client, thread.id, parent=reply.id), 404, "threads.not_found")


async def test_create_on_locked_thread_423_for_member_and_admin(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    await _lock(db_session, thread)

    await login_as(client, user)
    _assert_error(await _create(client, thread.id), 423, "threads.locked")
    client.cookies.clear()
    await login_as(client, admin)
    _assert_error(await _create(client, thread.id), 423, "threads.locked")


async def test_create_with_invalid_parent_422(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, other, category, thread = await _setup(
        db_session, cleanup_users, cleanup_forum_categories
    )
    elsewhere = await _thread(db_session, category, author_id=other.id)
    foreign = await _reply(db_session, elsewhere, author_id=other.id)
    top = await _reply(db_session, thread, author_id=other.id)
    child = await _reply(db_session, thread, author_id=other.id, parent_reply_id=top.id)
    deleted = await _reply(db_session, thread, author_id=other.id, status=ContentStatus.DELETED)
    hidden = await _reply(
        db_session,
        thread,
        author_id=other.id,
        status=ContentStatus.HIDDEN,
        hidden_reason=HiddenReason.ADMIN,
    )
    await login_as(client, user)

    for parent in (foreign.id, child.id, deleted.id, hidden.id, 9_000_000_000):
        response = await _create(client, thread.id, parent=parent)
        _assert_field(response, "parent_reply_id", "invalid")
    assert (await _create(client, thread.id, parent=top.id)).status_code == 201


async def test_body_is_sanitised(client, db_session, cleanup_users, cleanup_forum_categories):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    await login_as(client, user)

    response = await _create(
        client,
        thread.id,
        '<p onclick="x()">See <a href="https://example.org">this</a></p>'
        '<img src="https://example.org/a.png" alt="a"><script>alert(1)</script>',
    )

    assert response.status_code == 201, response.text
    html = response.json()["body_html"]
    assert "<img" not in html
    assert "<script" not in html and "alert" not in html
    assert "onclick" not in html
    assert 'rel="nofollow noopener noreferrer"' in html


@pytest.mark.parametrize(
    "html", ["", "   ", "<script>alert(1)</script>", "<p> </p>", '<img src="https://e.org/a.png">']
)
async def test_empty_body_rejected(
    client, db_session, cleanup_users, cleanup_forum_categories, html
):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    await login_as(client, user)

    _assert_field(await _create(client, thread.id, html), "body_html", "empty")


async def test_body_text_length_limit(client, db_session, cleanup_users, cleanup_forum_categories):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    await login_as(client, user)

    ok = await _create(client, thread.id, f"<p>{'a' * 10_000}</p>")
    assert ok.status_code == 201, ok.text
    too_long = await _create(client, thread.id, f"<p>{'a' * 10_001}</p>")
    _assert_field(too_long, "body_html", "too_long")
    _assert_field(await client.post(_replies_url(thread.id), json={}), "body_html")


async def test_counters_move_on_create_and_delete(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    long_ago = datetime.now(UTC) - timedelta(days=3)
    user, _, _, thread = await _setup(
        db_session, cleanup_users, cleanup_forum_categories, last_activity_at=long_ago
    )
    await login_as(client, user)
    before = await _thread_detail(client, thread)
    assert before["reply_count"] == 0

    first = (await _create(client, thread.id)).json()
    await _create(client, thread.id, parent=first["id"])

    after = await _thread_detail(client, thread)
    assert after["reply_count"] == 2
    assert datetime.fromisoformat(after["last_activity_at"]) > long_ago + timedelta(days=2)

    assert (await client.delete(_reply_url(first["id"]))).status_code == 204
    assert (await _thread_detail(client, thread))["reply_count"] == 1


async def test_create_rate_limited(
    client, db_session, cleanup_users, cleanup_forum_categories, limits
):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    await login_as(client, user)

    # Rejected requests count too.
    url = _replies_url(thread.id)
    statuses = [(await client.post(url, json={})).status_code for _ in range(60)]
    assert statuses == [422] * 60

    _assert_error(await _create(client, thread.id), 429, "rate.limited")


async def test_create_writes_audit_row(client, db_session, cleanup_users, cleanup_forum_categories):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    await login_as(client, user)

    top = (await _create(client, thread.id)).json()
    nested = (await _create(client, thread.id, parent=top["id"])).json()

    rows = await _audit(db_session, nested["id"], "reply.created")
    assert len(rows) == 1
    assert rows[0].actor_id == user.id
    assert rows[0].metadata_ == {
        "reply_id": nested["id"],
        "thread_id": thread.id,
        "parent_reply_id": top["id"],
    }


# --- update -----------------------------------------------------------------------------------


async def test_author_edits_within_24h(client, db_session, cleanup_users, cleanup_forum_categories):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    await login_as(client, user)
    created = (await _create(client, thread.id, "<p>First version.</p>")).json()
    await _backdate(db_session, created["id"], timedelta(hours=23))

    response = await client.patch(
        _reply_url(created["id"]),
        json={"body_html": '<p>Second version.</p><img src="https://e.org/x.png">'},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == REPLY_FIELDS
    assert body["body_html"] == "<p>Second version.</p>"
    assert body["is_edited"] is True
    assert body["author"]["id"] == user.id
    stored = await _fresh(db_session, created["id"])
    assert stored.body_text == "Second version."

    rows = await _audit(db_session, created["id"], "reply.updated")
    assert len(rows) == 1
    assert rows[0].actor_id == user.id
    assert rows[0].metadata_ == {
        "reply_id": created["id"],
        "thread_id": thread.id,
        "parent_reply_id": None,
    }


async def test_author_cannot_edit_after_24h(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    reply = await _reply(db_session, thread, author_id=user.id)
    await _backdate(db_session, reply.id, timedelta(hours=24, minutes=1))
    await login_as(client, user)

    response = await client.patch(_reply_url(reply.id), json={"body_html": "<p>Late.</p>"})

    _assert_error(response, 403, "replies.forbidden")


async def test_admin_edits_any_reply_any_time(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    reply = await _reply(db_session, thread, author_id=user.id)
    await _backdate(db_session, reply.id, timedelta(days=30))
    await _lock(db_session, thread)
    await login_as(client, admin)

    response = await client.patch(
        _reply_url(reply.id), json={"body_html": "<p>Edited by a moderator.</p>"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["body_html"] == "<p>Edited by a moderator.</p>"
    assert response.json()["author"]["id"] == user.id
    rows = await _audit(db_session, reply.id, "reply.updated")
    assert [row.actor_id for row in rows] == [admin.id]


async def test_locked_thread_blocks_author_edit(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    reply = await _reply(db_session, thread, author_id=user.id)
    await _lock(db_session, thread)
    await login_as(client, user)

    response = await client.patch(_reply_url(reply.id), json={"body_html": "<p>Changed.</p>"})

    _assert_error(response, 423, "threads.locked")


async def test_other_member_cannot_edit_or_delete(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, thread_author, _, thread = await _setup(
        db_session, cleanup_users, cleanup_forum_categories
    )
    reply = await _reply(db_session, thread, author_id=user.id)
    # Even the thread's author cannot touch someone else's reply.
    await login_as(client, thread_author)

    response = await client.patch(_reply_url(reply.id), json={"body_html": "<p>Mine.</p>"})
    _assert_error(response, 403, "replies.forbidden")
    _assert_error(await client.delete(_reply_url(reply.id)), 403, "replies.forbidden")


async def test_update_validation_and_unknown_reply(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    reply = await _reply(db_session, thread, author_id=user.id)
    deleted = await _reply(db_session, thread, author_id=user.id, status=ContentStatus.DELETED)
    await login_as(client, user)

    url = _reply_url(reply.id)
    _assert_field(await client.patch(url, json={"body_html": "<p> </p>"}), "body_html", "empty")
    _assert_field(await client.patch(url, json={}), "body_html")
    for reply_id in (deleted.id, 9_000_000_000):
        response = await client.patch(_reply_url(reply_id), json={"body_html": "<p>x</p>"})
        _assert_error(response, 404, "replies.not_found")
        _assert_error(await client.delete(_reply_url(reply_id)), 404, "replies.not_found")

    client.cookies.clear()
    response = await client.patch(url, json={"body_html": "<p>x</p>"})
    _assert_error(response, 401, "auth.not_authenticated")


# --- delete -----------------------------------------------------------------------------------


async def test_author_deletes_parent_children_survive(
    client, db_session, cleanup_users, cleanup_forum_categories
):
    user, other, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    parent = await _reply(db_session, thread, author_id=user.id)
    child = await _reply(db_session, thread, author_id=other.id, parent_reply_id=parent.id)
    await _backdate(db_session, parent.id, timedelta(days=7))
    await login_as(client, user)

    response = await client.delete(_reply_url(parent.id))

    assert response.status_code == 204, response.text
    stored = await _fresh(db_session, parent.id)
    assert stored.status == ContentStatus.DELETED
    assert stored.deleted_at is not None
    kept = await _fresh(db_session, child.id)
    assert kept.status == ContentStatus.PUBLISHED
    assert kept.parent_reply_id == parent.id

    listing = await client.get(_replies_url(thread.id))
    assert _tree(listing) == [(parent.id, [child.id])]
    assert listing.json()["items"][0]["status"] == "deleted"
    assert listing.json()["items"][0]["author"] is None

    rows = await _audit(db_session, parent.id, "reply.deleted")
    assert len(rows) == 1
    assert rows[0].actor_id == user.id
    assert rows[0].metadata_ == {
        "reply_id": parent.id,
        "thread_id": thread.id,
        "parent_reply_id": None,
    }


async def test_admin_deletes_any_reply(client, db_session, cleanup_users, cleanup_forum_categories):
    user, _, _, thread = await _setup(db_session, cleanup_users, cleanup_forum_categories)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    reply = await _reply(db_session, thread, author_id=user.id)
    await login_as(client, admin)

    assert (await client.delete(_reply_url(reply.id))).status_code == 204
    assert (await _thread_detail(client, thread))["reply_count"] == 0
    assert _ids(await client.get(_replies_url(thread.id))) == []
    rows = await _audit(db_session, reply.id, "reply.deleted")
    assert [row.actor_id for row in rows] == [admin.id]

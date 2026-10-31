"""Increment 4d: admin moderation endpoints - the pending queue, the six content actions and the
moderation log - and their permission matrix.

Rows are committed (the app uses its own sessions). Users go through ``cleanup_users`` (which
also removes the audit rows they wrote or that are about them), content through categories
registered with ``cleanup_forum_categories`` (threads first, then posts with their comments),
and actor-less audit rows through the local ``audit_ids`` fixture.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.crud.audit import log_action
from app.db.enums import CategoryKind, ContentStatus, ContentType, HiddenReason
from app.db.models import AuditLog, User
from tests.factories import (
    create_admin,
    create_category,
    create_comment,
    create_post,
    create_reply,
    create_superadmin,
    create_thread,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
MOD = f"{API}/moderation"
QUEUE = f"{MOD}/queue/"
LOG = f"{MOD}/log/"

P = ContentStatus.PENDING
PUB = ContentStatus.PUBLISHED
H = ContentStatus.HIDDEN
D = ContentStatus.DELETED
ACTIONS = ("approve", "reject", "hide", "unhide", "delete", "restore")
# Long ago, so this test's pending items come first in the (global) queue.
OLD = datetime(2001, 1, 1, tzinfo=UTC)


# --- fixtures and helpers ---------------------------------------------------------------------


@pytest.fixture
async def audit_ids(database_url: str) -> AsyncIterator[set[int]]:
    """Ids of audit rows the test commits that no user cleanup would remove (no actor)."""
    from app.db.session import AsyncSessionLocal

    ids: set[int] = set()
    yield ids
    if not ids:
        return
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(delete(AuditLog).where(AuditLog.id.in_(ids)))


@pytest.fixture
def env(db_session, cleanup_users, cleanup_forum_categories):
    class Env:
        db = db_session
        users = cleanup_users
        categories = cleanup_forum_categories

    return Env


async def _user(env, factory=create_verified_user, **kwargs) -> User:
    user = await factory(env.db, **kwargs)
    env.users.add(user.email)
    await env.db.commit()
    return user


async def _signed_in(client, env, factory=create_admin, **kwargs) -> User:
    user = await _user(env, factory=factory, **kwargs)
    await login_as(client, user)
    return user


async def _make(env, content_type: ContentType, status: ContentStatus, *, author_id=None, **kw):
    """A committed post/thread/reply/comment in ``status`` (hidden by an admin; deleted ones had
    been published) in a fresh category."""
    db = env.db
    extra: dict = dict(kw)
    if status == H:
        extra.setdefault("hidden_reason", HiddenReason.ADMIN)
    if status == D:
        extra["deleted_at"] = datetime.now(UTC) - timedelta(days=1)
    kind = (
        CategoryKind.BLOG
        if content_type in (ContentType.POST, ContentType.COMMENT)
        else CategoryKind.FORUM
    )
    category = await create_category(db, kind=kind)
    env.categories.add(category.id)
    if content_type == ContentType.POST:
        obj = await create_post(
            db, category_id=category.id, status=status, author_id=author_id, **extra
        )
    elif content_type == ContentType.THREAD:
        obj = await create_thread(
            db, category_id=category.id, status=status, author_id=author_id, **extra
        )
    elif content_type == ContentType.COMMENT:
        post = await create_post(db, category_id=category.id)
        obj = await create_comment(db, post_id=post.id, status=status, author_id=author_id, **extra)
    else:
        thread = await create_thread(db, category_id=category.id)
        obj = await create_reply(
            db, thread_id=thread.id, status=status, author_id=author_id, **extra
        )
    if content_type in (ContentType.POST, ContentType.THREAD) and status in (H, D):
        obj.published_at = datetime.now(UTC) - timedelta(days=2)
    await db.flush()
    await db.commit()
    return obj


def _action_url(content_type: ContentType | str, content_id: int, action: str) -> str:
    return f"{MOD}/{content_type}/{content_id}/{action}"


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


async def _audits(db, *, target_type: str, target_id: int, action: str | None = None):
    stmt = select(AuditLog).where(
        AuditLog.target_type == target_type, AuditLog.target_id == target_id
    )
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    return list((await db.scalars(stmt.order_by(AuditLog.id))).all())


async def _reload_user(db, user_id: int) -> User:
    stmt = select(User).where(User.id == user_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


# --- permission matrix ------------------------------------------------------------------------


async def test_queue_requires_login(client):
    _assert_error(await client.get(QUEUE), 401, "auth.not_authenticated")


async def test_log_requires_login(client):
    _assert_error(await client.get(LOG), 401, "auth.not_authenticated")


@pytest.mark.parametrize("action", ACTIONS)
async def test_actions_require_login(client, env, action):
    post = await _make(env, ContentType.POST, P)
    _assert_error(
        await client.post(_action_url("post", post.id, action)), 401, "auth.not_authenticated"
    )


async def test_queue_and_log_forbidden_for_member(client, env):
    await _signed_in(client, env, factory=create_verified_user)
    _assert_error(await client.get(QUEUE), 403, "auth.forbidden")
    _assert_error(await client.get(LOG), 403, "auth.forbidden")


@pytest.mark.parametrize("action", ACTIONS)
async def test_actions_forbidden_for_member(client, env, action):
    post = await _make(env, ContentType.POST, P)
    await _signed_in(client, env, factory=create_verified_user)

    _assert_error(await client.post(_action_url("post", post.id, action)), 403, "auth.forbidden")

    await env.db.refresh(post)
    assert post.status == P


@pytest.mark.parametrize("factory", [create_admin, create_superadmin])
async def test_queue_and_log_allowed_for_admins(client, env, factory):
    await _signed_in(client, env, factory=factory)
    assert (await client.get(QUEUE)).status_code == 200
    assert (await client.get(LOG)).status_code == 200


@pytest.mark.parametrize("factory", [create_admin, create_superadmin])
async def test_action_allowed_for_admins(client, env, factory):
    post = await _make(env, ContentType.POST, P)
    await _signed_in(client, env, factory=factory)

    response = await client.post(_action_url("post", post.id, "approve"))

    assert response.status_code == 200, response.text


# --- queue ------------------------------------------------------------------------------------


async def test_queue_mixes_posts_and_threads_oldest_first(client, env):
    author = await _user(env, display_name="Queue Author")
    newest = await _make(
        env, ContentType.POST, P, author_id=author.id, created_at=OLD + timedelta(hours=3)
    )
    middle = await _make(
        env, ContentType.THREAD, P, author_id=author.id, created_at=OLD + timedelta(hours=2)
    )
    oldest = await _make(
        env, ContentType.POST, P, author_id=author.id, created_at=OLD + timedelta(hours=1)
    )
    await _make(env, ContentType.POST, PUB, author_id=author.id, created_at=OLD)
    await _signed_in(client, env)

    response = await client.get(QUEUE)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 3
    first = [(item["content_type"], item["id"]) for item in body["items"][:3]]
    assert first == [("post", oldest.id), ("thread", middle.id), ("post", newest.id)]


async def test_queue_item_shape(client, env):
    author = await _user(env, display_name="Shape Author")
    thread = await _make(
        env, ContentType.THREAD, P, author_id=author.id, created_at=OLD, body_text="x" * 300
    )
    await _signed_in(client, env)

    item = (await client.get(QUEUE)).json()["items"][0]

    await env.db.refresh(thread, ["category"])
    assert item == {
        "content_type": "thread",
        "id": thread.id,
        "title": thread.title,
        "slug": thread.slug,
        "excerpt": "x" * 200,
        "locale": "en",
        "author": {"id": author.id, "display_name": "Shape Author", "trusted": False},
        "category": {
            "id": thread.category.id,
            "name": thread.category.name,
            "slug": thread.category.slug,
        },
        "created_at": item["created_at"],
        "resubmitted": False,
    }
    assert datetime.fromisoformat(item["created_at"]) == OLD


async def test_queue_item_without_author(client, env):
    await _make(env, ContentType.POST, P, created_at=OLD)
    await _signed_in(client, env)

    item = (await client.get(QUEUE)).json()["items"][0]

    assert item["author"] is None


async def test_queue_pagination(client, env):
    made = [
        await _make(env, ContentType.POST, P, created_at=OLD + timedelta(minutes=i))
        for i in range(3)
    ]
    await _signed_in(client, env)

    page1 = (await client.get(QUEUE, params={"limit": 2})).json()
    page2 = (await client.get(QUEUE, params={"skip": 2, "limit": 1})).json()

    assert [i["id"] for i in page1["items"]] == [made[0].id, made[1].id]
    assert [i["id"] for i in page2["items"]] == [made[2].id]
    assert page1["total"] == page2["total"] >= 3


async def test_queue_rejects_bad_pagination(client, env):
    await _signed_in(client, env)
    assert (await client.get(QUEUE, params={"limit": 0})).status_code == 422
    assert (await client.get(QUEUE, params={"skip": -1})).status_code == 422


# --- actions ----------------------------------------------------------------------------------


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
async def test_approve_publishes_and_trusts_author(client, env, content_type):
    author = await _user(env)
    content = await _make(env, content_type, P, author_id=author.id)
    admin = await _signed_in(client, env)

    response = await client.post(_action_url(content_type, content.id, "approve"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content_type"] == content_type.value
    assert body["id"] == content.id
    assert body["status"] == "published"
    assert body["hidden_reason"] is None
    assert body["published_at"] is not None
    assert body["deleted_at"] is None
    assert body["author_trusted"] is True
    assert (await _reload_user(env.db, author.id)).trusted_at is not None
    (row,) = await _audits(
        env.db, target_type=content_type.value, target_id=content.id, action="moderation.approve"
    )
    assert row.actor_id == admin.id


async def test_approve_without_author(client, env):
    post = await _make(env, ContentType.POST, P)
    await _signed_in(client, env)

    body = (await client.post(_action_url("post", post.id, "approve"))).json()

    assert body["status"] == "published"
    assert body["author_trusted"] is False


async def test_approve_published_post_is_409(client, env):
    post = await _make(env, ContentType.POST, PUB)
    await _signed_in(client, env)

    _assert_error(
        await client.post(_action_url("post", post.id, "approve")),
        409,
        "moderation.invalid_transition",
    )


@pytest.mark.parametrize("content_type", [ContentType.REPLY, ContentType.COMMENT])
@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_review_actions_on_replies_and_comments_are_409(client, env, content_type, action):
    content = await _make(env, content_type, PUB)
    await _signed_in(client, env)

    _assert_error(
        await client.post(_action_url(content_type, content.id, action)),
        409,
        "moderation.invalid_transition",
    )
    assert await _audits(env.db, target_type=content_type.value, target_id=content.id) == []


@pytest.mark.parametrize("action", ACTIONS)
async def test_unknown_content_is_404(client, env, action):
    await _signed_in(client, env)
    _assert_error(
        await client.post(_action_url("post", 2_000_000_000, action)),
        404,
        "moderation.content_not_found",
    )


@pytest.mark.parametrize("content_type", ["post", "thread", "reply"])
async def test_id_beyond_integer_range_is_404(client, env, content_type):
    await _signed_in(client, env)
    _assert_error(
        await client.post(_action_url(content_type, 3_000_000_000, "hide")),
        404,
        "moderation.content_not_found",
    )


async def test_unknown_content_type_is_422(client, env):
    await _signed_in(client, env)
    response = await client.post(_action_url("user", 1, "approve"))
    assert response.status_code == 422


async def test_reject_with_reason_lands_in_audit(client, env):
    author = await _user(env)
    post = await _make(env, ContentType.POST, P, author_id=author.id)
    await _signed_in(client, env)

    response = await client.post(
        _action_url("post", post.id, "reject"), json={"reason": "Off-topic advertising"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "hidden"
    assert body["hidden_reason"] == "rejected"
    assert body["author_trusted"] is False
    (row,) = await _audits(
        env.db, target_type="post", target_id=post.id, action="moderation.reject"
    )
    assert row.metadata_["reason"] == "Off-topic advertising"


async def test_reject_without_body(client, env):
    thread = await _make(env, ContentType.THREAD, P)
    await _signed_in(client, env)

    response = await client.post(_action_url("thread", thread.id, "reject"))

    assert response.status_code == 200, response.text
    (row,) = await _audits(
        env.db, target_type="thread", target_id=thread.id, action="moderation.reject"
    )
    assert "reason" not in row.metadata_


async def test_reason_longer_than_500_is_422(client, env):
    post = await _make(env, ContentType.POST, P)
    await _signed_in(client, env)

    response = await client.post(_action_url("post", post.id, "reject"), json={"reason": "x" * 501})

    assert response.status_code == 422
    await env.db.refresh(post)
    assert post.status == P


@pytest.mark.parametrize(
    "content_type",
    [ContentType.POST, ContentType.THREAD, ContentType.REPLY, ContentType.COMMENT],
)
async def test_hide_unhide_round_trip(client, env, content_type):
    content = await _make(env, content_type, PUB)
    await _signed_in(client, env)

    hidden = await client.post(
        _action_url(content_type, content.id, "hide"), json={"reason": "abusive"}
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["status"] == "hidden"
    assert hidden.json()["hidden_reason"] == "admin"
    (row,) = await _audits(
        env.db, target_type=content_type.value, target_id=content.id, action="moderation.hide"
    )
    assert row.metadata_["reason"] == "abusive"

    shown = await client.post(_action_url(content_type, content.id, "unhide"))
    assert shown.status_code == 200, shown.text
    assert shown.json()["status"] == "published"
    assert shown.json()["hidden_reason"] is None


@pytest.mark.parametrize(
    "content_type",
    [ContentType.POST, ContentType.THREAD, ContentType.REPLY, ContentType.COMMENT],
)
async def test_delete_restore_round_trip(client, env, content_type):
    content = await _make(env, content_type, PUB)
    await _signed_in(client, env)

    deleted = await client.post(_action_url(content_type, content.id, "delete"))
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "deleted"
    assert deleted.json()["deleted_at"] is not None

    restored = await client.post(_action_url(content_type, content.id, "restore"))
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "published"
    assert restored.json()["deleted_at"] is None


async def test_reply_response_has_no_published_at(client, env):
    reply = await _make(env, ContentType.REPLY, PUB)
    await _signed_in(client, env)

    body = (await client.post(_action_url("reply", reply.id, "hide"))).json()

    assert body["published_at"] is None


async def test_restore_never_approved_goes_back_to_pending(client, env):
    post = await _make(env, ContentType.POST, P)
    await _signed_in(client, env)

    assert (await client.post(_action_url("post", post.id, "delete"))).status_code == 200
    body = (await client.post(_action_url("post", post.id, "restore"))).json()

    assert body["status"] == "pending"


async def test_unhide_pending_is_409(client, env):
    post = await _make(env, ContentType.POST, P)
    await _signed_in(client, env)

    _assert_error(
        await client.post(_action_url("post", post.id, "unhide")),
        409,
        "moderation.invalid_transition",
    )


async def test_restore_published_is_409(client, env):
    comment = await _make(env, ContentType.COMMENT, PUB)
    await _signed_in(client, env)

    _assert_error(
        await client.post(_action_url("comment", comment.id, "restore")),
        409,
        "moderation.invalid_transition",
    )


# --- log --------------------------------------------------------------------------------------


async def test_log_newest_first_with_actor(client, env):
    post = await _make(env, ContentType.POST, PUB)
    admin = await _signed_in(client, env, display_name="Log Admin")
    await client.post(_action_url("post", post.id, "hide"))
    await client.post(_action_url("post", post.id, "unhide"))

    body = (await client.get(LOG, params={"actor_id": admin.id, "action": "moderation."})).json()

    assert body["total"] == 2
    first, second = body["items"]
    assert first["action"] == "moderation.unhide"
    assert second["action"] == "moderation.hide"
    assert first["actor"] == {"id": admin.id, "display_name": "Log Admin"}
    assert first["target_type"] == "post"
    assert first["target_id"] == post.id
    assert first["metadata"] == {"from": "hidden", "to": "published"}
    assert first["created_at"] >= second["created_at"]
    assert first["id"] > second["id"]


async def test_log_action_prefix_and_exact_filters(client, env):
    target = await _user(env)
    post = await _make(env, ContentType.POST, PUB)
    admin = await _signed_in(client, env)
    await client.post(_action_url("post", post.id, "hide"))
    await client.post(f"{API}/admin/users/{target.id}/trust")

    everything = (await client.get(LOG, params={"actor_id": admin.id})).json()
    moderation_only = (
        await client.get(LOG, params={"actor_id": admin.id, "action": "moderation."})
    ).json()
    exact = (await client.get(LOG, params={"actor_id": admin.id, "action": "admin.trust"})).json()
    partial = (await client.get(LOG, params={"actor_id": admin.id, "action": "admin.tr"})).json()

    # The admin's own sign-in is audited too (``auth.login``).
    assert {i["action"] for i in everything["items"]} == {
        "auth.login",
        "moderation.hide",
        "admin.trust",
    }
    assert [i["action"] for i in moderation_only["items"]] == ["moderation.hide"]
    assert [i["action"] for i in exact["items"]] == ["admin.trust"]
    assert partial["total"] == 0


async def test_log_target_type_filter(client, env):
    target = await _user(env)
    post = await _make(env, ContentType.POST, PUB)
    admin = await _signed_in(client, env)
    await client.post(_action_url("post", post.id, "hide"))
    await client.post(f"{API}/admin/users/{target.id}/trust")

    users = (await client.get(LOG, params={"actor_id": admin.id, "target_type": "user"})).json()
    posts = (await client.get(LOG, params={"actor_id": admin.id, "target_type": "post"})).json()

    assert [(i["action"], i["target_id"]) for i in users["items"]] == [
        ("admin.trust", target.id),
        ("auth.login", admin.id),
    ]
    assert [(i["action"], i["target_id"]) for i in posts["items"]] == [("moderation.hide", post.id)]


async def test_log_actor_null_for_automatic_actions(client, env, audit_ids):
    marker = f"auto-{uuid.uuid4().hex[:8]}"
    row = await log_action(
        env.db,
        actor_id=None,
        action="moderation.auto_hidden",
        target_type="post",
        target_id=2_000_000_001,
        metadata={"marker": marker},
    )
    audit_ids.add(row.id)
    await env.db.commit()
    await _signed_in(client, env)

    body = (await client.get(LOG, params={"action": "moderation.auto_hidden", "limit": 200})).json()

    (item,) = [i for i in body["items"] if i["metadata"].get("marker") == marker]
    assert item["actor"] is None
    assert item["id"] == row.id


async def test_log_pagination(client, env):
    post = await _make(env, ContentType.POST, PUB)
    admin = await _signed_in(client, env)
    for action in ("hide", "unhide", "delete"):
        assert (await client.post(_action_url("post", post.id, action))).status_code == 200

    page = (
        await client.get(
            LOG, params={"actor_id": admin.id, "action": "moderation.", "skip": 1, "limit": 1}
        )
    ).json()

    assert page["total"] == 3
    assert [i["action"] for i in page["items"]] == ["moderation.unhide"]


# --- 5o: rejection note and resubmission ------------------------------------------------------


async def _rejected_by_admin(client, env, content_type=ContentType.POST, *, reason="Add sources."):
    """A post/thread by a fresh verified author, rejected through the API by a fresh admin (the
    client is left signed in as that admin). Returns ``(author, content)``."""
    author = await _user(env)
    content = await _make(env, content_type, P, author_id=author.id)
    await _signed_in(client, env)
    response = await client.post(
        _action_url(content_type, content.id, "reject"), json={"reason": reason}
    )
    assert response.status_code == 200, response.text
    return author, content


def _detail_url(content_type: ContentType, slug: str) -> str:
    return f"{API}/posts/{slug}" if content_type == ContentType.POST else f"{API}/threads/{slug}"


async def test_resubmit_requires_login(client, env):
    post = await _make(env, ContentType.POST, H, hidden_reason=HiddenReason.REJECTED)
    _assert_error(
        await client.post(_action_url("post", post.id, "resubmit")),
        401,
        "auth.not_authenticated",
    )


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
async def test_reject_stores_note_shown_to_the_author(client, env, content_type):
    author, content = await _rejected_by_admin(client, env, content_type, reason="Add a map.")
    await login_as(client, author)

    detail = (await client.get(_detail_url(content_type, content.slug))).json()

    assert detail["status"] == "hidden"
    assert detail["hidden_reason"] == "rejected"
    assert detail["moderation_note"] == "Add a map."


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
async def test_author_resubmits_rejected_item(client, env, content_type):
    author, content = await _rejected_by_admin(client, env, content_type, reason="Add a map.")
    await login_as(client, author)

    response = await client.post(_action_url(content_type, content.id, "resubmit"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["hidden_reason"] is None
    assert body["published_at"] is None
    assert body["author_trusted"] is False
    await env.db.refresh(content)
    assert content.status == P
    assert content.moderation_note == "Add a map."
    (row,) = await _audits(
        env.db, target_type=content_type.value, target_id=content.id, action="moderation.resubmit"
    )
    assert row.actor_id == author.id
    assert row.metadata_ == {"from": "hidden", "to": "pending"}
    detail = (await client.get(_detail_url(content_type, content.slug))).json()
    assert detail["status"] == "pending"
    assert detail["moderation_note"] == "Add a map."


async def test_resubmit_twice_is_409(client, env):
    author, post = await _rejected_by_admin(client, env)
    await login_as(client, author)
    assert (await client.post(_action_url("post", post.id, "resubmit"))).status_code == 200

    _assert_error(
        await client.post(_action_url("post", post.id, "resubmit")),
        409,
        "moderation.invalid_transition",
    )


async def test_resubmit_published_own_item_is_409(client, env):
    author = await _signed_in(client, env, factory=create_verified_user)
    post = await _make(env, ContentType.POST, PUB, author_id=author.id)

    _assert_error(
        await client.post(_action_url("post", post.id, "resubmit")),
        409,
        "moderation.invalid_transition",
    )


async def test_resubmit_by_another_member_is_404(client, env):
    _, post = await _rejected_by_admin(client, env)
    await _signed_in(client, env, factory=create_verified_user)

    _assert_error(
        await client.post(_action_url("post", post.id, "resubmit")),
        404,
        "moderation.content_not_found",
    )
    await env.db.refresh(post)
    assert post.status == H


@pytest.mark.parametrize("factory", [create_admin, create_superadmin])
async def test_resubmit_by_admin_on_someone_elses_item_is_403(client, env, factory):
    _, thread = await _rejected_by_admin(client, env, ContentType.THREAD)
    await _signed_in(client, env, factory=factory)

    _assert_error(
        await client.post(_action_url("thread", thread.id, "resubmit")), 403, "auth.forbidden"
    )
    await env.db.refresh(thread)
    assert thread.status == H


async def test_resubmit_unknown_content_is_404(client, env):
    await _signed_in(client, env, factory=create_verified_user)
    _assert_error(
        await client.post(_action_url("post", 2**31 - 1, "resubmit")),
        404,
        "moderation.content_not_found",
    )


async def test_resubmit_unverified_member_is_403(client, env):
    from tests.factories import create_user

    author = await _signed_in(client, env, factory=create_user)
    post = await _make(
        env, ContentType.POST, H, author_id=author.id, hidden_reason=HiddenReason.REJECTED
    )

    response = await client.post(_action_url("post", post.id, "resubmit"))

    assert response.status_code == 403, response.text
    await env.db.refresh(post)
    assert post.status == H


async def test_queue_flags_resubmitted_items(client, env):
    author, post = await _rejected_by_admin(client, env)
    post.created_at = OLD
    await env.db.commit()
    fresh = await _make(env, ContentType.THREAD, P, created_at=OLD)
    await login_as(client, author)
    assert (await client.post(_action_url("post", post.id, "resubmit"))).status_code == 200
    await _signed_in(client, env)

    items = (await client.get(QUEUE, params={"limit": 200})).json()["items"]

    flags = {(i["content_type"], i["id"]): i["resubmitted"] for i in items}
    assert flags[("post", post.id)] is True
    assert flags[("thread", fresh.id)] is False


async def test_published_detail_has_no_note(client, env):
    admin_author = await _user(env)
    post = await _make(env, ContentType.POST, PUB, author_id=admin_author.id)

    detail = (await client.get(_detail_url(ContentType.POST, post.slug))).json()

    assert detail["moderation_note"] is None

"""Increment 7a: ``GET /moderation/deleted/`` (the deleted posts and discussions an admin can
restore or purge before the retention sweep removes them) and ``target_path`` on the audit log.

Rows are committed (the app uses its own sessions). Users go through ``cleanup_users`` (with the
audit rows they wrote), content through categories (``cleanup_forum_categories``) and actor-less
audit rows through ``audit_ids``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.core.config import settings
from app.crud.audit import log_action
from app.db.enums import CategoryKind, ContentStatus
from app.db.models import AuditLog, Post, Thread, User
from tests.factories import (
    create_admin,
    create_category,
    create_post,
    create_superadmin,
    create_thread,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
MOD = f"{API}/moderation"
DELETED = f"{MOD}/deleted/"
LOG = f"{MOD}/log/"

D = ContentStatus.DELETED
PUB = ContentStatus.PUBLISHED
# Far in the future, so this test's items come first in the (global) newest-first list.
FUTURE = datetime(2100, 1, 1, tzinfo=UTC)


@pytest.fixture
async def audit_ids(database_url: str) -> AsyncIterator[set[int]]:
    from app.db.session import AsyncSessionLocal

    ids: set[int] = set()
    yield ids
    if ids:
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


async def _post(env, status=D, *, deleted_at: datetime | None = None, **kw) -> Post:
    category = await create_category(env.db, kind=CategoryKind.BLOG)
    env.categories.add(category.id)
    post = await create_post(
        env.db,
        category_id=category.id,
        status=status,
        deleted_at=deleted_at if status == D else None,
        **kw,
    )
    await env.db.commit()
    return post


async def _thread(env, status=D, *, deleted_at: datetime | None = None, **kw) -> Thread:
    category = await create_category(env.db, kind=CategoryKind.FORUM)
    env.categories.add(category.id)
    thread = await create_thread(
        env.db,
        category_id=category.id,
        status=status,
        deleted_at=deleted_at if status == D else None,
        **kw,
    )
    await env.db.commit()
    return thread


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


def _find(body: dict, content_type: str, content_id: int) -> dict:
    (item,) = [
        i for i in body["items"] if i["content_type"] == content_type and i["id"] == content_id
    ]
    return item


# --- permissions ------------------------------------------------------------------------------


async def test_deleted_requires_login(client):
    _assert_error(await client.get(DELETED), 401, "auth.not_authenticated")


async def test_deleted_forbidden_for_member(client, env):
    await _signed_in(client, env, factory=create_verified_user)
    _assert_error(await client.get(DELETED), 403, "auth.forbidden")


@pytest.mark.parametrize("factory", [create_admin, create_superadmin])
async def test_deleted_allowed_for_admins(client, env, factory):
    await _signed_in(client, env, factory=factory)
    response = await client.get(DELETED)
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"total", "items"}


# --- listing ----------------------------------------------------------------------------------


async def test_deleted_lists_posts_and_threads_newest_first(client, env):
    older = await _post(env, deleted_at=FUTURE + timedelta(hours=1))
    newest = await _thread(env, deleted_at=FUTURE + timedelta(hours=3))
    middle = await _post(env, deleted_at=FUTURE + timedelta(hours=2))
    await _post(env, PUB)
    await _signed_in(client, env)

    body = (await client.get(DELETED)).json()

    first = [(i["content_type"], i["id"]) for i in body["items"][:3]]
    assert first == [("thread", newest.id), ("post", middle.id), ("post", older.id)]
    assert body["total"] >= 3


async def test_deleted_type_filter(client, env):
    post = await _post(env, deleted_at=FUTURE + timedelta(hours=5))
    thread = await _thread(env, deleted_at=FUTURE + timedelta(hours=4))
    await _signed_in(client, env)

    posts = (await client.get(DELETED, params={"type": "post", "limit": 200})).json()
    threads = (await client.get(DELETED, params={"type": "thread", "limit": 200})).json()

    assert {i["content_type"] for i in posts["items"]} == {"post"}
    assert {i["content_type"] for i in threads["items"]} == {"thread"}
    assert posts["items"][0]["id"] == post.id
    assert threads["items"][0]["id"] == thread.id


async def test_deleted_rejects_other_types_and_bad_pagination(client, env):
    await _signed_in(client, env)
    assert (await client.get(DELETED, params={"type": "reply"})).status_code == 422
    assert (await client.get(DELETED, params={"limit": 0})).status_code == 422
    assert (await client.get(DELETED, params={"skip": -1})).status_code == 422


async def test_deleted_pagination(client, env):
    made = [await _post(env, deleted_at=FUTURE + timedelta(days=10, hours=i)) for i in range(3)]
    await _signed_in(client, env)

    page1 = (await client.get(DELETED, params={"limit": 2})).json()
    page2 = (await client.get(DELETED, params={"skip": 2, "limit": 1})).json()

    assert [i["id"] for i in page1["items"]] == [made[2].id, made[1].id]
    assert [i["id"] for i in page2["items"]] == [made[0].id]
    assert page1["total"] == page2["total"] >= 3


async def test_deleted_item_shape_and_purge_at(client, env):
    author = await _user(env, display_name="Bin Author")
    deleted_at = FUTURE + timedelta(days=20)
    thread = await _thread(env, deleted_at=deleted_at, author_id=author.id)
    await _signed_in(client, env)

    item = (await client.get(DELETED)).json()["items"][0]

    await env.db.refresh(thread, ["category"])
    assert item == {
        "content_type": "thread",
        "id": thread.id,
        "title": thread.title,
        "slug": thread.slug,
        "author": {"id": author.id, "display_name": "Bin Author"},
        "category": {
            "id": thread.category.id,
            "name": thread.category.name,
            "slug": thread.category.slug,
        },
        "deleted_at": item["deleted_at"],
        "deleted_by": None,
        "purge_at": item["purge_at"],
    }
    assert datetime.fromisoformat(item["deleted_at"]) == deleted_at
    days = settings.DELETED_CONTENT_RETENTION_DAYS
    assert datetime.fromisoformat(item["purge_at"]) == deleted_at + timedelta(days=days)


async def test_deleted_purge_at_follows_the_setting(client, env, monkeypatch):
    deleted_at = FUTURE + timedelta(days=30)
    await _post(env, deleted_at=deleted_at)
    await _signed_in(client, env)

    monkeypatch.setattr(settings, "DELETED_CONTENT_RETENTION_DAYS", 3)
    item = (await client.get(DELETED)).json()["items"][0]
    assert datetime.fromisoformat(item["purge_at"]) == deleted_at + timedelta(days=3)

    monkeypatch.setattr(settings, "DELETED_CONTENT_RETENTION_DAYS", 0)
    item = (await client.get(DELETED)).json()["items"][0]
    assert item["purge_at"] is None


async def test_deleted_item_without_author(client, env):
    await _post(env, deleted_at=FUTURE + timedelta(days=40))
    await _signed_in(client, env)

    item = (await client.get(DELETED)).json()["items"][0]

    assert item["author"] is None


async def test_deleted_by_the_author(client, env):
    author = await _signed_in(client, env, factory=create_verified_user, display_name="Self")
    post = await _post(env, PUB, author_id=author.id)
    assert (await client.delete(f"{API}/posts/{post.id}")).status_code == 204
    await _signed_in(client, env)

    item = _find((await client.get(DELETED, params={"limit": 200})).json(), "post", post.id)

    assert item["deleted_by"] == {"id": author.id, "display_name": "Self"}
    assert item["author"] == {"id": author.id, "display_name": "Self"}


async def test_deleted_thread_by_its_author(client, env):
    author = await _signed_in(client, env, factory=create_verified_user, display_name="Op")
    thread = await _thread(env, PUB, author_id=author.id)
    assert (await client.delete(f"{API}/threads/{thread.id}")).status_code == 204
    await _signed_in(client, env)

    item = _find((await client.get(DELETED, params={"limit": 200})).json(), "thread", thread.id)

    assert item["deleted_by"] == {"id": author.id, "display_name": "Op"}


async def test_deleted_by_an_admin_latest_deletion_wins(client, env):
    author = await _user(env)
    post = await _post(env, PUB, author_id=author.id)
    first = await _signed_in(client, env, display_name="First Admin")
    assert (await client.post(f"{MOD}/post/{post.id}/delete")).status_code == 200
    assert (await client.post(f"{MOD}/post/{post.id}/restore")).status_code == 200
    second = await _signed_in(client, env, display_name="Second Admin")
    assert (await client.post(f"{MOD}/post/{post.id}/delete")).status_code == 200

    item = _find((await client.get(DELETED, params={"limit": 200})).json(), "post", post.id)

    assert first.id != second.id
    assert item["deleted_by"] == {"id": second.id, "display_name": "Second Admin"}


async def test_deleted_list_has_no_n_plus_one(client, env):
    """The page loads in a fixed number of queries, whatever its size."""
    from sqlalchemy import event

    from app.db.session import engine

    author = await _user(env)
    posts = [await _post(env, PUB, author_id=author.id) for _ in range(4)]
    await _signed_in(client, env)
    for post in posts:
        assert (await client.post(f"{MOD}/post/{post.id}/delete")).status_code == 200

    async def count(limit: int) -> int:
        statements: list[str] = []

        def on_execute(conn, cursor, statement, *args):
            statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", on_execute)
        try:
            assert (await client.get(DELETED, params={"limit": limit})).status_code == 200
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", on_execute)
        return len(statements)

    assert await count(1) == await count(4)


# --- audit log target_path --------------------------------------------------------------------


async def test_log_links_existing_posts_and_threads(client, env):
    post = await _post(env, PUB)
    thread = await _thread(env, D, deleted_at=datetime.now(UTC))
    admin = await _signed_in(client, env)
    assert (await client.post(f"{MOD}/post/{post.id}/hide")).status_code == 200
    assert (await client.post(f"{MOD}/thread/{thread.id}/restore")).status_code == 200

    body = (await client.get(LOG, params={"actor_id": admin.id, "action": "moderation."})).json()

    paths = {(i["target_type"], i["target_id"]): i["target_path"] for i in body["items"]}
    assert paths == {
        ("post", post.id): f"/blog/{post.slug}",
        ("thread", thread.id): f"/forum/t/{thread.slug}",
    }


async def test_log_links_deleted_items_too(client, env):
    post = await _post(env, PUB)
    admin = await _signed_in(client, env)
    assert (await client.post(f"{MOD}/post/{post.id}/delete")).status_code == 200

    body = (await client.get(LOG, params={"actor_id": admin.id, "action": "moderation."})).json()

    assert body["items"][0]["target_path"] == f"/blog/{post.slug}"


async def test_log_has_no_link_for_purged_items_or_other_targets(client, env):
    post = await _post(env, PUB)
    target = await _user(env)
    admin = await _signed_in(client, env)
    assert (await client.post(f"{MOD}/post/{post.id}/purge")).status_code == 200
    assert (await client.post(f"{API}/admin/users/{target.id}/trust")).status_code == 200

    body = (await client.get(LOG, params={"actor_id": admin.id, "limit": 200})).json()

    assert body["items"], body
    assert all(i["target_path"] is None for i in body["items"])


async def test_log_has_no_link_for_rows_without_target(client, env, audit_ids):
    row = await log_action(env.db, actor_id=None, action="maintenance.deleted_content")
    audit_ids.add(row.id)
    await env.db.commit()
    await _signed_in(client, env)

    body = (await client.get(LOG, params={"action": "maintenance.deleted_content"})).json()

    (item,) = [i for i in body["items"] if i["id"] == row.id]
    assert item["target_path"] is None

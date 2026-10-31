"""Increment 2d: tags - find-or-create (reused by posts in 2e), usage counts, public list, admin
delete and merge.

Crud tests run inside the rolled-back ``db_session``. Endpoint tests commit their rows and
register them with ``cleanup_tags`` / ``cleanup_posts`` / ``cleanup_categories``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.exceptions import AppError
from app.crud import tag as crud_tag
from app.db.enums import ContentStatus
from app.db.models import AuditLog, Category, Tag, User, post_tags
from tests.factories import (
    create_admin,
    create_post,
    create_tag,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
TAGS = f"{API}/tags/"


# --- helpers ----------------------------------------------------------------------------------


def _token() -> str:
    return uuid.uuid4().hex[:10]


async def _committed(db, cleanup_users, factory=create_verified_user, **kwargs) -> User:
    user = await factory(db, **kwargs)
    cleanup_users.add(user.email)
    await db.commit()
    return user


async def _admin_client(client, db, cleanup_users) -> User:
    admin = await _committed(db, cleanup_users, factory=create_admin)
    await login_as(client, admin)
    return admin


async def _news_id(db) -> int:
    return await db.scalar(select(Category.id).where(Category.slug == "news"))


async def _junction_count(db, tag_id: int) -> int:
    return await db.scalar(
        select(func.count()).select_from(post_tags).where(post_tags.c.tag_id == tag_id)
    )


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


def _assert_app_error(excinfo, status: int, code: str) -> None:
    assert excinfo.value.status_code == status
    assert excinfo.value.code == code


# --- get_or_create_tags -----------------------------------------------------------------------


async def test_get_or_create_normalises_and_dedups(db_session):
    tags = await crud_tag.get_or_create_tags(db_session, names=["NBS", " nbs ", "Nbs"])

    assert len(tags) == 1
    assert tags[0].name == "NBS"
    assert tags[0].slug == "nbs"
    assert tags[0].id is not None

    # A second call finds the existing tag (case-insensitively) instead of creating one.
    again = await crud_tag.get_or_create_tags(db_session, names=["nbs", "Urban   Flooding"])
    assert [t.id for t in again][0] == tags[0].id
    assert again[1].name == "Urban Flooding"
    assert again[1].slug == "urban-flooding"
    count = await db_session.scalar(
        select(func.count()).select_from(Tag).where(Tag.slug.in_(["nbs", "urban-flooding"]))
    )
    assert count == 2


async def test_get_or_create_keeps_input_order_and_empty_list(db_session):
    token = _token()
    names = [f"zeta {token}", f"alpha {token}", f"mid {token}"]

    tags = await crud_tag.get_or_create_tags(db_session, names=names)

    assert [t.name for t in tags] == names
    assert await crud_tag.get_or_create_tags(db_session, names=[]) == []


@pytest.mark.parametrize("bad", ["", "   ", "a" * 41, "???"])
async def test_get_or_create_rejects_invalid_names(db_session, bad):
    with pytest.raises(AppError) as excinfo:
        await crud_tag.get_or_create_tags(db_session, names=["valid", bad])

    _assert_app_error(excinfo, 422, "validation.failed")
    assert excinfo.value.fields == {"tags": "invalid"}


async def test_get_or_create_accepts_40_chars_and_rejects_more_than_10(db_session):
    tags = await crud_tag.get_or_create_tags(db_session, names=["b" * 40])
    assert tags[0].name == "b" * 40

    with pytest.raises(AppError) as excinfo:
        await crud_tag.get_or_create_tags(db_session, names=[f"t{i}" for i in range(11)])
    _assert_app_error(excinfo, 422, "validation.failed")
    assert excinfo.value.fields == {"tags": "too_many"}


# --- usage counts -----------------------------------------------------------------------------


async def test_recount_counts_published_posts_only(db_session):
    news_id = await _news_id(db_session)
    tag = await create_tag(db_session)
    other = await create_tag(db_session, usage_count=7)
    await create_post(db_session, category_id=news_id, tags=[tag])
    await create_post(db_session, category_id=news_id, tags=[tag, other])
    await create_post(db_session, category_id=news_id, tags=[tag], status=ContentStatus.PENDING)
    await create_post(db_session, category_id=news_id, tags=[tag], status=ContentStatus.DELETED)

    await crud_tag.recount_tag_usage(db_session, tag_ids=[tag.id, other.id])

    await db_session.refresh(tag)
    await db_session.refresh(other)
    assert tag.usage_count == 2
    assert other.usage_count == 1
    await crud_tag.recount_tag_usage(db_session, tag_ids=[])  # no-op


# --- public list ------------------------------------------------------------------------------


async def test_list_q_and_sorts(client, db_session, cleanup_tags):
    token = _token()
    low = await create_tag(db_session, name=f"Alpha {token}", usage_count=1)
    high = await create_tag(db_session, name=f"beta {token}", usage_count=9)
    mid = await create_tag(db_session, name=f"Gamma {token}", usage_count=5)
    unrelated = await create_tag(db_session, usage_count=100)
    cleanup_tags.update({low.id, high.id, mid.id, unrelated.id})
    await db_session.commit()

    popular = await client.get(TAGS, params={"q": token})
    assert popular.status_code == 200, popular.text
    body = popular.json()
    assert body["total"] == 3
    assert [i["id"] for i in body["items"]] == [high.id, mid.id, low.id]
    assert set(body["items"][0]) == {"id", "slug", "name", "usage_count"}
    assert body["items"][0]["usage_count"] == 9

    by_name = (await client.get(TAGS, params={"q": token.upper(), "sort": "name"})).json()
    assert [i["id"] for i in by_name["items"]] == [low.id, high.id, mid.id]

    paged = (await client.get(TAGS, params={"q": token, "skip": 1, "limit": 1})).json()
    assert paged["total"] == 3
    assert [i["id"] for i in paged["items"]] == [mid.id]

    unfiltered = (await client.get(TAGS)).json()
    assert unfiltered["total"] >= 4


async def test_list_validation(client):
    assert (await client.get(TAGS, params={"q": ""})).status_code == 422
    assert (await client.get(TAGS, params={"sort": "newest"})).status_code == 422
    assert (await client.get(TAGS, params={"limit": 101})).status_code == 422
    assert (await client.get(TAGS, params={"q": "%_"})).json()["total"] >= 0


# --- admin delete -----------------------------------------------------------------------------


async def test_delete_requires_admin_and_removes_junction_rows(
    client, db_session, cleanup_users, cleanup_tags, cleanup_posts
):
    tag = await create_tag(db_session)
    cleanup_tags.add(tag.id)
    post = await create_post(db_session, category_id=await _news_id(db_session), tags=[tag])
    cleanup_posts.add(post.id)
    await db_session.commit()

    _assert_error(await client.delete(f"{TAGS}{tag.id}"), 401, "auth.not_authenticated")
    member = await _committed(db_session, cleanup_users)
    await login_as(client, member)
    _assert_error(await client.delete(f"{TAGS}{tag.id}"), 403, "auth.forbidden")

    admin = await _admin_client(client, db_session, cleanup_users)
    response = await client.delete(f"{TAGS}{tag.id}")

    assert response.status_code == 204, response.text
    tag_id, tag_slug, admin_id = tag.id, tag.slug, admin.id
    db_session.expire_all()
    assert await db_session.get(Tag, tag_id) is None
    assert await _junction_count(db_session, tag_id) == 0
    audit = (
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.action == "tag.deleted",
                AuditLog.target_type == "tag",
                AuditLog.target_id == tag_id,
            )
        )
    ).all()
    assert len(audit) == 1
    assert audit[0].actor_id == admin_id
    assert audit[0].metadata_["slug"] == tag_slug

    _assert_error(await client.delete(f"{TAGS}{tag_id}"), 404, "tags.not_found")


# --- admin merge ------------------------------------------------------------------------------


async def test_merge_moves_posts_keeps_target_deletes_source_and_recounts(
    client, db_session, cleanup_users, cleanup_tags, cleanup_posts
):
    news_id = await _news_id(db_session)
    source = await create_tag(db_session)
    target = await create_tag(db_session)
    cleanup_tags.update({source.id, target.id})
    only_source = await create_post(db_session, category_id=news_id, tags=[source])
    both = await create_post(db_session, category_id=news_id, tags=[source, target])
    only_target = await create_post(db_session, category_id=news_id, tags=[target])
    pending = await create_post(
        db_session, category_id=news_id, tags=[source], status=ContentStatus.PENDING
    )
    cleanup_posts.update({only_source.id, both.id, only_target.id, pending.id})
    await db_session.commit()
    admin = await _admin_client(client, db_session, cleanup_users)

    response = await client.post(f"{TAGS}{source.id}/merge", json={"target_id": target.id})

    source_id, target_id, admin_id = source.id, target.id, admin.id
    post_ids_expected = {only_source.id, both.id, only_target.id, pending.id}
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == target_id
    assert body["usage_count"] == 3  # only_source, both, only_target (pending not counted)
    db_session.expire_all()
    assert await db_session.get(Tag, source_id) is None
    post_ids = set(
        (
            await db_session.scalars(
                select(post_tags.c.post_id).where(post_tags.c.tag_id == target_id)
            )
        ).all()
    )
    assert post_ids == post_ids_expected
    audit = (
        await db_session.scalars(
            select(AuditLog).where(AuditLog.action == "tag.merged", AuditLog.target_id == target_id)
        )
    ).all()
    assert len(audit) == 1
    assert audit[0].actor_id == admin_id
    assert audit[0].metadata_ == {"source_id": source_id, "target_id": target_id}


async def test_merge_errors(client, db_session, cleanup_users, cleanup_tags):
    tag = await create_tag(db_session)
    cleanup_tags.add(tag.id)
    await db_session.commit()

    _assert_error(
        await client.post(f"{TAGS}{tag.id}/merge", json={"target_id": 999999999}),
        401,
        "auth.not_authenticated",
    )
    await _admin_client(client, db_session, cleanup_users)
    _assert_error(
        await client.post(f"{TAGS}{tag.id}/merge", json={"target_id": tag.id}), 409, "tags.same"
    )
    _assert_error(
        await client.post(f"{TAGS}{tag.id}/merge", json={"target_id": 999999999}),
        404,
        "tags.not_found",
    )
    _assert_error(
        await client.post(f"{TAGS}999999999/merge", json={"target_id": tag.id}),
        404,
        "tags.not_found",
    )
    assert (await client.post(f"{TAGS}{tag.id}/merge", json={})).status_code == 422


async def test_merge_moves_thread_tags_too(db_session):
    from sqlalchemy.orm import selectinload

    from app.db.enums import CategoryKind
    from app.db.models import Thread, thread_tags
    from tests.factories import create_category, create_thread

    forum = await create_category(db_session, kind=CategoryKind.FORUM)
    source = await create_tag(db_session)
    target = await create_tag(db_session)
    only_source = await create_thread(db_session, category_id=forum.id, tags=[source])
    both = await create_thread(db_session, category_id=forum.id, tags=[source, target])
    pending = await create_thread(
        db_session, category_id=forum.id, tags=[source], status=ContentStatus.PENDING
    )

    merged = await crud_tag.merge_tags(db_session, source_id=source.id, target_id=target.id)

    assert merged.usage_count == 2  # only_source and both; pending is not counted
    thread_ids = set(
        (
            await db_session.scalars(
                select(thread_tags.c.thread_id).where(thread_tags.c.tag_id == target.id)
            )
        ).all()
    )
    assert thread_ids == {only_source.id, both.id, pending.id}
    stmt = (
        select(Thread).where(Thread.id == only_source.id).execution_options(populate_existing=True)
    )
    reloaded = await db_session.scalar(stmt.options(selectinload(Thread.tags)))
    assert [tag.id for tag in reloaded.tags] == [target.id]

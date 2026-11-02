"""``crud/visibility.py``: :func:`parent_visible` (7j), the one rule for "may ``user`` see the
thread of this reply / the post of this comment", shared by reports and the edit/delete checks.

Every test runs inside the ``db_session`` transaction and only flushes.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.crud.visibility import parent_visible
from app.db.enums import CategoryKind, ContentStatus, HiddenReason
from app.db.models import Comment, Reply
from tests.factories import (
    create_admin,
    create_category,
    create_comment,
    create_post,
    create_reply,
    create_thread,
    create_verified_user,
)

PUB = ContentStatus.PUBLISHED
H = ContentStatus.HIDDEN
D = ContentStatus.DELETED
P = ContentStatus.PENDING


def _parent_fields(status: ContentStatus) -> dict:
    fields: dict = {"status": status}
    if status == H:
        fields["hidden_reason"] = HiddenReason.ADMIN
    if status == D:
        fields["deleted_at"] = datetime(2026, 10, 1, tzinfo=UTC)
    return fields


async def _child(db, kind: str, parent_status: ContentStatus, *, parent_author_id=None):
    """A published reply (``kind="reply"``) or comment whose thread/post is in
    ``parent_status``."""
    if kind == "reply":
        category = await create_category(db, kind=CategoryKind.FORUM)
        thread = await create_thread(
            db, category_id=category.id, author_id=parent_author_id, **_parent_fields(parent_status)
        )
        return await create_reply(db, thread_id=thread.id)
    category = await create_category(db, kind=CategoryKind.BLOG)
    post = await create_post(
        db, category_id=category.id, author_id=parent_author_id, **_parent_fields(parent_status)
    )
    return await create_comment(db, post_id=post.id)


@pytest.mark.parametrize("kind", ["reply", "comment"])
async def test_published_parent_is_visible_to_everyone(db_session, kind):
    child = await _child(db_session, kind, PUB)
    member = await create_verified_user(db_session)

    assert await parent_visible(db_session, child, None) is True
    assert await parent_visible(db_session, child, member) is True


@pytest.mark.parametrize("kind", ["reply", "comment"])
@pytest.mark.parametrize("status", [P, H])
async def test_unpublished_parent_only_for_its_author_and_admins(db_session, kind, status):
    parent_author = await create_verified_user(db_session)
    member = await create_verified_user(db_session)
    admin = await create_admin(db_session)
    child = await _child(db_session, kind, status, parent_author_id=parent_author.id)

    assert await parent_visible(db_session, child, None) is False
    assert await parent_visible(db_session, child, member) is False
    assert await parent_visible(db_session, child, member, include_deleted=True) is False
    assert await parent_visible(db_session, child, parent_author) is True
    assert await parent_visible(db_session, child, admin) is True


@pytest.mark.parametrize("kind", ["reply", "comment"])
async def test_deleted_parent_only_for_admins_with_include_deleted(db_session, kind):
    parent_author = await create_verified_user(db_session)
    member = await create_verified_user(db_session)
    admin = await create_admin(db_session)
    child = await _child(db_session, kind, D, parent_author_id=parent_author.id)

    assert await parent_visible(db_session, child, admin) is False
    assert await parent_visible(db_session, child, admin, include_deleted=True) is True
    for user in (None, member, parent_author):
        assert await parent_visible(db_session, child, user) is False
        assert await parent_visible(db_session, child, user, include_deleted=True) is False


async def test_posts_and_threads_have_no_parent(db_session):
    category = await create_category(db_session, kind=CategoryKind.BLOG)
    post = await create_post(db_session, category_id=category.id, **_parent_fields(D))
    forum = await create_category(db_session, kind=CategoryKind.FORUM)
    thread = await create_thread(db_session, category_id=forum.id, **_parent_fields(H))

    assert await parent_visible(db_session, post, None) is True
    assert await parent_visible(db_session, thread, None) is True


@pytest.mark.parametrize("model", [Reply, Comment])
async def test_missing_parent_is_not_visible(db_session, model):
    admin = await create_admin(db_session)
    orphan = (
        Reply(thread_id=2**31 - 1, body_html="<p>x</p>", body_text="x")
        if model is Reply
        else Comment(post_id=2**31 - 1, body_html="<p>x</p>", body_text="x")
    )

    assert await parent_visible(db_session, orphan, admin, include_deleted=True) is False

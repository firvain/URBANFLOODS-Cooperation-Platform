"""Increment 5h: ``POST /moderation/{type}/{id}/purge`` (permanent delete) and the upload usage
it relies on (``used_in`` on ``GET /uploads/mine/``, 409 ``uploads.in_use`` on delete).

Rows are committed (the app uses its own sessions). Users go through ``cleanup_users`` (with the
audit rows they wrote), content through categories (``cleanup_forum_categories``: threads, then
posts with their comments), reports, attachments, tags and KNOWBASE links through their own
cleanup fixtures; rows the purge already removed are fine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.db.enums import CategoryKind, ContentStatus, ContentType, HiddenReason, ReportStatus
from app.db.models import (
    Attachment,
    AuditLog,
    Comment,
    KnowbaseLink,
    Post,
    Reply,
    Report,
    Tag,
    Thread,
    User,
    post_tags,
    thread_tags,
)
from app.services import images
from tests.factories import (
    create_admin,
    create_attachment,
    create_category,
    create_comment,
    create_knowbase_link,
    create_post,
    create_reply,
    create_report,
    create_superadmin,
    create_tag,
    create_thread,
    create_thread_knowbase_link,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
MOD = f"{API}/moderation"
MINE = f"{API}/uploads/mine/"
PREFIX = settings.UPLOAD_URL_PREFIX

P = ContentStatus.PENDING
PUB = ContentStatus.PUBLISHED
H = ContentStatus.HIDDEN
D = ContentStatus.DELETED


# --- fixtures and helpers ---------------------------------------------------------------------


@pytest.fixture
def env(
    db_session,
    cleanup_users,
    cleanup_forum_categories,
    cleanup_reports,
    cleanup_attachments,
    cleanup_tags,
    cleanup_knowbase_links,
    upload_dir,
):
    class Env:
        db = db_session
        users = cleanup_users
        categories = cleanup_forum_categories
        reports = cleanup_reports
        attachments = cleanup_attachments
        tags = cleanup_tags
        links = cleanup_knowbase_links
        uploads = upload_dir

    return Env


@dataclass(frozen=True)
class Stored:
    """An attachment's id and paths, captured before commit (ORM attributes expire)."""

    id: int
    storage_path: str
    thumb_path: str


async def _user(env, factory=create_verified_user, **kwargs) -> User:
    user = await factory(env.db, **kwargs)
    env.users.add(user.email)
    await env.db.commit()
    return user


async def _signed_in(client, env, factory=create_admin) -> User:
    user = await _user(env, factory=factory)
    await login_as(client, user)
    return user


async def _category(env, kind: CategoryKind) -> int:
    category = await create_category(env.db, kind=kind)
    env.categories.add(category.id)
    return category.id


def _status_fields(status: ContentStatus) -> dict:
    fields: dict = {}
    if status == H:
        fields["hidden_reason"] = HiddenReason.ADMIN
    if status == D:
        fields["deleted_at"] = datetime.now(UTC) - timedelta(days=1)
    return fields


async def _post(env, status: ContentStatus = PUB, **kw) -> Post:
    return await create_post(
        env.db,
        category_id=await _category(env, CategoryKind.BLOG),
        status=status,
        **_status_fields(status),
        **kw,
    )


async def _thread(env, status: ContentStatus = PUB, **kw) -> Thread:
    return await create_thread(
        env.db,
        category_id=await _category(env, CategoryKind.FORUM),
        status=status,
        **_status_fields(status),
        **kw,
    )


async def _file(env, *, uploader_id: int | None) -> Stored:
    attachment = await create_attachment(env.db, uploader_id=uploader_id)
    assert attachment.thumb_path is not None
    images.save_files(
        env.uploads, attachment.storage_path, b"main", attachment.thumb_path, b"thumb"
    )
    env.attachments.add(attachment.id)
    return Stored(attachment.id, attachment.storage_path, attachment.thumb_path)


def _img(stored: Stored, *, thumb: bool = False) -> str:
    path = stored.thumb_path if thumb else stored.storage_path
    return f'<p>Text</p><p><img src="{PREFIX}/{path}" alt="Flood"></p>'


def _files_exist(env, stored: Stored) -> tuple[bool, bool]:
    uploads: Path = env.uploads
    return (
        (uploads / stored.storage_path).exists(),
        (uploads / stored.thumb_path).exists(),
    )


async def _exists(db, model, row_id: int) -> bool:
    return await db.scalar(select(model.id).where(model.id == row_id)) is not None


async def _report(env, *, content_type: str, content_id: int, **kw) -> Report:
    reporter = await _user(env)
    report = await create_report(
        env.db, reporter_id=reporter.id, content_type=content_type, content_id=content_id, **kw
    )
    env.reports.add(report.id)
    return report


async def _reload_report(db, report_id: int) -> Report:
    stmt = select(Report).where(Report.id == report_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


async def _reload(db, model, row_id: int):
    stmt = select(model).where(model.id == row_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


def _purge_url(content_type: ContentType | str, content_id: int) -> str:
    return f"{MOD}/{content_type}/{content_id}/purge"


async def _purge(client, content_type: ContentType | str, content_id: int):
    return await client.post(_purge_url(content_type, content_id))


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


async def _purge_audit(db, content_type: ContentType, content_id: int) -> AuditLog:
    stmt = select(AuditLog).where(
        AuditLog.action == "moderation.purge",
        AuditLog.target_type == content_type.value,
        AuditLog.target_id == content_id,
    )
    return (await db.execute(stmt.execution_options(populate_existing=True))).scalar_one()


# --- permission matrix ------------------------------------------------------------------------


async def test_purge_requires_login(client, env):
    post = await _post(env)
    await env.db.commit()
    _assert_error(await _purge(client, "post", post.id), 401, "auth.not_authenticated")
    assert await _exists(env.db, Post, post.id)


async def test_purge_forbidden_for_member(client, env):
    post = await _post(env)
    await env.db.commit()
    await _signed_in(client, env, factory=create_verified_user)
    response = await _purge(client, "post", post.id)
    assert response.status_code == 403, response.text
    assert await _exists(env.db, Post, post.id)


async def test_purge_forbidden_for_the_author(client, env):
    author = await _signed_in(client, env, factory=create_verified_user)
    post = await _post(env, author_id=author.id)
    await env.db.commit()
    assert (await _purge(client, "post", post.id)).status_code == 403
    assert await _exists(env.db, Post, post.id)


@pytest.mark.parametrize("factory", [create_admin, create_superadmin])
async def test_purge_allowed_for_admins(client, env, factory):
    post = await _post(env)
    await env.db.commit()
    await _signed_in(client, env, factory=factory)
    response = await _purge(client, "post", post.id)
    assert response.status_code == 200, response.text
    assert not await _exists(env.db, Post, post.id)


@pytest.mark.parametrize("content_type", list(ContentType))
async def test_purge_unknown_content_is_404(client, env, content_type):
    await _signed_in(client, env)
    _assert_error(
        await _purge(client, content_type, 2_000_000_000), 404, "moderation.content_not_found"
    )


async def test_purge_unknown_content_type_is_422(client, env):
    await _signed_in(client, env)
    assert (await _purge(client, "page", 1)).status_code == 422


# --- purge per type ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [P, PUB, H, D])
async def test_purge_post_from_any_status(client, env, status):
    post = await _post(env, status)
    slug = post.slug
    await env.db.commit()
    await _signed_in(client, env)

    response = await _purge(client, "post", post.id)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "content_type": "post",
        "id": post.id,
        "purged": True,
        "children_deleted": 0,
        "attachments_deleted": 0,
        "reports_resolved": 0,
    }
    assert not await _exists(env.db, Post, post.id)
    assert (await client.get(f"{API}/posts/{slug}")).status_code == 404


async def test_purge_twice_is_404(client, env):
    thread = await _thread(env)
    await env.db.commit()
    await _signed_in(client, env)
    assert (await _purge(client, "thread", thread.id)).status_code == 200
    _assert_error(await _purge(client, "thread", thread.id), 404, "moderation.content_not_found")
    _assert_error(
        await client.post(f"{MOD}/thread/{thread.id}/restore"), 404, "moderation.content_not_found"
    )


async def test_purge_post_removes_comments_tags_and_links(client, env):
    db = env.db
    tag = await create_tag(db, usage_count=1)
    env.tags.add(tag.id)
    post = await _post(env, tags=[tag])
    env.links.add(post.id)
    await create_knowbase_link(db, post_id=post.id)
    comments = [
        await create_comment(db, post_id=post.id),
        await create_comment(db, post_id=post.id, status=H),
        await create_comment(db, post_id=post.id, status=D, deleted_at=datetime.now(UTC)),
    ]
    comment_ids = [c.id for c in comments]
    await db.commit()
    await _signed_in(client, env)

    response = await _purge(client, "post", post.id)

    assert response.status_code == 200, response.text
    assert response.json()["children_deleted"] == 3
    for comment_id in comment_ids:
        assert not await _exists(db, Comment, comment_id)
    junction = await db.scalar(
        select(func.count()).select_from(post_tags).where(post_tags.c.post_id == post.id)
    )
    assert junction == 0
    links = await db.scalar(
        select(func.count())
        .select_from(KnowbaseLink)
        .where(KnowbaseLink.content_type == ContentType.POST, KnowbaseLink.content_id == post.id)
    )
    assert links == 0
    assert (await _reload(db, Tag, tag.id)).usage_count == 0


async def test_purge_thread_removes_replies_at_all_levels_tags_and_links(client, env):
    db = env.db
    tag = await create_tag(db, usage_count=1)
    env.tags.add(tag.id)
    thread = await _thread(env, tags=[tag])
    await create_thread_knowbase_link(db, thread_id=thread.id)
    top = await create_reply(db, thread_id=thread.id)
    child = await create_reply(db, thread_id=thread.id, parent_reply_id=top.id)
    other = await create_reply(db, thread_id=thread.id, status=H)
    reply_ids = [top.id, child.id, other.id]
    await db.commit()
    await _signed_in(client, env)

    response = await _purge(client, "thread", thread.id)

    assert response.status_code == 200, response.text
    assert response.json()["children_deleted"] == 3
    assert not await _exists(db, Thread, thread.id)
    for reply_id in reply_ids:
        assert not await _exists(db, Reply, reply_id)
    junction = await db.scalar(
        select(func.count()).select_from(thread_tags).where(thread_tags.c.thread_id == thread.id)
    )
    assert junction == 0
    links = await db.scalar(
        select(func.count())
        .select_from(KnowbaseLink)
        .where(
            KnowbaseLink.content_type == ContentType.THREAD, KnowbaseLink.content_id == thread.id
        )
    )
    assert links == 0
    assert (await _reload(db, Tag, tag.id)).usage_count == 0


async def test_purge_top_level_reply_removes_its_children_and_recounts(client, env):
    db = env.db
    thread = await _thread(env)
    top = await create_reply(db, thread_id=thread.id)
    child_a = await create_reply(db, thread_id=thread.id, parent_reply_id=top.id)
    child_b = await create_reply(db, thread_id=thread.id, parent_reply_id=top.id)
    survivor = await create_reply(db, thread_id=thread.id)
    await db.commit()
    assert (await _reload(db, Thread, thread.id)).reply_count == 4
    await _signed_in(client, env)

    response = await _purge(client, "reply", top.id)

    assert response.status_code == 200, response.text
    assert response.json()["children_deleted"] == 2
    for reply_id in (top.id, child_a.id, child_b.id):
        assert not await _exists(db, Reply, reply_id)
    assert await _exists(db, Reply, survivor.id)
    assert (await _reload(db, Thread, thread.id)).reply_count == 1


async def test_purge_child_reply_keeps_parent(client, env):
    db = env.db
    thread = await _thread(env)
    top = await create_reply(db, thread_id=thread.id)
    child = await create_reply(db, thread_id=thread.id, parent_reply_id=top.id)
    await db.commit()
    await _signed_in(client, env)

    response = await _purge(client, "reply", child.id)

    assert response.status_code == 200, response.text
    assert response.json()["children_deleted"] == 0
    assert await _exists(db, Reply, top.id)
    assert not await _exists(db, Reply, child.id)
    assert (await _reload(db, Thread, thread.id)).reply_count == 1


async def test_purge_comment_recounts_the_post(client, env):
    db = env.db
    post = await _post(env)
    gone = await create_comment(db, post_id=post.id)
    kept = await create_comment(db, post_id=post.id)
    await db.commit()
    assert (await _reload(db, Post, post.id)).comment_count == 2
    await _signed_in(client, env)

    response = await _purge(client, "comment", gone.id)

    assert response.status_code == 200, response.text
    assert response.json()["children_deleted"] == 0
    assert not await _exists(db, Comment, gone.id)
    assert await _exists(db, Comment, kept.id)
    assert (await _reload(db, Post, post.id)).comment_count == 1


# --- reports ----------------------------------------------------------------------------------


async def test_purge_post_resolves_reports_on_it_and_its_comments(client, env):
    db = env.db
    post = await _post(env)
    comment = await create_comment(db, post_id=post.id)
    on_post = await _report(env, content_type="post", content_id=post.id)
    on_comment = await _report(env, content_type="comment", content_id=comment.id)
    dismissed = await _report(
        env, content_type="post", content_id=post.id, status=ReportStatus.DISMISSED
    )
    await db.commit()
    admin = await _signed_in(client, env)

    response = await _purge(client, "post", post.id)

    assert response.status_code == 200, response.text
    assert response.json()["reports_resolved"] == 2
    for report_id in (on_post.id, on_comment.id):
        report = await _reload_report(db, report_id)
        assert report.status == ReportStatus.RESOLVED
        assert report.resolved_by == admin.id
        assert report.resolved_at is not None
    assert (await _reload_report(db, dismissed.id)).status == ReportStatus.DISMISSED


async def test_purge_thread_resolves_reports_on_replies(client, env):
    db = env.db
    thread = await _thread(env)
    top = await create_reply(db, thread_id=thread.id)
    child = await create_reply(db, thread_id=thread.id, parent_reply_id=top.id)
    reports = [
        await _report(env, content_type="thread", content_id=thread.id),
        await _report(env, content_type="reply", content_id=top.id),
        await _report(env, content_type="reply", content_id=child.id),
    ]
    await db.commit()
    await _signed_in(client, env)

    response = await _purge(client, "thread", thread.id)

    assert response.json()["reports_resolved"] == 3
    for report in reports:
        assert (await _reload_report(db, report.id)).status == ReportStatus.RESOLVED


async def test_purge_reply_resolves_reports_on_it_and_children_only(client, env):
    db = env.db
    thread = await _thread(env)
    top = await create_reply(db, thread_id=thread.id)
    child = await create_reply(db, thread_id=thread.id, parent_reply_id=top.id)
    on_top = await _report(env, content_type="reply", content_id=top.id)
    on_child = await _report(env, content_type="reply", content_id=child.id)
    on_thread = await _report(env, content_type="thread", content_id=thread.id)
    await db.commit()
    await _signed_in(client, env)

    response = await _purge(client, "reply", top.id)

    assert response.json()["reports_resolved"] == 2
    assert (await _reload_report(db, on_top.id)).status == ReportStatus.RESOLVED
    assert (await _reload_report(db, on_child.id)).status == ReportStatus.RESOLVED
    assert (await _reload_report(db, on_thread.id)).status == ReportStatus.OPEN


async def test_purge_comment_resolves_its_reports(client, env):
    db = env.db
    post = await _post(env)
    comment = await create_comment(db, post_id=post.id)
    report = await _report(env, content_type="comment", content_id=comment.id)
    await db.commit()
    await _signed_in(client, env)

    response = await _purge(client, "comment", comment.id)

    assert response.json()["reports_resolved"] == 1
    assert (await _reload_report(db, report.id)).status == ReportStatus.RESOLVED


# --- attachments ------------------------------------------------------------------------------


async def test_purge_post_deletes_cover_and_inline_images_and_files(client, env):
    db = env.db
    author = await _user(env)
    cover = await _file(env, uploader_id=author.id)
    inline = await _file(env, uploader_id=author.id)
    post = await _post(env, author_id=author.id, cover_attachment_id=cover.id)
    post.body_html = _img(inline)
    await db.commit()
    await _signed_in(client, env)

    response = await _purge(client, "post", post.id)

    assert response.status_code == 200, response.text
    assert response.json()["attachments_deleted"] == 2
    for stored in (cover, inline):
        assert not await _exists(db, Attachment, stored.id)
        assert _files_exist(env, stored) == (False, False)


async def test_purge_keeps_images_used_elsewhere(client, env):
    db = env.db
    shared = await _file(env, uploader_id=None)
    cover_shared = await _file(env, uploader_id=None)
    post = await _post(env, cover_attachment_id=cover_shared.id)
    post.body_html = _img(shared)
    other = await _post(env, cover_attachment_id=cover_shared.id)
    other.body_html = _img(shared)
    await db.commit()
    await _signed_in(client, env)

    response = await _purge(client, "post", post.id)

    assert response.json()["attachments_deleted"] == 0
    for stored in (shared, cover_shared):
        assert await _exists(db, Attachment, stored.id)
        assert _files_exist(env, stored) == (True, True)


async def test_purge_keeps_an_image_that_is_someones_avatar(client, env):
    db = env.db
    owner = await _user(env)
    avatar = await _file(env, uploader_id=owner.id)
    owner.avatar_attachment_id = avatar.id
    post = await _post(env)
    post.body_html = _img(avatar)
    await db.commit()
    await _signed_in(client, env)

    response = await _purge(client, "post", post.id)

    assert response.json()["attachments_deleted"] == 0
    assert await _exists(db, Attachment, avatar.id)
    assert _files_exist(env, avatar) == (True, True)


async def test_purge_post_deletes_images_in_its_comments_by_thumbnail_path(client, env):
    db = env.db
    in_comment = await _file(env, uploader_id=None)
    post = await _post(env)
    comment = await create_comment(db, post_id=post.id)
    comment.body_html = _img(in_comment, thumb=True)
    await db.commit()
    await _signed_in(client, env)

    response = await _purge(client, "post", post.id)

    assert response.json()["attachments_deleted"] == 1
    assert not await _exists(db, Attachment, in_comment.id)
    assert _files_exist(env, in_comment) == (False, False)


async def test_purge_thread_deletes_images_in_body_and_replies_of_any_uploader(client, env):
    db = env.db
    alice = await _user(env)
    bob = await _user(env)
    in_body = await _file(env, uploader_id=alice.id)
    in_reply = await _file(env, uploader_id=bob.id)
    thread = await _thread(env, author_id=alice.id)
    thread.body_html = _img(in_body)
    reply = await create_reply(db, thread_id=thread.id, author_id=bob.id)
    reply.body_html = _img(in_reply)
    await db.commit()
    await _signed_in(client, env)

    response = await _purge(client, "thread", thread.id)

    assert response.json()["attachments_deleted"] == 2
    for stored in (in_body, in_reply):
        assert not await _exists(db, Attachment, stored.id)
        assert _files_exist(env, stored) == (False, False)


async def test_purge_reply_keeps_the_threads_images(client, env):
    db = env.db
    image = await _file(env, uploader_id=None)
    own = await _file(env, uploader_id=None)
    thread = await _thread(env)
    thread.body_html = _img(image)
    reply = await create_reply(db, thread_id=thread.id)
    reply.body_html = _img(image) + _img(own)
    await db.commit()
    await _signed_in(client, env)

    response = await _purge(client, "reply", reply.id)

    assert response.json()["attachments_deleted"] == 1
    assert await _exists(db, Attachment, image.id)
    assert not await _exists(db, Attachment, own.id)
    assert _files_exist(env, image) == (True, True)


async def test_purge_never_touches_unrelated_unused_uploads(client, env):
    db = env.db
    unrelated = await _file(env, uploader_id=None)
    post = await _post(env)
    await db.commit()
    await _signed_in(client, env)

    assert (await _purge(client, "post", post.id)).status_code == 200
    assert await _exists(db, Attachment, unrelated.id)
    assert _files_exist(env, unrelated) == (True, True)


# --- audit ------------------------------------------------------------------------------------


async def test_purge_audit_row_counts_and_no_body(client, env):
    db = env.db
    image = await _file(env, uploader_id=None)
    post = await _post(env, H, title="Purged title")
    post.body_html = "<p>SECRET-BODY-TEXT</p>" + _img(image)
    post.body_text = "SECRET-BODY-TEXT"
    await create_comment(db, post_id=post.id)
    await _report(env, content_type="post", content_id=post.id)
    await db.commit()
    admin = await _signed_in(client, env)

    assert (await _purge(client, "post", post.id)).status_code == 200

    entry = await _purge_audit(db, ContentType.POST, post.id)
    assert entry.actor_id == admin.id
    assert entry.metadata_ == {
        "from": "hidden",
        "content_type": "post",
        "content_id": post.id,
        "title": "Purged title",
        "children_deleted": 1,
        "attachments_deleted": 1,
        "reports_resolved": 1,
    }
    assert "SECRET-BODY-TEXT" not in str(entry.metadata_)


async def test_purge_audit_keeps_a_full_length_title(client, env):
    # Titles are at most 200 characters (the column), the audit cap.
    thread = await _thread(env, title="T" * 200)
    await env.db.commit()
    await _signed_in(client, env)

    assert (await _purge(client, "thread", thread.id)).status_code == 200

    entry = await _purge_audit(env.db, ContentType.THREAD, thread.id)
    assert entry.metadata_["title"] == "T" * 200


async def test_purge_audit_for_comment_has_no_title(client, env):
    db = env.db
    post = await _post(env)
    comment = await create_comment(db, post_id=post.id, status=D, deleted_at=datetime.now(UTC))
    await db.commit()
    await _signed_in(client, env)

    assert (await _purge(client, "comment", comment.id)).status_code == 200

    entry = await _purge_audit(db, ContentType.COMMENT, comment.id)
    assert "title" not in entry.metadata_
    assert entry.metadata_["from"] == "deleted"
    assert entry.metadata_["content_type"] == "comment"


# --- uploads: used_in and delete --------------------------------------------------------------


def _item(body: dict, attachment_id: int) -> dict:
    return next(item for item in body["items"] if item["id"] == attachment_id)


async def test_mine_used_in_is_empty_for_unused_upload(client, env):
    member = await _signed_in(client, env, factory=create_verified_user)
    stored = await _file(env, uploader_id=member.id)
    await env.db.commit()

    body = (await client.get(MINE)).json()

    assert _item(body, stored.id)["used_in"] == []


async def test_mine_used_in_lists_cover_and_inline_posts(client, env):
    db = env.db
    member = await _signed_in(client, env, factory=create_verified_user)
    stored = await _file(env, uploader_id=member.id)
    as_cover = await _post(env, author_id=member.id, cover_attachment_id=stored.id)
    inline = await _post(env, D, author_id=member.id)
    inline.body_html = _img(stored)
    await db.commit()

    used_in = _item((await client.get(MINE)).json(), stored.id)["used_in"]

    assert sorted(used_in, key=lambda u: u["id"]) == sorted(
        [
            {
                "content_type": "post",
                "id": as_cover.id,
                "title": as_cover.title,
                "slug": as_cover.slug,
                "status": "published",
            },
            {
                "content_type": "post",
                "id": inline.id,
                "title": inline.title,
                "slug": inline.slug,
                "status": "deleted",
            },
        ],
        key=lambda u: u["id"],
    )


async def test_mine_used_in_lists_threads_replies_and_comments_with_parent(client, env):
    db = env.db
    member = await _signed_in(client, env, factory=create_verified_user)
    stored = await _file(env, uploader_id=member.id)
    thread = await _thread(env)
    thread.body_html = _img(stored)
    reply = await create_reply(db, thread_id=thread.id)
    reply.body_html = _img(stored, thumb=True)
    post = await _post(env)
    comment = await create_comment(db, post_id=post.id)
    comment.body_html = _img(stored)
    await db.commit()

    used_in = _item((await client.get(MINE)).json(), stored.id)["used_in"]
    by_type = {u["content_type"]: u for u in used_in}

    assert len(used_in) == 3
    assert by_type["thread"] == {
        "content_type": "thread",
        "id": thread.id,
        "title": thread.title,
        "slug": thread.slug,
        "status": "published",
    }
    # Replies and comments point at their thread/post (the page they are shown on).
    assert by_type["reply"]["id"] == reply.id
    assert by_type["reply"]["slug"] == thread.slug
    assert by_type["reply"]["title"] == thread.title
    assert by_type["comment"]["id"] == comment.id
    assert by_type["comment"]["slug"] == post.slug


async def test_delete_upload_used_as_cover_is_409(client, env):
    db = env.db
    member = await _signed_in(client, env, factory=create_verified_user)
    stored = await _file(env, uploader_id=member.id)
    await _post(env, author_id=member.id, cover_attachment_id=stored.id)
    await db.commit()

    response = await client.delete(f"{API}/uploads/{stored.id}")

    _assert_error(response, 409, "uploads.in_use")
    assert (await _reload(db, Attachment, stored.id)).deleted_at is None
    assert _files_exist(env, stored) == (True, True)


async def test_delete_upload_used_inline_in_a_reply_is_409(client, env):
    db = env.db
    member = await _signed_in(client, env, factory=create_verified_user)
    stored = await _file(env, uploader_id=member.id)
    thread = await _thread(env)
    reply = await create_reply(db, thread_id=thread.id, status=D, deleted_at=datetime.now(UTC))
    reply.body_html = _img(stored, thumb=True)
    await db.commit()

    _assert_error(await client.delete(f"{API}/uploads/{stored.id}"), 409, "uploads.in_use")


async def test_admin_cannot_delete_a_referenced_upload_either(client, env):
    db = env.db
    member = await _user(env)
    stored = await _file(env, uploader_id=member.id)
    post = await _post(env, author_id=member.id)
    post.body_html = _img(stored)
    await db.commit()
    await _signed_in(client, env)

    _assert_error(await client.delete(f"{API}/uploads/{stored.id}"), 409, "uploads.in_use")


async def test_delete_avatar_is_not_blocked_by_usage(client, env):
    db = env.db
    member = await _signed_in(client, env, factory=create_verified_user)
    stored = await _file(env, uploader_id=member.id)
    member.avatar_attachment_id = stored.id
    await db.commit()

    assert (await client.delete(f"{API}/uploads/{stored.id}")).status_code == 204


async def test_after_purge_the_members_upload_is_gone_from_mine(client, other_client, env):
    db = env.db
    member = await _user(env)
    stored = await _file(env, uploader_id=member.id)
    post = await _post(env, author_id=member.id)
    post.body_html = _img(stored)
    await db.commit()
    await login_as(client, member)
    assert _item((await client.get(MINE)).json(), stored.id)["used_in"] != []
    admin = await _user(env, factory=create_admin)
    await login_as(other_client, admin)

    assert (await _purge(other_client, "post", post.id)).status_code == 200

    body = (await client.get(MINE)).json()
    assert all(item["id"] != stored.id for item in body["items"])

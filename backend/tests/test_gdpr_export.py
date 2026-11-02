"""Increment 1i-b: GDPR export completeness (``GET /auth/me/export`` lists the member's own
content, uploads, reports and audit rows) and attachment handling on ``DELETE /auth/me``
(avatar and unreferenced uploads removed with their files; contributions kept).

Rows are committed (the app uses its own sessions). Categories are registered with
``cleanup_forum_categories`` (which removes the posts and threads in them, with their comments,
replies and thread links), reports with ``cleanup_reports``, post links with
``cleanup_knowbase_links`` and attachments with ``cleanup_attachments``. Audit rows
are removed with their actor by ``cleanup_users`` / ``cleanup_user_ids``.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.crud import audit as crud_audit
from app.crud.token import create_email_token
from app.db.enums import CategoryKind, ContentStatus, HiddenReason, ReportStatus, TokenPurpose
from app.db.models import (
    Attachment,
    AuditLog,
    EmailToken,
    ExpertiseTag,
    Organisation,
    Post,
    Reply,
    Session,
    User,
)
from app.db.session import AsyncSessionLocal
from app.services import images
from tests.factories import (
    DEFAULT_PASSWORD,
    create_admin,
    create_attachment,
    create_category,
    create_comment,
    create_knowbase_link,
    create_post,
    create_reply,
    create_report,
    create_tag,
    create_thread,
    create_thread_knowbase_link,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
ME = f"{API}/auth/me"
EXPORT = f"{API}/auth/me/export"
STATUSES = ("pending", "published", "hidden", "deleted")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ADMIN_IDENTITY_KEYS = {"actor_id", "admin_id", "resolved_by", "approved_by"}


# --- fixtures and helpers ---------------------------------------------------------------------


@pytest.fixture
async def cleanup_tag_ids(database_url: str) -> AsyncIterator[set[int]]:
    from app.db.models import Tag

    ids: set[int] = set()
    yield ids
    if not ids:
        return
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(delete(Tag).where(Tag.id.in_(ids)))


@dataclass
class World:
    user: User
    other: User
    admin: User
    body: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    posts: dict[str, int] = field(default_factory=dict)
    threads: dict[str, int] = field(default_factory=dict)
    replies: dict[str, int] = field(default_factory=dict)
    comments: dict[str, int] = field(default_factory=dict)
    other_ids: dict[str, int] = field(default_factory=dict)
    ids: dict[str, int] = field(default_factory=dict)


def _status_fields(status: str, now: datetime) -> dict[str, Any]:
    fields: dict[str, Any] = {"status": ContentStatus(status)}
    if status == "hidden":
        fields["hidden_reason"] = HiddenReason.ADMIN
    if status == "deleted":
        fields["deleted_at"] = now
    return fields


@pytest.fixture
async def world(
    client,
    db_session,
    cleanup_users,
    cleanup_user_ids,
    cleanup_forum_categories,
    cleanup_knowbase_links,
    cleanup_reports,
    cleanup_attachments,
    cleanup_tag_ids,
) -> World:
    """A member with content of every status, uploads, reports and audit rows, plus another
    member's and an admin's rows that must stay out of the export; then the export itself."""
    db = db_session
    now = datetime.now(UTC)
    uowm = (
        await db.execute(select(Organisation).where(Organisation.short_name == "UOWM"))
    ).scalar_one()
    expertise = list(
        (await db.scalars(select(ExpertiseTag).order_by(ExpertiseTag.id).limit(2))).all()
    )
    user = await create_verified_user(
        db, display_name="Exporter", organisation_id=uowm.id, expertise=expertise
    )
    other = await create_verified_user(db, display_name="Other Member")
    admin = await create_admin(db, display_name="Some Admin")
    for person in (user, other, admin):
        cleanup_users.add(person.email)
        cleanup_user_ids.add(person.id)
    w = World(user=user, other=other, admin=admin)

    blog = await create_category(db, kind=CategoryKind.BLOG)
    forum = await create_category(db, kind=CategoryKind.FORUM)
    cleanup_forum_categories.update({blog.id, forum.id})
    tag = await create_tag(db)
    cleanup_tag_ids.add(tag.id)
    w.ids.update(blog=blog.id, forum=forum.id, tag=tag.id)

    live = await create_attachment(db, uploader_id=user.id, alt_text="Flooded street")
    gone = await create_attachment(db, uploader_id=user.id, deleted_at=now)
    others_upload = await create_attachment(db, uploader_id=other.id)
    cleanup_attachments.update({live.id, gone.id, others_upload.id})
    w.ids.update(live_attachment=live.id, deleted_attachment=gone.id)
    w.other_ids["attachment"] = others_upload.id

    for status in STATUSES:
        extra: dict[str, Any] = {}
        if status == "published":
            extra = {
                "excerpt": "Short excerpt",
                "event_at": now + timedelta(days=10),
                "event_url": "https://example.org/event",
                "cover_attachment_id": live.id,
                "approved_by": admin.id,
                "approved_at": now,
                "tags": [tag],
            }
        post = await create_post(
            db,
            category_id=blog.id,
            author_id=user.id,
            title=f"My {status} post",
            **_status_fields(status, now),
            **extra,
        )
        w.posts[status] = post.id
    cleanup_knowbase_links.add(w.posts["published"])
    await create_knowbase_link(db, post_id=w.posts["published"], kb_type="measure", kb_id=42)
    other_post = await create_post(db, category_id=blog.id, author_id=other.id)
    w.other_ids["post"] = other_post.id

    for status in STATUSES:
        extra = (
            {"is_pinned": True, "is_locked": True, "tags": [tag]} if status == "published" else {}
        )
        thread = await create_thread(
            db,
            category_id=forum.id,
            author_id=user.id,
            title=f"My {status} thread",
            **_status_fields(status, now),
            **extra,
        )
        w.threads[status] = thread.id
    await create_thread_knowbase_link(
        db, thread_id=w.threads["published"], kb_type="document", kb_id=9
    )
    other_thread = await create_thread(db, category_id=forum.id, author_id=other.id)
    w.other_ids["thread"] = other_thread.id

    for status in STATUSES:
        reply = await create_reply(
            db,
            thread_id=other_thread.id,
            author_id=user.id,
            body=f"My {status} reply",
            **_status_fields(status, now),
        )
        w.replies[status] = reply.id
    other_reply = await create_reply(db, thread_id=other_thread.id, author_id=other.id)
    child = await create_reply(
        db,
        thread_id=other_thread.id,
        author_id=user.id,
        parent_reply_id=other_reply.id,
        body="My child reply",
    )
    w.ids["child_reply"] = child.id
    w.other_ids["reply"] = other_reply.id

    for status in STATUSES:
        comment = await create_comment(
            db,
            post_id=other_post.id,
            author_id=user.id,
            body=f"My {status} comment",
            **_status_fields(status, now),
        )
        w.comments[status] = comment.id
    other_comment = await create_comment(db, post_id=w.posts["published"], author_id=other.id)
    w.other_ids["comment"] = other_comment.id

    mine = await create_report(
        db,
        reporter_id=user.id,
        content_type="post",
        content_id=other_post.id,
        reason="spam",
        details="Looks like spam",
        status=ReportStatus.RESOLVED,
        resolved_by=admin.id,
        resolved_at=now,
    )
    theirs = await create_report(
        db, reporter_id=other.id, content_type="post", content_id=w.posts["published"]
    )
    cleanup_reports.update({mine.id, theirs.id})
    w.ids["report"] = mine.id
    w.other_ids["report"] = theirs.id

    hide = await crud_audit.log_action(
        db,
        actor_id=admin.id,
        action="post.hide",
        target_type="post",
        target_id=w.posts["hidden"],
        metadata={
            "from": "published",
            "to": "hidden",
            "reason": "admin",
            "actor_id": admin.id,
            "resolved_by": admin.id,
            "details": {"admin_id": admin.id, "note": "kept"},
        },
    )
    await crud_audit.log_action(
        db, actor_id=admin.id, action="admin.trust", target_type="user", target_id=user.id
    )
    await crud_audit.log_action(
        db,
        actor_id=admin.id,
        action="post.hide",
        target_type="post",
        target_id=other_post.id,
        metadata={"from": "published", "to": "hidden"},
    )
    await crud_audit.log_action(
        db,
        actor_id=other.id,
        action="report.create",
        target_type="report",
        target_id=theirs.id,
        metadata={"content_type": "post", "content_id": w.posts["published"]},
    )
    await crud_audit.log_action(
        db, actor_id=other.id, action="auth.logout", target_type="user", target_id=other.id
    )
    w.ids["hide_audit"] = hide.id
    await create_email_token(db, user_id=user.id, purpose=TokenPurpose.RESET_PASSWORD)
    await db.commit()

    await login_as(client, user, user_agent="Exporter/2.0")
    response = await client.get(EXPORT)
    assert response.status_code == 200, response.text
    w.body = response.json()
    w.text = response.text
    return w


def _by_id(items: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {item["id"]: item for item in items}


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys |= _all_keys(item)
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys |= _all_keys(item)
        return keys
    return set()


# --- export: shape ----------------------------------------------------------------------------


async def test_export_format_version_and_top_level_keys(world):
    body = world.body
    assert body["format_version"] == 2
    assert set(body) == {
        "exported_at",
        "format_version",
        "licence_note",
        "user",
        "notification_preferences",
        "sessions",
        "audit_log",
        "content",
        "attachments",
        "reports_made",
    }
    assert set(body["content"]) == {"posts", "threads", "replies", "comments"}
    exported_at = datetime.fromisoformat(body["exported_at"])
    assert abs((datetime.now(UTC) - exported_at).total_seconds()) < 60


async def test_export_includes_organisation_and_expertise(world):
    user = world.body["user"]
    assert user["organisation"]["short_name"] == "UOWM"
    assert len(user["expertise"]) == 2
    assert world.body["notification_preferences"]["digest_frequency"] == "daily"
    assert world.body["notification_preferences"]["moderation_decisions"] is False
    assert world.body["notification_preferences"]["admin_digest"] is True


# --- export: posts ----------------------------------------------------------------------------


async def test_export_posts_every_status(world):
    posts = _by_id(world.body["content"]["posts"])
    assert set(posts) == set(world.posts.values())
    for status, post_id in world.posts.items():
        assert posts[post_id]["status"] == status
        assert posts[post_id]["title"] == f"My {status} post"
    assert posts[world.posts["deleted"]]["deleted_at"] is not None
    assert posts[world.posts["hidden"]]["hidden_reason"] == "admin"


async def test_export_post_fields(world):
    post = _by_id(world.body["content"]["posts"])[world.posts["published"]]
    assert set(post) == {
        "id",
        "slug",
        "title",
        "locale",
        "status",
        "hidden_reason",
        "category",
        "tags",
        "body_html",
        "body_text",
        "excerpt",
        "cover_attachment_id",
        "event_at",
        "event_url",
        "created_at",
        "updated_at",
        "published_at",
        "deleted_at",
        "knowbase_links",
    }
    assert post["category"]["id"] == world.ids["blog"]
    assert post["category"]["kind"] == "blog"
    assert [tag["id"] for tag in post["tags"]] == [world.ids["tag"]]
    assert post["excerpt"] == "Short excerpt"
    assert post["event_url"] == "https://example.org/event"
    assert post["event_at"] is not None
    assert post["published_at"] is not None
    assert post["cover_attachment_id"] == world.ids["live_attachment"]
    assert post["body_html"].startswith("<p>")
    assert "Nature-based" in post["body_text"]
    assert post["knowbase_links"] == [
        {
            "kb_type": "measure",
            "kb_id": 42,
            "title_en": "Linked KNOWBASE item",
            "title_local": None,
            "url": "/knowbase/measures/42",
        }
    ]


async def test_export_post_never_names_the_approving_admin(world):
    keys = _all_keys(world.body["content"])
    assert "approved_by" not in keys


# --- export: threads, replies, comments -------------------------------------------------------


async def test_export_threads_every_status(world):
    threads = _by_id(world.body["content"]["threads"])
    assert set(threads) == set(world.threads.values())
    for status, thread_id in world.threads.items():
        assert threads[thread_id]["status"] == status
    assert threads[world.threads["deleted"]]["deleted_at"] is not None


async def test_export_thread_fields(world):
    thread = _by_id(world.body["content"]["threads"])[world.threads["published"]]
    assert set(thread) == {
        "id",
        "slug",
        "title",
        "locale",
        "status",
        "hidden_reason",
        "category",
        "tags",
        "body_html",
        "body_text",
        "is_pinned",
        "is_locked",
        "created_at",
        "updated_at",
        "published_at",
        "deleted_at",
        "knowbase_links",
    }
    assert thread["is_pinned"] is True
    assert thread["is_locked"] is True
    assert thread["category"]["id"] == world.ids["forum"]
    assert [tag["id"] for tag in thread["tags"]] == [world.ids["tag"]]
    assert [(link["kb_type"], link["kb_id"]) for link in thread["knowbase_links"]] == [
        ("document", 9)
    ]


async def test_export_replies_every_status_and_fields(world):
    replies = _by_id(world.body["content"]["replies"])
    assert set(replies) == {*world.replies.values(), world.ids["child_reply"]}
    for status, reply_id in world.replies.items():
        reply = replies[reply_id]
        assert reply["status"] == status
        assert reply["thread_id"] == world.other_ids["thread"]
        assert f"My {status} reply" in reply["body_text"]
    child = replies[world.ids["child_reply"]]
    assert child["parent_reply_id"] == world.other_ids["reply"]
    assert set(child) == {
        "id",
        "thread_id",
        "parent_reply_id",
        "body_html",
        "body_text",
        "status",
        "hidden_reason",
        "created_at",
        "updated_at",
        "deleted_at",
    }


async def test_export_comments_every_status_and_fields(world):
    comments = _by_id(world.body["content"]["comments"])
    assert set(comments) == set(world.comments.values())
    for status, comment_id in world.comments.items():
        comment = comments[comment_id]
        assert comment["status"] == status
        assert comment["post_id"] == world.other_ids["post"]
    assert set(comments[world.comments["published"]]) == {
        "id",
        "post_id",
        "body_html",
        "body_text",
        "status",
        "hidden_reason",
        "created_at",
        "updated_at",
        "deleted_at",
    }


async def test_export_excludes_other_members_content(world):
    content = world.body["content"]
    assert world.other_ids["post"] not in _by_id(content["posts"])
    assert world.other_ids["thread"] not in _by_id(content["threads"])
    assert world.other_ids["reply"] not in _by_id(content["replies"])
    assert world.other_ids["comment"] not in _by_id(content["comments"])


# --- export: attachments and reports ----------------------------------------------------------


async def test_export_attachments_mine_only_including_deleted(world):
    attachments = _by_id(world.body["attachments"])
    assert set(attachments) == {world.ids["live_attachment"], world.ids["deleted_attachment"]}
    live = attachments[world.ids["live_attachment"]]
    assert set(live) == {
        "id",
        "original_filename",
        "mime",
        "size_bytes",
        "width",
        "height",
        "alt_text",
        "created_at",
        "deleted_at",
        "url",
        "thumb_url",
    }
    assert live["alt_text"] == "Flooded street"
    assert live["url"].startswith(f"{settings.UPLOAD_URL_PREFIX}/2026/01/")
    assert live["deleted_at"] is None
    assert attachments[world.ids["deleted_attachment"]]["deleted_at"] is not None


async def test_export_reports_made_mine_only(world):
    reports = _by_id(world.body["reports_made"])
    assert set(reports) == {world.ids["report"]}
    report = reports[world.ids["report"]]
    assert set(report) == {
        "id",
        "content_type",
        "content_id",
        "reason",
        "details",
        "status",
        "created_at",
        "resolved_at",
    }
    assert report["content_type"] == "post"
    assert report["content_id"] == world.other_ids["post"]
    assert report["reason"] == "spam"
    assert report["details"] == "Looks like spam"
    assert report["status"] == "resolved"
    assert "resolved_by" not in _all_keys(world.body["reports_made"])


# --- export: audit log ------------------------------------------------------------------------


async def test_export_audit_includes_moderation_of_own_content(world):
    rows = [
        row
        for row in world.body["audit_log"]
        if row["action"] == "post.hide" and row["target_id"] == world.posts["hidden"]
    ]
    assert len(rows) == 1
    assert rows[0]["target_type"] == "post"
    assert "admin.trust" in [row["action"] for row in world.body["audit_log"]]


async def test_export_audit_metadata_never_names_the_admin(world):
    row = next(
        row
        for row in world.body["audit_log"]
        if row["action"] == "post.hide" and row["target_id"] == world.posts["hidden"]
    )
    assert row["metadata"] == {
        "from": "published",
        "to": "hidden",
        "reason": "admin",
        "details": {"note": "kept"},
    }
    for entry in world.body["audit_log"]:
        assert set(entry) == {"action", "target_type", "target_id", "metadata", "created_at"}
        assert _all_keys(entry["metadata"]).isdisjoint(ADMIN_IDENTITY_KEYS)


async def test_export_audit_excludes_rows_about_others(world):
    for row in world.body["audit_log"]:
        assert not (row["target_type"] == "post" and row["target_id"] == world.other_ids["post"])
        assert not (
            row["target_type"] == "report" and row["target_id"] == world.other_ids["report"]
        )
        assert row["action"] != "auth.logout"


# --- export: nothing that belongs to anyone else, no secrets ----------------------------------


async def test_export_contains_no_other_email_address(world):
    assert world.other.email not in world.text
    assert world.admin.email not in world.text
    assert set(EMAIL_RE.findall(world.text)) == {world.user.email}


async def test_export_contains_no_hashes(world, db_session):
    assert "$argon2" not in world.text
    token_hashes = (
        await db_session.scalars(select(Session.token_hash).where(Session.user_id == world.user.id))
    ).all()
    assert token_hashes
    email_hashes = (
        await db_session.scalars(
            select(EmailToken.token_hash).where(EmailToken.user_id == world.user.id)
        )
    ).all()
    assert email_hashes
    for value in (*token_hashes, *email_hashes):
        assert value not in world.text
    keys = _all_keys(world.body)
    assert keys.isdisjoint({"password_hash", "token_hash", "storage_path", "thumb_path"})


async def test_export_sessions_as_on_the_sessions_page(world):
    assert len(world.body["sessions"]) == 1
    session = world.body["sessions"][0]
    assert set(session) == {
        "id",
        "created_at",
        "last_seen_at",
        "expires_at",
        "user_agent",
        "revoked_at",
    }
    assert session["user_agent"] == "Exporter/2.0"


async def test_export_is_valid_json_download(world):
    # The text round-trips (one document, nothing appended).
    assert json.loads(world.text) == world.body


# --- deletion: attachments --------------------------------------------------------------------


@dataclass(frozen=True)
class Stored:
    """An attachment's id and paths, captured before commit (ORM attributes expire)."""

    id: int
    storage_path: str
    thumb_path: str


async def _with_files(db, upload_dir: Path, *, uploader_id: int | None) -> Stored:
    attachment = await create_attachment(db, uploader_id=uploader_id)
    assert attachment.thumb_path is not None
    images.save_files(upload_dir, attachment.storage_path, b"main", attachment.thumb_path, b"thumb")
    return Stored(attachment.id, attachment.storage_path, attachment.thumb_path)


def _files_exist(upload_dir: Path, attachment: Stored) -> tuple[bool, bool]:
    return (
        (upload_dir / attachment.storage_path).exists(),
        (upload_dir / attachment.thumb_path).exists(),
    )


async def _attachment_exists(db, attachment_id: int) -> bool:
    found = await db.scalar(select(Attachment.id).where(Attachment.id == attachment_id))
    return found is not None


async def _deletion_audit(db, user_id: int) -> AuditLog:
    stmt = select(AuditLog).where(
        AuditLog.action == "auth.account_deleted",
        AuditLog.target_type == "user",
        AuditLog.target_id == user_id,
    )
    return (await db.execute(stmt.execution_options(populate_existing=True))).scalar_one()


async def _member(db, cleanup_users, cleanup_user_ids) -> User:
    user = await create_verified_user(db)
    cleanup_users.add(user.email)
    cleanup_user_ids.add(user.id)
    return user


def _delete_me(client):
    return client.request("DELETE", ME, json={"current_password": DEFAULT_PASSWORD})


async def test_delete_removes_avatar_and_its_files(
    client, db_session, cleanup_users, cleanup_user_ids, cleanup_attachments, upload_dir
):
    user = await _member(db_session, cleanup_users, cleanup_user_ids)
    avatar = await _with_files(db_session, upload_dir, uploader_id=user.id)
    cleanup_attachments.add(avatar.id)
    user.avatar_attachment_id = avatar.id
    await db_session.commit()
    await login_as(client, user)

    response = await _delete_me(client)

    assert response.status_code == 204, response.text
    assert not await _attachment_exists(db_session, avatar.id)
    assert _files_exist(upload_dir, avatar) == (False, False)


async def test_delete_removes_unreferenced_uploads_and_files(
    client, db_session, cleanup_users, cleanup_user_ids, cleanup_attachments, upload_dir
):
    user = await _member(db_session, cleanup_users, cleanup_user_ids)
    unused = await _with_files(db_session, upload_dir, uploader_id=user.id)
    already_deleted = await create_attachment(
        db_session, uploader_id=user.id, deleted_at=datetime.now(UTC)
    )
    cleanup_attachments.update({unused.id, already_deleted.id})
    await db_session.commit()
    await login_as(client, user)

    assert (await _delete_me(client)).status_code == 204

    assert not await _attachment_exists(db_session, unused.id)
    assert not await _attachment_exists(db_session, already_deleted.id)
    assert _files_exist(upload_dir, unused) == (False, False)


async def test_delete_keeps_cover_and_inline_images_of_contributions(
    client,
    db_session,
    cleanup_users,
    cleanup_user_ids,
    cleanup_attachments,
    cleanup_forum_categories,
    upload_dir,
):
    db = db_session
    user = await _member(db, cleanup_users, cleanup_user_ids)
    blog = await create_category(db, kind=CategoryKind.BLOG)
    forum = await create_category(db, kind=CategoryKind.FORUM)
    cleanup_forum_categories.update({blog.id, forum.id})
    cover = await _with_files(db, upload_dir, uploader_id=user.id)
    inline = await _with_files(db, upload_dir, uploader_id=user.id)
    thumb_inline = await _with_files(db, upload_dir, uploader_id=user.id)
    cleanup_attachments.update({cover.id, inline.id, thumb_inline.id})
    post = await create_post(
        db, category_id=blog.id, author_id=user.id, cover_attachment_id=cover.id
    )
    post.body_html = (
        f'<p><img src="{settings.UPLOAD_URL_PREFIX}/{inline.storage_path}" alt="Inline"></p>'
    )
    thread = await create_thread(db, category_id=forum.id, author_id=user.id)
    reply = await create_reply(db, thread_id=thread.id, author_id=user.id)
    reply.body_html = (
        f'<p><img src="{settings.UPLOAD_URL_PREFIX}/{thumb_inline.thumb_path}" alt="T"></p>'
    )
    await db.commit()
    await login_as(client, user)

    assert (await _delete_me(client)).status_code == 204

    for kept in (cover, inline, thumb_inline):
        assert await _attachment_exists(db, kept.id)
        assert _files_exist(upload_dir, kept) == (True, True)
    stored_post = await db.get(Post, post.id, populate_existing=True)
    assert stored_post is not None
    assert stored_post.cover_attachment_id == cover.id
    stored_reply = await db.get(Reply, reply.id, populate_existing=True)
    assert stored_reply is not None
    assert stored_reply.author_id == user.id


async def test_delete_keeps_avatar_used_as_a_post_cover(
    client,
    db_session,
    cleanup_users,
    cleanup_user_ids,
    cleanup_attachments,
    cleanup_forum_categories,
    upload_dir,
):
    db = db_session
    user = await _member(db, cleanup_users, cleanup_user_ids)
    blog = await create_category(db, kind=CategoryKind.BLOG)
    cleanup_forum_categories.add(blog.id)
    avatar = await _with_files(db, upload_dir, uploader_id=user.id)
    cleanup_attachments.add(avatar.id)
    user.avatar_attachment_id = avatar.id
    await create_post(db, category_id=blog.id, author_id=user.id, cover_attachment_id=avatar.id)
    await db.commit()
    await login_as(client, user)

    assert (await _delete_me(client)).status_code == 204

    assert await _attachment_exists(db, avatar.id)
    assert _files_exist(upload_dir, avatar) == (True, True)
    stored = await db.get(User, user.id, populate_existing=True)
    assert stored is not None
    assert stored.avatar_attachment_id is None


def _embed(stored: Stored) -> str:
    return f'<p><img src="{settings.UPLOAD_URL_PREFIX}/{stored.storage_path}" alt="Inline"></p>'


async def test_delete_keeps_avatar_embedded_in_own_content(
    client,
    db_session,
    cleanup_users,
    cleanup_user_ids,
    cleanup_attachments,
    cleanup_forum_categories,
    upload_dir,
):
    db = db_session
    user = await _member(db, cleanup_users, cleanup_user_ids)
    forum = await create_category(db, kind=CategoryKind.FORUM)
    cleanup_forum_categories.add(forum.id)
    avatar = await _with_files(db, upload_dir, uploader_id=user.id)
    cleanup_attachments.add(avatar.id)
    user.avatar_attachment_id = avatar.id
    thread = await create_thread(db, category_id=forum.id, author_id=user.id)
    thread.body_html = _embed(avatar)
    await db.commit()
    await login_as(client, user)

    assert (await _delete_me(client)).status_code == 204

    assert await _attachment_exists(db, avatar.id)
    assert _files_exist(upload_dir, avatar) == (True, True)


async def test_another_members_embed_does_not_keep_the_erased_members_images(
    client,
    db_session,
    cleanup_users,
    cleanup_user_ids,
    cleanup_attachments,
    cleanup_forum_categories,
    upload_dir,
):
    """7m: erasure counts only the member's own content; another member embedding the avatar
    (or any other upload of the member) does not keep it on disk and public."""
    db = db_session
    user = await _member(db, cleanup_users, cleanup_user_ids)
    other = await _member(db, cleanup_users, cleanup_user_ids)
    blog = await create_category(db, kind=CategoryKind.BLOG)
    cleanup_forum_categories.add(blog.id)
    avatar = await _with_files(db, upload_dir, uploader_id=user.id)
    inline = await _with_files(db, upload_dir, uploader_id=user.id)
    cleanup_attachments.update({avatar.id, inline.id})
    user.avatar_attachment_id = avatar.id
    theirs = await create_post(
        db, category_id=blog.id, author_id=other.id, cover_attachment_id=inline.id
    )
    theirs.body_html = _embed(avatar) + _embed(inline)
    await db.commit()
    await login_as(client, user)

    assert (await _delete_me(client)).status_code == 204

    for gone in (avatar, inline):
        assert not await _attachment_exists(db, gone.id)
        assert _files_exist(upload_dir, gone) == (False, False)
    stored_post = await db.get(Post, theirs.id, populate_existing=True)
    assert stored_post is not None
    assert stored_post.cover_attachment_id is None
    row = await _deletion_audit(db, user.id)
    assert row.metadata_["attachments_deleted"] == 2


async def test_delete_removes_an_avatar_only_mentioned_in_own_content(
    client,
    db_session,
    cleanup_users,
    cleanup_user_ids,
    cleanup_attachments,
    cleanup_forum_categories,
    upload_dir,
):
    db = db_session
    user = await _member(db, cleanup_users, cleanup_user_ids)
    blog = await create_category(db, kind=CategoryKind.BLOG)
    cleanup_forum_categories.add(blog.id)
    avatar = await _with_files(db, upload_dir, uploader_id=user.id)
    cleanup_attachments.add(avatar.id)
    user.avatar_attachment_id = avatar.id
    post = await create_post(db, category_id=blog.id, author_id=user.id)
    post.body_html = f"<p>My avatar: {settings.UPLOAD_URL_PREFIX}/{avatar.storage_path}</p>"
    await db.commit()
    await login_as(client, user)

    assert (await _delete_me(client)).status_code == 204

    assert not await _attachment_exists(db, avatar.id)
    assert _files_exist(upload_dir, avatar) == (False, False)


async def test_delete_unlinks_but_keeps_an_avatar_uploaded_by_another_member(
    client, db_session, cleanup_users, cleanup_user_ids, cleanup_attachments, upload_dir
):
    user = await _member(db_session, cleanup_users, cleanup_user_ids)
    other = await _member(db_session, cleanup_users, cleanup_user_ids)
    theirs = await _with_files(db_session, upload_dir, uploader_id=other.id)
    cleanup_attachments.add(theirs.id)
    user.avatar_attachment_id = theirs.id
    await db_session.commit()
    await login_as(client, user)

    assert (await _delete_me(client)).status_code == 204

    stored = await db_session.get(User, user.id, populate_existing=True)
    assert stored is not None
    assert stored.avatar_attachment_id is None
    assert await _attachment_exists(db_session, theirs.id)
    assert _files_exist(upload_dir, theirs) == (True, True)
    row = await _deletion_audit(db_session, user.id)
    assert row.metadata_["attachments_deleted"] == 0


async def test_delete_leaves_other_members_uploads_alone(
    client, db_session, cleanup_users, cleanup_user_ids, cleanup_attachments, upload_dir
):
    user = await _member(db_session, cleanup_users, cleanup_user_ids)
    other = await _member(db_session, cleanup_users, cleanup_user_ids)
    theirs = await _with_files(db_session, upload_dir, uploader_id=other.id)
    cleanup_attachments.add(theirs.id)
    await db_session.commit()
    await login_as(client, user)

    assert (await _delete_me(client)).status_code == 204

    assert await _attachment_exists(db_session, theirs.id)
    assert _files_exist(upload_dir, theirs) == (True, True)


async def test_delete_audit_counts_attachments_deleted(
    client,
    db_session,
    cleanup_users,
    cleanup_user_ids,
    cleanup_attachments,
    cleanup_forum_categories,
    upload_dir,
):
    db = db_session
    user = await _member(db, cleanup_users, cleanup_user_ids)
    blog = await create_category(db, kind=CategoryKind.BLOG)
    cleanup_forum_categories.add(blog.id)
    avatar = await _with_files(db, upload_dir, uploader_id=user.id)
    unused = await _with_files(db, upload_dir, uploader_id=user.id)
    cover = await _with_files(db, upload_dir, uploader_id=user.id)
    cleanup_attachments.update({avatar.id, unused.id, cover.id})
    user.avatar_attachment_id = avatar.id
    await create_post(db, category_id=blog.id, author_id=user.id, cover_attachment_id=cover.id)
    await db.commit()
    await login_as(client, user)

    assert (await _delete_me(client)).status_code == 204

    row = await _deletion_audit(db, user.id)
    assert row.actor_id == user.id
    assert row.metadata_ == {
        "role": "member",
        "attachments_deleted": 2,
        "reports_closed": 0,
        "content_recounted": 0,
    }


async def test_delete_without_uploads_audits_zero(
    client, db_session, cleanup_users, cleanup_user_ids
):
    user = await _member(db_session, cleanup_users, cleanup_user_ids)
    await db_session.commit()
    await login_as(client, user)

    assert (await _delete_me(client)).status_code == 204

    row = await _deletion_audit(db_session, user.id)
    assert row.metadata_ == {
        "role": "member",
        "attachments_deleted": 0,
        "reports_closed": 0,
        "content_recounted": 0,
    }


# --- crud -------------------------------------------------------------------------------------


async def test_crud_delete_unreferenced_uploads_returns_paths(db_session):
    from app.crud import attachment as crud_attachment

    user = await create_verified_user(db_session)
    unused = await create_attachment(db_session, uploader_id=user.id)
    blog = await create_category(db_session, kind=CategoryKind.BLOG)
    cover = await create_attachment(db_session, uploader_id=user.id)
    await create_post(
        db_session, category_id=blog.id, author_id=user.id, cover_attachment_id=cover.id
    )

    paths = await crud_attachment.delete_unreferenced_uploads(db_session, user_id=user.id)

    assert paths == [(unused.storage_path, unused.thumb_path)]
    assert not await _attachment_exists(db_session, unused.id)
    assert await _attachment_exists(db_session, cover.id)

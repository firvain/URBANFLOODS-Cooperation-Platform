"""Transactional notification emails: a reply to my thread, a reply to my reply, a comment on my
post.

The create endpoints schedule :func:`send_reply_notifications` / :func:`send_comment_notifications`
as FastAPI background tasks. ``DbTx`` (``scope="function"``) commits before the response is sent
and background tasks run after it, so the task sees the committed row; it opens its own
read-only session. Failures are logged (``notification.failed``, kind and ids only) and
swallowed: a notification never fails the request that caused it.

A recipient is skipped when they are the actor, have no account any more (author removed), are
inactive, deleted or unverified, or have turned the matching preference off. A missing
preferences row counts as the defaults (all on); it is not created here (read-only session).

A nested reply notifies the parent reply's author (``reply_to_reply``) and the thread author
(``reply_to_thread``). When they are the same person they get one email: ``reply_to_reply`` if
they accept it, else ``reply_to_thread`` if they accept that.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ContentStatus
from app.db.models import Comment, NotificationPreference, Post, Reply, Thread, User
from app.db.session import AsyncSessionLocal
from app.services import email as email_service
from app.services.email import OutgoingEmail

EXCERPT_MAX_LENGTH = 200
SETTINGS_PATH = "/account?tab=notifications"

REPLY_TO_THREAD = "reply_to_thread"
REPLY_TO_REPLY = "reply_to_reply"
COMMENT_ON_POST = "comment_on_post"


def make_excerpt(text: str, limit: int = EXCERPT_MAX_LENGTH) -> str:
    """``text`` on one line (whitespace collapsed), cut to at most ``limit`` characters with an
    ellipsis when it is longer."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"


def _published(row: Any) -> bool:
    return row is not None and row.status == ContentStatus.PUBLISHED and row.deleted_at is None


async def _recipient(
    db: AsyncSession, *, user_id: int | None, actor_id: int, preference: str
) -> User | None:
    """The user to notify, or ``None`` when they must not get this kind of email."""
    if user_id is None or user_id == actor_id:
        return None
    user = await db.get(User, user_id)
    if user is None or not user.is_active or not user.is_verified or user.deleted_at is not None:
        return None
    preferences = await db.get(NotificationPreference, user_id)
    if preferences is not None and not getattr(preferences, preference):
        return None
    return user


async def _actor(db: AsyncSession, author_id: int | None) -> User | None:
    return None if author_id is None else await db.get(User, author_id)


async def _send(
    *,
    kind: str,
    recipient: User,
    content_id: int,
    context: dict[str, Any],
) -> OutgoingEmail:
    msg = await email_service.send_email(
        to=recipient.email,
        template=kind,
        locale=recipient.locale,
        context={
            **context,
            "display_name": recipient.display_name,
            "settings_url": SETTINGS_PATH,
        },
    )
    structlog.get_logger(__name__).info(
        "notification.sent", kind=kind, recipient_id=recipient.id, content_id=content_id
    )
    return msg


def _thread_link(thread: Thread, reply: Reply) -> str:
    return f"/forum/t/{quote(thread.slug, safe='')}#reply-{reply.id}"


async def _reply_context(db: AsyncSession, reply: Reply) -> tuple[Thread, User] | None:
    """The reply's thread and author when a notification about it may go out at all."""
    if not _published(reply) or reply.author_id is None:
        return None
    thread = await db.get(Thread, reply.thread_id)
    actor = await _actor(db, reply.author_id)
    if not _published(thread) or actor is None:
        return None
    assert thread is not None
    return thread, actor


async def _reply_to_reply_recipient(db: AsyncSession, reply: Reply) -> User | None:
    """The parent reply's author when they get a ``reply_to_reply`` email for ``reply``."""
    if reply.parent_reply_id is None or reply.author_id is None:
        return None
    parent = await db.get(Reply, reply.parent_reply_id)
    if parent is None or parent.status == ContentStatus.DELETED:
        return None
    return await _recipient(
        db, user_id=parent.author_id, actor_id=reply.author_id, preference="reply_to_my_reply"
    )


def _reply_email_context(thread: Thread, actor: User, reply: Reply) -> dict[str, Any]:
    return {
        "actor_name": actor.display_name,
        "thread_title": thread.title,
        "excerpt": make_excerpt(reply.body_text),
        "link_url": _thread_link(thread, reply),
    }


async def notify_reply_to_thread(db: AsyncSession, *, reply: Reply) -> OutgoingEmail | None:
    """Email the thread's author about ``reply``. Returns what was sent, or ``None``."""
    loaded = await _reply_context(db, reply)
    if loaded is None:
        return None
    thread, actor = loaded
    recipient = await _recipient(
        db, user_id=thread.author_id, actor_id=actor.id, preference="reply_to_my_thread"
    )
    if recipient is None:
        return None
    # Already told about this reply by the more specific reply-to-reply email.
    covered = await _reply_to_reply_recipient(db, reply)
    if covered is not None and covered.id == recipient.id:
        return None
    return await _send(
        kind=REPLY_TO_THREAD,
        recipient=recipient,
        content_id=reply.id,
        context=_reply_email_context(thread, actor, reply),
    )


async def notify_reply_to_reply(db: AsyncSession, *, reply: Reply) -> OutgoingEmail | None:
    """Email the parent reply's author about the nested ``reply``. Returns what was sent, or
    ``None`` (also for a top-level reply)."""
    if reply.parent_reply_id is None:
        return None
    loaded = await _reply_context(db, reply)
    if loaded is None:
        return None
    thread, actor = loaded
    recipient = await _reply_to_reply_recipient(db, reply)
    if recipient is None:
        return None
    return await _send(
        kind=REPLY_TO_REPLY,
        recipient=recipient,
        content_id=reply.id,
        context=_reply_email_context(thread, actor, reply),
    )


async def notify_comment_on_post(db: AsyncSession, *, comment: Comment) -> OutgoingEmail | None:
    """Email the post's author about ``comment``. Returns what was sent, or ``None``."""
    if not _published(comment) or comment.author_id is None:
        return None
    post = await db.get(Post, comment.post_id)
    actor = await _actor(db, comment.author_id)
    if not _published(post) or actor is None:
        return None
    assert post is not None
    recipient = await _recipient(
        db, user_id=post.author_id, actor_id=actor.id, preference="comment_on_my_post"
    )
    if recipient is None:
        return None
    return await _send(
        kind=COMMENT_ON_POST,
        recipient=recipient,
        content_id=comment.id,
        context={
            "actor_name": actor.display_name,
            "post_title": post.title,
            "excerpt": make_excerpt(comment.body_text),
            "link_url": f"/blog/{quote(post.slug, safe='')}#comment-{comment.id}",
        },
    )


# --- background tasks -------------------------------------------------------------------------


def _failed(kind: str, exc: BaseException, **ids: int) -> None:
    # Error type only: the message or a traceback could carry an address.
    structlog.get_logger(__name__).error(
        "notification.failed", kind=kind, error=type(exc).__name__, **ids
    )


async def send_reply_notifications(reply_id: int) -> None:
    """Background task after a reply is created: both reply notifications, each isolated."""
    try:
        async with AsyncSessionLocal() as db:
            reply = await db.get(Reply, reply_id)
            if reply is None:
                return
            for kind, notify in (
                (REPLY_TO_REPLY, notify_reply_to_reply),
                (REPLY_TO_THREAD, notify_reply_to_thread),
            ):
                try:
                    await notify(db, reply=reply)
                except Exception as exc:
                    _failed(kind, exc, reply_id=reply_id)
    except Exception as exc:
        _failed("reply", exc, reply_id=reply_id)


async def send_comment_notifications(comment_id: int) -> None:
    """Background task after a comment is created."""
    try:
        async with AsyncSessionLocal() as db:
            comment = await db.get(Comment, comment_id)
            if comment is None:
                return
            try:
                await notify_comment_on_post(db, comment=comment)
            except Exception as exc:
                _failed(COMMENT_ON_POST, exc, comment_id=comment_id)
    except Exception as exc:
        _failed("comment", exc, comment_id=comment_id)

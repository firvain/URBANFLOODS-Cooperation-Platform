"""Blog post comment data access: list, get, create, update (author within 24 h, or an admin)
and soft delete. Never commits; the caller (``get_db_tx``) does.

Comments are ``published`` on creation (no trust gate); moderation may later hide or delete
them. Reads go through :func:`app.crud.visibility.visible_filter`, so deleted comments are never
listed. ``posts.comment_count`` is kept by the ``comments_comment_count`` trigger (migration
0005), so nothing here touches it.

Bodies use a narrower allow-list than posts (:func:`sanitize_comment_html`): no headings,
images, tables, rules or code blocks.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import nh3
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.exceptions import AppError, validation_error
from app.crud.post import not_found as post_not_found
from app.crud.visibility import is_admin, is_visible, visible_filter
from app.db.enums import ContentStatus
from app.db.models import Comment, Post, User
from app.services.sanitize import LINK_REL, URL_SCHEMES, html_to_text, sanitize_html

BODY_TEXT_MAX_LENGTH = 5000
EDIT_WINDOW = timedelta(hours=24)

COMMENT_ALLOWED_TAGS = frozenset(
    {"p", "br", "strong", "em", "u", "s", "a", "code", "blockquote", "ul", "ol", "li"}
)
COMMENT_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {"a": {"href", "title", "target"}}
# Headings become paragraphs (rather than running into the next block) before the strip.
_HEADING_TAG = re.compile(r"<(/?)h[1-6]>")


# --- errors -----------------------------------------------------------------------------------


def not_found() -> AppError:
    return AppError(404, "comments.not_found", "Comment not found.")


def forbidden() -> AppError:
    return AppError(403, "comments.forbidden", "You cannot change this comment.")


def post_not_published() -> AppError:
    return AppError(
        422, "comments.post_not_published", "Comments are open on published posts only."
    )


# --- sanitising -------------------------------------------------------------------------------


def sanitize_comment_html(html: str) -> str:
    """:func:`app.services.sanitize.sanitize_html` narrowed to the comment allow-list. Text of
    stripped tags is kept (headings become paragraphs); images vanish. ``""`` when no text
    remains."""
    cleaned = sanitize_html(html)
    if not cleaned:
        return ""
    cleaned = _HEADING_TAG.sub(r"<\1p>", cleaned)
    cleaned = nh3.clean(
        cleaned,
        tags=set(COMMENT_ALLOWED_TAGS),
        attributes=COMMENT_ALLOWED_ATTRIBUTES,
        url_schemes=set(URL_SCHEMES),
        link_rel=LINK_REL,
        strip_comments=True,
    ).strip()
    return cleaned if html_to_text(cleaned) else ""


def _clean_body(body_html: str) -> tuple[str, str]:
    """``(sanitised html, plain text)``; 422 ``body_html`` = ``empty`` / ``too_long``."""
    html = sanitize_comment_html(body_html)
    if not html:
        raise validation_error({"body_html": "empty"})
    text = html_to_text(html)
    if len(text) > BODY_TEXT_MAX_LENGTH:
        raise validation_error({"body_html": "too_long"})
    return html, text


# --- reads ------------------------------------------------------------------------------------


def _with_author(stmt: Any) -> Any:
    return stmt.options(
        joinedload(Comment.author).joinedload(User.organisation),
        joinedload(Comment.author).joinedload(User.avatar),
    )


async def list_comments(
    db: AsyncSession, *, post: Post, user: User | None, skip: int = 0, limit: int = 50
) -> tuple[int, list[Comment]]:
    """``(total, comments)`` on ``post`` visible to ``user``, oldest first. The caller checks
    that ``user`` may see the post."""
    conditions = [Comment.post_id == post.id, visible_filter(Comment, user)]
    total_stmt = select(func.count()).select_from(select(Comment.id).where(*conditions).subquery())
    total = (await db.execute(total_stmt)).scalar_one()
    stmt = _with_author(
        select(Comment).where(*conditions).order_by(Comment.created_at.asc(), Comment.id.asc())
    )
    rows = await db.scalars(stmt.offset(skip).limit(limit))
    return total, list(rows.unique().all())


async def get_comment(db: AsyncSession, *, comment_id: int) -> Comment | None:
    """The comment (any status), author loaded and refreshed from the database."""
    stmt = _with_author(select(Comment).where(Comment.id == comment_id)).execution_options(
        populate_existing=True
    )
    return (await db.scalars(stmt)).unique().one_or_none()


async def get_visible_post(db: AsyncSession, *, post_id: int, user: User | None) -> Post:
    """The post ``user`` may see; 404 ``posts.not_found`` otherwise."""
    post = await db.get(Post, post_id)
    if post is None or not is_visible(post, user):
        raise post_not_found()
    return post


async def get_editable_comment(db: AsyncSession, *, comment_id: int, user: User) -> Comment:
    """The comment ``user`` may change or delete: its author, or an admin.

    404 ``comments.not_found`` when it does not exist, is deleted or ``user`` cannot see it;
    403 ``comments.forbidden`` for anyone else. The edit window is checked by
    :func:`update_comment` (deleting has no time limit).
    """
    comment = await get_comment(db, comment_id=comment_id)
    if comment is None or comment.status == ContentStatus.DELETED or not is_visible(comment, user):
        raise not_found()
    if comment.author_id != user.id and not is_admin(user):
        raise forbidden()
    return comment


# --- writes -----------------------------------------------------------------------------------


async def create_comment(
    db: AsyncSession, *, post: Post, author: User, body_html: str, now: datetime | None = None
) -> Comment:
    """Insert a published comment on ``post`` and return it with its author loaded.

    404 ``posts.not_found`` when ``author`` cannot see the post; 422
    ``comments.post_not_published`` when it is not published; 422 for an empty or too long body.
    """
    if not is_visible(post, author):
        raise post_not_found()
    if post.status != ContentStatus.PUBLISHED:
        raise post_not_published()
    html, text = _clean_body(body_html)
    now = now or datetime.now(UTC)
    comment = Comment(
        post_id=post.id,
        author_id=author.id,
        body_html=html,
        body_text=text,
        status=ContentStatus.PUBLISHED,
        created_at=now,
        updated_at=now,
    )
    db.add(comment)
    await db.flush()
    loaded = await get_comment(db, comment_id=comment.id)
    assert loaded is not None
    return loaded


async def update_comment(
    db: AsyncSession,
    *,
    comment: Comment,
    user: User,
    body_html: str,
    now: datetime | None = None,
) -> bool:
    """Replace the body (re-sanitised) and bump ``updated_at``. Returns whether it changed.

    Admins may edit any time; the author within :data:`EDIT_WINDOW` of creation; anyone else,
    or the author later, gets 403 ``comments.forbidden``.
    """
    now = now or datetime.now(UTC)
    if not is_admin(user) and (
        comment.author_id != user.id or now - comment.created_at > EDIT_WINDOW
    ):
        raise forbidden()
    html, text = _clean_body(body_html)
    if html == comment.body_html:
        return False
    comment.body_html, comment.body_text = html, text
    comment.updated_at = now
    await db.flush()
    return True


async def soft_delete_comment(
    db: AsyncSession, *, comment: Comment, now: datetime | None = None
) -> Comment:
    """Mark the comment deleted (``status`` + ``deleted_at``); the trigger recounts the post."""
    comment.status = ContentStatus.DELETED
    comment.deleted_at = now or datetime.now(UTC)
    await db.flush()
    return comment

"""Async test factories: create rows directly in the database (bypassing the API).

Factories only ``flush``. Tests that drive the HTTP API must ``commit`` the session so the app,
which uses its own sessions, can see the rows; register committed users with the
``cleanup_users`` fixture so they are deleted afterwards.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.db.enums import CategoryKind, ContentStatus, OrganisationType, UserRole
from app.db.models import (
    Attachment,
    Category,
    NotificationPreference,
    Organisation,
    Post,
    Tag,
    User,
)
from app.services.sanitize import html_to_text, sanitize_html

if TYPE_CHECKING:
    import httpx

DEFAULT_PASSWORD = "correct-horse-battery-staple"
LOGIN_PATH = f"{settings.API_V1_PREFIX}/auth/login"


def unique_email(prefix: str = "user") -> str:
    """A fresh address, so tests never collide even if a cleanup was missed."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.org"


async def create_user(
    db: AsyncSession,
    *,
    email: str | None = None,
    password: str = DEFAULT_PASSWORD,
    display_name: str = "Test User",
    is_verified: bool = False,
    is_active: bool = True,
    role: UserRole = UserRole.MEMBER,
    **fields: Any,
) -> User:
    """Insert a user (with notification preferences) and flush. Unverified by default."""
    user = User(
        email=email or unique_email(),
        password_hash=hash_password(password),
        display_name=display_name,
        is_verified=is_verified,
        is_active=is_active,
        role=role,
        **fields,
    )
    user.notification_preferences = NotificationPreference()
    db.add(user)
    await db.flush()
    return user


async def create_verified_user(db: AsyncSession, **kwargs: Any) -> User:
    """A user whose email address is already verified."""
    return await create_user(db, is_verified=True, **kwargs)


async def create_admin(db: AsyncSession, **kwargs: Any) -> User:
    """A verified ``admin``."""
    return await create_verified_user(db, role=UserRole.ADMIN, **kwargs)


async def create_superadmin(db: AsyncSession, **kwargs: Any) -> User:
    """A verified ``superadmin``."""
    return await create_verified_user(db, role=UserRole.SUPERADMIN, **kwargs)


async def login_as(
    client: httpx.AsyncClient,
    user: User,
    *,
    password: str = DEFAULT_PASSWORD,
    user_agent: str | None = None,
) -> httpx.Response:
    """Log ``user`` in through ``POST /auth/login``; the session cookie stays on ``client``.

    The user must be committed first (the app uses its own database sessions).
    """
    headers = {"User-Agent": user_agent} if user_agent else None
    response = await client.post(
        LOGIN_PATH, json={"email": user.email, "password": password}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert settings.SESSION_COOKIE_NAME in client.cookies
    return response


async def create_organisation(
    db: AsyncSession,
    *,
    name: str | None = None,
    short_name: str = "TST",
    country: str = "GR",
    type: OrganisationType = OrganisationType.OTHER,
    is_partner: bool = False,
    sort_order: int = 0,
    website: str | None = None,
) -> Organisation:
    """Insert a (non-partner by default) organisation and flush. Register committed ones with
    the ``cleanup_organisations`` fixture."""
    organisation = Organisation(
        name=name or f"Test Organisation {uuid.uuid4().hex[:12]}",
        short_name=short_name,
        country=country,
        type=type,
        is_partner=is_partner,
        sort_order=sort_order,
        website=website,
    )
    db.add(organisation)
    await db.flush()
    return organisation


async def create_category(
    db: AsyncSession,
    *,
    kind: CategoryKind = CategoryKind.BLOG,
    name: str | None = None,
    slug: str | None = None,
    **fields: Any,
) -> Category:
    """Insert a category (random slug unless given) and flush. Register committed ones (by id)
    with the ``cleanup_categories`` fixture."""
    token = uuid.uuid4().hex[:12]
    category = Category(
        kind=kind,
        name=name or f"Test Category {token}",
        slug=slug or f"test-category-{token}",
        **fields,
    )
    db.add(category)
    await db.flush()
    await db.refresh(category)
    return category


async def create_tag(
    db: AsyncSession, *, name: str | None = None, slug: str | None = None, usage_count: int = 0
) -> Tag:
    """Insert a tag (random name/slug unless given) and flush. Register committed ones (by id)
    with the ``cleanup_tags`` fixture."""
    token = uuid.uuid4().hex[:12]
    tag = Tag(name=name or f"tag {token}", slug=slug or f"tag-{token}", usage_count=usage_count)
    db.add(tag)
    await db.flush()
    await db.refresh(tag)
    return tag


async def create_post(
    db: AsyncSession,
    *,
    category_id: int,
    title: str | None = None,
    slug: str | None = None,
    status: ContentStatus = ContentStatus.PUBLISHED,
    author_id: int | None = None,
    tags: Sequence[Tag] = (),
    **fields: Any,
) -> Post:
    """Insert a post row directly (sanitised dummy body; ``published_at`` set when published)
    and flush. Register committed ones (by id) with the ``cleanup_posts`` fixture."""
    token = uuid.uuid4().hex[:12]
    body_html = sanitize_html("<p>Nature-based solutions reduce urban flooding.</p>")
    post = Post(
        category_id=category_id,
        author_id=author_id,
        title=title or f"Test post {token}",
        slug=slug or f"test-post-{token}",
        body_html=body_html,
        body_text=html_to_text(body_html),
        status=status,
        published_at=datetime.now(UTC) if status == ContentStatus.PUBLISHED else None,
        **fields,
    )
    post.tags = list(tags)
    db.add(post)
    await db.flush()
    return post


async def create_attachment(
    db: AsyncSession,
    *,
    uploader_id: int | None,
    alt_text: str = "An image",
    width: int = 10,
    height: int = 10,
    size_bytes: int = 100,
    deleted_at: datetime | None = None,
) -> Attachment:
    """Insert an attachment row (no files on disk) and flush. Paths are unique and random."""
    stem = f"2026/01/{uuid.uuid4().hex}"
    attachment = Attachment(
        uploader_id=uploader_id,
        storage_path=f"{stem}.webp",
        thumb_path=f"{stem}_thumb.webp",
        original_filename="image.png",
        mime="image/webp",
        size_bytes=size_bytes,
        width=width,
        height=height,
        alt_text=alt_text,
        deleted_at=deleted_at,
    )
    db.add(attachment)
    await db.flush()
    return attachment


async def create_knowbase_link(
    db: AsyncSession,
    *,
    post_id: int,
    kb_type: str = "measure",
    kb_id: int = 7,
    title_en: str = "Linked KNOWBASE item",
    title_local: str | None = None,
    order: int = 0,
) -> Any:
    """Insert a ``knowbase_links`` row for a post (no KNOWBASE call) and flush. Register committed
    ones (by post id) with the ``cleanup_knowbase_links`` fixture."""
    from app.db.enums import ContentType, KbType
    from app.db.models import KnowbaseLink

    link = KnowbaseLink(
        content_type=ContentType.POST,
        content_id=post_id,
        kb_type=KbType(kb_type),
        kb_id=kb_id,
        cached_title_en=title_en,
        cached_title_local=title_local,
        sort_order=order,
    )
    db.add(link)
    await db.flush()
    return link


async def create_thread(
    db: AsyncSession,
    *,
    category_id: int,
    title: str | None = None,
    slug: str | None = None,
    status: ContentStatus = ContentStatus.PUBLISHED,
    author_id: int | None = None,
    tags: Sequence[Tag] = (),
    body_text: str | None = None,
    **fields: Any,
) -> Any:
    """Insert a thread row directly (sanitised dummy body unless ``body_text`` is given;
    ``published_at`` set when published) and flush. ``category_id`` should be a forum category.
    Register committed ones (by id) with the ``cleanup_threads`` fixture."""
    from app.db.models import Thread

    token = uuid.uuid4().hex[:12]
    body_html = sanitize_html(f"<p>{body_text or 'How do you size retention ponds?'}</p>")
    thread = Thread(
        category_id=category_id,
        author_id=author_id,
        title=title or f"Test thread {token}",
        slug=slug or f"test-thread-{token}",
        body_html=body_html,
        body_text=html_to_text(body_html),
        status=status,
        published_at=datetime.now(UTC) if status == ContentStatus.PUBLISHED else None,
        **fields,
    )
    thread.tags = list(tags)
    db.add(thread)
    await db.flush()
    return thread


async def create_reply(
    db: AsyncSession,
    *,
    thread_id: int,
    author_id: int | None = None,
    parent_reply_id: int | None = None,
    status: ContentStatus = ContentStatus.PUBLISHED,
    body: str = "We used swales and a detention basin.",
    **fields: Any,
) -> Any:
    """Insert a reply row directly (sanitised body) and flush. Replies go away with their
    thread (``cleanup_threads``)."""
    from app.db.models import Reply

    body_html = sanitize_html(f"<p>{body}</p>")
    reply = Reply(
        thread_id=thread_id,
        author_id=author_id,
        parent_reply_id=parent_reply_id,
        body_html=body_html,
        body_text=html_to_text(body_html),
        status=status,
        **fields,
    )
    db.add(reply)
    await db.flush()
    return reply


async def create_comment(
    db: AsyncSession,
    *,
    post_id: int,
    author_id: int | None = None,
    status: ContentStatus = ContentStatus.PUBLISHED,
    body: str = "Thanks for sharing this case study.",
    **fields: Any,
) -> Any:
    """Insert a comment row directly (sanitised body) and flush. Comments go away with their
    post (``cleanup_posts``) or, on a post that stays, via ``cleanup_comments``."""
    from app.db.models import Comment

    body_html = sanitize_html(f"<p>{body}</p>")
    comment = Comment(
        post_id=post_id,
        author_id=author_id,
        body_html=body_html,
        body_text=html_to_text(body_html),
        status=status,
        **fields,
    )
    db.add(comment)
    await db.flush()
    return comment


async def create_thread_knowbase_link(
    db: AsyncSession,
    *,
    thread_id: int,
    kb_type: str = "measure",
    kb_id: int = 7,
    title_en: str = "Linked KNOWBASE item",
    title_local: str | None = None,
    order: int = 0,
) -> Any:
    """Insert a ``knowbase_links`` row for a thread (no KNOWBASE call) and flush. The rows go
    away with ``cleanup_threads`` / ``cleanup_forum_categories``."""
    from app.db.enums import ContentType, KbType
    from app.db.models import KnowbaseLink

    link = KnowbaseLink(
        content_type=ContentType.THREAD,
        content_id=thread_id,
        kb_type=KbType(kb_type),
        kb_id=kb_id,
        cached_title_en=title_en,
        cached_title_local=title_local,
        sort_order=order,
    )
    db.add(link)
    await db.flush()
    return link

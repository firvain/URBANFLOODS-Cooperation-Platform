"""Category data access (blog and forum). Never commits; the caller (``get_db_tx``) does.

``post_count`` is the number of published, not-deleted posts in a category, computed with a
correlated subquery. Forum categories count 0 until threads arrive (M3).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.db.enums import CategoryKind, ContentStatus
from app.db.models import Category, Post
from app.services.slugs import slugify_title

SLUG_UNIQUE_CONSTRAINT = "uq_categories_kind_slug"
SLUG_MAX_LENGTH = 80
UPDATABLE_FIELDS = frozenset(
    {"name", "slug", "name_i18n", "description", "sort_order", "admin_only", "is_archived"}
)


def _post_count():
    return (
        select(func.count(Post.id))
        .where(
            Post.category_id == Category.id,
            Post.status == ContentStatus.PUBLISHED,
            Post.deleted_at.is_(None),
        )
        .correlate(Category)
        .scalar_subquery()
        .label("post_count")
    )


def _slug_taken() -> AppError:
    return AppError(409, "categories.slug_taken", "A category with this slug exists.")


def _slug_locked() -> AppError:
    return AppError(
        409, "categories.slug_locked", "The slug of a category with posts cannot change."
    )


def _last_active() -> AppError:
    return AppError(
        409, "categories.last_active", "The last active category of a kind cannot be archived."
    )


async def list_categories(
    db: AsyncSession, *, kind: CategoryKind | None = None, include_archived: bool = False
) -> list[tuple[Category, int]]:
    """``[(category, post_count), ...]`` ordered by kind, ``sort_order``, name."""
    conditions = []
    if kind is not None:
        conditions.append(Category.kind == kind)
    if not include_archived:
        conditions.append(Category.is_archived.is_(False))
    stmt = (
        select(Category, _post_count())
        .where(*conditions)
        .order_by(Category.kind, Category.sort_order, Category.name, Category.id)
    )
    rows = (await db.execute(stmt)).all()
    return [(category, count) for category, count in rows]


async def get_category(db: AsyncSession, *, kind: CategoryKind, slug: str) -> Category | None:
    stmt = select(Category).where(Category.kind == kind, Category.slug == slug)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_category_by_id(db: AsyncSession, *, category_id: int) -> Category | None:
    return await db.get(Category, category_id)


async def count_published_posts(db: AsyncSession, *, category_id: int) -> int:
    stmt = select(func.count(Post.id)).where(
        Post.category_id == category_id,
        Post.status == ContentStatus.PUBLISHED,
        Post.deleted_at.is_(None),
    )
    return (await db.execute(stmt)).scalar_one()


async def _has_posts(db: AsyncSession, *, category_id: int) -> bool:
    """Any post row at all (whatever its status): their URLs and history hang on the slug."""
    stmt = select(select(Post.id).where(Post.category_id == category_id).exists())
    return bool((await db.execute(stmt)).scalar_one())


async def _ensure_not_last_active(db: AsyncSession, *, category: Category) -> None:
    """Raise 409 ``categories.last_active`` if no other active category of the kind remains.

    The active rows of the kind are locked, so two concurrent archives cannot both pass.
    """
    stmt = (
        select(Category.id)
        .where(
            Category.kind == category.kind,
            Category.is_archived.is_(False),
            Category.id != category.id,
        )
        .with_for_update()
    )
    others = (await db.execute(stmt)).scalars().all()
    if not others:
        raise _last_active()


async def _flush_slug_safely(db: AsyncSession, apply: Any) -> None:
    """Run ``apply()`` in a savepoint and flush; map the (kind, slug) unique violation to 409."""
    try:
        async with db.begin_nested():
            apply()
    except IntegrityError as exc:
        if SLUG_UNIQUE_CONSTRAINT in str(exc.orig):
            raise _slug_taken() from None
        raise


async def create_category(
    db: AsyncSession,
    *,
    kind: CategoryKind,
    name: str,
    slug: str | None = None,
    name_i18n: Mapping[str, str] | None = None,
    description: str | None = None,
    sort_order: int = 0,
    admin_only: bool = False,
) -> Category:
    """Insert a category; ``slug`` is derived from ``name`` when not given. Raises ``AppError``
    409 ``categories.slug_taken`` when the slug exists for the kind."""
    category = Category(
        kind=kind,
        name=name,
        slug=slug or slugify_title(name, max_length=SLUG_MAX_LENGTH),
        name_i18n=dict(name_i18n or {}),
        description=description,
        sort_order=sort_order,
        admin_only=admin_only,
    )
    await _flush_slug_safely(db, lambda: db.add(category))
    await db.refresh(category)
    return category


async def update_category(
    db: AsyncSession, *, category: Category, changes: Mapping[str, Any]
) -> list[str]:
    """Apply ``changes`` (only the keys present). Returns the sorted names of the fields whose
    value actually changed.

    Raises ``AppError`` 409 ``categories.slug_taken``, ``categories.slug_locked`` (slug change
    while the category has posts) or ``categories.last_active`` (archiving the last active
    category of its kind).
    """
    unknown = set(changes) - UPDATABLE_FIELDS
    if unknown:
        raise ValueError(f"not category fields: {sorted(unknown)}")
    changed = sorted(name for name, value in changes.items() if getattr(category, name) != value)
    if not changed:
        return changed
    if "slug" in changed and await _has_posts(db, category_id=category.id):
        raise _slug_locked()
    if "is_archived" in changed and changes["is_archived"]:
        await _ensure_not_last_active(db, category=category)

    def apply() -> None:
        for name in changed:
            setattr(category, name, changes[name])

    await _flush_slug_safely(db, apply)
    await db.refresh(category)
    return changed


async def archive_category(db: AsyncSession, *, category: Category) -> bool:
    """Archive ``category``; False if it already was. Raises ``AppError`` 409
    ``categories.last_active`` for the last active category of its kind."""
    if category.is_archived:
        return False
    await _ensure_not_last_active(db, category=category)
    category.is_archived = True
    await db.flush()
    return True

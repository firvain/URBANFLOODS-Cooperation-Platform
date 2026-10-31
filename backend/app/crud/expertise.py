"""Expertise vocabulary data access. Never commits; the caller (``get_db_tx``) does."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.db.models import ExpertiseTag
from app.services.slugs import slugify_title

SLUG_UNIQUE_CONSTRAINT = "uq_expertise_tags_slug"
SLUG_MAX_LENGTH = 64
UPDATABLE_FIELDS = frozenset({"label", "slug", "sort_order", "is_active"})


def _slug_taken() -> AppError:
    return AppError(409, "expertise.slug_taken", "An expertise tag with this slug exists.")


async def list_tags(db: AsyncSession, *, include_inactive: bool = False) -> list[ExpertiseTag]:
    """Tags in ``sort_order`` (then id): the active ones, or all with ``include_inactive``."""
    stmt = select(ExpertiseTag).order_by(ExpertiseTag.sort_order, ExpertiseTag.id)
    if not include_inactive:
        stmt = stmt.where(ExpertiseTag.is_active.is_(True))
    return list((await db.scalars(stmt)).all())


async def list_active_tags(db: AsyncSession) -> list[ExpertiseTag]:
    """Every active tag, in ``sort_order`` (then id)."""
    return await list_tags(db)


async def get_tag(db: AsyncSession, *, tag_id: int) -> ExpertiseTag | None:
    return await db.get(ExpertiseTag, tag_id)


async def get_active_tags(db: AsyncSession, *, tag_ids: Iterable[int]) -> list[ExpertiseTag]:
    """The active tags among ``tag_ids`` (unknown and inactive ids are left out), in
    ``sort_order``."""
    ids = set(tag_ids)
    if not ids:
        return []
    stmt = (
        select(ExpertiseTag)
        .where(ExpertiseTag.id.in_(ids), ExpertiseTag.is_active.is_(True))
        .order_by(ExpertiseTag.sort_order, ExpertiseTag.id)
    )
    return list((await db.scalars(stmt)).all())


async def _flush_slug_safely(db: AsyncSession, apply: Callable[[], Any]) -> None:
    """Run ``apply()`` in a savepoint and flush; map the slug unique violation to 409."""
    try:
        async with db.begin_nested():
            apply()
    except IntegrityError as exc:
        if SLUG_UNIQUE_CONSTRAINT in str(exc.orig):
            raise _slug_taken() from None
        raise


async def create_tag(
    db: AsyncSession, *, label: str, slug: str | None = None, sort_order: int = 0
) -> ExpertiseTag:
    """Insert an active tag; ``slug`` is derived from ``label`` when not given. Raises
    ``AppError`` 409 ``expertise.slug_taken``."""
    tag = ExpertiseTag(
        label=label,
        slug=slug or slugify_title(label, max_length=SLUG_MAX_LENGTH),
        sort_order=sort_order,
        is_active=True,
    )
    await _flush_slug_safely(db, lambda: db.add(tag))
    await db.refresh(tag)
    return tag


async def update_tag(
    db: AsyncSession, *, tag: ExpertiseTag, changes: Mapping[str, Any]
) -> list[str]:
    """Apply ``changes`` (only the keys present). Returns the sorted names of the fields whose
    value actually changed. Deactivating keeps the tag on the members who hold it. Raises
    ``AppError`` 409 ``expertise.slug_taken``."""
    unknown = set(changes) - UPDATABLE_FIELDS
    if unknown:
        raise ValueError(f"not expertise tag fields: {sorted(unknown)}")
    changed = sorted(name for name, value in changes.items() if getattr(tag, name) != value)
    if not changed:
        return changed

    def apply() -> None:
        for name in changed:
            setattr(tag, name, changes[name])

    await _flush_slug_safely(db, apply)
    await db.refresh(tag)
    return changed

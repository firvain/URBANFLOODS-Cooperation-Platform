"""Expertise vocabulary data access. Never commits; the caller (``get_db_tx``) does."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExpertiseTag


async def list_active_tags(db: AsyncSession) -> list[ExpertiseTag]:
    """Every active tag, in ``sort_order`` (then id)."""
    stmt = (
        select(ExpertiseTag)
        .where(ExpertiseTag.is_active.is_(True))
        .order_by(ExpertiseTag.sort_order, ExpertiseTag.id)
    )
    return list((await db.scalars(stmt)).all())


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

"""Members directory data access (public profiles and suggested collaborators). Never commits.

The directory shows only users who are verified, active, not deleted and have not opted out
(``show_in_directory``). Suggestions rank directory members by the number of expertise tags they
share with the caller (``func.count`` over ``user_expertise``), newest first on ties.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.db.models import Organisation, User, user_expertise

SUGGESTED_LIMIT = 6


def _in_directory():
    return (
        User.is_verified.is_(True),
        User.is_active.is_(True),
        User.deleted_at.is_(None),
        User.show_in_directory.is_(True),
    )


def _load_profile():
    return joinedload(User.organisation), selectinload(User.expertise)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_members(
    db: AsyncSession,
    *,
    q: str | None = None,
    expertise_ids: Sequence[int] | None = None,
    country: str | None = None,
    organisation_id: int | None = None,
    skip: int = 0,
    limit: int = 24,
) -> tuple[int, list[User]]:
    """``(total, users)`` of the directory, newest first, with ``organisation`` and
    ``expertise`` loaded.

    ``q`` is a case-insensitive substring of the display name, the free-text organisation, the
    free-text area of expertise, or the listed organisation's name or short name.
    ``expertise_ids`` matches users with any of the tags (never the free-text area).
    """
    conditions = list(_in_directory())
    if q:
        pattern = f"%{_escape_like(q)}%"
        matching_orgs = select(Organisation.id).where(
            or_(
                Organisation.name.ilike(pattern, escape="\\"),
                Organisation.short_name.ilike(pattern, escape="\\"),
            )
        )
        conditions.append(
            or_(
                User.display_name.ilike(pattern, escape="\\"),
                User.organisation_other.ilike(pattern, escape="\\"),
                User.expertise_other.ilike(pattern, escape="\\"),
                User.organisation_id.in_(matching_orgs),
            )
        )
    if expertise_ids:
        tagged = select(user_expertise.c.user_id).where(
            user_expertise.c.tag_id.in_(set(expertise_ids))
        )
        conditions.append(User.id.in_(tagged))
    if country is not None:
        conditions.append(User.country == country)
    if organisation_id is not None:
        conditions.append(User.organisation_id == organisation_id)

    total_stmt = select(func.count()).select_from(select(User.id).where(*conditions).subquery())
    total = (await db.execute(total_stmt)).scalar_one()
    stmt = (
        select(User)
        .options(*_load_profile())
        .where(*conditions)
        .order_by(User.created_at.desc(), User.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return total, list((await db.scalars(stmt)).all())


async def get_member(db: AsyncSession, *, user_id: int) -> User | None:
    """The directory member ``user_id`` (``organisation`` and ``expertise`` loaded), or None
    if there is no such user or they are not in the directory."""
    stmt = select(User).options(*_load_profile()).where(User.id == user_id, *_in_directory())
    return (await db.scalars(stmt)).one_or_none()


async def suggested_members(
    db: AsyncSession, *, user: User, limit: int = SUGGESTED_LIMIT
) -> list[tuple[User, int]]:
    """Up to ``limit`` ``(member, shared_tag_count)`` for ``user``: directory members sharing
    the most expertise tags first, newest first on ties, so members sharing nothing (count 0)
    fill any remaining places newest first. ``user`` is never included."""
    my_tags = select(user_expertise.c.tag_id).where(user_expertise.c.user_id == user.id)
    shared = (
        select(user_expertise.c.user_id, func.count().label("shared"))
        .where(user_expertise.c.tag_id.in_(my_tags))
        .group_by(user_expertise.c.user_id)
        .subquery()
    )
    shared_count = func.coalesce(shared.c.shared, 0).label("shared_expertise")
    stmt = (
        select(User, shared_count)
        .outerjoin(shared, shared.c.user_id == User.id)
        .options(*_load_profile())
        .where(*_in_directory(), User.id != user.id)
        .order_by(shared_count.desc(), User.created_at.desc(), User.id.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [(member, count) for member, count in rows]

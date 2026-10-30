"""Organisation data access. Never commits; the caller (``get_db_tx``) does.

``member_count`` is the number of verified, active, not-deleted users of an organisation (the
people the public ``/partners`` page may speak of), computed with a correlated subquery.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.db.enums import OrganisationType
from app.db.models import Organisation, User

NAME_UNIQUE_CONSTRAINT = "uq_organisations_name"
UPDATABLE_FIELDS = frozenset(
    {"name", "short_name", "country", "type", "website", "is_partner", "sort_order"}
)
# LP/PP before AP before anything else.
_TYPE_RANK = case(
    (Organisation.type == OrganisationType.PP, 0),
    (Organisation.type == OrganisationType.AP, 1),
    else_=2,
)


def _member_count():
    return (
        select(func.count(User.id))
        .where(
            User.organisation_id == Organisation.id,
            User.is_verified.is_(True),
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
        .correlate(Organisation)
        .scalar_subquery()
        .label("member_count")
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _name_taken() -> AppError:
    return AppError(409, "organisations.name_taken", "An organisation with this name exists.")


async def list_organisations(
    db: AsyncSession,
    *,
    partners_only: bool | None = None,
    q: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> tuple[int, list[tuple[Organisation, int]]]:
    """``(total, [(organisation, member_count), ...])``: partners first, then PP, AP, other, then
    ``sort_order`` and name. ``q`` is a case-insensitive substring of name or short name."""
    conditions = []
    if partners_only:
        conditions.append(Organisation.is_partner.is_(True))
    if q:
        pattern = f"%{_escape_like(q)}%"
        conditions.append(
            or_(
                Organisation.name.ilike(pattern, escape="\\"),
                Organisation.short_name.ilike(pattern, escape="\\"),
            )
        )

    total_stmt = select(func.count()).select_from(
        select(Organisation.id).where(*conditions).subquery()
    )
    total = (await db.execute(total_stmt)).scalar_one()

    stmt = (
        select(Organisation, _member_count())
        .where(*conditions)
        .order_by(
            Organisation.is_partner.desc(),
            _TYPE_RANK,
            Organisation.sort_order,
            Organisation.name,
            Organisation.id,
        )
        .offset(skip)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return total, [(organisation, count) for organisation, count in rows]


async def get_organisation(db: AsyncSession, *, organisation_id: int) -> Organisation | None:
    return await db.get(Organisation, organisation_id)


async def get_organisation_with_member_count(
    db: AsyncSession, *, organisation_id: int
) -> tuple[Organisation, int] | None:
    stmt = select(Organisation, _member_count()).where(Organisation.id == organisation_id)
    row = (await db.execute(stmt)).first()
    return (row[0], row[1]) if row is not None else None


async def create_organisation(
    db: AsyncSession,
    *,
    name: str,
    short_name: str,
    country: str,
    type: OrganisationType,
    website: str | None = None,
    is_partner: bool = False,
    sort_order: int = 0,
) -> Organisation:
    """Insert an organisation. Raises ``AppError`` 409 ``organisations.name_taken``."""
    organisation = Organisation(
        name=name,
        short_name=short_name,
        country=country,
        type=type,
        website=website,
        is_partner=is_partner,
        sort_order=sort_order,
    )
    try:
        # A savepoint keeps the outer transaction usable if the insert fails.
        async with db.begin_nested():
            db.add(organisation)
    except IntegrityError as exc:
        if NAME_UNIQUE_CONSTRAINT in str(exc.orig):
            raise _name_taken() from None
        raise
    await db.refresh(organisation)
    return organisation


async def update_organisation(
    db: AsyncSession, *, organisation: Organisation, changes: Mapping[str, Any]
) -> list[str]:
    """Apply ``changes`` (only the keys present). Returns the sorted names of the fields whose
    value actually changed. Raises ``AppError`` 409 ``organisations.name_taken``."""
    unknown = set(changes) - UPDATABLE_FIELDS
    if unknown:
        raise ValueError(f"not organisation fields: {sorted(unknown)}")
    changed = sorted(
        name for name, value in changes.items() if getattr(organisation, name) != value
    )
    if not changed:
        return changed
    try:
        async with db.begin_nested():
            for name in changed:
                setattr(organisation, name, changes[name])
    except IntegrityError as exc:
        if NAME_UNIQUE_CONSTRAINT in str(exc.orig):
            raise _name_taken() from None
        raise
    await db.refresh(organisation)
    return changed

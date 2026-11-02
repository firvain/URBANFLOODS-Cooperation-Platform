"""Admin user management.

Rules (each enforced in one helper, shared by the action routes and ``PATCH``):

- Any change that makes someone a superadmin, or changes a superadmin's role or active state,
  needs a superadmin (403 ``auth.forbidden`` otherwise).
- The last active superadmin cannot be demoted or banned (409 ``admin.last_superadmin``).
- Admins cannot change their own role (409 ``admin.cannot_change_own_role``) or ban themselves
  (409 ``admin.cannot_ban_self``).
- A soft-deleted account cannot be changed (409 ``admin.user_deleted``).
- Every effective change writes an ``admin.<action>`` audit row with the admin as actor; a
  request that changes nothing (ban an already banned user) writes none.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.params import PathId, QueryId
from app.api.v1.schemas.admin import (
    AdminStats,
    AdminUserList,
    AdminUserOut,
    AdminUserUpdate,
    CacheClearResult,
    DigestSendResult,
)
from app.api.v1.schemas.auth import MessageResponse
from app.api.v1.schemas.knowbase import KnowbaseStatus
from app.core.deps import AdminUser, DbTx, Knowbase
from app.core.exceptions import AppError, error_body, validation_error
from app.crud import audit as crud_audit
from app.crud import stats as crud_stats
from app.crud import token as crud_token
from app.crud import user as crud_user
from app.db.enums import TokenPurpose, UserRole
from app.db.models import User
from app.services.csv_cells import csv_cell
from app.services.digest import send_admin_digest
from app.services.email import send_email

router = APIRouter()
log = structlog.get_logger(__name__)

ROLE_RANK = {UserRole.MEMBER: 0, UserRole.ADMIN: 1, UserRole.SUPERADMIN: 2}
DEMOTED_ROLE = {UserRole.SUPERADMIN: UserRole.ADMIN, UserRole.ADMIN: UserRole.MEMBER}
VERIFICATION_SENT = MessageResponse(
    code="admin.verification_sent", message="A new verification email has been sent."
)


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


ACTION_ERRORS = _error_responses(401, 403, 404, 409, 422)


def _forbidden() -> AppError:
    return AppError(403, "auth.forbidden", "You do not have permission to do this.")


async def _audit(
    db: AsyncSession,
    *,
    actor: User,
    action: str,
    target: User,
    metadata: dict[str, Any] | None = None,
) -> None:
    await crud_audit.log_action(
        db,
        actor_id=actor.id,
        action=f"admin.{action}",
        target_type="user",
        target_id=target.id,
        metadata=metadata,
    )


async def _get_target(db: AsyncSession, user_id: int, *, allow_deleted: bool = False) -> User:
    user = await crud_user.get_user_by_id(db, user_id=user_id)
    if user is None:
        raise AppError(404, "users.not_found", "User not found.")
    if user.deleted_at is not None and not allow_deleted:
        raise AppError(409, "admin.user_deleted", "This account has been deleted.")
    return user


async def _is_last_superadmin(db: AsyncSession, user: User) -> bool:
    return (
        user.role == UserRole.SUPERADMIN
        and user.is_active
        and await crud_user.count_superadmins(db) <= 1
    )


async def _out(db: AsyncSession, user: User) -> AdminUserOut:
    loaded = await crud_user.get_user_by_id(db, user_id=user.id)
    return AdminUserOut.model_validate(loaded)


async def _change_role(db: AsyncSession, *, actor: User, target: User, role: UserRole) -> None:
    old = target.role
    if role == old:
        return
    if UserRole.SUPERADMIN in (old, role) and actor.role != UserRole.SUPERADMIN:
        raise _forbidden()
    if old == UserRole.SUPERADMIN and await _is_last_superadmin(db, target):
        raise AppError(409, "admin.last_superadmin", "The last superadmin cannot be demoted.")
    if target.id == actor.id:
        raise AppError(409, "admin.cannot_change_own_role", "You cannot change your own role.")
    await crud_user.set_role(db, user=target, role=role)
    action = "promote" if ROLE_RANK[role] > ROLE_RANK[old] else "demote"
    await _audit(db, actor=actor, action=action, target=target, metadata={"from": old, "to": role})


async def _set_active(db: AsyncSession, *, actor: User, target: User, active: bool) -> None:
    if not active and target.id == actor.id:
        raise AppError(409, "admin.cannot_ban_self", "You cannot ban yourself.")
    if target.role == UserRole.SUPERADMIN and actor.role != UserRole.SUPERADMIN:
        raise _forbidden()
    if not active and await _is_last_superadmin(db, target):
        raise AppError(409, "admin.last_superadmin", "The last superadmin cannot be banned.")
    if await crud_user.set_active(db, user=target, active=active):
        await _audit(db, actor=actor, action="unban" if active else "ban", target=target)


async def _set_trusted(db: AsyncSession, *, actor: User, target: User, trusted: bool) -> None:
    if await crud_user.set_trusted(db, user=target, trusted=trusted):
        await _audit(db, actor=actor, action="trust" if trusted else "untrust", target=target)


# --- routes -----------------------------------------------------------------------------------


@router.get("/users/", response_model=AdminUserList, responses=_error_responses(401, 403, 422))
async def list_users(
    admin: AdminUser,
    db: DbTx,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    role: UserRole | None = None,
    trusted: bool | None = None,
    verified: bool | None = None,
    active: bool | None = None,
    organisation_id: QueryId = None,
    include_deleted: bool = False,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdminUserList:
    """Accounts, newest first. Soft-deleted ones are left out unless ``include_deleted=true``
    (deletion also clears ``is_active``, so ``active=false`` alone lists banned accounts)."""
    total, users = await crud_user.list_users(
        db,
        q=q,
        role=role,
        trusted=trusted,
        verified=verified,
        active=active,
        organisation_id=organisation_id,
        include_deleted=include_deleted,
        skip=skip,
        limit=limit,
    )
    return AdminUserList(total=total, items=[AdminUserOut.model_validate(u) for u in users])


@router.get("/users/{user_id}", response_model=AdminUserOut, responses=ACTION_ERRORS)
async def get_user(user_id: PathId, admin: AdminUser, db: DbTx) -> AdminUserOut:
    """One account, including a soft-deleted one."""
    user = await _get_target(db, user_id, allow_deleted=True)
    return AdminUserOut.model_validate(user)


@router.patch("/users/{user_id}", response_model=AdminUserOut, responses=ACTION_ERRORS)
async def update_user(
    user_id: PathId, body: AdminUserUpdate, admin: AdminUser, db: DbTx
) -> AdminUserOut:
    """Change role, active state and/or trust. Each field follows the rules of the matching
    action route; if any fails, nothing is changed."""
    target = await _get_target(db, user_id)
    changes = body.model_dump(exclude_unset=True)
    if "role" in changes:
        await _change_role(db, actor=admin, target=target, role=changes["role"])
    if "is_active" in changes:
        await _set_active(db, actor=admin, target=target, active=changes["is_active"])
    if "trusted" in changes:
        await _set_trusted(db, actor=admin, target=target, trusted=changes["trusted"])
    return await _out(db, target)


@router.post("/users/{user_id}/promote", response_model=AdminUserOut, responses=ACTION_ERRORS)
async def promote_user(
    user_id: PathId,
    admin: AdminUser,
    db: DbTx,
    to: Literal["admin", "superadmin"] = "admin",
) -> AdminUserOut:
    """Raise a user's role (default member → admin). ``to=superadmin`` needs a superadmin."""
    target = await _get_target(db, user_id)
    role = UserRole(to)
    if ROLE_RANK[role] <= ROLE_RANK[target.role]:
        raise AppError(409, "admin.invalid_role_change", "The user already has this role.")
    await _change_role(db, actor=admin, target=target, role=role)
    return await _out(db, target)


@router.post("/users/{user_id}/demote", response_model=AdminUserOut, responses=ACTION_ERRORS)
async def demote_user(user_id: PathId, admin: AdminUser, db: DbTx) -> AdminUserOut:
    """Lower a user's role by one step (admin → member; superadmin → admin needs a
    superadmin)."""
    target = await _get_target(db, user_id)
    role = DEMOTED_ROLE.get(target.role)
    if role is None:
        raise AppError(409, "admin.invalid_role_change", "Members cannot be demoted.")
    await _change_role(db, actor=admin, target=target, role=role)
    return await _out(db, target)


@router.post("/users/{user_id}/ban", response_model=AdminUserOut, responses=ACTION_ERRORS)
async def ban_user(user_id: PathId, admin: AdminUser, db: DbTx) -> AdminUserOut:
    """Deactivate the account and sign it out everywhere."""
    target = await _get_target(db, user_id)
    await _set_active(db, actor=admin, target=target, active=False)
    return await _out(db, target)


@router.post("/users/{user_id}/unban", response_model=AdminUserOut, responses=ACTION_ERRORS)
async def unban_user(user_id: PathId, admin: AdminUser, db: DbTx) -> AdminUserOut:
    """Reactivate the account."""
    target = await _get_target(db, user_id)
    await _set_active(db, actor=admin, target=target, active=True)
    return await _out(db, target)


@router.post("/users/{user_id}/trust", response_model=AdminUserOut, responses=ACTION_ERRORS)
async def trust_user(user_id: PathId, admin: AdminUser, db: DbTx) -> AdminUserOut:
    """Mark the user trusted (their posts and threads publish without review)."""
    target = await _get_target(db, user_id)
    await _set_trusted(db, actor=admin, target=target, trusted=True)
    return await _out(db, target)


@router.post("/users/{user_id}/untrust", response_model=AdminUserOut, responses=ACTION_ERRORS)
async def untrust_user(user_id: PathId, admin: AdminUser, db: DbTx) -> AdminUserOut:
    """Clear the user's trusted mark."""
    target = await _get_target(db, user_id)
    await _set_trusted(db, actor=admin, target=target, trusted=False)
    return await _out(db, target)


@router.post(
    "/users/{user_id}/resend-verification",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_error_responses(401, 403, 404, 409, 422, 502),
)
async def resend_verification(user_id: PathId, admin: AdminUser, db: DbTx) -> MessageResponse:
    """Email the user a new verification link (older links stop working)."""
    target = await _get_target(db, user_id)
    if target.is_verified:
        raise AppError(409, "admin.already_verified", "This email address is already verified.")
    _, raw = await crud_token.create_email_token(
        db, user_id=target.id, purpose=TokenPurpose.VERIFY_EMAIL
    )
    try:
        await send_email(
            to=target.email,
            template="verify_email",
            locale=target.locale,
            context={
                "display_name": target.display_name,
                "verify_url": f"/verify-email?token={raw}",
            },
        )
    except Exception as exc:
        log.warning("admin.email_not_sent", user_id=target.id, error=type(exc).__name__)
        raise AppError(
            502, "admin.email_not_sent", "The email could not be sent. Try again later."
        ) from None
    await _audit(db, actor=admin, action="resend_verification", target=target)
    return VERIFICATION_SENT


# --- stats and reporting ----------------------------------------------------------------------

# Start of the URBANFLOODS project: the default lower bound of the stats export.
PROJECT_START = date(2024, 9, 1)
FRESH_CACHE_CLASSES = ("lists", "details", "lookups")


@router.get("/stats", response_model=AdminStats, responses=_error_responses(401, 403))
async def get_stats(admin: AdminUser, db: DbTx, kb: Knowbase) -> AdminStats:
    """Dashboard counts: users, content, pending items, open reports, and the KNOWBASE proxy
    state (the same object as ``GET /knowbase/status``)."""
    counts = await crud_stats.overview(db)
    return AdminStats(**counts, knowbase=KnowbaseStatus.model_validate(kb.status()))


@router.post(
    "/knowbase/cache/clear", response_model=CacheClearResult, responses=_error_responses(401, 403)
)
async def clear_knowbase_cache(admin: AdminUser, db: DbTx, kb: Knowbase) -> CacheClearResult:
    """Empty the KNOWBASE proxy cache (stale copies included). ``cleared`` is the number of
    cached responses dropped (each is kept fresh and as a stale copy; counted once).

    The cache lives in the memory of this backend process: the platform runs a single worker by
    design, so this clears the only copy. With several workers it would clear one of them only.
    """
    cache = kb.status()["cache"]
    cleared = max(sum(cache[name] for name in FRESH_CACHE_CLASSES), cache["stale"])
    await crud_audit.log_action(
        db, actor_id=admin.id, action="admin.knowbase_cache_clear", metadata={"cleared": cleared}
    )
    kb.clear_cache()
    return CacheClearResult(cleared=cleared)


@router.post("/digest/send", response_model=DigestSendResult, responses=_error_responses(401, 403))
async def send_digest(admin: AdminUser, db: DbTx) -> DigestSendResult:
    """Send the admin moderation digest now (forced: sent even when nothing is pending) to every
    admin whose digest preference is on, as ``python -m app.cli digest --force`` does. The run
    is recorded in this request's transaction. When every email fails nothing is recorded and
    the answer is ``sent: false`` with zero counts (the failure is logged)."""
    run = await send_admin_digest(db, force=True)
    result = (
        DigestSendResult(recipients=run.recipients, items=run.items, sent=True)
        if run is not None
        else DigestSendResult(recipients=0, items=0, sent=False)
    )
    await crud_audit.log_action(
        db, actor_id=admin.id, action="admin.digest_sent", metadata=result.model_dump()
    )
    return result


def _write_section(
    writer: Any, name: str, header: Sequence[str], rows: Iterable[Sequence[object]]
) -> None:
    writer.writerow([name])
    writer.writerow(header)
    writer.writerows([csv_cell(value) for value in row] for row in rows)


def _stats_csv(data: crud_stats.ExportStats) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    sections: list[tuple[str, Sequence[str], Iterable[Sequence[object]]]] = [
        (
            "users_by_country",
            ("country", "count"),
            [(country or "unknown", count) for country, count in data.users_by_country],
        ),
        (
            "users_by_organisation",
            ("organisation", "is_partner", "count"),
            data.users_by_organisation,
        ),
        ("content", ("metric", "count"), list(data.content.items())),
        (
            "active_users",
            ("metric", "count"),
            [("contributors", data.contributors), ("logged_in", data.logged_in)],
        ),
        (
            "rco87",
            ("organisation", "is_partner", "country", "contributions"),
            [
                (name, is_partner, country or "unknown", count)
                for name, is_partner, country, count in data.rco87
            ],
        ),
    ]
    for index, (name, header, rows) in enumerate(sections):
        if index:
            writer.writerow([])
        _write_section(writer, name, header, rows)
    return buffer.getvalue()


@router.get(
    "/stats/export.csv",
    response_class=Response,
    responses={
        200: {"description": "CSV report", "content": {"text/csv": {}}},
        **_error_responses(401, 403, 422),
    },
)
async def export_stats(
    admin: AdminUser,
    db: DbTx,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> Response:
    """Reporting CSV for the days ``from``..``to`` (inclusive; defaults: project start, today).

    Sections, separated by a blank line, each a name row then a header row: users registered in
    the range by country and by organisation (free-text organisations as "Other"), published
    content created in the range, active users (contributors, sign-ins) and RCO87 (listed and
    free-text organisations whose members contributed). See ``crud/stats.py`` for the
    definitions.
    """
    end = to or datetime.now(UTC).date()
    start = from_ or PROJECT_START
    if start > end:
        raise validation_error({"query.from": "date_range_invalid"}, "from must not be after to.")
    data = await crud_stats.export_stats(db, start=start, end=end)
    await crud_audit.log_action(
        db,
        actor_id=admin.id,
        action="admin.stats_export",
        metadata={"from": start.isoformat(), "to": end.isoformat()},
    )
    filename = f"urbanfloods-cooperation-stats-{start.isoformat()}-{end.isoformat()}.csv"
    return Response(
        content=_stats_csv(data),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

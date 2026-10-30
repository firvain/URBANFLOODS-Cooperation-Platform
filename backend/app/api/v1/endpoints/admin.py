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

from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.admin import AdminUserList, AdminUserOut, AdminUserUpdate
from app.api.v1.schemas.auth import MessageResponse
from app.core.deps import AdminUser, DbTx
from app.core.exceptions import AppError, error_body
from app.crud import audit as crud_audit
from app.crud import token as crud_token
from app.crud import user as crud_user
from app.db.enums import TokenPurpose, UserRole
from app.db.models import User
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
    organisation_id: int | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdminUserList:
    """All accounts (including soft-deleted ones), newest first."""
    total, users = await crud_user.list_users(
        db,
        q=q,
        role=role,
        trusted=trusted,
        verified=verified,
        active=active,
        organisation_id=organisation_id,
        skip=skip,
        limit=limit,
    )
    return AdminUserList(total=total, items=[AdminUserOut.model_validate(u) for u in users])


@router.get("/users/{user_id}", response_model=AdminUserOut, responses=ACTION_ERRORS)
async def get_user(user_id: int, admin: AdminUser, db: DbTx) -> AdminUserOut:
    """One account, including a soft-deleted one."""
    user = await _get_target(db, user_id, allow_deleted=True)
    return AdminUserOut.model_validate(user)


@router.patch("/users/{user_id}", response_model=AdminUserOut, responses=ACTION_ERRORS)
async def update_user(
    user_id: int, body: AdminUserUpdate, admin: AdminUser, db: DbTx
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
    user_id: int,
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
async def demote_user(user_id: int, admin: AdminUser, db: DbTx) -> AdminUserOut:
    """Lower a user's role by one step (admin → member; superadmin → admin needs a
    superadmin)."""
    target = await _get_target(db, user_id)
    role = DEMOTED_ROLE.get(target.role)
    if role is None:
        raise AppError(409, "admin.invalid_role_change", "Members cannot be demoted.")
    await _change_role(db, actor=admin, target=target, role=role)
    return await _out(db, target)


@router.post("/users/{user_id}/ban", response_model=AdminUserOut, responses=ACTION_ERRORS)
async def ban_user(user_id: int, admin: AdminUser, db: DbTx) -> AdminUserOut:
    """Deactivate the account and sign it out everywhere."""
    target = await _get_target(db, user_id)
    await _set_active(db, actor=admin, target=target, active=False)
    return await _out(db, target)


@router.post("/users/{user_id}/unban", response_model=AdminUserOut, responses=ACTION_ERRORS)
async def unban_user(user_id: int, admin: AdminUser, db: DbTx) -> AdminUserOut:
    """Reactivate the account."""
    target = await _get_target(db, user_id)
    await _set_active(db, actor=admin, target=target, active=True)
    return await _out(db, target)


@router.post("/users/{user_id}/trust", response_model=AdminUserOut, responses=ACTION_ERRORS)
async def trust_user(user_id: int, admin: AdminUser, db: DbTx) -> AdminUserOut:
    """Mark the user trusted (their posts and threads publish without review)."""
    target = await _get_target(db, user_id)
    await _set_trusted(db, actor=admin, target=target, trusted=True)
    return await _out(db, target)


@router.post("/users/{user_id}/untrust", response_model=AdminUserOut, responses=ACTION_ERRORS)
async def untrust_user(user_id: int, admin: AdminUser, db: DbTx) -> AdminUserOut:
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
async def resend_verification(user_id: int, admin: AdminUser, db: DbTx) -> MessageResponse:
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

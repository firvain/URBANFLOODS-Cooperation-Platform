"""Registration, email verification, login/logout, the signed-in user's profile and sessions.

Failed logins raise ``AppError(..., keep_changes=True)`` so the request transaction still commits
the ``auth.login_failed`` audit row.
"""

from __future__ import annotations

import asyncio
import secrets
import uuid
from functools import cache
from typing import Any

import structlog
from fastapi import APIRouter, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.auth import (
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    SessionInfo,
    SessionList,
    UpdateMeRequest,
    UserMe,
    VerifyEmailRequest,
)
from app.core.config import settings
from app.core.deps import AuthUser, CurrentUser, DbTx, client_ip
from app.core.exceptions import AppError, error_body, validation_error
from app.core.security import (
    PasswordPolicyError,
    hash_password,
    session_cookie_params,
    verify_password,
)
from app.crud import audit as crud_audit
from app.crud import session as crud_session
from app.crud import token as crud_token
from app.crud import user as crud_user
from app.db.enums import TokenPurpose
from app.db.models import User
from app.services.email import send_email
from app.services.turnstile import TurnstileError, verify_turnstile

TERMS_VERSION = "v1"
RESENT_RESPONSE = MessageResponse(
    code="auth.verification_resent",
    message="If an account exists for this address, a new verification email has been sent.",
)

router = APIRouter()
log = structlog.get_logger(__name__)


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


@cache
def _dummy_hash() -> str:
    """A hash to verify against when the email is unknown, so both failure paths cost one argon2
    verification. Computed on first use (not at import), then reused."""
    return hash_password(secrets.token_urlsafe(32))


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(value=raw_token, **session_cookie_params(settings))


def _clear_session_cookie(response: Response) -> None:
    """Expire the cookie with the same attributes it was set with."""
    params = session_cookie_params(settings)
    params.pop("max_age")
    response.delete_cookie(**params)


async def _check_turnstile(token: str | None, request: Request) -> None:
    try:
        await verify_turnstile(token, client_ip(request))
    except TurnstileError as exc:
        raise AppError(400, exc.code, "The bot check failed. Please try again.") from None


async def _send_quietly(*, user: User, template: str, context: dict[str, Any]) -> bool:
    """Send an email; on failure log and return False instead of failing the request (the
    account change must still commit; the user can ask for the email again)."""
    try:
        await send_email(to=user.email, template=template, locale=user.locale, context=context)
    except Exception as exc:
        log.warning(
            "auth.email_not_sent", template=template, user_id=user.id, error=type(exc).__name__
        )
        return False
    return True


async def _send_verification(db: AsyncSession, *, user: User) -> None:
    _, raw = await crud_token.create_email_token(
        db, user_id=user.id, purpose=TokenPurpose.VERIFY_EMAIL
    )
    await _send_quietly(
        user=user,
        template="verify_email",
        context={"display_name": user.display_name, "verify_url": f"/verify-email?token={raw}"},
    )


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_error_responses(400, 409, 422),
)
async def register(body: RegisterRequest, request: Request, db: DbTx) -> RegisterResponse:
    """Create an unverified account and email a verification link."""
    await _check_turnstile(body.turnstile_token, request)
    try:
        user = await crud_user.create_user(
            db,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            organisation_id=body.organisation_id,
            organisation_other=body.organisation_other,
            country=body.country,
            locale=body.locale,
        )
    except PasswordPolicyError as exc:
        raise validation_error({"password": exc.code}) from None

    await _send_verification(db, user=user)
    await crud_audit.log_action(
        db,
        actor_id=user.id,
        action="auth.register",
        target_type="user",
        target_id=user.id,
        metadata={"locale": user.locale, "consent": True},
    )
    # GDPR: the audit row's created_at is the consent timestamp.
    await crud_audit.log_action(
        db,
        actor_id=user.id,
        action="auth.consent",
        target_type="user",
        target_id=user.id,
        metadata={"terms_version": TERMS_VERSION, "accepted": True},
    )
    return RegisterResponse.model_validate(user)


@router.post("/verify-email", response_model=UserMe, responses=_error_responses(400, 403, 422))
async def verify_email(
    body: VerifyEmailRequest, request: Request, response: Response, db: DbTx
) -> UserMe:
    """Consume a verification token, mark the address verified and sign the user in."""
    token = await crud_token.consume_email_token(
        db, raw_token=body.token, purpose=TokenPurpose.VERIFY_EMAIL
    )
    if token is None:
        raise AppError(400, "auth.token_invalid", "This link is invalid or has expired.")

    user = await crud_user.get_user_by_id(db, user_id=token.user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise AppError(403, "auth.account_disabled", "This account is disabled.")

    newly_verified = not user.is_verified
    if newly_verified:
        await crud_user.mark_verified(db, user=user)
        await crud_audit.log_action(
            db,
            actor_id=user.id,
            action="auth.email_verified",
            target_type="user",
            target_id=user.id,
        )

    _, raw_session = await crud_session.create_session(
        db, user_id=user.id, user_agent=request.headers.get("user-agent")
    )
    _set_session_cookie(response, raw_session)

    if newly_verified:
        await _send_quietly(
            user=user, template="welcome", context={"display_name": user.display_name}
        )
    return UserMe.model_validate(user)


@router.post(
    "/resend-verification",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_error_responses(400, 422),
)
async def resend_verification(
    body: ResendVerificationRequest, request: Request, db: DbTx
) -> MessageResponse:
    """Email a new verification link. Always 202, whether or not the address is registered."""
    await _check_turnstile(body.turnstile_token, request)
    user = await crud_user.get_user_by_email(db, email=body.email)
    if user is not None and user.is_active and user.deleted_at is None and not user.is_verified:
        await _send_verification(db, user=user)
        await crud_audit.log_action(
            db,
            actor_id=user.id,
            action="auth.verification_resent",
            target_type="user",
            target_id=user.id,
        )
    return RESENT_RESPONSE


# TODO(1g): rate limit 10/15min
@router.post("/login", response_model=UserMe, responses=_error_responses(401, 403, 422))
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    current: CurrentUser,
    db: DbTx,
) -> UserMe:
    """Check email and password and start a session (cookie). Unverified users may sign in.

    A session named by the request's existing cookie is revoked first, so signing in again in the
    same browser does not leave an orphaned active session.
    """
    user = await crud_user.get_user_by_email(db, email=body.email)
    password_hash = user.password_hash if user is not None else _dummy_hash()
    # argon2 is deliberately slow; keep it off the event loop.
    password_ok = await asyncio.to_thread(verify_password, body.password, password_hash)

    if user is None or not password_ok:
        await crud_audit.log_action(
            db,
            actor_id=None,
            action="auth.login_failed",
            target_type="user" if user is not None else None,
            target_id=user.id if user is not None else None,
        )
        raise AppError(
            401,
            "auth.invalid_credentials",
            "The email address or password is incorrect.",
            keep_changes=True,
        )

    if not user.is_active or user.deleted_at is not None:
        await crud_audit.log_action(
            db, actor_id=None, action="auth.login_failed", target_type="user", target_id=user.id
        )
        raise AppError(403, "auth.account_disabled", "This account is disabled.", keep_changes=True)

    previous = request.state.session
    if current is not None and previous is not None:
        await crud_session.revoke_session(db, session_id=previous.id, user_id=current.id)

    await crud_user.record_login(db, user=user, password=body.password)
    session, raw_session = await crud_session.create_session(
        db, user_id=user.id, user_agent=request.headers.get("user-agent")
    )
    _set_session_cookie(response, raw_session)
    await crud_audit.log_action(
        db,
        actor_id=user.id,
        action="auth.login",
        target_type="user",
        target_id=user.id,
        metadata={"user_agent": session.user_agent},
    )
    loaded = await crud_user.get_user_by_id(db, user_id=user.id)
    return UserMe.model_validate(loaded)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout(request: Request, response: Response, user: CurrentUser, db: DbTx) -> None:
    """End the current session if there is one and clear the cookie. Always 204."""
    session = request.state.session
    if user is not None and session is not None:
        await crud_session.revoke_session(db, session_id=session.id, user_id=user.id)
        await crud_audit.log_action(
            db, actor_id=user.id, action="auth.logout", target_type="user", target_id=user.id
        )
    _clear_session_cookie(response)


@router.get("/me", response_model=UserMe, responses=_error_responses(401))
async def read_me(user: AuthUser) -> UserMe:
    """The signed-in user's own account."""
    return UserMe.model_validate(user)


@router.patch("/me", response_model=UserMe, responses=_error_responses(401, 422))
async def update_me(body: UpdateMeRequest, user: AuthUser, db: DbTx) -> UserMe:
    """Update the signed-in user's profile. Omitted fields are kept; ``null`` clears."""
    changed = await crud_user.update_profile(
        db, user=user, changes=body.model_dump(exclude_unset=True)
    )
    if changed:
        await crud_audit.log_action(
            db,
            actor_id=user.id,
            action="auth.profile_updated",
            target_type="user",
            target_id=user.id,
            metadata={"fields": changed},
        )
    loaded = await crud_user.get_user_by_id(db, user_id=user.id)
    return UserMe.model_validate(loaded)


@router.get("/me/sessions", response_model=SessionList, responses=_error_responses(401))
async def list_my_sessions(request: Request, user: AuthUser, db: DbTx) -> SessionList:
    """The signed-in user's active sessions, newest first; ``is_current`` marks this one."""
    current_id = request.state.session.id
    sessions = await crud_session.list_sessions_for_user(db, user_id=user.id)
    items = [
        SessionInfo(
            id=session.id,
            created_at=session.created_at,
            last_seen_at=session.last_seen_at,
            expires_at=session.expires_at,
            user_agent=session.user_agent,
            is_current=session.id == current_id,
        )
        for session in sessions
    ]
    return SessionList(total=len(items), items=items)


@router.delete(
    "/me/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_error_responses(401, 404, 422),
)
async def revoke_my_session(
    session_id: uuid.UUID, request: Request, response: Response, user: AuthUser, db: DbTx
) -> None:
    """Sign out one of the user's sessions. Revoking the current one also clears the cookie."""
    revoked = await crud_session.revoke_session(db, session_id=session_id, user_id=user.id)
    if not revoked:
        raise AppError(404, "auth.session_not_found", "Session not found.")
    is_current = session_id == request.state.session.id
    if is_current:
        _clear_session_cookie(response)
    await crud_audit.log_action(
        db,
        actor_id=user.id,
        action="auth.session_revoked",
        target_type="user",
        target_id=user.id,
        metadata={"session_id": str(session_id), "current": is_current},
    )

"""Registration and email verification. Login, logout and ``/me`` arrive in increment 1e."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.auth import (
    MessageResponse,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    UserMe,
    VerifyEmailRequest,
)
from app.core.config import settings
from app.core.deps import DbTx, client_ip
from app.core.exceptions import AppError, error_body, validation_error
from app.core.security import PasswordPolicyError, session_cookie_params
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
    response.set_cookie(value=raw_session, **session_cookie_params(settings))

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

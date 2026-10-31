"""Registration, email verification, login/logout, the signed-in user's profile and sessions,
password reset and change, email change.

Failed logins (and wrong current passwords) raise ``AppError(..., keep_changes=True)`` so the
request transaction still commits the ``auth.*_failed`` audit row.
"""

from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import UTC, datetime
from functools import cache
from typing import Any

import structlog
from fastapi import APIRouter, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.auth import (
    AccountExport,
    ChangeEmailRequest,
    ChangePasswordRequest,
    ConfirmEmailRequest,
    DeleteAccountRequest,
    ExportAuditEntry,
    ExportContent,
    ExportSession,
    ExportUser,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    NotificationPreferences,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
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
from app.db.enums import TokenPurpose, UserRole
from app.db.models import User
from app.services.email import send_email
from app.services.turnstile import TurnstileError, verify_turnstile

TERMS_VERSION = "v1"
RESENT_RESPONSE = MessageResponse(
    code="auth.verification_resent",
    message="If an account exists for this address, a new verification email has been sent.",
)
RESET_SENT_RESPONSE = MessageResponse(
    code="auth.password_reset_sent",
    message="If an account exists for this address, a password reset email has been sent.",
)
EMAIL_CHANGE_SENT_RESPONSE = MessageResponse(
    code="auth.email_change_sent",
    message="A confirmation link has been sent to the new address.",
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


async def _send_quietly(
    *, user: User, template: str, context: dict[str, Any], to: str | None = None
) -> bool:
    """Send an email (to ``user.email`` unless ``to`` is given, in the user's locale); on failure
    log and return False instead of failing the request (the account change must still commit;
    the user can ask for the email again)."""
    try:
        await send_email(
            to=to or user.email, template=template, locale=user.locale, context=context
        )
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
            expertise_ids=body.expertise_ids,
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
        metadata={
            "locale": user.locale,
            "consent": True,
            "expertise_count": len(user.expertise),
        },
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


# Rate limited by app.core.rate_limit.ROUTE_LIMITS (auth.login: 10 per 15 min per IP).
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


# --- password reset and change ----------------------------------------------------------------


def _is_disabled(user: User | None) -> bool:
    return user is None or not user.is_active or user.deleted_at is not None


async def _check_current_password(
    db: AsyncSession, *, user: User, password: str, failed_action: str
) -> None:
    """400 ``auth.invalid_credentials`` (keeping a ``failed_action`` audit row) unless
    ``password`` is the user's current password."""
    # argon2 is deliberately slow; keep it off the event loop.
    if await asyncio.to_thread(verify_password, password, user.password_hash):
        return
    await crud_audit.log_action(
        db, actor_id=user.id, action=failed_action, target_type="user", target_id=user.id
    )
    raise AppError(
        400, "auth.invalid_credentials", "The current password is incorrect.", keep_changes=True
    )


# Rate limited by app.core.rate_limit.ROUTE_LIMITS (auth.password_forgot: 3/hour per IP).
@router.post(
    "/password/forgot",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_error_responses(400, 422),
)
async def forgot_password(
    body: ForgotPasswordRequest, request: Request, db: DbTx
) -> MessageResponse:
    """Email a password reset link. Always 202, whether or not the address is registered.

    Unverified users may reset too: using the link proves they own the address.
    """
    await _check_turnstile(body.turnstile_token, request)
    user = await crud_user.get_user_by_email(db, email=body.email)
    if not _is_disabled(user):
        assert user is not None
        _, raw = await crud_token.create_email_token(
            db, user_id=user.id, purpose=TokenPurpose.RESET_PASSWORD
        )
        await _send_quietly(
            user=user,
            template="reset_password",
            context={
                "display_name": user.display_name,
                "reset_url": f"/reset-password?token={raw}",
            },
        )
        await crud_audit.log_action(
            db,
            actor_id=user.id,
            action="auth.password_reset_requested",
            target_type="user",
            target_id=user.id,
        )
    return RESET_SENT_RESPONSE


@router.post("/password/reset", response_model=UserMe, responses=_error_responses(400, 403, 422))
async def reset_password(
    body: ResetPasswordRequest, request: Request, response: Response, db: DbTx
) -> UserMe:
    """Consume a reset token, set the new password, sign out every session and sign this browser
    in. Also marks the address verified and cancels pending email changes.

    Any failure rolls back, so the link stays usable (e.g. after a weak-password 422).
    """
    token = await crud_token.consume_email_token(
        db, raw_token=body.token, purpose=TokenPurpose.RESET_PASSWORD
    )
    if token is None:
        raise AppError(400, "auth.token_invalid", "This link is invalid or has expired.")

    user = await crud_user.get_user_by_id(db, user_id=token.user_id)
    if _is_disabled(user):
        raise AppError(403, "auth.account_disabled", "This account is disabled.")
    assert user is not None
    try:
        await crud_user.set_password(db, user=user, password=body.password)
    except PasswordPolicyError as exc:
        raise validation_error({"password": exc.code}) from None

    revoked = await crud_session.revoke_all_sessions_for_user(db, user_id=user.id)
    # Whoever had a session may have started an email change; it must not outlive the reset.
    await crud_token.invalidate_email_tokens(
        db, user_id=user.id, purposes=(TokenPurpose.CHANGE_EMAIL,)
    )
    newly_verified = not user.is_verified
    if newly_verified:
        await crud_user.mark_verified(db, user=user)

    _, raw_session = await crud_session.create_session(
        db, user_id=user.id, user_agent=request.headers.get("user-agent")
    )
    _set_session_cookie(response, raw_session)
    await crud_audit.log_action(
        db,
        actor_id=user.id,
        action="auth.password_reset",
        target_type="user",
        target_id=user.id,
        metadata={"sessions_revoked": revoked, "verified": newly_verified},
    )
    return UserMe.model_validate(user)


@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_error_responses(400, 401, 422),
)
async def change_password(
    body: ChangePasswordRequest, request: Request, user: AuthUser, db: DbTx
) -> None:
    """Change the password (current one required). Other sessions are signed out; this one
    stays. Pending email changes are cancelled."""
    await _check_current_password(
        db, user=user, password=body.current_password, failed_action="auth.password_change_failed"
    )
    if body.new_password == body.current_password:
        raise validation_error({"new_password": "auth.password_same"})
    try:
        await crud_user.set_password(db, user=user, password=body.new_password)
    except PasswordPolicyError as exc:
        raise validation_error({"new_password": exc.code}) from None

    revoked = await crud_session.revoke_all_sessions_for_user(
        db, user_id=user.id, except_session_id=request.state.session.id
    )
    await crud_token.invalidate_email_tokens(
        db, user_id=user.id, purposes=(TokenPurpose.CHANGE_EMAIL,)
    )
    await crud_audit.log_action(
        db,
        actor_id=user.id,
        action="auth.password_changed",
        target_type="user",
        target_id=user.id,
        metadata={"sessions_revoked": revoked},
    )


# --- email change -----------------------------------------------------------------------------


@router.post(
    "/me/email",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_error_responses(400, 401, 422),
)
async def request_email_change(
    body: ChangeEmailRequest, user: AuthUser, db: DbTx
) -> MessageResponse:
    """Email a confirmation link to the new address (current password required). The address
    changes only when the link is used.

    An address that belongs to another account gets the same 202 but no email, so the endpoint
    cannot be used to find out who is registered.
    """
    await _check_current_password(
        db, user=user, password=body.current_password, failed_action="auth.email_change_failed"
    )
    existing = await crud_user.get_user_by_email(db, email=body.new_email)
    if body.new_email.casefold() == user.email.casefold() or (
        existing is not None and existing.id == user.id
    ):
        raise validation_error({"new_email": "auth.email_same"})

    if existing is not None:
        await crud_audit.log_action(
            db,
            actor_id=user.id,
            action="auth.email_change_blocked",
            target_type="user",
            target_id=user.id,
        )
        return EMAIL_CHANGE_SENT_RESPONSE

    _, raw = await crud_token.create_email_token(
        db, user_id=user.id, purpose=TokenPurpose.CHANGE_EMAIL, new_email=body.new_email
    )
    await _send_quietly(
        user=user,
        to=body.new_email,
        template="change_email",
        context={
            "display_name": user.display_name,
            "old_email": user.email,
            "new_email": body.new_email,
            "confirm_url": f"/confirm-email?token={raw}",
        },
    )
    await crud_audit.log_action(
        db,
        actor_id=user.id,
        action="auth.email_change_requested",
        target_type="user",
        target_id=user.id,
    )
    return EMAIL_CHANGE_SENT_RESPONSE


@router.post(
    "/email/confirm", response_model=UserMe, responses=_error_responses(400, 403, 409, 422)
)
async def confirm_email_change(body: ConfirmEmailRequest, db: DbTx) -> UserMe:
    """Consume a change-email token and switch the account to the new address. No sign-in
    needed (the link may be opened anywhere); sessions are kept.

    Links already sent to the old address (verification, password reset) stop working. Using the
    link proves ownership of the new address, so the account counts as verified.
    """
    token = await crud_token.consume_email_token(
        db, raw_token=body.token, purpose=TokenPurpose.CHANGE_EMAIL
    )
    if token is None or token.new_email is None:
        raise AppError(400, "auth.token_invalid", "This link is invalid or has expired.")

    user = await crud_user.get_user_by_id(db, user_id=token.user_id)
    if _is_disabled(user):
        raise AppError(403, "auth.account_disabled", "This account is disabled.")
    assert user is not None
    existing = await crud_user.get_user_by_email(db, email=token.new_email)
    if existing is not None and existing.id != user.id:
        raise AppError(
            409, "auth.email_taken", "An account with this email address already exists."
        )
    await crud_user.set_email(db, user=user, email=token.new_email)
    await crud_token.invalidate_email_tokens(
        db,
        user_id=user.id,
        purposes=(TokenPurpose.VERIFY_EMAIL, TokenPurpose.RESET_PASSWORD),
    )
    newly_verified = not user.is_verified
    if newly_verified:
        await crud_user.mark_verified(db, user=user)
    await crud_audit.log_action(
        db,
        actor_id=user.id,
        action="auth.email_changed",
        target_type="user",
        target_id=user.id,
        metadata={"verified": newly_verified},
    )
    return UserMe.model_validate(user)


# --- notification preferences -----------------------------------------------------------------


@router.get(
    "/me/notifications", response_model=NotificationPreferences, responses=_error_responses(401)
)
async def read_my_notifications(user: AuthUser, db: DbTx) -> NotificationPreferences:
    """The signed-in user's email notification preferences."""
    preferences = await crud_user.get_notification_preferences(db, user=user)
    return NotificationPreferences.model_validate(preferences)


@router.put(
    "/me/notifications",
    response_model=NotificationPreferences,
    responses=_error_responses(401, 422),
)
async def replace_my_notifications(
    body: NotificationPreferences, user: AuthUser, db: DbTx
) -> NotificationPreferences:
    """Replace the notification preferences (every field required)."""
    preferences, changed = await crud_user.update_notification_preferences(
        db, user=user, values=body.model_dump()
    )
    if changed:
        await crud_audit.log_action(
            db,
            actor_id=user.id,
            action="auth.notifications_updated",
            target_type="user",
            target_id=user.id,
            metadata={"fields": changed},
        )
    return NotificationPreferences.model_validate(preferences)


# --- GDPR: data export and account deletion ---------------------------------------------------

EXPORT_FORMAT_VERSION = 1


@router.get(
    "/me/export",
    response_model=AccountExport,
    responses={
        **_error_responses(401),
        200: {"description": "The account data as a JSON file download (Content-Disposition)."},
    },
)
async def export_my_data(response: Response, user: AuthUser, db: DbTx) -> AccountExport:
    """Everything stored about the signed-in user, as a JSON download (GDPR access and
    portability). Never includes the password hash or any token."""
    data = await crud_user.export_user_data(db, user=user)
    now = datetime.now(UTC)
    preferences = data.user.notification_preferences
    export = AccountExport(
        exported_at=now,
        format_version=EXPORT_FORMAT_VERSION,
        licence_note=settings.CONTENT_LICENSE_URL,
        user=ExportUser.model_validate(data.user),
        notification_preferences=(
            NotificationPreferences.model_validate(preferences) if preferences else None
        ),
        sessions=[ExportSession.model_validate(session) for session in data.sessions],
        audit_log=[ExportAuditEntry.model_validate(entry) for entry in data.audit_entries],
        # Placeholders until posts (M2) and the forum (M3) exist.
        content=ExportContent(),
    )
    await crud_audit.log_action(
        db, actor_id=user.id, action="auth.data_exported", target_type="user", target_id=user.id
    )
    filename = f"urbanfloods-account-{user.id}-{now:%Y%m%d}.json"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "no-store"
    return export


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_error_responses(400, 401, 409, 422),
)
async def delete_me(
    body: DeleteAccountRequest, response: Response, user: AuthUser, db: DbTx
) -> None:
    """Delete the account (current password required): personal data is erased and the account
    disabled; published content stays, attributed to "Deleted user". Every session ends and the
    cookie is cleared. The last superadmin cannot delete their account."""
    await _check_current_password(
        db, user=user, password=body.current_password, failed_action="auth.delete_failed"
    )
    if user.role == UserRole.SUPERADMIN and await crud_user.count_superadmins(db) <= 1:
        raise AppError(
            409, "admin.last_superadmin", "The last superadmin cannot delete their account."
        )
    # Audit first, while the row still describes the account it is about.
    await crud_audit.log_action(
        db,
        actor_id=user.id,
        action="auth.account_deleted",
        target_type="user",
        target_id=user.id,
        metadata={"role": user.role},
    )
    await crud_user.anonymise_user(db, user=user)
    _clear_session_cookie(response)

"""One-click unsubscribe (RFC 8058) for the notification emails.

Mounted at ``/notifications``. ``POST /unsubscribe?token=…`` is the target of the
``List-Unsubscribe`` header: mail clients and providers POST ``List-Unsubscribe=One-Click`` as a
form body (ignored here), without a session and without ``X-Requested-With``, so the path is
exempt from the CSRF middleware (``core/csrf.py``). The session is never read: the signed token
(``services/unsubscribe.py``) names the user and the one preference to switch off. There is no
GET: link scanners fetch URLs, and a GET must not change state; the email body links to the
account settings for that.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.v1.schemas.notification import UnsubscribeResult
from app.core.deps import DbTx
from app.core.exceptions import AppError, error_body
from app.crud import audit as crud_audit
from app.crud import user as crud_user
from app.services.unsubscribe import read_token

router = APIRouter()


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


@router.post(
    "/unsubscribe",
    response_model=UnsubscribeResult,
    responses=_error_responses(400, 429),
)
async def unsubscribe(db: DbTx, token: str = Query(default="")) -> UnsubscribeResult:
    """Switch off the one email preference named by the signed ``token`` (no session needed).
    Audited as ``notifications.unsubscribed`` when the switch was on."""
    target = read_token(token)
    if target is None:
        raise AppError(400, "notifications.invalid_token", "Invalid unsubscribe link.")
    user_id, preference = target
    changed = await crud_user.disable_notification_preference(
        db, user_id=user_id, preference=preference
    )
    if changed:
        await crud_audit.log_action(
            db,
            actor_id=user_id,
            action="notifications.unsubscribed",
            target_type="user",
            target_id=user_id,
            metadata={"preference": preference, "via": "list-unsubscribe"},
        )
    return UnsubscribeResult(status="unsubscribed")

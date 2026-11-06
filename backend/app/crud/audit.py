"""Audit log writer. Every status or role change goes through ``log_action``.

Secrets never belong in the audit log. As a defensive measure, any metadata key whose name has a
``password``, ``token`` or ``secret`` part (split on ``_``/``-``/``.``/space, case-insensitive,
e.g. ``password``, ``new_password``, ``reset_token``, ``client-secret``) is dropped at any depth
before storage, and a warning naming the dropped keys (never the values) is logged.

Retention (7r): audit rows are kept for good, except the *security events* in
``SECURITY_AUDIT_ACTIONS``, which the maintenance step ``audit_retention`` deletes once they are
older than ``SECURITY_AUDIT_RETENTION_DAYS`` (``purge_security_events``). The list is an explicit
allow-list: an action not named there is never deleted, so a new action is kept until someone
decides otherwise.

- Deleted after the retention period: sign-ins and sign-outs, failed attempts, revoked sessions,
  reset and verification requests, and password and email changes. They serve to investigate
  abuse of an account, which needs months, not years.
- Kept: ``auth.register``, ``auth.consent``, ``auth.email_verified``, ``auth.profile_updated``
  and ``auth.notifications_updated`` (they record the member's consent and their
  directory/email-visibility choices, the evidence for them), ``auth.data_exported`` and
  ``auth.account_deleted`` (data-subject requests), and every ``moderation.*``, ``report.*``,
  ``admin.*``, content and ``maintenance.*`` row (the accountability trail).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db.models import AuditLog

SENSITIVE_KEY_PARTS = frozenset({"password", "token", "secret"})
_KEY_SPLIT = re.compile(r"[_\-.\s]+")

# Deleted after ``SECURITY_AUDIT_RETENTION_DAYS``; everything else is kept (module docstring).
# Widening this list deletes more of the audit trail: a deliberate, reviewed change.
SECURITY_AUDIT_ACTIONS: frozenset[str] = frozenset(
    {
        "auth.login",
        "auth.login_failed",
        "auth.logout",
        "auth.session_revoked",
        "auth.password_reset_requested",
        "auth.verification_resent",
        "auth.password_change_failed",
        "auth.email_change_failed",
        "auth.email_change_blocked",
        "auth.delete_failed",
        "auth.password_changed",
        "auth.password_reset",
        "auth.email_change_requested",
        "auth.email_changed",
    }
)

log = structlog.get_logger(__name__)


def _is_sensitive(key: Any) -> bool:
    parts = _KEY_SPLIT.split(str(key).casefold())
    return any(part in SENSITIVE_KEY_PARTS for part in parts)


def strip_keys(
    value: Any,
    dropped: list[str] | None = None,
    *,
    drop: Callable[[Any], bool] = _is_sensitive,
) -> Any:
    """Return a copy of ``value`` without the dict keys for which ``drop(key)`` is true
    (recursing into dicts and lists). Dropped key names are appended to ``dropped`` if given.
    The default predicate drops sensitive keys (see the module docstring)."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if drop(key):
                if dropped is not None:
                    dropped.append(str(key))
                continue
            cleaned[key] = strip_keys(item, dropped, drop=drop)
        return cleaned
    if isinstance(value, list | tuple):
        return [strip_keys(item, dropped, drop=drop) for item in value]
    return value


async def log_action(
    db: AsyncSession,
    *,
    actor_id: int | None,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Add an audit row and flush. Sensitive metadata keys are stripped (see module docstring)."""
    dropped: list[str] = []
    cleaned = strip_keys(metadata or {}, dropped)
    if dropped:
        log.warning("audit_metadata_sensitive_keys_dropped", action=action, keys=sorted(dropped))

    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata_=cleaned,
    )
    db.add(entry)
    await db.flush()
    return entry


async def purge_security_events(db: AsyncSession, *, cutoff: datetime, limit: int) -> int:
    """Delete at most ``limit`` security events (``SECURITY_AUDIT_ACTIONS``) created before
    ``cutoff``, oldest first, in one statement. Returns the number deleted."""
    due = (
        select(AuditLog.id)
        .where(AuditLog.action.in_(sorted(SECURITY_AUDIT_ACTIONS)), AuditLog.created_at < cutoff)
        .order_by(AuditLog.created_at, AuditLog.id)
        .limit(limit)
        .scalar_subquery()
    )
    result = await db.execute(
        delete(AuditLog).where(AuditLog.id.in_(due)).execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_actions(
    db: AsyncSession,
    *,
    action: str | None = None,
    actor_id: int | None = None,
    target_type: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[AuditLog]]:
    """``(total, rows)`` of audit rows, newest first, each with its actor loaded.

    ``action`` ending in ``.`` is a prefix (``moderation.`` matches every moderation action);
    otherwise it must match exactly.
    """
    conditions = []
    if action is not None:
        if action.endswith("."):
            conditions.append(AuditLog.action.like(f"{_escape_like(action)}%", escape="\\"))
        else:
            conditions.append(AuditLog.action == action)
    if actor_id is not None:
        conditions.append(AuditLog.actor_id == actor_id)
    if target_type is not None:
        conditions.append(AuditLog.target_type == target_type)

    filtered = select(AuditLog.id).where(*conditions).subquery()
    total = (await db.execute(select(func.count()).select_from(filtered))).scalar_one()
    rows = await db.scalars(
        select(AuditLog)
        .where(*conditions)
        .options(joinedload(AuditLog.actor))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return total, list(rows.unique())

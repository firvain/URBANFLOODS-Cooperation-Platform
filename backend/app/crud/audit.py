"""Audit log writer. Every status or role change goes through ``log_action``.

Secrets never belong in the audit log. As a defensive measure, any metadata key whose name has a
``password``, ``token`` or ``secret`` part (split on ``_``/``-``/``.``/space, case-insensitive,
e.g. ``password``, ``new_password``, ``reset_token``, ``client-secret``) is dropped at any depth
before storage, and a warning naming the dropped keys (never the values) is logged.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db.models import AuditLog

SENSITIVE_KEY_PARTS = frozenset({"password", "token", "secret"})
_KEY_SPLIT = re.compile(r"[_\-.\s]+")

log = structlog.get_logger(__name__)


def _is_sensitive(key: Any) -> bool:
    parts = _KEY_SPLIT.split(str(key).casefold())
    return any(part in SENSITIVE_KEY_PARTS for part in parts)


def _strip_sensitive(value: Any, dropped: list[str]) -> Any:
    """Return a copy of ``value`` without sensitive dict keys (recursing into dicts and lists)."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive(key):
                dropped.append(str(key))
                continue
            cleaned[key] = _strip_sensitive(item, dropped)
        return cleaned
    if isinstance(value, list | tuple):
        return [_strip_sensitive(item, dropped) for item in value]
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
    cleaned = _strip_sensitive(metadata or {}, dropped)
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

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
from sqlalchemy.ext.asyncio import AsyncSession

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

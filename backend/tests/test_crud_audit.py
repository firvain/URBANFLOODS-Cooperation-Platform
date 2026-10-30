"""Increment 1b: audit log writer (``app.crud.audit``)."""

from __future__ import annotations

from sqlalchemy import select

from app.crud.audit import log_action
from app.db.models import AuditLog, User


async def _make_user(db, email: str = "audit-user@example.org") -> User:
    user = User(email=email, password_hash="not-a-real-hash", display_name="Audit User")
    db.add(user)
    await db.flush()
    return user


async def test_log_action_persists(db_session):
    user = await _make_user(db_session)

    entry = await log_action(
        db_session,
        actor_id=user.id,
        action="user.promote",
        target_type="user",
        target_id=user.id,
        metadata={"from": "member", "to": "admin"},
    )

    assert entry.id is not None
    db_session.expunge_all()
    stored = (
        await db_session.execute(select(AuditLog).where(AuditLog.id == entry.id))
    ).scalar_one()
    assert stored.actor_id == user.id
    assert stored.action == "user.promote"
    assert stored.target_type == "user"
    assert stored.target_id == user.id
    assert stored.metadata_ == {"from": "member", "to": "admin"}
    assert stored.created_at is not None


async def test_log_action_without_actor_or_metadata(db_session):
    entry = await log_action(db_session, actor_id=None, action="auth.consent")
    await db_session.refresh(entry)

    assert entry.actor_id is None
    assert entry.target_type is None and entry.target_id is None
    assert entry.metadata_ == {}


async def test_log_action_strips_sensitive_keys(db_session):
    metadata = {
        "password": "hunter2hunter2",
        "Token": "abc",
        "secret": "s",
        "new_password": "x",
        "reset_token": "y",
        "client-secret": "z",
        "email": "kept@example.org",
        "nested": {"token": "t", "reason": "kept"},
        "items": [{"password": "p", "ok": 1}],
    }

    entry = await log_action(db_session, actor_id=None, action="auth.test", metadata=metadata)
    db_session.expunge_all()
    stored = (
        await db_session.execute(select(AuditLog).where(AuditLog.id == entry.id))
    ).scalar_one()

    assert stored.metadata_ == {
        "email": "kept@example.org",
        "nested": {"reason": "kept"},
        "items": [{"ok": 1}],
    }
    # The caller's dict is not mutated.
    assert metadata["password"] == "hunter2hunter2"

"""Increment 1b: audit log writer (``app.crud.audit``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.crud.audit import SECURITY_AUDIT_ACTIONS, log_action, purge_security_events
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


# --- 7r: security-event retention -------------------------------------------------------------

# Far in the past, so only this section's rows are older than the cutoff.
CUTOFF = datetime(1995, 1, 1, tzinfo=UTC)


async def _row(db, action: str, created_at: datetime) -> int:
    entry = AuditLog(action=action, created_at=created_at)
    db.add(entry)
    await db.flush()
    return entry.id


async def _ids(db, ids) -> set[int]:
    db.expire_all()
    return set((await db.scalars(select(AuditLog.id).where(AuditLog.id.in_(ids)))).all())


def test_security_audit_actions_are_exactly_the_reviewed_allow_list():
    """Widening the list deletes more of the audit trail: a deliberate, reviewed change."""
    assert (
        frozenset(
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
        == SECURITY_AUDIT_ACTIONS
    )
    assert isinstance(SECURITY_AUDIT_ACTIONS, frozenset)


async def test_purge_security_events_deletes_only_old_security_rows(db_session):
    old = CUTOFF - timedelta(seconds=1)
    old_login = await _row(db_session, "auth.login", old)
    at_cutoff = await _row(db_session, "auth.login", CUTOFF)
    old_consent = await _row(db_session, "auth.consent", old)
    old_moderation = await _row(db_session, "moderation.approve", old)
    ids = old_login, at_cutoff, old_consent, old_moderation

    count = await purge_security_events(db_session, cutoff=CUTOFF, limit=100)

    assert count == 1
    assert await _ids(db_session, ids) == {at_cutoff, old_consent, old_moderation}


async def test_purge_security_events_takes_the_oldest_first_up_to_the_limit(db_session):
    ids = [await _row(db_session, "auth.logout", CUTOFF - timedelta(days=d)) for d in (1, 3, 2)]

    count = await purge_security_events(db_session, cutoff=CUTOFF, limit=2)

    assert count == 2
    # Day 3 and day 2 (the oldest) go; day 1 waits for the next run.
    assert await _ids(db_session, ids) == {ids[0]}


async def test_purge_security_events_with_nothing_due_returns_0(db_session):
    kept = await _row(db_session, "auth.login", CUTOFF + timedelta(days=1))

    assert await purge_security_events(db_session, cutoff=CUTOFF, limit=100) == 0
    assert await _ids(db_session, [kept]) == {kept}

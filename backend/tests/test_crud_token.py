"""Increment 1b: single-use email tokens (``app.crud.token``).

Every test runs inside the ``db_session`` transaction and only flushes; the fixture rolls back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.security import hash_token
from app.crud.token import consume_email_token, create_email_token, delete_expired_tokens
from app.db.enums import TokenPurpose
from app.db.models import EmailToken, User

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


async def _make_user(db, email: str = "token-user@example.org") -> User:
    user = User(email=email, password_hash="not-a-real-hash", display_name="Token User")
    db.add(user)
    await db.flush()
    return user


async def test_create_stores_hash_and_expiry(db_session):
    user = await _make_user(db_session)

    token, raw = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.RESET_PASSWORD, now=T0
    )

    assert token.id is not None
    assert token.user_id == user.id
    assert token.purpose is TokenPurpose.RESET_PASSWORD
    assert token.token_hash == hash_token(raw) != raw
    assert token.expires_at == T0 + timedelta(hours=1)
    assert token.used_at is None
    assert token.new_email is None


async def test_consume_succeeds_once(db_session):
    user = await _make_user(db_session)
    _, raw = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.VERIFY_EMAIL, now=T0
    )
    later = T0 + timedelta(hours=1)

    consumed = await consume_email_token(
        db_session, raw_token=raw, purpose=TokenPurpose.VERIFY_EMAIL, now=later
    )

    assert consumed is not None
    assert consumed.user_id == user.id
    assert consumed.used_at == later

    again = await consume_email_token(
        db_session, raw_token=raw, purpose=TokenPurpose.VERIFY_EMAIL, now=later
    )
    assert again is None


async def test_consume_wrong_purpose(db_session):
    user = await _make_user(db_session)
    _, raw = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.VERIFY_EMAIL, now=T0
    )

    assert (
        await consume_email_token(
            db_session, raw_token=raw, purpose=TokenPurpose.RESET_PASSWORD, now=T0
        )
        is None
    )
    # A wrong-purpose attempt does not burn the token.
    assert await consume_email_token(
        db_session, raw_token=raw, purpose=TokenPurpose.VERIFY_EMAIL, now=T0
    )


async def test_consume_expired(db_session):
    user = await _make_user(db_session)
    _, raw = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.RESET_PASSWORD, now=T0
    )

    assert (
        await consume_email_token(
            db_session,
            raw_token=raw,
            purpose=TokenPurpose.RESET_PASSWORD,
            now=T0 + timedelta(hours=1),
        )
        is None
    )


async def test_consume_unknown_token(db_session):
    assert (
        await consume_email_token(
            db_session, raw_token="does-not-exist", purpose=TokenPurpose.VERIFY_EMAIL, now=T0
        )
        is None
    )


async def test_new_token_invalidates_older_unused_of_same_purpose(db_session):
    user = await _make_user(db_session)
    old_verify, old_raw = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.VERIFY_EMAIL, now=T0
    )
    reset, reset_raw = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.RESET_PASSWORD, now=T0
    )
    later = T0 + timedelta(minutes=5)

    new_verify, new_raw = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.VERIFY_EMAIL, now=later
    )

    await db_session.refresh(old_verify)
    await db_session.refresh(reset)
    assert old_verify.used_at == later
    assert reset.used_at is None  # other purposes untouched
    assert new_verify.used_at is None

    assert (
        await consume_email_token(
            db_session, raw_token=old_raw, purpose=TokenPurpose.VERIFY_EMAIL, now=later
        )
        is None
    )
    assert await consume_email_token(
        db_session, raw_token=new_raw, purpose=TokenPurpose.VERIFY_EMAIL, now=later
    )
    assert await consume_email_token(
        db_session, raw_token=reset_raw, purpose=TokenPurpose.RESET_PASSWORD, now=later
    )


async def test_new_token_does_not_touch_other_users(db_session):
    alice = await _make_user(db_session, email="alice-token@example.org")
    bob = await _make_user(db_session, email="bob-token@example.org")
    _, alice_raw = await create_email_token(
        db_session, user_id=alice.id, purpose=TokenPurpose.VERIFY_EMAIL, now=T0
    )
    await create_email_token(db_session, user_id=bob.id, purpose=TokenPurpose.VERIFY_EMAIL, now=T0)

    assert await consume_email_token(
        db_session, raw_token=alice_raw, purpose=TokenPurpose.VERIFY_EMAIL, now=T0
    )


async def test_consume_change_email_returns_new_email(db_session):
    user = await _make_user(db_session)
    _, raw = await create_email_token(
        db_session,
        user_id=user.id,
        purpose=TokenPurpose.CHANGE_EMAIL,
        new_email="new-address@example.org",
        now=T0,
    )

    consumed = await consume_email_token(
        db_session, raw_token=raw, purpose=TokenPurpose.CHANGE_EMAIL, now=T0 + timedelta(hours=23)
    )

    assert consumed is not None
    assert consumed.new_email == "new-address@example.org"


async def test_delete_expired_tokens(db_session):
    user = await _make_user(db_session)
    now = T0 + timedelta(days=30)

    # Unused, still valid: kept.
    fresh, _ = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.VERIFY_EMAIL, now=now
    )
    # Expired 3 days ago: kept (within grace).
    recent, _ = await create_email_token(
        db_session,
        user_id=user.id,
        purpose=TokenPurpose.RESET_PASSWORD,
        now=now - timedelta(days=3),
    )
    # Expired 10 days ago: deleted.
    old, _ = await create_email_token(
        db_session,
        user_id=user.id,
        purpose=TokenPurpose.CHANGE_EMAIL,
        new_email="x@example.org",
        now=now - timedelta(days=11),
    )

    deleted = await delete_expired_tokens(db_session, now=now)

    assert deleted == 1
    remaining = set(
        (await db_session.scalars(select(EmailToken.id).where(EmailToken.user_id == user.id))).all()
    )
    assert remaining == {fresh.id, recent.id}


async def test_delete_used_tokens_after_window(db_session):
    user = await _make_user(db_session)
    now = T0 + timedelta(days=30)
    # Verify tokens live 48h; this one was used 8 days ago and would otherwise still be "valid".
    _, raw = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.VERIFY_EMAIL, now=now - timedelta(days=8)
    )
    await consume_email_token(
        db_session, raw_token=raw, purpose=TokenPurpose.VERIFY_EMAIL, now=now - timedelta(days=8)
    )

    assert await delete_expired_tokens(db_session, now=now) == 1
    count = await db_session.scalar(
        select(func.count()).select_from(EmailToken).where(EmailToken.user_id == user.id)
    )
    assert count == 0


async def test_invalidate_email_tokens_only_named_purposes_and_unused(db_session):
    from app.crud.token import invalidate_email_tokens

    user = await _make_user(db_session)
    other = await _make_user(db_session, email="token-other@example.org")
    used, _ = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.RESET_PASSWORD, now=T0
    )
    reset, _ = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.RESET_PASSWORD, now=T0
    )
    change, _ = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.CHANGE_EMAIL, new_email="n@example.org"
    )
    verify, _ = await create_email_token(
        db_session, user_id=user.id, purpose=TokenPurpose.VERIFY_EMAIL
    )
    others, _ = await create_email_token(
        db_session, user_id=other.id, purpose=TokenPurpose.RESET_PASSWORD
    )
    later = T0 + timedelta(minutes=5)

    count = await invalidate_email_tokens(
        db_session,
        user_id=user.id,
        purposes=(TokenPurpose.RESET_PASSWORD, TokenPurpose.VERIFY_EMAIL),
        now=later,
    )

    assert count == 2
    for token in (used, reset, change, verify, others):
        await db_session.refresh(token)
    assert used.used_at == T0  # invalidated earlier by the second create; untouched
    assert reset.used_at == later
    assert verify.used_at == later
    assert change.used_at is None
    assert others.used_at is None

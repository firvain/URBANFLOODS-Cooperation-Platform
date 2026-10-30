"""Increment 1h: ``python -m app.cli`` (create-superadmin, promote).

``main`` runs its own event loop (``asyncio.run``), so it is called in a worker thread from these
async tests; it talks to the session test database and commits, hence ``cleanup_users``.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select

from app import cli
from app.core.security import verify_password
from app.db.enums import UserRole
from app.db.models import AuditLog, Organisation, User
from tests.factories import (
    create_admin,
    create_superadmin,
    create_user,
    create_verified_user,
    unique_email,
)

PASSWORD = "a-very-long-cli-password"


async def _run(*argv: str) -> int:
    return await asyncio.to_thread(cli.main, list(argv))


async def _user(db, email: str) -> User | None:
    stmt = select(User).where(User.email == email).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _audit(db, user_id: int, action: str) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.target_type == "user",
            AuditLog.target_id == user_id,
            AuditLog.action == action,
        )
        .order_by(AuditLog.id)
    )
    return list((await db.scalars(stmt)).all())


async def test_create_superadmin(db_session, cleanup_users, capsys):
    email = unique_email("boot")
    cleanup_users.add(email)
    uowm_id = await db_session.scalar(
        select(Organisation.id).where(Organisation.short_name == "UOWM")
    )

    code = await _run(
        "create-superadmin",
        "--email",
        email,
        "--display-name",
        "Boot Strap",
        "--password",
        PASSWORD,
        "--organisation-id",
        str(uowm_id),
    )

    assert code == 0
    user = await _user(db_session, email)
    assert user is not None
    assert capsys.readouterr().out.strip() == str(user.id)
    assert user.role == UserRole.SUPERADMIN
    assert user.is_verified is True
    assert user.trusted_at is not None
    assert user.is_active is True
    assert user.display_name == "Boot Strap"
    assert user.organisation_id == uowm_id
    assert verify_password(PASSWORD, user.password_hash)
    rows = await _audit(db_session, user.id, "admin.bootstrap_superadmin")
    assert len(rows) == 1
    assert rows[0].actor_id is None
    assert rows[0].metadata_ == {"created": True, "from": None, "to": "superadmin"}


async def test_create_superadmin_is_idempotent(db_session, cleanup_users, capsys):
    email = unique_email("boot")
    cleanup_users.add(email)
    args = ("create-superadmin", "--email", email, "--display-name", "Boot", "--password", PASSWORD)

    assert await _run(*args) == 0
    first = capsys.readouterr().out.strip()
    assert await _run(*args) == 0
    second = capsys.readouterr().out.strip()

    assert first == second
    user = await _user(db_session, email)
    assert user.role == UserRole.SUPERADMIN
    count = await db_session.scalar(select(func.count()).where(User.email == email))
    assert count == 1
    # Nothing changed the second time, so no second audit row.
    assert len(await _audit(db_session, user.id, "admin.bootstrap_superadmin")) == 1


async def test_create_superadmin_promotes_existing_member(db_session, cleanup_users, capsys):
    member = await create_user(db_session)  # unverified member
    cleanup_users.add(member.email)
    original_hash = member.password_hash
    await db_session.commit()

    code = await _run(
        "create-superadmin", "--email", member.email.upper(), "--display-name", "Ignored"
    )

    assert code == 0
    assert capsys.readouterr().out.strip() == str(member.id)
    user = await _user(db_session, member.email)
    assert user.role == UserRole.SUPERADMIN
    assert user.is_verified is True
    assert user.trusted_at is not None
    # An existing account keeps its password and name.
    assert user.password_hash == original_hash
    assert user.display_name == "Test User"
    rows = await _audit(db_session, member.id, "admin.bootstrap_superadmin")
    assert rows[0].metadata_ == {"created": False, "from": "member", "to": "superadmin"}


async def test_create_superadmin_prompts_for_password(
    db_session, cleanup_users, capsys, monkeypatch
):
    email = unique_email("boot")
    cleanup_users.add(email)
    prompts: list[str] = []

    def fake_getpass(prompt: str = "") -> str:
        prompts.append(prompt)
        return PASSWORD

    monkeypatch.setattr(cli.getpass, "getpass", fake_getpass)

    code = await _run("create-superadmin", "--email", email, "--display-name", "Prompted")

    assert code == 0
    assert len(prompts) == 2  # password + confirmation
    user = await _user(db_session, email)
    assert verify_password(PASSWORD, user.password_hash)


async def test_create_superadmin_prompt_mismatch(db_session, cleanup_users, capsys, monkeypatch):
    email = unique_email("boot")
    cleanup_users.add(email)
    answers = iter([PASSWORD, PASSWORD + "x"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))

    code = await _run("create-superadmin", "--email", email, "--display-name", "Prompted")

    assert code == 1
    assert "do not match" in capsys.readouterr().err
    assert await _user(db_session, email) is None


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (("--password", "short"), "password"),
        (("--organisation-id", "999999"), "organisation"),
    ],
)
async def test_create_superadmin_rejects_bad_input(
    db_session, cleanup_users, capsys, extra, message
):
    email = unique_email("boot")
    cleanup_users.add(email)
    args = ["create-superadmin", "--email", email, "--display-name", "Bad"]
    if "--password" not in extra:
        args += ["--password", PASSWORD]

    code = await _run(*args, *extra)

    assert code == 1
    assert message in capsys.readouterr().err.lower()
    assert await _user(db_session, email) is None


async def test_create_superadmin_invalid_email(capsys):
    code = await _run(
        "create-superadmin",
        "--email",
        "not-an-email",
        "--display-name",
        "X Y",
        "--password",
        PASSWORD,
    )
    assert code == 1
    assert "email" in capsys.readouterr().err.lower()


async def test_promote(db_session, cleanup_users, capsys):
    member = await create_verified_user(db_session)
    cleanup_users.add(member.email)
    await db_session.commit()

    assert await _run("promote", "--email", member.email, "--to", "admin") == 0
    assert (await _user(db_session, member.email)).role == UserRole.ADMIN
    rows = await _audit(db_session, member.id, "admin.promote")
    assert rows[-1].actor_id is None
    assert rows[-1].metadata_ == {"from": "member", "to": "admin", "via": "cli"}

    assert await _run("promote", "--email", member.email, "--to", "superadmin") == 0
    assert (await _user(db_session, member.email)).role == UserRole.SUPERADMIN
    assert len(await _audit(db_session, member.id, "admin.promote")) == 2


async def test_promote_same_role_is_noop(db_session, cleanup_users, capsys):
    admin = await create_admin(db_session)
    cleanup_users.add(admin.email)
    await db_session.commit()

    assert await _run("promote", "--email", admin.email, "--to", "admin") == 0
    assert await _audit(db_session, admin.id, "admin.promote") == []


async def test_promote_refuses_demotion(db_session, cleanup_users, capsys):
    superadmin = await create_superadmin(db_session)
    cleanup_users.add(superadmin.email)
    await db_session.commit()

    assert await _run("promote", "--email", superadmin.email, "--to", "admin") == 1
    assert (await _user(db_session, superadmin.email)).role == UserRole.SUPERADMIN


async def test_promote_unknown_email(capsys):
    assert await _run("promote", "--email", unique_email("nobody"), "--to", "admin") == 1
    assert "no user" in capsys.readouterr().err.lower()


def test_usage_errors_exit_2(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["promote", "--email", "a@example.org", "--to", "owner"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit):
        cli.main([])

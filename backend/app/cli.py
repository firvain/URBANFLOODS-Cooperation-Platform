"""Operator command line.

    python -m app.cli create-superadmin --email X --display-name Y [--password Z]
                                        [--organisation-id N]
    python -m app.cli promote --email X --to admin|superadmin
    python -m app.cli digest [--force]
    python -m app.cli maintenance

``create-superadmin`` creates a verified, trusted superadmin, or, if the address is already
registered, makes that account a verified, trusted superadmin (its password and profile are
kept). Running it again changes nothing. Without ``--password`` the password is prompted for
(twice) when a new account is created. Both commands print the user id on success, write an
audit row with no actor, and exit 0; errors go to stderr with exit code 1 (2 for usage errors).

``digest`` sends the admin moderation digest now (``--force`` sends it even when nothing is
pending or reported) and prints ``recipients=N items=M``. ``maintenance`` runs the maintenance
sweeps once and prints one ``step=count`` line per step; it exits 1 if a step failed (``-1``).
Both exit 1 with one ``error: <type>: <message>`` line (addresses redacted) if the job raises,
and ``digest`` also when every email failed.

Each run uses its own short-lived engine (no pool), so ``main`` can be called from any thread
that has no running event loop.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import re
import sys
from collections.abc import Sequence
from functools import partial

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.security import PasswordPolicyError
from app.crud import audit as crud_audit
from app.crud import user as crud_user
from app.db.enums import UserRole
from app.db.models import User
from app.db.session import AsyncSessionLocal
from app.services import scheduler

ROLE_RANK = {UserRole.MEMBER: 0, UserRole.ADMIN: 1, UserRole.SUPERADMIN: 2}
DISPLAY_NAME_MIN, DISPLAY_NAME_MAX = 2, 120
_email_adapter: TypeAdapter[str] = TypeAdapter(EmailStr)


class CliError(Exception):
    """A user-facing failure: printed to stderr, exit code 1."""


def _email(value: str) -> str:
    try:
        return _email_adapter.validate_python(value.strip())
    except ValidationError:
        raise CliError(f"invalid email address: {value!r}") from None


def _prompt_password() -> str:
    password = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != password:
        raise CliError("passwords do not match")
    return password


async def _audit(db: AsyncSession, *, action: str, user: User, metadata: dict) -> None:
    await crud_audit.log_action(
        db, actor_id=None, action=action, target_type="user", target_id=user.id, metadata=metadata
    )


async def _create_superadmin(db: AsyncSession, args: argparse.Namespace) -> int:
    """Returns the user id."""
    email = _email(args.email)
    user = await crud_user.get_user_by_email(db, email=email)
    created = user is None
    old_role: UserRole | None = None

    if user is None:
        display_name = args.display_name.strip()
        if not DISPLAY_NAME_MIN <= len(display_name) <= DISPLAY_NAME_MAX:
            raise CliError(f"display name must be {DISPLAY_NAME_MIN}-{DISPLAY_NAME_MAX} characters")
        password = args.password if args.password is not None else _prompt_password()
        try:
            user = await crud_user.create_user(
                db,
                email=email,
                password=password,
                display_name=display_name,
                organisation_id=args.organisation_id,
            )
        except PasswordPolicyError as exc:
            raise CliError(f"password rejected ({exc.code})") from None
        except AppError as exc:
            fields = ", ".join(f"{k}={v}" for k, v in (exc.fields or {}).items())
            raise CliError(f"{exc.code}: {fields or exc.message}") from None
    else:
        if user.deleted_at is not None:
            raise CliError(f"the account {email} has been deleted")
        old_role = user.role
        if not user.is_active:
            print(f"warning: the account {email} is banned (inactive)", file=sys.stderr)

    changed = created
    changed |= await crud_user.set_role(db, user=user, role=UserRole.SUPERADMIN)
    if not user.is_verified:
        await crud_user.mark_verified(db, user=user)
        changed = True
    changed |= await crud_user.set_trusted(db, user=user, trusted=True)
    if changed:
        await _audit(
            db,
            action="admin.bootstrap_superadmin",
            user=user,
            metadata={"created": created, "from": old_role, "to": UserRole.SUPERADMIN},
        )
    return user.id


async def _promote(db: AsyncSession, args: argparse.Namespace) -> int:
    """Returns the user id."""
    email = _email(args.email)
    user = await crud_user.get_user_by_email(db, email=email)
    if user is None:
        raise CliError(f"no user with email {email}")
    if user.deleted_at is not None:
        raise CliError(f"the account {email} has been deleted")
    role = UserRole(args.to)
    old_role = user.role
    if ROLE_RANK[role] < ROLE_RANK[old_role]:
        raise CliError(f"{email} is {old_role}; use the admin interface to demote")
    if await crud_user.set_role(db, user=user, role=role):
        await _audit(
            db,
            action="admin.promote",
            user=user,
            metadata={"from": old_role, "to": role, "via": "cli"},
        )
    return user.id


COMMANDS = {"create-superadmin": _create_superadmin, "promote": _promote}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser(
        "create-superadmin", help="create (or promote) a verified, trusted superadmin"
    )
    create.add_argument("--email", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument("--password", help="prompted for when omitted (new accounts only)")
    create.add_argument("--organisation-id", type=int)

    promote = commands.add_parser("promote", help="raise an existing user's role")
    promote.add_argument("--email", required=True)
    promote.add_argument("--to", required=True, choices=["admin", "superadmin"])

    digest = commands.add_parser("digest", help="send the admin moderation digest now")
    digest.add_argument(
        "--force", action="store_true", help="send even when nothing is pending or reported"
    )
    commands.add_parser("maintenance", help="run the maintenance sweeps once")
    return parser


async def _run(args: argparse.Namespace) -> int:
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with AsyncSessionLocal(bind=engine) as db, db.begin():
            user_id = await COMMANDS[args.command](db, args)
    finally:
        await engine.dispose()
    # Printed only once the transaction has committed.
    print(user_id)
    return 0


async def _run_job(args: argparse.Namespace) -> int:
    """``digest`` / ``maintenance``: the scheduler's coroutines on a short-lived engine."""
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    session_factory = partial(AsyncSessionLocal, bind=engine)
    try:
        if args.command == "digest":
            run = await scheduler.run_digest(args.force, session_factory=session_factory)
            if run is None:
                print("error: every digest email failed; nothing recorded", file=sys.stderr)
                return 1
            print(f"recipients={run.recipients} items={run.items}")
            return 0
        counts = await scheduler.run_maintenance(session_factory=session_factory)
    finally:
        await engine.dispose()
    for step, count in counts.items():
        print(f"{step}={count}")
    return 1 if any(count < 0 for count in counts.values()) else 0


JOB_COMMANDS = frozenset({"digest", "maintenance"})
# Job errors are printed without email addresses (a database or SMTP message may carry one).
_ADDRESS = re.compile(r"[^\s@<>\"']+@[^\s@<>\"']+")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command in JOB_COMMANDS:
            try:
                return asyncio.run(_run_job(args))
            except Exception as exc:
                message = _ADDRESS.sub("<address>", " ".join(str(exc).split()))
                print(f"error: {type(exc).__name__}: {message}", file=sys.stderr)
                return 1
        return asyncio.run(_run(args))
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

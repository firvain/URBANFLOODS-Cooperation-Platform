"""Increment 4e: the APScheduler setup, the app lifespan hook, the job wrappers and the
``digest`` / ``maintenance`` CLI commands."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from asgi_lifespan import LifespanManager
from sqlalchemy import delete, func, select

from app import cli
from app.core.config import settings
from app.db.models import AuditLog, DigestRun
from app.services import scheduler
from tests.factories import create_admin


def _fields(job) -> dict[str, str]:
    assert isinstance(job.trigger, CronTrigger)
    return {field.name: str(field) for field in job.trigger.fields}


# --- create_scheduler -------------------------------------------------------------------------


def test_create_scheduler_registers_two_jobs() -> None:
    sched = scheduler.create_scheduler()

    assert isinstance(sched, AsyncIOScheduler)
    assert not sched.running
    assert {job.id for job in sched.get_jobs()} == {"admin_digest", "maintenance"}
    assert str(sched.timezone) == "UTC"


def test_jobs_run_daily_at_digest_hour_and_the_hour_before(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DIGEST_HOUR_UTC", 6)
    jobs = {job.id: job for job in scheduler.create_scheduler().get_jobs()}

    digest = _fields(jobs["admin_digest"])
    maintenance = _fields(jobs["maintenance"])
    assert (digest["hour"], digest["minute"], digest["day_of_week"]) == ("6", "0", "*")
    assert (maintenance["hour"], maintenance["minute"]) == ("5", "0")
    assert str(jobs["admin_digest"].trigger.timezone) == "UTC"


def test_maintenance_hour_wraps_around_midnight(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DIGEST_HOUR_UTC", 0)
    jobs = {job.id: job for job in scheduler.create_scheduler().get_jobs()}

    assert _fields(jobs["admin_digest"])["hour"] == "0"
    assert _fields(jobs["maintenance"])["hour"] == "23"


def test_jobs_coalesce_with_one_instance_and_an_hour_of_grace() -> None:
    for job in scheduler.create_scheduler().get_jobs():
        assert job.coalesce is True
        assert job.max_instances == 1
        assert job.misfire_grace_time == 3600


def test_jobs_call_the_wrappers() -> None:
    jobs = {job.id: job for job in scheduler.create_scheduler().get_jobs()}

    assert jobs["admin_digest"].func is scheduler.digest_job
    assert jobs["maintenance"].func is scheduler.maintenance_job


async def test_digest_job_runs_digest_and_swallows_errors(monkeypatch) -> None:
    calls = []

    async def fake_run_digest(force=False, **kwargs):
        calls.append(force)
        raise ConnectionError("smtp down for admin@example.org")

    monkeypatch.setattr(scheduler, "run_digest", fake_run_digest)

    with structlog.testing.capture_logs() as logs:
        await scheduler.digest_job()

    assert calls == [False]
    failed = [e for e in logs if e["event"] == "scheduler.job_failed"]
    assert [(e["job"], e["error"]) for e in failed] == [("admin_digest", "ConnectionError")]
    assert "admin@example.org" not in repr(logs)


async def test_maintenance_job_runs_maintenance_and_swallows_errors(monkeypatch) -> None:
    calls = []

    async def fake_run_maintenance(now=None, **kwargs):
        calls.append(now)
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "run_maintenance", fake_run_maintenance)

    with structlog.testing.capture_logs() as logs:
        await scheduler.maintenance_job()

    assert calls == [None]
    assert [e["job"] for e in logs if e["event"] == "scheduler.job_failed"] == ["maintenance"]


# --- lifespan ---------------------------------------------------------------------------------


class FakeScheduler:
    def __init__(self) -> None:
        self.started = 0
        self.shutdowns: list[bool] = []

    def start(self) -> None:
        self.started += 1

    def shutdown(self, wait: bool = True) -> None:
        self.shutdowns.append(wait)


@pytest.fixture
def fake_scheduler(monkeypatch) -> FakeScheduler:
    fake = FakeScheduler()
    monkeypatch.setattr(scheduler, "create_scheduler", lambda: fake)
    return fake


async def test_lifespan_starts_and_stops_scheduler_when_enabled(
    monkeypatch, fake_scheduler
) -> None:
    from app.main import create_app

    monkeypatch.setattr(settings, "ENABLE_SCHEDULER", True)
    app = create_app()

    async with LifespanManager(app):
        assert fake_scheduler.started == 1
        assert fake_scheduler.shutdowns == []
        assert app.state.scheduler is fake_scheduler

    assert fake_scheduler.shutdowns == [False]


async def test_lifespan_leaves_scheduler_off_when_disabled(monkeypatch, fake_scheduler) -> None:
    from app.main import create_app

    monkeypatch.setattr(settings, "ENABLE_SCHEDULER", False)
    app = create_app()

    async with LifespanManager(app):
        assert getattr(app.state, "scheduler", None) is None

    assert fake_scheduler.started == 0
    assert fake_scheduler.shutdowns == []


# --- CLI --------------------------------------------------------------------------------------


async def _cli(*argv: str) -> int:
    return await asyncio.to_thread(cli.main, list(argv))


@pytest.fixture
async def cleanup_job_rows(database_url: str) -> AsyncIterator[None]:
    """Delete the digest runs and maintenance audit rows a CLI run commits."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        max_run = await db.scalar(select(func.coalesce(func.max(DigestRun.id), 0)))
        max_audit = await db.scalar(select(func.coalesce(func.max(AuditLog.id), 0)))
    yield
    async with AsyncSessionLocal() as db, db.begin():
        await db.execute(delete(DigestRun).where(DigestRun.id > max_run))
        await db.execute(
            delete(AuditLog).where(AuditLog.id > max_audit, AuditLog.action.like("maintenance.%"))
        )


async def test_cli_digest_force(db_session, cleanup_users, cleanup_job_rows, outbox, capsys):
    admin = await create_admin(db_session)
    cleanup_users.add(admin.email)
    await db_session.commit()

    code = await _cli("digest", "--force")

    assert code == 0
    out = capsys.readouterr().out
    assert "recipients=" in out
    assert "items=" in out
    assert admin.email in {m.to for m in outbox}
    runs = (await db_session.scalars(select(DigestRun).order_by(DigestRun.id.desc()))).first()
    assert runs is not None and runs.recipients >= 1


async def test_cli_maintenance(cleanup_job_rows, capsys) -> None:
    code = await _cli("maintenance")

    assert code == 0
    out = capsys.readouterr().out
    for key in (
        "sessions",
        "tokens",
        "unverified_users",
        "orphan_uploads",
        "auto_approved",
        "deleted_content",
    ):
        assert f"{key}=" in out


async def test_cli_maintenance_failure_exits_1(monkeypatch, capsys) -> None:
    async def failing(now=None, **kwargs):
        return {"sessions": 0, "orphan_uploads": -1}

    monkeypatch.setattr(scheduler, "run_maintenance", failing)

    code = await _cli("maintenance")

    assert code == 1
    assert "orphan_uploads=-1" in capsys.readouterr().out


@pytest.mark.parametrize("job_name", ["digest_job", "maintenance_job"])
async def test_jobs_tolerate_cancellation_at_shutdown(monkeypatch, job_name) -> None:
    started = asyncio.Event()

    async def hang(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(scheduler, "run_digest", hang)
    monkeypatch.setattr(scheduler, "run_maintenance", hang)

    with structlog.testing.capture_logs() as logs:
        task = asyncio.create_task(getattr(scheduler, job_name)())
        await started.wait()
        task.cancel()
        await asyncio.wait([task])

    assert not task.cancelled()
    assert task.exception() is None
    cancelled = [e for e in logs if e["event"] == "scheduler.job_cancelled"]
    assert [e["job"] for e in cancelled] == [
        "admin_digest" if job_name == "digest_job" else "maintenance"
    ]
    assert not [e for e in logs if e["event"] == "scheduler.job_failed"]


@pytest.mark.parametrize(
    ("command", "target"), [("digest", "run_digest"), ("maintenance", "run_maintenance")]
)
async def test_cli_job_error_exits_1_without_addresses(monkeypatch, capsys, command, target):
    async def failing(*args, **kwargs):
        raise RuntimeError("database gone while mailing admin@example.org")

    monkeypatch.setattr(scheduler, target, failing)

    code = await _cli(command)

    assert code == 1
    captured = capsys.readouterr()
    err_lines = captured.err.strip().splitlines()
    assert len(err_lines) == 1
    assert err_lines[0].startswith("error: RuntimeError: database gone while mailing")
    assert "admin@example.org" not in captured.err + captured.out


async def test_cli_digest_all_sends_failed_exits_1(monkeypatch, capsys) -> None:
    async def none_recorded(*args, **kwargs):
        return None

    monkeypatch.setattr(scheduler, "run_digest", none_recorded)

    code = await _cli("digest")

    assert code == 1
    assert "every digest email failed" in capsys.readouterr().err

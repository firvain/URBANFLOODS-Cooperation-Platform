"""Increment 4e: the daily admin moderation digest (``services/digest.py``).

Pending items and open reports are current state, not windowed, so every test that counts them
first neutralises whatever other tests left in the database (``_clear_queue``, rolled back with
``db_session``). Windowed counts (new members, published content) use a window in 2020, which no
other test writes into.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import structlog
from sqlalchemy import delete, select, update

from app.db.enums import CategoryKind, ContentStatus, DigestFrequency, ReportStatus, UserRole
from app.db.models import (
    DigestRun,
    NotificationPreference,
    Post,
    Report,
    Thread,
    User,
)
from app.services import digest as digest_service
from app.services.digest import (
    ADMIN_DIGEST_KIND,
    build_admin_digest,
    send_admin_digest,
)
from tests.factories import (
    create_admin,
    create_category,
    create_comment,
    create_post,
    create_reply,
    create_report,
    create_superadmin,
    create_thread,
    create_user,
    create_verified_user,
)

# A Tuesday, so weekly recipients are not due.
NOW = datetime(2020, 6, 2, 6, 0, tzinfo=UTC)
MONDAY = datetime(2020, 6, 1, 6, 0, tzinfo=UTC)


async def _clear_queue(db) -> None:
    """Hide other tests' pending content, dismiss their open reports, forget earlier runs and
    neutralise other admins (all rolled back at the end of the test)."""
    for model in (Post, Thread):
        await db.execute(
            update(model)
            .where(model.status == ContentStatus.PENDING)
            .values(status=ContentStatus.HIDDEN)
        )
    await db.execute(
        update(Report).where(Report.status == ReportStatus.OPEN).values(status="dismissed")
    )
    await db.execute(delete(DigestRun))
    await db.execute(
        update(User)
        .where(User.role.in_([UserRole.ADMIN, UserRole.SUPERADMIN]))
        .values(is_active=False)
    )


async def _set_prefs(db, user: User, **values) -> None:
    prefs = await db.get(NotificationPreference, user.id)
    for key, value in values.items():
        setattr(prefs, key, value)
    await db.flush()


async def _pending_post(db, *, author: User, title: str = "Pending post", **fields) -> Post:
    category = await create_category(db)
    return await create_post(
        db,
        category_id=category.id,
        author_id=author.id,
        title=title,
        status=ContentStatus.PENDING,
        **fields,
    )


async def _runs(db) -> list[DigestRun]:
    stmt = select(DigestRun).where(DigestRun.kind == ADMIN_DIGEST_KIND).order_by(DigestRun.id)
    return list((await db.scalars(stmt)).all())


# --- reuse -----------------------------------------------------------------------------------


def test_open_report_count_comes_from_crud_reports() -> None:
    from app.crud import digest as crud_digest
    from app.crud import reports as crud_reports

    assert not hasattr(crud_digest, "count_open_reports")
    assert digest_service.crud_reports is crud_reports
    assert not hasattr(digest_service, "frequency_due")


# --- window -----------------------------------------------------------------------------------


async def test_window_defaults_to_last_24_hours(db_session) -> None:
    await _clear_queue(db_session)

    data = await build_admin_digest(db_session, now=NOW)

    assert data.window_start == NOW - timedelta(hours=24)
    assert data.window_end == NOW


async def test_window_starts_at_last_run(db_session) -> None:
    await _clear_queue(db_session)
    last_end = NOW - timedelta(hours=30)
    db_session.add_all(
        [
            DigestRun(
                kind=ADMIN_DIGEST_KIND,
                window_start=last_end - timedelta(days=2),
                window_end=last_end - timedelta(days=1),
            ),
            DigestRun(
                kind=ADMIN_DIGEST_KIND,
                window_start=last_end - timedelta(days=1),
                window_end=last_end,
            ),
            # Another kind never moves the admin window.
            DigestRun(
                kind="member_weekly",
                window_start=NOW - timedelta(hours=2),
                window_end=NOW - timedelta(hours=1),
            ),
        ]
    )
    await db_session.flush()

    data = await build_admin_digest(db_session, now=NOW)

    assert data.window_start == last_end
    assert data.window_end == NOW


# --- contents ---------------------------------------------------------------------------------


async def test_digest_lists_pending_posts_and_threads(db_session) -> None:
    await _clear_queue(db_session)
    author = await create_verified_user(db_session, display_name="Penny Pending")
    post = await _pending_post(db_session, author=author, title="Green roofs in Thessaloniki")
    forum = await create_category(db_session, kind=CategoryKind.FORUM)
    thread = await create_thread(
        db_session,
        category_id=forum.id,
        author_id=author.id,
        title="Sizing detention basins",
        status=ContentStatus.PENDING,
    )

    data = await build_admin_digest(db_session, now=NOW)

    assert data.pending_total == 2
    by_title = {item.title: item for item in data.pending}
    assert set(by_title) == {"Green roofs in Thessaloniki", "Sizing detention basins"}
    assert by_title["Green roofs in Thessaloniki"].content_type == "post"
    assert by_title["Green roofs in Thessaloniki"].content_id == post.id
    assert by_title["Sizing detention basins"].content_type == "thread"
    assert by_title["Sizing detention basins"].content_id == thread.id
    assert all(item.author_name == "Penny Pending" for item in data.pending)
    assert all(item.created_at is not None for item in data.pending)


async def test_digest_counts_open_reports_and_lists_newest_ten(db_session) -> None:
    await _clear_queue(db_session)
    author = await create_verified_user(db_session)
    category = await create_category(db_session)
    post = await create_post(db_session, category_id=category.id, author_id=author.id)
    reports = []
    for i in range(12):
        reporter = await create_verified_user(db_session)
        reports.append(
            await create_report(
                db_session,
                reporter_id=reporter.id,
                content_id=post.id,
                reason="abuse" if i == 11 else "spam",
                created_at=NOW - timedelta(minutes=60 - i),
            )
        )
    closed_reporter = await create_verified_user(db_session)
    await create_report(
        db_session,
        reporter_id=closed_reporter.id,
        content_id=post.id,
        status=ReportStatus.RESOLVED,
    )

    data = await build_admin_digest(db_session, now=NOW)

    assert data.reports_total == 12
    assert len(data.reports) == 10
    assert [r.report_id for r in data.reports] == [r.id for r in reversed(reports)][:10]
    newest = data.reports[0]
    assert (newest.content_type, newest.content_id, newest.reason) == ("post", post.id, "abuse")


async def test_digest_items_is_pending_plus_open_reports(db_session) -> None:
    await _clear_queue(db_session)
    author = await create_verified_user(db_session)
    post = await _pending_post(db_session, author=author)
    reporter = await create_verified_user(db_session)
    await create_report(db_session, reporter_id=reporter.id, content_id=post.id)

    data = await build_admin_digest(db_session, now=NOW)

    assert data.items == 2


async def test_digest_counts_new_members_in_window(db_session) -> None:
    await _clear_queue(db_session)
    inside = NOW - timedelta(hours=3)
    await create_user(db_session, created_at=inside)
    await create_verified_user(db_session, created_at=inside)
    await create_user(db_session, created_at=NOW - timedelta(hours=25))  # before the window
    await create_user(db_session, created_at=NOW)  # window end is exclusive
    await create_user(db_session, created_at=inside, deleted_at=inside)

    data = await build_admin_digest(db_session, now=NOW)

    assert data.new_members == 2


async def test_digest_counts_content_published_in_window(db_session) -> None:
    await _clear_queue(db_session)
    inside = NOW - timedelta(hours=2)
    outside = NOW - timedelta(days=3)
    author = await create_verified_user(db_session)
    blog = await create_category(db_session)
    forum = await create_category(db_session, kind=CategoryKind.FORUM)
    post = await create_post(db_session, category_id=blog.id, author_id=author.id)
    old_post = await create_post(db_session, category_id=blog.id, author_id=author.id)
    thread = await create_thread(db_session, category_id=forum.id, author_id=author.id)
    # The factories set ``published_at`` to the current time.
    post.published_at = inside
    old_post.published_at = outside
    thread.published_at = inside
    await create_reply(db_session, thread_id=thread.id, author_id=author.id, created_at=inside)
    await create_reply(db_session, thread_id=thread.id, author_id=author.id, created_at=outside)
    await create_reply(
        db_session,
        thread_id=thread.id,
        author_id=author.id,
        created_at=inside,
        status=ContentStatus.HIDDEN,
    )
    await create_comment(db_session, post_id=post.id, author_id=author.id, created_at=inside)

    data = await build_admin_digest(db_session, now=NOW)

    assert data.published == {"posts": 1, "threads": 1, "replies": 1, "comments": 1}


# --- recipients -------------------------------------------------------------------------------


async def test_recipients_are_active_verified_admins_who_want_it(db_session, outbox) -> None:
    await _clear_queue(db_session)
    admin = await create_admin(db_session)
    superadmin = await create_superadmin(db_session)
    await create_verified_user(db_session)  # member
    await create_user(db_session, role=UserRole.ADMIN)  # unverified admin
    await create_admin(db_session, is_active=False)  # banned admin
    gone = await create_admin(db_session)
    gone.deleted_at = NOW
    opted_out = await create_admin(db_session)
    await _set_prefs(db_session, opted_out, admin_digest=False)
    author = await create_verified_user(db_session)
    await _pending_post(db_session, author=author)

    run = await send_admin_digest(db_session, now=NOW)

    assert sorted(m.to for m in outbox) == sorted([admin.email, superadmin.email])
    assert run.recipients == 2


async def test_admin_without_preferences_row_gets_the_digest(db_session, outbox) -> None:
    await _clear_queue(db_session)
    admin = await create_admin(db_session)
    await db_session.execute(
        delete(NotificationPreference).where(NotificationPreference.user_id == admin.id)
    )
    db_session.expire_all()
    author = await create_verified_user(db_session)
    await _pending_post(db_session, author=author)

    await send_admin_digest(db_session, now=NOW)

    assert [m.to for m in outbox] == [admin.email]


async def test_weekly_recipient_only_on_monday(db_session, outbox) -> None:
    await _clear_queue(db_session)
    daily = await create_admin(db_session)
    weekly = await create_admin(db_session)
    await _set_prefs(db_session, weekly, digest_frequency=DigestFrequency.WEEKLY)
    author = await create_verified_user(db_session)
    await _pending_post(db_session, author=author)

    await send_admin_digest(db_session, now=NOW)  # Tuesday
    assert [m.to for m in outbox] == [daily.email]

    outbox.clear()
    await send_admin_digest(db_session, now=MONDAY + timedelta(days=7))
    assert sorted(m.to for m in outbox) == sorted([daily.email, weekly.email])


# --- sending ----------------------------------------------------------------------------------


async def test_nothing_to_report_sends_nothing_but_records_run(db_session, outbox) -> None:
    await _clear_queue(db_session)
    await create_admin(db_session)

    run = await send_admin_digest(db_session, now=NOW)

    assert outbox == []
    assert run is not None
    assert (run.recipients, run.items) == (0, 0)
    assert (run.window_start, run.window_end) == (NOW - timedelta(hours=24), NOW)
    assert [r.id for r in await _runs(db_session)] == [run.id]


async def test_run_without_items_advances_the_window(db_session, outbox) -> None:
    await _clear_queue(db_session)
    await create_admin(db_session)

    first = await send_admin_digest(db_session, now=NOW)
    later = NOW + timedelta(days=1)
    data = await build_admin_digest(db_session, now=later)

    assert data.window_start == first.window_end == NOW


async def test_force_sends_even_without_items(db_session, outbox) -> None:
    await _clear_queue(db_session)
    admin = await create_admin(db_session)

    run = await send_admin_digest(db_session, now=NOW, force=True)

    assert [m.to for m in outbox] == [admin.email]
    assert (run.recipients, run.items) == (1, 0)
    msg = outbox[0]
    assert "Moderation digest: 0 pending, 0 reports" in msg.subject
    assert "Nothing is waiting for review." in msg.text
    assert "No open reports." in msg.text
    assert "Nothing is waiting for review." in msg.html


async def test_digest_run_fields(db_session, outbox) -> None:
    await _clear_queue(db_session)
    await create_admin(db_session)
    await create_admin(db_session)
    author = await create_verified_user(db_session)
    post = await _pending_post(db_session, author=author)
    for _ in range(2):
        reporter = await create_verified_user(db_session)
        await create_report(db_session, reporter_id=reporter.id, content_id=post.id)

    run = await send_admin_digest(db_session, now=NOW)

    stored = await _runs(db_session)
    assert [r.id for r in stored] == [run.id]
    assert run.kind == "admin_daily"
    assert run.ran_at == NOW
    assert run.window_start == NOW - timedelta(hours=24)
    assert run.window_end == NOW
    assert run.recipients == 2
    assert run.items == 3


async def test_subject_carries_counts(db_session, outbox) -> None:
    await _clear_queue(db_session)
    await create_admin(db_session)
    author = await create_verified_user(db_session)
    first = await _pending_post(db_session, author=author)
    await _pending_post(db_session, author=author)
    reporter = await create_verified_user(db_session)
    await create_report(db_session, reporter_id=reporter.id, content_id=first.id)

    await send_admin_digest(db_session, now=NOW)

    assert outbox[0].subject == (
        "[URBANFLOODS Cooperation] Moderation digest: 2 pending, 1 reports"
    )


async def test_email_lists_pending_items_reports_and_links(db_session, outbox) -> None:
    from app.core.config import settings

    await _clear_queue(db_session)
    await create_admin(db_session, display_name="Ada Admin")
    author = await create_verified_user(db_session, display_name="Penny Pending")
    post = await _pending_post(db_session, author=author, title="Rain gardens <for> all")
    reporter = await create_verified_user(db_session)
    await create_report(
        db_session, reporter_id=reporter.id, content_id=post.id, reason="misinformation"
    )

    await send_admin_digest(db_session, now=NOW)

    msg = outbox[0]
    frontend = settings.FRONTEND_URL.rstrip("/")
    assert "Ada Admin" in msg.text
    assert "Rain gardens <for> all" in msg.text
    assert "Rain gardens &lt;for&gt; all" in msg.html
    assert "Penny Pending" in msg.text
    assert "misinformation" in msg.text
    assert f"post #{post.id}" in msg.text
    assert f"{frontend}/admin/queue" in msg.text
    assert f"{frontend}/admin/reports" in msg.text
    assert f'href="{frontend}/admin/queue"' in msg.html
    assert f'href="{frontend}/admin/reports"' in msg.html
    assert "No open reports." not in msg.text


async def test_email_per_recipient_locale(db_session, outbox, monkeypatch) -> None:
    await _clear_queue(db_session)
    greek = await create_admin(db_session, locale="el")
    english = await create_admin(db_session)
    author = await create_verified_user(db_session)
    await _pending_post(db_session, author=author)
    calls: list[dict] = []
    real_send = digest_service.email_service.send_email

    async def spy(**kwargs):
        calls.append(kwargs)
        return await real_send(**kwargs)

    monkeypatch.setattr(digest_service.email_service, "send_email", spy)

    await send_admin_digest(db_session, now=NOW)

    locales = {call["to"]: call["locale"] for call in calls}
    assert locales == {greek.email: "el", english.email: "en"}
    assert all(call["template"] == "admin_digest" for call in calls)
    # No Greek template yet: English is used.
    assert {m.locale for m in outbox} == {"en"}


async def test_link_context_is_frontend_paths(db_session, outbox, monkeypatch) -> None:
    await _clear_queue(db_session)
    await create_admin(db_session)
    calls: list[dict] = []

    async def fake_send(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(digest_service.email_service, "send_email", fake_send)

    await send_admin_digest(db_session, now=NOW, force=True)

    context = calls[0]["context"]
    assert context["queue_url"] == "/admin/queue"
    assert context["reports_url"] == "/admin/reports"
    assert context["settings_url"].startswith("/account")


async def test_failed_send_is_logged_without_address_and_skipped(
    db_session, outbox, monkeypatch
) -> None:
    await _clear_queue(db_session)
    bad = await create_admin(db_session)
    good = await create_admin(db_session)
    real_send = digest_service.email_service.send_email

    async def flaky(**kwargs):
        if kwargs["to"] == bad.email:
            raise ConnectionError(f"cannot reach {bad.email}")
        return await real_send(**kwargs)

    monkeypatch.setattr(digest_service.email_service, "send_email", flaky)

    with structlog.testing.capture_logs() as logs:
        run = await send_admin_digest(db_session, now=NOW, force=True)

    assert [m.to for m in outbox] == [good.email]
    assert run.recipients == 1
    failed = [e for e in logs if e["event"] == "digest.failed"]
    assert len(failed) == 1
    assert failed[0]["recipient_id"] == bad.id
    assert failed[0]["error"] == "ConnectionError"
    assert bad.email not in repr(logs)


async def test_logs_never_contain_addresses(db_session, outbox) -> None:
    await _clear_queue(db_session)
    admin = await create_admin(db_session)
    author = await create_verified_user(db_session)
    await _pending_post(db_session, author=author)

    with structlog.testing.capture_logs() as logs:
        await send_admin_digest(db_session, now=NOW)

    sent = [e for e in logs if e["event"] == "digest.sent"]
    assert len(sent) == 1
    assert sent[0]["recipients"] == 1
    assert sent[0]["items"] == 1
    assert admin.email not in repr(logs)


async def test_default_now_is_current_time(db_session, outbox) -> None:
    await _clear_queue(db_session)
    before = datetime.now(UTC)

    run = await send_admin_digest(db_session)

    assert before <= run.window_end <= datetime.now(UTC)


@pytest.mark.parametrize("pending", [0, 1])
async def test_force_flag_matters_only_without_items(db_session, outbox, pending) -> None:
    await _clear_queue(db_session)
    await create_admin(db_session)
    author = await create_verified_user(db_session)
    for _ in range(pending):
        await _pending_post(db_session, author=author)

    await send_admin_digest(db_session, now=NOW, force=False)

    assert len(outbox) == pending


async def test_weekly_recipient_gets_a_seven_day_window(db_session, outbox) -> None:
    await _clear_queue(db_session)
    monday = MONDAY + timedelta(days=7)
    daily = await create_admin(db_session)
    weekly = await create_admin(db_session)
    await _set_prefs(db_session, weekly, digest_frequency=DigestFrequency.WEEKLY)
    for age in (timedelta(hours=3), timedelta(days=3), timedelta(days=6)):
        await create_user(db_session, created_at=monday - age)
    await create_user(db_session, created_at=monday - timedelta(days=8))  # before both windows
    author = await create_verified_user(db_session, created_at=monday - timedelta(days=30))
    await _pending_post(db_session, author=author)

    run = await send_admin_digest(db_session, now=monday)

    texts = {m.to: m.text for m in outbox}
    assert "New members: 1" in texts[daily.email]
    assert "New members: 3" in texts[weekly.email]
    assert "2020-06-07 06:00 UTC" in texts[daily.email]
    assert "2020-06-01 06:00 UTC" in texts[weekly.email]
    # The recorded run is the daily window.
    assert run.window_start == monday - timedelta(hours=24)


async def test_weekly_build_skipped_without_weekly_recipients(
    db_session, outbox, monkeypatch
) -> None:
    await _clear_queue(db_session)
    await create_admin(db_session)
    author = await create_verified_user(db_session)
    await _pending_post(db_session, author=author)
    calls = []
    real_build = digest_service.build_admin_digest

    async def spy(db, **kwargs):
        calls.append(kwargs)
        return await real_build(db, **kwargs)

    monkeypatch.setattr(digest_service, "build_admin_digest", spy)

    await send_admin_digest(db_session, now=MONDAY)

    assert len(calls) == 1


class _RaisingBackend:
    async def send(self, msg) -> None:
        raise ConnectionError("smtp refused")


async def test_all_sends_failed_records_no_run(db_session, monkeypatch) -> None:
    from app.services import email as email_service

    await _clear_queue(db_session)
    admin = await create_admin(db_session)
    await create_admin(db_session)
    author = await create_verified_user(db_session)
    await _pending_post(db_session, author=author)
    monkeypatch.setattr(email_service, "_backend", _RaisingBackend())

    with structlog.testing.capture_logs() as logs:
        run = await send_admin_digest(db_session, now=NOW)

    assert run is None
    assert await _runs(db_session) == []
    failed_all = [e for e in logs if e["event"] == "digest.failed_all"]
    assert len(failed_all) == 1
    assert (failed_all[0]["recipients"], failed_all[0]["items"]) == (2, 1)
    assert admin.email not in repr(logs)
    # The window is retried on the next run.
    later = await build_admin_digest(db_session, now=NOW + timedelta(hours=1))
    assert later.window_start == NOW + timedelta(hours=1) - timedelta(hours=24)

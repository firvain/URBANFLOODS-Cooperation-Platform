"""Increment 4c: reports - members report published content (counted towards the auto-hide at
``REPORT_AUTO_HIDE_THRESHOLD`` distinct open reporters); admins list, inspect, resolve and dismiss
them.

Every test works in fresh categories (``cleanup_forum_categories`` removes the threads, then
``cleanup_categories`` the posts; replies and comments cascade). Reports on the test's content and
the audit rows about that content or those reports go with the local ``tracked`` fixture; audit
rows by the test's users go with ``cleanup_users``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, or_, select, update

from app.core import rate_limit
from app.core.config import settings
from app.crud import reports as crud_reports
from app.db.enums import (
    CategoryKind,
    ContentStatus,
    ContentType,
    HiddenReason,
    ReportReason,
    ReportStatus,
)
from app.db.models import AuditLog, Post, Report, User
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
    login_as,
)

API = settings.API_V1_PREFIX
REPORTS = f"{API}/reports/"
PUB = ContentStatus.PUBLISHED
ALL_TYPES = list(ContentType)
CREATED_FIELDS = {
    "id",
    "content_type",
    "content_id",
    "reason",
    "status",
    "created_at",
    "auto_hidden",
}
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


# --- fixtures and helpers ---------------------------------------------------------------------


@pytest.fixture
def limits(monkeypatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    rate_limit.reset()
    yield
    rate_limit.reset()


@pytest.fixture
async def tracked(database_url: str) -> AsyncIterator[set[tuple[ContentType, int]]]:
    """``(content_type, id)`` of content the test commits: its reports, and the audit rows about
    it or about those reports, are deleted afterwards (nothing cascades: both are polymorphic)."""
    from app.db.session import AsyncSessionLocal

    items: set[tuple[ContentType, int]] = set()
    yield items
    if not items:
        return
    async with AsyncSessionLocal() as session, session.begin():
        for content_type, content_id in items:
            report_ids = list(
                (
                    await session.scalars(
                        select(Report.id).where(
                            Report.content_type == content_type, Report.content_id == content_id
                        )
                    )
                ).all()
            )
            await session.execute(
                delete(AuditLog).where(
                    or_(
                        (AuditLog.target_type == content_type.value)
                        & (AuditLog.target_id == content_id),
                        (AuditLog.target_type == "report") & AuditLog.target_id.in_(report_ids),
                    )
                )
            )
            await session.execute(delete(Report).where(Report.id.in_(report_ids)))


class Ctx:
    """Committed users and content for one test."""

    def __init__(self, db, users: set[str], categories: set[int], tracked: set) -> None:
        self.db = db
        self._users = users
        self._categories = categories
        self._tracked = tracked

    async def user(self, factory=create_verified_user, **kwargs: Any) -> User:
        user = await factory(self.db, **kwargs)
        self._users.add(user.email)
        await self.db.commit()
        return user

    async def admin(self) -> User:
        return await self.user(create_admin)

    async def _category(self, kind: CategoryKind):
        category = await create_category(self.db, kind=kind)
        self._categories.add(category.id)
        return category

    async def content(
        self,
        content_type: ContentType,
        status: ContentStatus = PUB,
        *,
        author: User | None = None,
        **kwargs: Any,
    ):
        """A post/thread/reply/comment in ``status`` by ``author`` (a fresh member by default)."""
        if author is None:
            author = await self.user()
        extra: dict[str, Any] = dict(kwargs)
        if status == ContentStatus.HIDDEN:
            extra["hidden_reason"] = HiddenReason.ADMIN
        if status == ContentStatus.DELETED:
            extra["deleted_at"] = T0
        db = self.db
        if content_type in (ContentType.POST, ContentType.COMMENT):
            category = await self._category(CategoryKind.BLOG)
            if content_type == ContentType.POST:
                obj = await create_post(
                    db, category_id=category.id, status=status, author_id=author.id, **extra
                )
            else:
                post = await create_post(db, category_id=category.id)
                obj = await create_comment(
                    db, post_id=post.id, status=status, author_id=author.id, **extra
                )
        else:
            category = await self._category(CategoryKind.FORUM)
            if content_type == ContentType.THREAD:
                obj = await create_thread(
                    db, category_id=category.id, status=status, author_id=author.id, **extra
                )
            else:
                thread = await create_thread(db, category_id=category.id)
                obj = await create_reply(
                    db, thread_id=thread.id, status=status, author_id=author.id, **extra
                )
        await db.commit()
        self._tracked.add((content_type, obj.id))
        return obj

    async def report(self, content_type: ContentType, content_id: int, **kwargs: Any) -> Report:
        """A report row inserted directly (no counting)."""
        report = await create_report(
            self.db, content_type=content_type.value, content_id=content_id, **kwargs
        )
        await self.db.commit()
        return report


@pytest.fixture
async def ctx(db_session, cleanup_users, cleanup_forum_categories, tracked) -> Ctx:
    return Ctx(db_session, cleanup_users, cleanup_forum_categories, tracked)


async def _report(client, content_type: ContentType, content_id: int, **body: Any):
    payload = {"content_type": content_type.value, "content_id": content_id, "reason": "spam"}
    payload.update(body)
    return await client.post(REPORTS, json=payload)


async def _fresh(db, model, obj_id: int):
    """The row re-read from the database."""
    return await db.get(model, obj_id, populate_existing=True)


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


async def _audits(db, *, action: str, target_type: str, target_id: int) -> list[AuditLog]:
    stmt = select(AuditLog).where(
        AuditLog.action == action,
        AuditLog.target_type == target_type,
        AuditLog.target_id == target_id,
    )
    return list((await db.scalars(stmt.order_by(AuditLog.id))).all())


def _model(content_type: ContentType):
    from app.crud.moderation import MODELS

    return MODELS[content_type]


async def _report_as(client, other_client, ctx: Ctx, content, content_type, n: int) -> list:
    """``n`` distinct fresh members report ``content`` in turn; returns the responses."""
    responses = []
    for _ in range(n):
        reporter = await ctx.user()
        other_client.cookies.clear()
        await login_as(other_client, reporter)
        responses.append(await _report(other_client, content_type, content.id))
    return responses


# --- create -----------------------------------------------------------------------------------


@pytest.mark.parametrize("content_type", ALL_TYPES)
async def test_member_reports_content(client, ctx, content_type):
    reporter = await ctx.user()
    content = await ctx.content(content_type)
    await login_as(client, reporter)

    response = await _report(client, content_type, content.id, reason="abuse")

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == CREATED_FIELDS
    assert body["content_type"] == content_type.value
    assert body["content_id"] == content.id
    assert body["reason"] == "abuse"
    assert body["status"] == "open"
    assert body["auto_hidden"] is False
    report = await _fresh(ctx.db, Report, body["id"])
    assert report.reporter_id == reporter.id
    fresh = await _fresh(ctx.db, _model(content_type), content.id)
    assert fresh.report_count == 1
    assert fresh.status == PUB


async def test_create_requires_login(client, ctx):
    content = await ctx.content(ContentType.POST)
    _assert_error(
        await _report(client, ContentType.POST, content.id), 401, "auth.not_authenticated"
    )


async def test_create_requires_verified_email(client, ctx):
    user = await ctx.user(create_user)
    content = await ctx.content(ContentType.POST)
    await login_as(client, user)
    _assert_error(
        await _report(client, ContentType.POST, content.id), 403, "auth.email_not_verified"
    )


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.REPLY])
async def test_cannot_report_own_content(client, ctx, content_type):
    user = await ctx.user()
    content = await ctx.content(content_type, author=user)
    await login_as(client, user)
    _assert_error(await _report(client, content_type, content.id), 400, "report.own_content")
    fresh = await _fresh(ctx.db, _model(content_type), content.id)
    assert fresh.report_count == 0


async def test_duplicate_report_conflicts(client, ctx):
    reporter = await ctx.user()
    content = await ctx.content(ContentType.THREAD)
    await login_as(client, reporter)
    assert (await _report(client, ContentType.THREAD, content.id)).status_code == 201

    _assert_error(
        await _report(client, ContentType.THREAD, content.id, reason="abuse"),
        409,
        "report.already_reported",
    )
    fresh = await _fresh(ctx.db, _model(ContentType.THREAD), content.id)
    assert fresh.report_count == 1


@pytest.mark.parametrize(
    ("content_type", "status"),
    [
        (ContentType.POST, ContentStatus.PENDING),
        (ContentType.POST, ContentStatus.HIDDEN),
        (ContentType.POST, ContentStatus.DELETED),
        (ContentType.THREAD, ContentStatus.PENDING),
        (ContentType.REPLY, ContentStatus.HIDDEN),
        (ContentType.COMMENT, ContentStatus.DELETED),
    ],
)
async def test_cannot_report_unpublished_content(client, ctx, content_type, status):
    reporter = await ctx.user()
    content = await ctx.content(content_type, status)
    await login_as(client, reporter)
    _assert_error(await _report(client, content_type, content.id), 404, "report.content_not_found")


async def test_cannot_report_own_pending_content_either(client, ctx):
    """An author sees their own pending post, but it is not reportable: 404, not 400."""
    user = await ctx.user()
    content = await ctx.content(ContentType.POST, ContentStatus.PENDING, author=user)
    await login_as(client, user)
    _assert_error(
        await _report(client, ContentType.POST, content.id), 404, "report.content_not_found"
    )


@pytest.mark.parametrize("content_type", ALL_TYPES)
async def test_unknown_content_is_404(client, ctx, content_type):
    reporter = await ctx.user()
    await login_as(client, reporter)
    _assert_error(await _report(client, content_type, 2**31 - 2), 404, "report.content_not_found")


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
async def test_out_of_range_integer_id_is_404(client, ctx, content_type):
    """Posts and threads have INTEGER ids; 2**31 is not found, not a database error."""
    reporter = await ctx.user()
    await login_as(client, reporter)
    _assert_error(await _report(client, content_type, 2**31), 404, "report.content_not_found")


async def test_other_integrity_errors_propagate(db_session, monkeypatch):
    """Only the one-report-per-reporter constraint becomes 409; anything else is re-raised."""
    from sqlalchemy.exc import IntegrityError

    category = await create_category(db_session)
    post = await create_post(db_session, category_id=category.id)
    reporter = await create_verified_user(db_session)
    error = IntegrityError(
        "INSERT INTO reports ...",
        {},
        Exception('violates foreign key constraint "reports_reporter_id_fkey"'),
    )
    real_flush = db_session.flush

    async def failing_flush(*args, **kwargs):
        if any(isinstance(obj, Report) for obj in db_session.new):
            raise error
        return await real_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", failing_flush)
    with pytest.raises(IntegrityError) as exc:
        await crud_reports.create_report(
            db_session,
            reporter=reporter,
            content_type=ContentType.POST,
            content_id=post.id,
            reason=ReportReason.SPAM,
            details=None,
        )
    assert exc.value is error


async def test_unique_violation_race_becomes_409(db_session, monkeypatch):
    """A concurrent duplicate that slipped past the pre-check hits the constraint: 409."""
    from sqlalchemy.exc import IntegrityError

    from app.core.exceptions import AppError

    category = await create_category(db_session)
    post = await create_post(db_session, category_id=category.id)
    reporter = await create_verified_user(db_session)
    error = IntegrityError(
        "INSERT INTO reports ...",
        {},
        Exception('duplicate key value violates unique constraint "uq_reports_reporter_content"'),
    )
    real_flush = db_session.flush

    async def failing_flush(*args, **kwargs):
        if any(isinstance(obj, Report) for obj in db_session.new):
            raise error
        return await real_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", failing_flush)
    with pytest.raises(AppError) as exc:
        await crud_reports.create_report(
            db_session,
            reporter=reporter,
            content_type=ContentType.POST,
            content_id=post.id,
            reason=ReportReason.SPAM,
            details=None,
        )
    assert exc.value.status_code == 409
    assert exc.value.code == "report.already_reported"


async def test_details_are_trimmed_and_blank_becomes_null(client, ctx):
    first, second = await ctx.user(), await ctx.user()
    content = await ctx.content(ContentType.POST)

    await login_as(client, first)
    response = await _report(client, ContentType.POST, content.id, details="  spam link  ")
    assert response.status_code == 201, response.text
    assert (await _fresh(ctx.db, Report, response.json()["id"])).details == "spam link"

    client.cookies.clear()
    await login_as(client, second)
    response = await _report(client, ContentType.POST, content.id, details="   \n ")
    assert response.status_code == 201, response.text
    assert (await _fresh(ctx.db, Report, response.json()["id"])).details is None


async def test_details_length_limit(client, ctx):
    reporter = await ctx.user()
    content = await ctx.content(ContentType.POST)
    await login_as(client, reporter)

    response = await _report(client, ContentType.POST, content.id, details="x" * 1001)
    assert response.status_code == 422, response.text
    assert "details" in response.json()["detail"]["fields"]

    response = await _report(client, ContentType.POST, content.id, details=" " + "x" * 1000 + " ")
    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    "body",
    [
        {"reason": "nonsense"},
        {"content_type": "user"},
        {"content_id": 0},
        {"content_id": "abc"},
    ],
)
async def test_create_validation(client, ctx, body):
    reporter = await ctx.user()
    content = await ctx.content(ContentType.POST)
    await login_as(client, reporter)
    payload = {"content_type": "post", "content_id": content.id, "reason": "spam", **body}
    response = await client.post(REPORTS, json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "validation.failed"


async def test_create_writes_audit_without_details(client, ctx):
    reporter = await ctx.user()
    content = await ctx.content(ContentType.COMMENT)
    await login_as(client, reporter)

    response = await _report(
        client, ContentType.COMMENT, content.id, reason="misinformation", details="secret words"
    )
    assert response.status_code == 201, response.text

    rows = await _audits(
        ctx.db, action="report.create", target_type="report", target_id=response.json()["id"]
    )
    assert len(rows) == 1
    assert rows[0].actor_id == reporter.id
    assert rows[0].metadata_ == {
        "content_type": "comment",
        "content_id": content.id,
        "reason": "misinformation",
    }
    assert "secret words" not in str(rows[0].metadata_)


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.REPLY])
async def test_third_distinct_reporter_auto_hides(
    client, other_client, ctx, monkeypatch, content_type
):
    monkeypatch.setattr(settings, "REPORT_AUTO_HIDE_THRESHOLD", 3)
    content = await ctx.content(content_type)

    responses = await _report_as(client, other_client, ctx, content, content_type, 2)
    assert [r.status_code for r in responses] == [201, 201]
    assert [r.json()["auto_hidden"] for r in responses] == [False, False]
    fresh = await _fresh(ctx.db, _model(content_type), content.id)
    assert fresh.status == PUB
    assert fresh.report_count == 2

    [third] = await _report_as(client, other_client, ctx, content, content_type, 1)
    assert third.status_code == 201, third.text
    assert third.json()["auto_hidden"] is True
    fresh = await _fresh(ctx.db, _model(content_type), content.id)
    assert fresh.status == ContentStatus.HIDDEN
    assert fresh.hidden_reason == HiddenReason.AUTO_REPORTS
    assert fresh.report_count == 3
    rows = await _audits(
        ctx.db,
        action="moderation.auto_hidden",
        target_type=content_type.value,
        target_id=content.id,
    )
    assert len(rows) == 1
    assert rows[0].actor_id is None


async def test_threshold_setting_is_respected(client, other_client, ctx, monkeypatch):
    monkeypatch.setattr(settings, "REPORT_AUTO_HIDE_THRESHOLD", 2)
    content = await ctx.content(ContentType.THREAD)

    responses = await _report_as(client, other_client, ctx, content, ContentType.THREAD, 2)
    assert [r.json()["auto_hidden"] for r in responses] == [False, True]
    fresh = await _fresh(ctx.db, _model(ContentType.THREAD), content.id)
    assert fresh.status == ContentStatus.HIDDEN


async def test_auto_hidden_content_cannot_be_reported_further(
    client, other_client, ctx, monkeypatch
):
    monkeypatch.setattr(settings, "REPORT_AUTO_HIDE_THRESHOLD", 1)
    content = await ctx.content(ContentType.POST)
    [first] = await _report_as(client, other_client, ctx, content, ContentType.POST, 1)
    assert first.json()["auto_hidden"] is True

    [second] = await _report_as(client, other_client, ctx, content, ContentType.POST, 1)
    _assert_error(second, 404, "report.content_not_found")


async def test_anonymised_reporters_do_not_count(client, ctx, monkeypatch):
    monkeypatch.setattr(settings, "REPORT_AUTO_HIDE_THRESHOLD", 3)
    content = await ctx.content(ContentType.POST)
    await ctx.report(ContentType.POST, content.id, reporter_id=None)
    await ctx.report(ContentType.POST, content.id, reporter_id=None)

    reporter = await ctx.user()
    await login_as(client, reporter)
    response = await _report(client, ContentType.POST, content.id)

    assert response.status_code == 201, response.text
    assert response.json()["auto_hidden"] is False
    fresh = await _fresh(ctx.db, _model(ContentType.POST), content.id)
    assert fresh.status == PUB
    assert fresh.report_count == 1


async def test_closed_reports_do_not_count(client, ctx, monkeypatch):
    monkeypatch.setattr(settings, "REPORT_AUTO_HIDE_THRESHOLD", 2)
    admin = await ctx.admin()
    content = await ctx.content(ContentType.POST)
    old = await ctx.user()
    await ctx.report(
        ContentType.POST,
        content.id,
        reporter_id=old.id,
        status=ReportStatus.DISMISSED,
        resolved_by=admin.id,
        resolved_at=T0,
    )

    reporter = await ctx.user()
    await login_as(client, reporter)
    response = await _report(client, ContentType.POST, content.id)

    assert response.json()["auto_hidden"] is False
    fresh = await _fresh(ctx.db, _model(ContentType.POST), content.id)
    assert fresh.report_count == 1
    assert fresh.status == PUB


async def test_create_rate_limited(client, ctx, limits):
    reporter = await ctx.user()
    content = await ctx.content(ContentType.POST)
    await login_as(client, reporter)

    # Rejected requests count too.
    statuses = [(await client.post(REPORTS, json={})).status_code for _ in range(20)]
    assert statuses == [422] * 20

    response = await _report(client, ContentType.POST, content.id)
    _assert_error(response, 429, "rate.limited")
    assert int(response.headers["Retry-After"]) >= 1


# --- admin: permissions -----------------------------------------------------------------------


async def _admin_requests(client, report_id: int) -> list:
    return [
        await client.get(REPORTS),
        await client.get(f"{REPORTS}{report_id}"),
        await client.post(f"{REPORTS}{report_id}/resolve"),
        await client.post(f"{REPORTS}{report_id}/dismiss"),
    ]


async def test_admin_endpoints_need_login(client, ctx):
    content = await ctx.content(ContentType.POST)
    reporter = await ctx.user()
    report = await ctx.report(ContentType.POST, content.id, reporter_id=reporter.id)
    for response in await _admin_requests(client, report.id):
        _assert_error(response, 401, "auth.not_authenticated")


async def test_admin_endpoints_forbid_members(client, ctx):
    content = await ctx.content(ContentType.POST)
    reporter = await ctx.user()
    report = await ctx.report(ContentType.POST, content.id, reporter_id=reporter.id)
    await login_as(client, reporter)
    for response in await _admin_requests(client, report.id):
        _assert_error(response, 403, "auth.forbidden")
    assert (await _fresh(ctx.db, Report, report.id)).status == ReportStatus.OPEN


@pytest.mark.parametrize("factory", [create_admin, create_superadmin])
async def test_admins_and_superadmins_may_list_and_get(client, ctx, factory):
    staff = await ctx.user(factory)
    content = await ctx.content(ContentType.POST)
    reporter = await ctx.user()
    report = await ctx.report(ContentType.POST, content.id, reporter_id=reporter.id)
    await login_as(client, staff)

    listing = await client.get(REPORTS, params={"limit": 200})
    assert listing.status_code == 200, listing.text
    assert report.id in [item["id"] for item in listing.json()["items"]]
    detail = await client.get(f"{REPORTS}{report.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == report.id


@pytest.mark.parametrize("factory", [create_admin, create_superadmin])
@pytest.mark.parametrize("action", ["resolve", "dismiss"])
async def test_admins_and_superadmins_may_close(client, ctx, factory, action):
    staff = await ctx.user(factory)
    content = await ctx.content(ContentType.POST)
    reporter = await ctx.user()
    report = await ctx.report(ContentType.POST, content.id, reporter_id=reporter.id)
    await login_as(client, staff)

    response = await client.post(f"{REPORTS}{report.id}/{action}")
    assert response.status_code == 200, response.text


# --- admin: list ------------------------------------------------------------------------------


async def test_list_filters_and_orders_newest_first(client, ctx):
    admin = await ctx.admin()
    before = {
        status: (await crud_reports.list_reports(ctx.db, status=status, limit=1))[0]
        for status in ReportStatus
    }
    post = await ctx.content(ContentType.POST)
    reply = await ctx.content(ContentType.REPLY)
    a, b, c, d = await ctx.user(), await ctx.user(), await ctx.user(), await ctx.user()
    dismissed = await ctx.report(
        ContentType.REPLY,
        reply.id,
        reporter_id=d.id,
        created_at=T0 - timedelta(days=4),
        status=ReportStatus.DISMISSED,
        resolved_by=admin.id,
        resolved_at=T0,
    )
    oldest = await ctx.report(
        ContentType.POST, post.id, reporter_id=a.id, created_at=T0 - timedelta(days=3)
    )
    resolved = await ctx.report(
        ContentType.POST,
        post.id,
        reporter_id=b.id,
        created_at=T0 - timedelta(days=2),
        status=ReportStatus.RESOLVED,
        resolved_by=admin.id,
        resolved_at=T0,
    )
    newest = await ctx.report(
        ContentType.REPLY, reply.id, reporter_id=c.id, created_at=T0 - timedelta(days=1)
    )
    mine = {dismissed.id, oldest.id, resolved.id, newest.id}
    await login_as(client, admin)

    async def page(**params) -> dict:
        response = await client.get(REPORTS, params={"limit": 200, **params})
        assert response.status_code == 200, response.text
        return response.json()

    async def ids(**params) -> list[int]:
        return [item["id"] for item in (await page(**params))["items"] if item["id"] in mine]

    assert await ids() == [newest.id, resolved.id, oldest.id, dismissed.id]
    assert await ids(status="open") == [newest.id, oldest.id]
    assert await ids(status="resolved") == [resolved.id]
    assert await ids(status="dismissed") == [dismissed.id]
    assert await ids(content_type="post") == [resolved.id, oldest.id]
    assert await ids(content_type="reply", status="open") == [newest.id]
    assert await ids(content_type="comment") == []

    assert (await page(status="open"))["total"] == before[ReportStatus.OPEN] + 2
    assert (await page(status="resolved"))["total"] == before[ReportStatus.RESOLVED] + 1
    assert (await page(status="dismissed"))["total"] == before[ReportStatus.DISMISSED] + 1


async def test_list_pagination_and_total(client, ctx):
    admin = await ctx.admin()
    post = await ctx.content(ContentType.POST)
    for _ in range(3):
        reporter = await ctx.user()
        await ctx.report(ContentType.POST, post.id, reporter_id=reporter.id)
    await login_as(client, admin)

    full = (await client.get(REPORTS, params={"limit": 200})).json()
    page = await client.get(REPORTS, params={"skip": 1, "limit": 2})
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["total"] == full["total"] >= 3
    assert [i["id"] for i in body["items"]] == [i["id"] for i in full["items"][1:3]]


@pytest.mark.parametrize("params", [{"status": "bogus"}, {"content_type": "user"}, {"limit": 0}])
async def test_list_validation(client, ctx, params):
    admin = await ctx.admin()
    await login_as(client, admin)
    response = await client.get(REPORTS, params=params)
    assert response.status_code == 422, response.text


async def test_list_item_shape_with_reporter_and_resolver(client, ctx):
    admin = await ctx.admin()
    reporter = await ctx.user(display_name="Rita Reporter")
    post = await ctx.content(ContentType.POST)
    report = await ctx.report(
        ContentType.POST,
        post.id,
        reporter_id=reporter.id,
        reason="abuse",
        details="Insulting language",
        status=ReportStatus.RESOLVED,
        resolved_by=admin.id,
        resolved_at=T0,
    )
    anonymous = await ctx.report(ContentType.POST, post.id, reporter_id=None)
    await login_as(client, admin)

    body = (await client.get(f"{REPORTS}{report.id}")).json()
    assert body["reason"] == "abuse"
    assert body["details"] == "Insulting language"
    assert body["status"] == "resolved"
    assert body["reporter"] == {"id": reporter.id, "display_name": "Rita Reporter"}
    assert body["resolver"]["id"] == admin.id
    assert body["resolved_at"] is not None
    assert body["created_at"] is not None

    body = (await client.get(f"{REPORTS}{anonymous.id}")).json()
    assert body["reporter"] is None
    assert body["resolver"] is None
    assert body["resolved_at"] is None


async def test_content_summary_for_each_type(client, ctx):
    admin = await ctx.admin()
    reporter = await ctx.user()
    contents = {ct: await ctx.content(ct) for ct in ALL_TYPES}
    reports = {
        ct: await ctx.report(ct, obj.id, reporter_id=reporter.id) for ct, obj in contents.items()
    }
    await login_as(client, admin)

    listing = (await client.get(REPORTS, params={"limit": 200})).json()
    by_id = {item["id"]: item for item in listing["items"]}

    for ct, obj in contents.items():
        summary = by_id[reports[ct].id]["content"]
        assert summary["type"] == ct.value
        assert summary["id"] == obj.id
        assert summary["status"] == "published"
        assert summary["author_id"] == obj.author_id
        assert summary["excerpt"] == obj.body_text[:160]

    post, thread = contents[ContentType.POST], contents[ContentType.THREAD]
    assert by_id[reports[ContentType.POST].id]["content"]["title"] == post.title
    assert by_id[reports[ContentType.POST].id]["content"]["url_slug"] == post.slug
    assert by_id[reports[ContentType.THREAD].id]["content"]["title"] == thread.title
    assert by_id[reports[ContentType.THREAD].id]["content"]["url_slug"] == thread.slug

    reply, comment = contents[ContentType.REPLY], contents[ContentType.COMMENT]
    reply_summary = by_id[reports[ContentType.REPLY].id]["content"]
    comment_summary = by_id[reports[ContentType.COMMENT].id]["content"]
    assert reply_summary["title"] is None
    assert comment_summary["title"] is None
    # Replies and comments link through their thread / post.
    parent_thread = await _fresh(ctx.db, _model(ContentType.THREAD), reply.thread_id)
    parent_post = await _fresh(ctx.db, _model(ContentType.POST), comment.post_id)
    assert reply_summary["url_slug"] == parent_thread.slug
    assert comment_summary["url_slug"] == parent_post.slug


async def test_content_summary_excerpt_is_cut(client, ctx):
    admin = await ctx.admin()
    reporter = await ctx.user()
    thread = await ctx.content(ContentType.THREAD, body_text="word " * 100)
    report = await ctx.report(ContentType.THREAD, thread.id, reporter_id=reporter.id)
    await login_as(client, admin)

    summary = (await client.get(f"{REPORTS}{report.id}")).json()["content"]
    assert len(summary["excerpt"]) <= 160
    assert summary["excerpt"].startswith("word word")


async def test_content_summary_of_deleted_content(client, ctx):
    admin = await ctx.admin()
    reporter = await ctx.user()
    post = await ctx.content(ContentType.POST, ContentStatus.DELETED)
    report = await ctx.report(ContentType.POST, post.id, reporter_id=reporter.id)
    await login_as(client, admin)

    summary = (await client.get(f"{REPORTS}{report.id}")).json()["content"]
    assert summary["status"] == "deleted"
    assert summary["title"] == post.title


async def test_content_summary_of_vanished_content_is_null(client, ctx):
    admin = await ctx.admin()
    reporter = await ctx.user()
    report = await ctx.report(ContentType.COMMENT, 2**31 - 3, reporter_id=reporter.id)
    ctx._tracked.add((ContentType.COMMENT, 2**31 - 3))
    await login_as(client, admin)

    body = (await client.get(f"{REPORTS}{report.id}")).json()
    assert body["content"] is None


async def test_get_unknown_report_is_404(client, ctx):
    admin = await ctx.admin()
    await login_as(client, admin)
    _assert_error(await client.get(f"{REPORTS}{2**62}"), 404, "report.not_found")
    _assert_error(await client.post(f"{REPORTS}{2**62}/resolve"), 404, "report.not_found")
    _assert_error(await client.post(f"{REPORTS}{2**62}/dismiss"), 404, "report.not_found")


# --- admin: resolve / dismiss -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "status"),
    [("resolve", ReportStatus.RESOLVED), ("dismiss", ReportStatus.DISMISSED)],
)
async def test_close_sets_fields_audits_and_recounts(client, other_client, ctx, action, status):
    admin = await ctx.admin()
    content = await ctx.content(ContentType.REPLY)
    responses = await _report_as(client, other_client, ctx, content, ContentType.REPLY, 2)
    report_id = responses[0].json()["id"]
    assert (await _fresh(ctx.db, _model(ContentType.REPLY), content.id)).report_count == 2
    await login_as(client, admin)

    response = await client.post(f"{REPORTS}{report_id}/{action}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == status.value
    assert body["resolver"]["id"] == admin.id
    assert body["resolved_at"] is not None
    assert body["content"]["id"] == content.id
    report = await _fresh(ctx.db, Report, report_id)
    assert report.status == status
    assert report.resolved_by == admin.id
    assert report.resolved_at is not None
    assert (await _fresh(ctx.db, _model(ContentType.REPLY), content.id)).report_count == 1
    rows = await _audits(
        ctx.db, action=f"report.{action}", target_type="report", target_id=report_id
    )
    assert len(rows) == 1
    assert rows[0].actor_id == admin.id
    assert rows[0].metadata_ == {"content_type": "reply", "content_id": content.id}


async def test_close_report_on_soft_deleted_content(client, other_client, ctx):
    admin = await ctx.admin()
    content = await ctx.content(ContentType.POST)
    [created] = await _report_as(client, other_client, ctx, content, ContentType.POST, 1)
    await ctx.db.execute(
        update(Post)
        .where(Post.id == content.id)
        .values(status=ContentStatus.DELETED, deleted_at=T0)
    )
    await ctx.db.commit()
    await login_as(client, admin)

    response = await client.post(f"{REPORTS}{created.json()['id']}/resolve")
    assert response.status_code == 200, response.text
    assert response.json()["content"]["status"] == "deleted"
    assert (await _fresh(ctx.db, Post, content.id)).report_count == 0
    _assert_error(
        await client.post(f"{REPORTS}{created.json()['id']}/dismiss"), 409, "report.not_open"
    )


@pytest.mark.parametrize("action", ["resolve_report", "dismiss_report"])
async def test_close_rereads_the_report_under_lock(db_session, action):
    """A report closed by someone else after it was loaded is not closed again: 409."""
    from app.core.exceptions import AppError

    category = await create_category(db_session)
    post = await create_post(db_session, category_id=category.id)
    reporter = await create_verified_user(db_session)
    admin = await create_admin(db_session)
    report = await create_report(db_session, reporter_id=reporter.id, content_id=post.id)
    await db_session.execute(
        update(Report)
        .where(Report.id == report.id)
        .values(status=ReportStatus.RESOLVED, resolved_by=admin.id, resolved_at=T0)
        .execution_options(synchronize_session=False)
    )
    assert report.status == ReportStatus.OPEN  # stale in memory

    with pytest.raises(AppError) as exc:
        await getattr(crud_reports, action)(db_session, report=report, actor=admin)
    assert exc.value.status_code == 409
    assert exc.value.code == "report.not_open"


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("resolve", "resolve"),
        ("resolve", "dismiss"),
        ("dismiss", "dismiss"),
        ("dismiss", "resolve"),
    ],
)
async def test_close_twice_conflicts(client, ctx, first, second):
    admin = await ctx.admin()
    content = await ctx.content(ContentType.POST)
    reporter = await ctx.user()
    report = await ctx.report(ContentType.POST, content.id, reporter_id=reporter.id)
    await login_as(client, admin)

    assert (await client.post(f"{REPORTS}{report.id}/{first}")).status_code == 200
    _assert_error(await client.post(f"{REPORTS}{report.id}/{second}"), 409, "report.not_open")


async def test_close_report_on_vanished_content(client, ctx):
    admin = await ctx.admin()
    reporter = await ctx.user()
    report = await ctx.report(ContentType.THREAD, 2**31 - 4, reporter_id=reporter.id)
    ctx._tracked.add((ContentType.THREAD, 2**31 - 4))
    await login_as(client, admin)

    response = await client.post(f"{REPORTS}{report.id}/resolve")
    assert response.status_code == 200, response.text
    assert response.json()["content"] is None


async def test_dismissed_reporter_cannot_rereport_but_others_can(client, other_client, ctx):
    admin = await ctx.admin()
    first = await ctx.user()
    content = await ctx.content(ContentType.COMMENT)
    await login_as(client, first)
    report_id = (await _report(client, ContentType.COMMENT, content.id)).json()["id"]

    await login_as(other_client, admin)
    assert (await other_client.post(f"{REPORTS}{report_id}/dismiss")).status_code == 200
    assert (await _fresh(ctx.db, _model(ContentType.COMMENT), content.id)).report_count == 0

    _assert_error(
        await _report(client, ContentType.COMMENT, content.id), 409, "report.already_reported"
    )

    second = await ctx.user()
    client.cookies.clear()
    await login_as(client, second)
    response = await _report(client, ContentType.COMMENT, content.id)
    assert response.status_code == 201, response.text
    assert (await _fresh(ctx.db, _model(ContentType.COMMENT), content.id)).report_count == 1


# --- crud -------------------------------------------------------------------------------------


async def test_count_open(db_session):
    before = await crud_reports.count_open(db_session)
    category = await create_category(db_session)
    post = await create_post(db_session, category_id=category.id)
    a = await create_verified_user(db_session)
    b = await create_verified_user(db_session)
    admin = await create_admin(db_session)
    await create_report(db_session, reporter_id=a.id, content_id=post.id)
    await create_report(
        db_session,
        reporter_id=b.id,
        content_id=post.id,
        status=ReportStatus.RESOLVED,
        resolved_by=admin.id,
        resolved_at=T0,
    )
    await create_report(db_session, reporter_id=None, content_id=post.id)

    assert await crud_reports.count_open(db_session) == before + 2

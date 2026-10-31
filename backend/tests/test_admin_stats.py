"""Increment 4d: admin reporting - ``GET /admin/stats``, ``GET /admin/stats/export.csv`` and
``POST /admin/knowbase/cache/clear`` - and their permission matrix.

The overview numbers are global, so they are checked as differences against a baseline taken
in the same test. The CSV export is checked on a date range far in the past that only this
test's rows (with explicit ``created_at``) fall into. KNOWBASE is mocked with respx.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import respx
from sqlalchemy import select

from app.core.config import settings
from app.db.enums import CategoryKind, ContentStatus, HiddenReason, ReportStatus
from app.db.models import AuditLog, User
from tests.factories import (
    create_admin,
    create_category,
    create_comment,
    create_organisation,
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
STATS = f"{API}/admin/stats"
EXPORT = f"{API}/admin/stats/export.csv"
CACHE_CLEAR = f"{API}/admin/knowbase/cache/clear"
KB_BASE = "https://knowbase.test"
KB_API = f"{KB_BASE}/api/v1"

P = ContentStatus.PENDING
PUB = ContentStatus.PUBLISHED

# The export range used below, and instants inside / outside it.
FROM, TO = "2025-01-06", "2025-01-12"
IN_RANGE = datetime(2025, 1, 8, 10, 0, tzinfo=UTC)
LAST_DAY = datetime(2025, 1, 12, 23, 30, tzinfo=UTC)
BEFORE = datetime(2025, 1, 5, 23, 30, tzinfo=UTC)
AFTER = datetime(2025, 1, 13, 0, 0, tzinfo=UTC)


# --- fixtures and helpers ---------------------------------------------------------------------


@pytest.fixture(autouse=True)
def upstream(monkeypatch) -> Iterator[respx.MockRouter]:
    """Every request to the (test) KNOWBASE goes through this router; anything unmocked fails."""
    monkeypatch.setattr(settings, "KNOWBASE_BASE_URL", KB_BASE)
    with respx.mock(base_url=KB_API, assert_all_called=False, assert_all_mocked=True) as router:
        yield router


@pytest.fixture
def env(
    db_session, cleanup_users, cleanup_forum_categories, cleanup_organisations, cleanup_reports
):
    class Env:
        db = db_session
        users = cleanup_users
        categories = cleanup_forum_categories
        organisations = cleanup_organisations
        reports = cleanup_reports

    return Env


async def _user(env, factory=create_verified_user, **kwargs) -> User:
    user = await factory(env.db, **kwargs)
    env.users.add(user.email)
    await env.db.flush()
    return user


async def _signed_in(client, env, factory=create_admin, **kwargs) -> User:
    user = await _user(env, factory=factory, **kwargs)
    await env.db.commit()
    await login_as(client, user)
    return user


async def _category(env, kind: CategoryKind):
    category = await create_category(env.db, kind=kind)
    env.categories.add(category.id)
    return category


async def _organisation(env, **kwargs):
    organisation = await create_organisation(env.db, **kwargs)
    env.organisations.add(organisation.name)
    return organisation


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


def _sections(text: str) -> dict[str, list[list[str]]]:
    """``{section name: [header row, data rows...]}``; sections are separated by one blank
    line and start with a row holding only their name."""
    sections: dict[str, list[list[str]]] = {}
    current: list[list[str]] | None = None
    for row in csv.reader(io.StringIO(text)):
        if not row:
            current = None
        elif current is None:
            assert len(row) == 1, row
            current = sections.setdefault(row[0], [])
        else:
            current.append(row)
    return sections


def _diff(after: dict, before: dict) -> dict:
    return {
        key: _diff(value, before[key]) if isinstance(value, dict) else value - before[key]
        for key, value in after.items()
        if isinstance(value, dict | int) and not isinstance(value, bool)
    }


# --- permission matrix ------------------------------------------------------------------------

ROUTES = [("get", STATS), ("get", EXPORT), ("post", CACHE_CLEAR)]


@pytest.mark.parametrize(("method", "url"), ROUTES)
async def test_requires_login(client, method, url):
    _assert_error(await getattr(client, method)(url), 401, "auth.not_authenticated")


@pytest.mark.parametrize(("method", "url"), ROUTES)
async def test_forbidden_for_member(client, env, method, url):
    await _signed_in(client, env, factory=create_verified_user)
    _assert_error(await getattr(client, method)(url), 403, "auth.forbidden")


@pytest.mark.parametrize(("method", "url"), ROUTES)
@pytest.mark.parametrize("factory", [create_admin, create_superadmin])
async def test_allowed_for_admins(client, env, method, url, factory):
    await _signed_in(client, env, factory=factory)
    response = await getattr(client, method)(url)
    assert response.status_code == 200, response.text


# --- overview ---------------------------------------------------------------------------------


async def test_stats_shape(client, env):
    await _signed_in(client, env)

    body = (await client.get(STATS)).json()

    assert set(body) == {"users", "content", "reports_open", "knowbase"}
    assert set(body["users"]) == {"total", "verified", "trusted", "admins", "new_30d"}
    assert set(body["content"]) == {
        "posts_published",
        "threads_published",
        "replies",
        "comments",
        "pending",
    }
    # The same shape as ``GET /knowbase/status``.
    assert body["knowbase"] == {
        "reachable": True,
        "last_success_at": None,
        "last_error_at": None,
        "last_error": None,
        "cache": {"lists": 0, "details": 0, "lookups": 0, "stale": 0},
    }


async def test_stats_numbers_reflect_fixtures(client, env):
    await _signed_in(client, env)
    before = (await client.get(STATS)).json()
    db = env.db
    now = datetime.now(UTC)

    # Users: +6 non-deleted (one deleted account is not); the banned admin counts only in
    # ``total`` and ``new_30d``.
    author = await _user(env, trusted_at=now)
    await _user(env, factory=create_admin, is_active=False, trusted_at=now)  # banned
    await _user(env, factory=create_user)  # unverified
    await _user(env, factory=create_superadmin, created_at=now - timedelta(days=60))
    await _user(env, created_at=now - timedelta(days=31))
    await _user(env, deleted_at=now, is_active=False)

    blog = await _category(env, CategoryKind.BLOG)
    forum = await _category(env, CategoryKind.FORUM)
    post = await create_post(db, category_id=blog.id, author_id=author.id)
    await create_post(db, category_id=blog.id, status=P)
    await create_post(db, category_id=blog.id, status=ContentStatus.DELETED)
    thread = await create_thread(db, category_id=forum.id)
    await create_thread(db, category_id=forum.id, status=P)
    await create_thread(db, category_id=forum.id, status=P)
    await create_reply(db, thread_id=thread.id)
    await create_reply(db, thread_id=thread.id)
    await create_reply(
        db, thread_id=thread.id, status=ContentStatus.HIDDEN, hidden_reason=HiddenReason.ADMIN
    )
    await create_comment(db, post_id=post.id)
    reporter = await _user(env)
    report = await create_report(db, reporter_id=reporter.id, content_id=post.id)
    dismissed = await create_report(
        db,
        reporter_id=reporter.id,
        content_type="thread",
        content_id=thread.id,
        status=ReportStatus.DISMISSED,
    )
    env.reports.update({report.id, dismissed.id})
    await db.commit()

    after = (await client.get(STATS)).json()

    assert _diff(after, before) == {
        "users": {"total": 6, "verified": 4, "trusted": 1, "admins": 1, "new_30d": 4},
        "content": {
            "posts_published": 1,
            "threads_published": 1,
            "replies": 2,
            "comments": 1,
            "pending": 3,
        },
        "reports_open": 1,
        "knowbase": {"cache": {"lists": 0, "details": 0, "lookups": 0, "stale": 0}},
    }


async def test_stats_knowbase_cache_and_errors(client, env, upstream):
    upstream.get("/levels/").respond(json=[])
    upstream.get("/subjects/").respond(503)
    await _signed_in(client, env)

    assert (await client.get(f"{API}/knowbase/levels/")).status_code == 200
    fresh = (await client.get(STATS)).json()["knowbase"]
    assert (await client.get(f"{API}/knowbase/subjects/")).status_code == 503
    failing = (await client.get(STATS)).json()["knowbase"]

    assert fresh["reachable"] is True
    assert fresh["last_success_at"] is not None
    assert fresh["last_error_at"] is None
    assert fresh["cache"] == {"lists": 1, "details": 0, "lookups": 0, "stale": 1}
    assert failing["reachable"] is False
    assert failing["last_error"] == "http_503"
    assert failing["last_error_at"] is not None
    assert failing["cache"]["lists"] == 1


# --- KNOWBASE cache clear ---------------------------------------------------------------------


async def test_cache_clear_empties_cache_and_audits(client, env, upstream):
    levels = upstream.get("/levels/").respond(json=[])
    upstream.get("/subjects/").respond(json=[])
    admin = await _signed_in(client, env)
    await client.get(f"{API}/knowbase/levels/")
    await client.get(f"{API}/knowbase/subjects/")

    response = await client.post(CACHE_CLEAR)

    assert response.status_code == 200, response.text
    assert response.json() == {"cleared": 2}
    assert (await client.get(STATS)).json()["knowbase"]["cache"] == {
        "lists": 0,
        "details": 0,
        "lookups": 0,
        "stale": 0,
    }
    again = await client.get(f"{API}/knowbase/levels/")
    assert again.headers["X-Knowbase-Cache"] == "miss"
    assert levels.call_count == 2
    rows = (
        await env.db.scalars(
            select(AuditLog).where(
                AuditLog.actor_id == admin.id, AuditLog.action == "admin.knowbase_cache_clear"
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].metadata_ == {"cleared": 2}


async def test_cache_clear_when_empty(client, env):
    await _signed_in(client, env)
    assert (await client.post(CACHE_CLEAR)).json() == {"cleared": 0}


# --- CSV export -------------------------------------------------------------------------------


async def _export_fixtures(env) -> dict:
    """Users, content and organisations in and around the ``FROM``-``TO`` range."""
    db = env.db
    partner = await _organisation(env, country="GR", is_partner=True)
    other_org = await _organisation(env, country="IT")
    u1 = await _user(env, country="GR", organisation_id=partner.id, created_at=IN_RANGE)
    # ``last_login_at`` only holds the latest sign-in (after the range here).
    u2 = await _user(
        env, country="GR", organisation_id=partner.id, created_at=LAST_DAY, last_login_at=AFTER
    )
    u3 = await _user(env, country="IT", organisation_other="Some NGO", created_at=IN_RANGE)
    u4 = await _user(env, factory=create_user, created_at=IN_RANGE)  # no country, no org
    # Not counted as registered in range: deleted, before, after.
    deleted = await _user(env, country="GR", created_at=IN_RANGE, deleted_at=AFTER, is_active=False)
    u6 = await _user(
        env,
        country="MT",
        organisation_id=other_org.id,
        created_at=BEFORE,
        last_login_at=AFTER,
    )
    await _user(env, country="MT", created_at=AFTER)
    # Registered before the range; same free-text organisation as u3 once trimmed.
    u7 = await _user(env, country="IT", organisation_other="  Some NGO ", created_at=BEFORE)

    # Sign-ins (audit rows): u1 twice and u2 once in range count; u2's later sign-in, u6's
    # sign-in after the range and the deleted account's sign-in do not.
    for user, at in (
        (u1, IN_RANGE),
        (u1, LAST_DAY),
        (u2, IN_RANGE),
        (u2, AFTER),
        (u6, AFTER),
        (deleted, IN_RANGE),
    ):
        db.add(
            AuditLog(
                actor_id=user.id,
                action="auth.login",
                target_type="user",
                target_id=user.id,
                created_at=at,
            )
        )

    blog = await _category(env, CategoryKind.BLOG)
    forum = await _category(env, CategoryKind.FORUM)
    host_post = await create_post(db, category_id=blog.id)  # created now: out of range
    host_thread = await create_thread(db, category_id=forum.id)
    # In range: u1 post + comment, u2 reply, u3 thread, u7 thread.
    await create_post(db, category_id=blog.id, author_id=u1.id, created_at=IN_RANGE)
    await create_comment(db, post_id=host_post.id, author_id=u1.id, created_at=LAST_DAY)
    await create_reply(db, thread_id=host_thread.id, author_id=u2.id, created_at=IN_RANGE)
    await create_thread(db, category_id=forum.id, author_id=u3.id, created_at=IN_RANGE)
    await create_thread(db, category_id=forum.id, author_id=u7.id, created_at=IN_RANGE)
    # Not counted: pending post, hidden reply and deleted comment in range; published post /
    # reply out of range.
    await create_post(db, category_id=blog.id, author_id=u4.id, status=P, created_at=IN_RANGE)
    await create_reply(
        db,
        thread_id=host_thread.id,
        author_id=u2.id,
        status=ContentStatus.HIDDEN,
        hidden_reason=HiddenReason.ADMIN,
        created_at=IN_RANGE,
    )
    await create_comment(
        db,
        post_id=host_post.id,
        author_id=u4.id,
        status=ContentStatus.DELETED,
        deleted_at=AFTER,
        created_at=IN_RANGE,
    )
    await create_post(db, category_id=blog.id, author_id=u6.id, created_at=AFTER)
    await create_reply(db, thread_id=host_thread.id, author_id=u6.id, created_at=BEFORE)
    await db.commit()
    return {"partner": partner, "other_org": other_org}


async def test_export_sections_and_counts(client, env):
    orgs = await _export_fixtures(env)
    await _signed_in(client, env)

    response = await client.get(EXPORT, params={"from": FROM, "to": TO})

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    sections = _sections(response.text)
    assert list(sections) == [
        "users_by_country",
        "users_by_organisation",
        "content",
        "active_users",
        "rco87",
    ]
    assert sections["users_by_country"] == [
        ["country", "count"],
        ["GR", "2"],
        ["IT", "1"],
        ["unknown", "1"],
    ]
    assert sections["users_by_organisation"][0] == ["organisation", "is_partner", "count"]
    assert sorted(sections["users_by_organisation"][1:]) == sorted(
        [
            [orgs["partner"].name, "true", "2"],
            ["Other", "false", "1"],
            ["Unspecified", "false", "1"],
        ]
    )
    assert sections["content"] == [
        ["metric", "count"],
        ["posts", "1"],
        ["threads", "2"],
        ["replies", "1"],
        ["comments", "1"],
    ]
    assert sections["active_users"] == [
        ["metric", "count"],
        ["contributors", "4"],
        ["logged_in", "2"],
    ]
    # Free-text organisations are their own rows (trimmed), with the user's country.
    assert sections["rco87"] == [
        ["organisation", "is_partner", "country", "contributions"],
        [orgs["partner"].name, "true", "GR", "3"],
        ["Some NGO", "false", "IT", "2"],
    ]


async def test_export_filename_header(client, env):
    await _signed_in(client, env)

    response = await client.get(EXPORT, params={"from": FROM, "to": TO})

    assert response.headers["content-disposition"] == (
        f'attachment; filename="urbanfloods-cooperation-stats-{FROM}-{TO}.csv"'
    )


async def test_export_default_range(client, env):
    await _signed_in(client, env)

    before = datetime.now(UTC).date()
    response = await client.get(EXPORT)
    after = datetime.now(UTC).date()

    assert response.status_code == 200, response.text
    # Default ``from`` is the project start; ``to`` is the server's UTC date (either side of a
    # midnight that falls during the request).
    assert response.headers["content-disposition"] in {
        f'attachment; filename="urbanfloods-cooperation-stats-2024-09-01-{day.isoformat()}.csv"'
        for day in (before, after)
    }


async def test_export_single_day_range(client, env):
    await _export_fixtures(env)
    await _signed_in(client, env)

    sections = _sections((await client.get(EXPORT, params={"from": TO, "to": TO})).text)

    assert sections["users_by_country"] == [["country", "count"], ["GR", "1"]]
    assert sections["content"][4] == ["comments", "1"]


async def test_export_empty_range_has_headers_only(client, env):
    await _signed_in(client, env)

    sections = _sections(
        (await client.get(EXPORT, params={"from": "2000-01-01", "to": "2000-01-31"})).text
    )

    assert sections["users_by_country"] == [["country", "count"]]
    assert sections["rco87"] == [["organisation", "is_partner", "country", "contributions"]]
    assert sections["content"][1:] == [
        ["posts", "0"],
        ["threads", "0"],
        ["replies", "0"],
        ["comments", "0"],
    ]


async def test_export_invalid_range_is_422(client, env):
    await _signed_in(client, env)

    response = await client.get(EXPORT, params={"from": "2025-02-01", "to": "2025-01-01"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation.failed"


async def test_export_bad_date_is_422(client, env):
    await _signed_in(client, env)
    assert (await client.get(EXPORT, params={"from": "yesterday"})).status_code == 422


async def test_export_writes_audit_row(client, env):
    admin = await _signed_in(client, env)

    await client.get(EXPORT, params={"from": FROM, "to": TO})

    rows = (
        await env.db.scalars(
            select(AuditLog).where(
                AuditLog.actor_id == admin.id, AuditLog.action == "admin.stats_export"
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].metadata_ == {"from": FROM, "to": TO}


async def test_export_neutralises_formula_cells(client, env):
    name = f"=HYPERLINK({uuid.uuid4().hex[:8]})"
    partner = await _organisation(env, name=name, is_partner=True)
    await _user(env, organisation_id=partner.id, created_at=IN_RANGE)
    await env.db.commit()
    await _signed_in(client, env)

    sections = _sections((await client.get(EXPORT, params={"from": FROM, "to": TO})).text)

    assert [f"'{name}", "true", "1"] in sections["users_by_organisation"]

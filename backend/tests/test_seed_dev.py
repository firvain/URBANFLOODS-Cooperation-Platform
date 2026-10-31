"""Increment 2g: ``python -m scripts.seed_dev`` (idempotent development seed).

The seed runs inside ``db_session`` (rolled back after each test). The KNOWBASE is mocked with
respx; the live server is never called.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import httpx
import pytest
import respx
from sqlalchemy import func, select

from app.api.v1.schemas.auth import LoginRequest
from app.core.config import settings
from app.core.security import verify_password
from app.db.enums import CategoryKind, ContentStatus, ContentType, UserRole
from app.db.models import Category, KnowbaseLink, Post, Tag, User
from app.services.knowbase import KnowbaseClient
from scripts import seed_dev

KB_BASE = "https://knowbase.test"
KB_API = f"{KB_BASE}/api/v1"

MEASURE_1 = {"id": 1, "title_en": "Green roofs", "title_local": "Πράσινες στέγες"}
MEASURE_2 = {"id": 2, "title_en": "Retention basin", "title_local": None}
DOCUMENT_1 = {"id": 1, "name_of_document_en": "Floods Directive", "name_of_document_local": None}

EMAILS = {
    "admin@urbanfloods.example": "Admin-Dev-Pass-2026",
    "editor@urbanfloods.example": "Editor-Dev-Pass-2026",
    "member@urbanfloods.example": "Member-Dev-Pass-2026",
    "newbie@urbanfloods.example": "Newbie-Dev-Pass-2026",
}


@pytest.fixture(autouse=True)
def kb_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "KNOWBASE_BASE_URL", KB_BASE)


@pytest.fixture
def upstream(kb_settings) -> Iterator[respx.MockRouter]:
    """Every request to the (test) KNOWBASE goes through this router; anything unmocked fails."""
    with respx.mock(base_url=KB_API, assert_all_called=False, assert_all_mocked=True) as router:
        router.get("/measures/1").respond(json=MEASURE_1)
        router.get("/measures/2").respond(json=MEASURE_2)
        router.get("/documents/1").respond(json=DOCUMENT_1)
        yield router


@pytest.fixture
async def knowbase() -> AsyncIterator[KnowbaseClient]:
    client = KnowbaseClient()
    try:
        yield client
    finally:
        await client.aclose()


async def _users(db) -> dict[str, User]:
    from sqlalchemy.orm import selectinload

    stmt = (
        select(User)
        .options(selectinload(User.expertise), selectinload(User.organisation))
        .where(User.email.in_(EMAILS))
        .execution_options(populate_existing=True)
    )
    return {str(user.email): user for user in (await db.scalars(stmt)).all()}


async def _seed_posts(db) -> list[Post]:
    from sqlalchemy.orm import selectinload

    stmt = (
        select(Post)
        .join(User, Post.author_id == User.id)
        .options(selectinload(Post.category), selectinload(Post.author), selectinload(Post.tags))
        .where(User.email.in_(EMAILS))
        .order_by(Post.id)
        .execution_options(populate_existing=True)
    )
    return list((await db.scalars(stmt)).all())


async def _links(db, post_id: int) -> list[KnowbaseLink]:
    stmt = (
        select(KnowbaseLink)
        .where(KnowbaseLink.content_type == ContentType.POST, KnowbaseLink.content_id == post_id)
        .order_by(KnowbaseLink.sort_order)
    )
    return list((await db.scalars(stmt)).all())


async def test_seed_creates_accounts_and_posts_idempotently(db_session, upstream, knowbase):
    first = await seed_dev.seed(db_session, knowbase=knowbase)
    posts = await _seed_posts(db_session)
    tag_counts = dict((await db_session.execute(select(Tag.slug, Tag.usage_count))).all())

    second = await seed_dev.seed(db_session, knowbase=knowbase)

    # Idempotent: the second run creates nothing and changes nothing.
    assert all(row.created for row in first.users) and len(first.users) == 4
    assert all(row.created for row in first.posts) and len(first.posts) == len(posts)
    assert not any(row.created for row in second.users + second.posts)
    assert [p.id for p in await _seed_posts(db_session)] == [p.id for p in posts]
    assert dict((await db_session.execute(select(Tag.slug, Tag.usage_count))).all()) == tag_counts
    assert first.knowbase_reachable is True and first.warnings == []

    # Accounts.
    users = await _users(db_session)
    assert set(users) == set(EMAILS)
    for email, password in EMAILS.items():
        user = users[email]
        assert user.is_verified and user.is_active
        assert verify_password(password, user.password_hash)
        assert 2 <= len(user.expertise) <= 4
    admin, editor = users["admin@urbanfloods.example"], users["editor@urbanfloods.example"]
    member, newbie = users["member@urbanfloods.example"], users["newbie@urbanfloods.example"]
    assert admin.role == UserRole.SUPERADMIN and admin.trusted_at is not None
    assert editor.role == UserRole.ADMIN
    assert member.role == UserRole.MEMBER and member.trusted_at is not None
    assert newbie.role == UserRole.MEMBER and newbie.trusted_at is None
    orgs = {u.organisation.short_name if u.organisation else None for u in users.values()}
    assert orgs == {"UOWM", "DCMS", "HEIS", None}
    assert any(u.organisation_id is None and u.organisation_other for u in users.values())

    # Posts.
    assert 7 <= len(posts) <= 10
    categories = {p.category.slug for p in posts}
    assert {"news", "best-practices", "events", "policy", "resources"} <= categories
    pending = [p for p in posts if p.status == ContentStatus.PENDING]
    assert [p.author_id for p in pending] == [newbie.id]
    assert all(p.status == ContentStatus.PUBLISHED for p in posts if p not in pending)
    greek = [p for p in posts if p.locale == "el"]
    assert len(greek) == 1 and any("Ͱ" <= ch <= "Ͽ" for ch in greek[0].title)
    resources = [p for p in posts if p.category.slug == "resources"]
    assert len(resources) == 2 and all(p.author_id == admin.id for p in resources)
    events = [p for p in posts if p.category.slug == "events"]
    assert events and all(
        p.event_at is not None and p.event_at > datetime.now(UTC) and p.event_url for p in events
    )
    for post in posts:
        assert "<h2>" in post.body_html or "<h3>" in post.body_html
        assert "<ul>" in post.body_html or "<ol>" in post.body_html
        assert 'rel="nofollow noopener noreferrer"' in post.body_html
        assert post.body_html.count("<p>") >= 3
        assert post.tags
    seed_tags = {t.slug for p in posts for t in p.tags}
    assert {"nbs", "early-warning", "urban-drainage", "flood-risk-mapping"} <= seed_tags
    assert "civil-protection" in seed_tags
    for slug in seed_tags:
        stmt = select(Tag.usage_count).where(Tag.slug == slug)
        assert await db_session.scalar(stmt) >= 1

    # KNOWBASE links on two posts, titles cached from the (mocked) proxy.
    linked = {p.id: await _links(db_session, p.id) for p in posts}
    linked = {pid: rows for pid, rows in linked.items() if rows}
    assert len(linked) == 2
    pairs = sorted((r.kb_type.value, r.kb_id) for rows in linked.values() for r in rows)
    assert pairs == [("document", 1), ("measure", 1), ("measure", 2)]
    titles = {r.cached_title_en for rows in linked.values() for r in rows}
    assert titles == {"Green roofs", "Retention basin", "Floods Directive"}


def test_seed_accounts_can_log_in():
    """``.local``/``.test`` addresses fail ``EmailStr`` (special-use domains), so the login form
    would reject them: every seeded address and password must pass ``LoginRequest``."""
    assert {spec.email: spec.password for spec in seed_dev.ACCOUNTS} == EMAILS
    for email, password in EMAILS.items():
        LoginRequest(email=email, password=password)


async def test_seed_uses_placeholder_titles_when_knowbase_is_down(db_session, kb_settings):
    with respx.mock(base_url=KB_API, assert_all_mocked=True) as router:
        router.get(path__regex=r".*").mock(side_effect=httpx.ConnectError("down"))
        client = KnowbaseClient()
        try:
            summary = await seed_dev.seed(db_session, knowbase=client)
        finally:
            await client.aclose()

    assert summary.knowbase_reachable is False
    assert summary.warnings and "KNOWBASE" in summary.warnings[0]
    posts = await _seed_posts(db_session)
    rows = [r for p in posts for r in await _links(db_session, p.id)]
    assert len(rows) == 3
    assert all("placeholder" in r.cached_title_en for r in rows)


async def test_seed_refuses_in_prod(db_session, monkeypatch, upstream, knowbase):
    monkeypatch.setattr(settings, "ENV", "prod")
    before = await db_session.scalar(select(func.count()).select_from(User))

    with pytest.raises(seed_dev.SeedRefused):
        await seed_dev.seed(db_session, knowbase=knowbase)
    assert await asyncio.to_thread(seed_dev.main, []) == 1

    assert await db_session.scalar(select(func.count()).select_from(User)) == before
    assert not upstream.calls


async def test_seed_fails_cleanly_without_the_seeded_categories(db_session, upstream, knowbase):
    """Missing reference data is an error (exit 1 from ``main``), not a partial seed."""
    events = await db_session.scalar(
        select(Category).where(Category.kind == CategoryKind.BLOG, Category.slug == "events")
    )
    events.slug = "events-renamed"
    await db_session.flush()

    with pytest.raises(seed_dev.SeedError):
        await seed_dev.seed(db_session, knowbase=knowbase)

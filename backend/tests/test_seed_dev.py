"""``python -m scripts.seed_dev`` (idempotent development seed, ``--reset``).

Increment 2g, extended 2026-10-31: twelve personas covering every account state (superadmin,
admins, trusted and untrusted members, a free-text organisation, unverified, banned,
anonymised, a minimal profile) and demo content (posts, threads, replies, comments) spread
across them. ``--reset`` hard-deletes every demo account and what it authored, then seeds
afresh; accounts outside ``@urbanfloods.example`` and their content stay.

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
from sqlalchemy.orm import selectinload

from app.api.v1.schemas.auth import LoginRequest
from app.core.config import settings
from app.core.security import validate_password_policy, verify_password
from app.crud.user import DELETED_DISPLAY_NAME
from app.db.enums import CategoryKind, ContentStatus, ContentType, UserRole
from app.db.models import (
    Attachment,
    AuditLog,
    Category,
    Comment,
    KnowbaseLink,
    NotificationPreference,
    Post,
    Reply,
    Report,
    Tag,
    Thread,
    User,
)
from app.services.knowbase import KnowbaseClient
from scripts import seed_dev
from tests import factories

KB_BASE = "https://knowbase.test"
KB_API = f"{KB_BASE}/api/v1"

MEASURE_1 = {"id": 14, "title_en": "Green roofs", "title_local": "Πράσινες στέγες"}
MEASURE_2 = {"id": 17, "title_en": "Retention basin", "title_local": None}
DOCUMENT_1 = {"id": 1, "name_of_document_en": "Floods Directive", "name_of_document_local": None}

PASSWORD = "Urbanfloods-2026"
DOMAIN = "@urbanfloods.example"

# The four accounts the e2e suite logs in as (frontend/e2e/helpers/demo.ts).
SUPERADMIN = "eleni.papadopoulou@urbanfloods.example"
ADMIN_SI = "matej.kovacic@urbanfloods.example"
ADMIN_MK = "aleksandar.stojanovski@urbanfloods.example"
MEMBER_IT = "giulia.romano@urbanfloods.example"
MEMBER_HR = "ivana.babic@urbanfloods.example"
MEMBER_RS = "nikola.petrovic@urbanfloods.example"
NEWBIE_AL = "arben.hoxha@urbanfloods.example"
NEWBIE_BA = "amra.hadzic@urbanfloods.example"
UNVERIFIED = "dimitris.karagiannis@urbanfloods.example"
BANNED = "sara.conti@urbanfloods.example"
ANONYMISED = "kostas.nikolaidis@urbanfloods.example"  # gone after anonymisation
MINIMAL = "petra.vidmar@urbanfloods.example"

LIVE_EMAILS = (
    SUPERADMIN,
    ADMIN_SI,
    ADMIN_MK,
    MEMBER_IT,
    MEMBER_HR,
    MEMBER_RS,
    NEWBIE_AL,
    NEWBIE_BA,
    UNVERIFIED,
    BANNED,
    MINIMAL,
)


@pytest.fixture(autouse=True)
def kb_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "KNOWBASE_BASE_URL", KB_BASE)


@pytest.fixture
def upstream(kb_settings) -> Iterator[respx.MockRouter]:
    """Every request to the (test) KNOWBASE goes through this router; anything unmocked fails."""
    with respx.mock(base_url=KB_API, assert_all_called=False, assert_all_mocked=True) as router:
        router.get("/measures/14").respond(json=MEASURE_1)
        router.get("/measures/17").respond(json=MEASURE_2)
        router.get("/documents/1").respond(json=DOCUMENT_1)
        yield router


@pytest.fixture
async def knowbase() -> AsyncIterator[KnowbaseClient]:
    client = KnowbaseClient()
    try:
        yield client
    finally:
        await client.aclose()


# --- helpers ----------------------------------------------------------------------------------


async def _seeded_ids(db) -> set[int]:
    """Ids of the seed's accounts: the demo addresses plus the anonymised persona (found by its
    seed audit row, since anonymisation replaced its address)."""
    demo = select(User.id).where(User.email.like(f"%{DOMAIN}"))
    audited = (
        select(User.id)
        .join(AuditLog, AuditLog.target_id == User.id)
        .where(
            AuditLog.action == "admin.seed_dev_account",
            AuditLog.target_type == "user",
            User.deleted_at.is_not(None),
        )
    )
    return set((await db.scalars(demo)).all()) | set((await db.scalars(audited)).all())


async def _users(db) -> dict[str, User]:
    """Seeded accounts by email (the anonymised one under ``ANONYMISED``)."""
    stmt = (
        select(User)
        .options(selectinload(User.expertise), selectinload(User.organisation))
        .where(User.id.in_(await _seeded_ids(db)))
        .execution_options(populate_existing=True)
    )
    users: dict[str, User] = {}
    for user in (await db.scalars(stmt)).all():
        key = ANONYMISED if user.deleted_at is not None else str(user.email)
        assert key not in users, f"two seeded accounts for {key}"
        users[key] = user
    return users


async def _authored(db, model, ids: set[int]) -> list:
    options = []
    if model is Post:
        options = [selectinload(Post.category), selectinload(Post.tags)]
    elif model is Thread:
        options = [selectinload(Thread.category), selectinload(Thread.tags)]
    stmt = (
        select(model)
        .options(*options)
        .where(model.author_id.in_(ids))
        .order_by(model.id)
        .execution_options(populate_existing=True)
    )
    return list((await db.scalars(stmt)).all())


async def _seed_posts(db) -> list[Post]:
    return await _authored(db, Post, await _seeded_ids(db))


async def _links(db, post_id: int) -> list[KnowbaseLink]:
    stmt = (
        select(KnowbaseLink)
        .where(KnowbaseLink.content_type == ContentType.POST, KnowbaseLink.content_id == post_id)
        .order_by(KnowbaseLink.sort_order)
    )
    return list((await db.scalars(stmt)).all())


async def _count(db, model, *where) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*where))


# --- seed -------------------------------------------------------------------------------------


async def test_seed_is_idempotent(db_session, upstream, knowbase):
    first = await seed_dev.seed(db_session, knowbase=knowbase)
    ids = await _seeded_ids(db_session)
    snapshot = {
        model: [row.id for row in await _authored(db_session, model, ids)]
        for model in (Post, Thread, Reply, Comment)
    }
    tag_counts = dict((await db_session.execute(select(Tag.slug, Tag.usage_count))).all())

    second = await seed_dev.seed(db_session, knowbase=knowbase)

    assert len(first.users) == 12 and all(row.created for row in first.users)
    assert all(row.created for row in first.posts)
    assert first.threads and all(row.created for row in first.threads)
    assert len(second.users) == 12
    assert not any(row.created for row in second.users + second.posts + second.threads)
    assert second.rows_created == 0
    assert await _seeded_ids(db_session) == ids
    for model, before in snapshot.items():
        assert [row.id for row in await _authored(db_session, model, ids)] == before, model
    assert dict((await db_session.execute(select(Tag.slug, Tag.usage_count))).all()) == tag_counts
    assert first.knowbase_reachable is True and first.warnings == []


async def test_seed_account_states(db_session, upstream, knowbase):
    await seed_dev.seed(db_session, knowbase=knowbase)
    users = await _users(db_session)
    assert set(users) == {*LIVE_EMAILS, ANONYMISED}

    def org(email: str) -> str | None:
        user = users[email]
        return user.organisation.short_name if user.organisation else None

    def tags(email: str) -> set[str]:
        return {tag.slug for tag in users[email].expertise}

    # Everyone but the anonymised persona can be logged in with the shared password.
    for email in LIVE_EMAILS:
        assert verify_password(PASSWORD, users[email].password_hash), email
        assert users[email].deleted_at is None

    expected = {
        # email: (role, verified, active, trusted, locale, country, partner)
        SUPERADMIN: (UserRole.SUPERADMIN, True, True, True, "el", "GR", "UOWM"),
        ADMIN_SI: (UserRole.ADMIN, True, True, True, "sl", "SI", "DCMS"),
        ADMIN_MK: (UserRole.ADMIN, True, True, True, "mk", "MK", "FCSE-UKIM"),
        MEMBER_IT: (UserRole.MEMBER, True, True, True, "it", "IT", "MC"),
        MEMBER_HR: (UserRole.MEMBER, True, True, True, "hr", "HR", "RDA Porin"),
        MEMBER_RS: (UserRole.MEMBER, True, True, True, "sr", "RS", "RDA Backa"),
        NEWBIE_AL: (UserRole.MEMBER, True, True, False, "sq", "AL", "HydrowaterAL"),
        NEWBIE_BA: (UserRole.MEMBER, True, True, False, "bs", "BA", None),
        UNVERIFIED: (UserRole.MEMBER, False, True, False, "el", "GR", None),
        BANNED: (UserRole.MEMBER, True, False, True, "en", "IT", "Modica"),
        MINIMAL: (UserRole.MEMBER, True, True, False, "en", None, None),
    }
    for email, (role, verified, active, trusted, locale, country, partner) in expected.items():
        user = users[email]
        assert user.role == role, email
        assert user.is_verified is verified, email
        assert user.is_active is active, email
        assert (user.trusted_at is not None) is trusted, email
        assert user.locale == locale, email
        assert user.country == country, email
        assert org(email) == partner, email

    # Realistic names, not "Dev ..." placeholders.
    assert users[SUPERADMIN].display_name == "Eleni Papadopoulou"
    assert all(not users[e].display_name.startswith("Dev ") for e in LIVE_EMAILS)

    # Profile details.
    assert users[MEMBER_IT].bio and users[MEMBER_IT].show_email is True
    assert len(tags(MEMBER_IT)) == 3
    assert tags(MEMBER_HR) and tags(MEMBER_RS)
    assert users[MEMBER_RS].show_in_directory is False
    assert all(users[e].show_in_directory for e in LIVE_EMAILS if e != MEMBER_RS)
    assert all(not users[e].show_email for e in LIVE_EMAILS if e != MEMBER_IT)
    assert len(tags(NEWBIE_AL)) == 1
    assert users[NEWBIE_BA].organisation_id is None and users[NEWBIE_BA].organisation_other
    assert users[UNVERIFIED].organisation_id is None and users[UNVERIFIED].organisation_other
    minimal = users[MINIMAL]
    assert minimal.organisation_id is None and minimal.organisation_other is None
    assert not minimal.expertise and minimal.bio is None

    # Notifications: the demo personas opted in to the member notifications (the e2e suite and
    # the manual QA read reply/comment/approval emails in Mailpit); the minimal persona keeps
    # the defaults of a new account (member notifications off, admin digest on).
    member_switches = factories.MEMBER_NOTIFICATIONS
    for email in LIVE_EMAILS:
        prefs = await db_session.get(
            NotificationPreference, users[email].id, populate_existing=True
        )
        expected_on = email != MINIMAL
        assert all(getattr(prefs, name) is expected_on for name in member_switches), email
        assert prefs.admin_digest is True, email

    # Anonymised: personal data erased, row kept.
    gone = users[ANONYMISED]
    assert gone.display_name == DELETED_DISPLAY_NAME
    assert gone.email == f"deleted-{gone.id}@invalid" and gone.password_hash == ""
    assert not gone.is_active and not gone.is_verified and gone.deleted_at is not None
    assert gone.organisation_id is None and not gone.expertise
    assert await _count(db_session, User, User.email == ANONYMISED) == 0


async def test_seed_content(db_session, upstream, knowbase):
    await seed_dev.seed(db_session, knowbase=knowbase)
    users = await _users(db_session)
    uid = {email: user.id for email, user in users.items()}
    ids = set(uid.values())
    posts = await _seed_posts(db_session)
    threads = await _authored(db_session, Thread, ids)
    replies = await _authored(db_session, Reply, ids)
    comments = await _authored(db_session, Comment, ids)

    # Posts: the original eight plus three more, spread over the personas.
    assert 10 <= len(posts) <= 14
    authors = {p.author_id for p in posts}
    for email in (MEMBER_IT, MEMBER_HR, MEMBER_RS, BANNED, ANONYMISED, SUPERADMIN, ADMIN_SI):
        assert uid[email] in authors, email
    categories = {p.category.slug for p in posts}
    assert {"news", "best-practices", "events", "policy", "resources"} <= categories
    pending = [p for p in posts if p.status == ContentStatus.PENDING]
    assert len(pending) == 1 and pending[0].author_id in {uid[NEWBIE_AL], uid[NEWBIE_BA]}
    assert all(p.status == ContentStatus.PUBLISHED for p in posts if p not in pending)
    greek = [p for p in posts if p.locale == "el"]
    assert len(greek) == 1 and any("Ͱ" <= ch <= "Ͽ" for ch in greek[0].title)
    admins = {uid[SUPERADMIN], uid[ADMIN_SI], uid[ADMIN_MK]}
    resources = [p for p in posts if p.category.slug == "resources"]
    assert len(resources) == 2 and all(p.author_id in admins for p in resources)
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
    for slug in seed_tags:
        assert await db_session.scalar(select(Tag.usage_count).where(Tag.slug == slug)) >= 1

    # The e2e suite's anchor post: by the trusted Italian member, with two KNOWBASE links.
    green = next(p for p in posts if p.slug == seed_dev.GREEN_ROOFS_SLUG)
    assert green.author_id == uid[MEMBER_IT] and "Sarajevo pilot" in green.body_html
    assert [(r.kb_type.value, r.kb_id) for r in await _links(db_session, green.id)] == [
        ("measure", 14),
        ("measure", 17),
    ]

    # The banned and the anonymised personas keep a published, attributed post.
    for email in (BANNED, ANONYMISED):
        own = [p for p in posts if p.author_id == uid[email]]
        assert len(own) == 1 and own[0].status == ContentStatus.PUBLISHED, email

    # KNOWBASE links on two posts, titles cached from the (mocked) proxy.
    linked = {p.id: rows for p in posts if (rows := await _links(db_session, p.id))}
    assert len(linked) == 2
    pairs = sorted((r.kb_type.value, r.kb_id) for rows in linked.values() for r in rows)
    assert pairs == [("document", 1), ("measure", 14), ("measure", 17)]
    titles = {r.cached_title_en for rows in linked.values() for r in rows}
    assert titles == {"Green roofs", "Retention basin", "Floods Directive"}

    # Forum: published threads in several categories, one pinned, replies (one nested).
    assert len(threads) >= 3
    assert all(t.status == ContentStatus.PUBLISHED for t in threads)
    assert len({t.category.slug for t in threads}) >= 3
    assert all(t.category.kind == CategoryKind.FORUM for t in threads)
    assert sum(t.is_pinned for t in threads) == 1
    assert all(t.reply_count >= 1 for t in threads)
    assert any(r.parent_reply_id is not None for r in replies)
    assert len({r.author_id for r in replies}) >= 4

    # Comments by several personas, on published posts only.
    assert len(comments) >= 4 and len({c.author_id for c in comments}) >= 3
    by_id = {p.id: p for p in posts}
    assert all(by_id[c.post_id].status == ContentStatus.PUBLISHED for c in comments)

    # The untrusted e2e account (NEWBIE) has authored no post or thread: its first one is the
    # one the moderation spec sends for approval.
    assert not [p for p in posts if p.author_id == uid[NEWBIE_AL]]
    assert not [t for t in threads if t.author_id == uid[NEWBIE_AL]]
    # The unverified account has written nothing.
    assert not [
        c for c in [*posts, *threads, *replies, *comments] if c.author_id == uid[UNVERIFIED]
    ]


def test_seed_accounts_can_log_in():
    """``.local``/``.test`` addresses fail ``EmailStr`` (special-use domains), so the login form
    would reject them: every seeded address and the shared password must pass ``LoginRequest``
    and the password policy."""
    assert seed_dev.PASSWORD == PASSWORD
    validate_password_policy(PASSWORD)
    emails = [spec.email for spec in seed_dev.ACCOUNTS]
    assert len(emails) == len(set(emails)) == 12
    assert set(emails) == {*LIVE_EMAILS, ANONYMISED}
    for email in emails:
        assert email.endswith(DOMAIN)
        LoginRequest(email=email, password=PASSWORD)


async def test_summary_lists_accounts_without_secrets(db_session, upstream, knowbase):
    summary = await seed_dev.seed(db_session, knowbase=knowbase)
    text = seed_dev.format_summary(summary)
    users = await _users(db_session)

    for email in LIVE_EMAILS:
        assert email in text
    for state in ("superadmin", "admin", "trusted", "untrusted", "unverified", "banned"):
        assert state in text
    assert "anonymised" in text and "hidden from directory" in text
    assert "password: see README" in text
    assert PASSWORD not in text
    assert "$argon2" not in text
    assert all(user.password_hash not in text for user in users.values() if user.password_hash)


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


@pytest.mark.parametrize("args", [[], ["--reset"]])
async def test_seed_refuses_outside_dev_and_test(db_session, monkeypatch, upstream, knowbase, args):
    monkeypatch.setattr(settings, "ENV", "prod")
    before = await db_session.scalar(select(func.count()).select_from(User))

    with pytest.raises(seed_dev.SeedRefused):
        await seed_dev.seed(db_session, knowbase=knowbase)
    with pytest.raises(seed_dev.SeedRefused):
        await seed_dev.seed(db_session, knowbase=knowbase, reset=True)
    assert await asyncio.to_thread(seed_dev.main, args) == 1

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


# --- reset ------------------------------------------------------------------------------------


async def test_reset_deletes_demo_data_and_keeps_other_accounts(db_session, upstream, knowbase):
    await seed_dev.seed(db_session, knowbase=knowbase)
    old_users = await _users(db_session)
    old_ids = set(u.id for u in old_users.values())
    old_posts = {p.id for p in await _seed_posts(db_session)}
    old_threads = {t.id for t in await _authored(db_session, Thread, old_ids)}
    member = old_users[MEMBER_IT]
    giulia_post = next(p for p in await _seed_posts(db_session) if p.author_id == member.id)
    tag_counts = dict((await db_session.execute(select(Tag.slug, Tag.usage_count))).all())

    # An account outside the demo domain, with its own content, a comment on a demo post and a
    # report on demo content; plus a real (not seeded) anonymised account.
    keeper = await factories.create_verified_user(db_session, email="keeper@example.org")
    real_gone = await factories.create_user(db_session, email="deleted-999999@invalid")
    news = await db_session.scalar(
        select(Category).where(Category.kind == CategoryKind.BLOG, Category.slug == "news")
    )
    kept_post = await factories.create_post(
        db_session, category_id=news.id, author_id=keeper.id, title="Keeper's post"
    )
    kept_comment = await factories.create_comment(
        db_session, post_id=kept_post.id, author_id=keeper.id, body="My own comment."
    )
    demo_comment_on_kept = await factories.create_comment(
        db_session, post_id=kept_post.id, author_id=member.id, body="A demo comment."
    )
    await factories.create_comment(
        db_session, post_id=giulia_post.id, author_id=keeper.id, body="On a demo post."
    )
    keeper_report = await factories.create_report(
        db_session, reporter_id=keeper.id, content_type="post", content_id=giulia_post.id
    )
    demo_report = await factories.create_report(
        db_session, reporter_id=member.id, content_type="post", content_id=kept_post.id
    )
    # An upload by a demo account, with its files on disk.
    upload = await factories.create_attachment(db_session, uploader_id=member.id)
    upload_id = upload.id
    files = {(upload.storage_path, upload.thumb_path)}

    summary = await seed_dev.seed(db_session, knowbase=knowbase, reset=True)

    # Every old demo row is gone (hard delete), including the anonymised persona.
    assert await _count(db_session, User, User.id.in_(old_ids)) == 0
    assert await _count(db_session, Post, Post.id.in_(old_posts)) == 0
    assert await _count(db_session, Thread, Thread.id.in_(old_threads)) == 0
    assert await db_session.get(Comment, demo_comment_on_kept.id) is None
    assert await db_session.get(Report, demo_report.id) is None
    assert await db_session.get(Report, keeper_report.id) is None  # its target is gone
    assert await db_session.get(Attachment, upload_id) is None
    assert files <= set(summary.files)
    assert (
        await _count(
            db_session,
            KnowbaseLink,
            KnowbaseLink.content_type == ContentType.POST,
            KnowbaseLink.content_id.in_(old_posts),
        )
        == 0
    )

    # ...and seeded afresh: twelve new accounts, new content.
    new_users = await _users(db_session)
    assert set(new_users) == {*LIVE_EMAILS, ANONYMISED}
    assert not {u.id for u in new_users.values()} & old_ids
    assert len(summary.users) == 12 and all(row.created for row in summary.users)
    assert summary.reset is not None and summary.reset["users"] == 12
    assert summary.reset["posts"] == len(old_posts)
    assert summary.reset["attachments"] == 1
    # The keeper's comment on a demo post went with that post: reported, not silent.
    assert summary.reset["kept_authors_children"] == 1
    assert any("comment" in w for w in summary.warnings)

    # Other accounts and their own content are untouched.
    for row in (keeper, real_gone, kept_post, kept_comment):
        assert await db_session.get(type(row), row.id) is not None
    await db_session.refresh(kept_post)
    assert kept_post.comment_count == 1

    # Tag counts are recounted: the same as after the first seed.
    assert dict((await db_session.execute(select(Tag.slug, Tag.usage_count))).all()) == tag_counts


async def test_reset_twice_is_stable(db_session, upstream, knowbase):
    await seed_dev.seed(db_session, knowbase=knowbase, reset=True)
    counts = {m: await _count(db_session, m) for m in (User, Post, Thread, Reply, Comment)}
    await seed_dev.seed(db_session, knowbase=knowbase, reset=True)
    assert {m: await _count(db_session, m) for m in counts} == counts

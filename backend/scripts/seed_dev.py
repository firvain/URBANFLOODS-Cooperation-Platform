"""Development seed: demo accounts and blog posts. Never for production.

    cd backend && uv run python -m scripts.seed_dev

Creates, if missing, four verified accounts (a superadmin, an admin, a trusted member and an
untrusted member; passwords below) and eight blog posts across the seeded blog categories,
including a Greek post, a pending post by the untrusted member, two posts in the admin-only
Resources category and KNOWBASE links on two posts. Existing accounts and posts (matched by
email, and by author and title) are left untouched, so running it again changes nothing.

Everything goes through the crud layer (sanitisation, slugs, tag counts, the trust model) in one
transaction: on any error nothing is written, the error goes to stderr and the exit code is 1.
KNOWBASE titles are resolved through the real proxy; if it is unreachable the links are stored
with placeholder titles and a warning is printed. Refuses to run when ``ENV=prod``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.exceptions import AppError
from app.crud import audit as crud_audit
from app.crud import category as crud_category
from app.crud import post as crud_post
from app.crud import user as crud_user
from app.db.enums import CategoryKind, UserRole
from app.db.models import Category, ExpertiseTag, Organisation, Post, User
from app.db.session import AsyncSessionLocal
from app.services.knowbase import KnowbaseClient, KnowbaseError, KnowbaseUnavailable

LinkKey = tuple[str, int]
Titles = dict[LinkKey, dict[str, str | None] | None]


class SeedError(Exception):
    """The seed cannot run (missing reference data, rejected input): exit code 1."""


class SeedRefused(SeedError):
    """``ENV=prod``."""


# --- data -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AccountSpec:
    key: str
    email: str
    password: str
    display_name: str
    role: UserRole
    trusted: bool
    organisation: str | None  # partner short name; None = ``organisation_other``
    organisation_other: str | None
    country: str
    expertise: tuple[str, ...]  # expertise tag slugs


ACCOUNTS: tuple[AccountSpec, ...] = (
    AccountSpec(
        key="admin",
        email="admin@urbanfloods.example",
        password="Admin-Dev-Pass-2026",
        display_name="Dev Superadmin",
        role=UserRole.SUPERADMIN,
        trusted=True,
        organisation="UOWM",
        organisation_other=None,
        country="GR",
        expertise=("flood-risk-mapping", "hydraulic-modelling", "gis-remote-sensing"),
    ),
    AccountSpec(
        key="editor",
        email="editor@urbanfloods.example",
        password="Editor-Dev-Pass-2026",
        display_name="Dev Editor",
        role=UserRole.ADMIN,
        trusted=True,
        organisation="DCMS",
        organisation_other=None,
        country="SI",
        expertise=("civil-protection", "community-engagement"),
    ),
    AccountSpec(
        key="member",
        email="member@urbanfloods.example",
        password="Member-Dev-Pass-2026",
        display_name="Dev Member",
        role=UserRole.MEMBER,
        trusted=True,
        organisation="HEIS",
        organisation_other=None,
        country="BA",
        expertise=(
            "hydrology",
            "nature-based-solutions",
            "green-blue-infrastructure",
            "urban-planning",
        ),
    ),
    AccountSpec(
        key="newbie",
        email="newbie@urbanfloods.example",
        password="Newbie-Dev-Pass-2026",
        display_name="Dev Newbie",
        role=UserRole.MEMBER,
        trusted=False,
        organisation=None,
        organisation_other="Municipality of Kozani",
        country="GR",
        expertise=("water-supply-sewerage", "climate-adaptation"),
    ),
)


@dataclass(frozen=True)
class PostSpec:
    author: str  # AccountSpec.key
    category: str  # blog category slug
    title: str
    body_html: str
    tags: tuple[str, ...]
    locale: str = "en"
    event_in_days: int | None = None
    event_url: str | None = None
    knowbase_links: tuple[LinkKey, ...] = ()


POSTS: tuple[PostSpec, ...] = (
    PostSpec(
        author="editor",
        category="news",
        title="URBANFLOODS partners agree on a common pilot-site monitoring protocol",
        tags=("civil-protection", "flood-risk-mapping"),
        body_html="""
<p>At the third project meeting in Murska Sobota, the URBANFLOODS partners agreed on a single
protocol for monitoring the pilot sites in Greece, Slovenia and Bosnia and Herzegovina. Until
now each partner recorded rainfall, water levels and damage in its own format, which made the
results hard to compare.</p>
<h2>What the protocol covers</h2>
<p>The protocol defines the minimum data every pilot collects before, during and after a flood
event, and the format in which it is shared on the platform.</p>
<ul>
<li>Rainfall intensity at 10-minute resolution from at least one gauge per catchment.</li>
<li>Water levels at the critical culverts and drainage outlets.</li>
<li>A short damage log (streets closed, buildings flooded, interventions by civil protection).</li>
</ul>
<h2>Next steps</h2>
<p>Each partner will test the protocol during the coming autumn season and report back at the
next meeting. The data model follows the <a href="https://environment.ec.europa.eu/topics/water/floods_en">EU
Floods Directive</a> reporting categories, so the results can feed into the national flood risk
management plans.</p>
<p>Questions about the protocol can be posted in the forum under <em>Early warning and
data</em>.</p>
""",
    ),
    PostSpec(
        author="member",
        category="best-practices",
        title="Green roofs and retention basins: what two years of pilot data show",
        tags=("NBS", "urban-drainage"),
        knowbase_links=(("measure", 1), ("measure", 2)),
        body_html="""
<p>Two years ago the Sarajevo pilot combined green roofs on public buildings with a small
retention basin at the lowest point of the catchment. This post summarises what the monitoring
data shows and what we would do differently.</p>
<h2>Results</h2>
<p>During the eleven storms recorded, the combination reduced the peak discharge at the outlet
by 18 to 35 percent. The green roofs did most of the work during short, intense showers; the
basin mattered most during long frontal rain, when the roofs were already saturated.</p>
<h3>Lessons learned</h3>
<ol>
<li>Size the basin for the long event, not the intense one: roofs saturate quickly.</li>
<li>Plan maintenance from day one; sediment reduced the basin volume by a tenth in a year.</li>
<li>Involve the building managers early, since they own the roofs and the leaks.</li>
</ol>
<p>Both measures are documented in the KNOWBASE (linked below), and the
<a href="https://naturebasedsolutions.org/">nature-based solutions community</a> has more case
studies of combined grey and green infrastructure.</p>
""",
    ),
    PostSpec(
        author="editor",
        category="events",
        title="Webinar: impact-based early warning for small municipalities",
        tags=("early-warning", "civil-protection"),
        event_in_days=21,
        event_url="https://meet.jit.si/urbanfloods-early-warning-webinar",
        body_html="""
<p>Small municipalities often receive the same generic weather warnings as large cities, but
lack the staff to translate them into local action. This webinar presents how impact-based
warnings can close that gap.</p>
<h2>Programme</h2>
<ul>
<li>From hazard to impact: what an impact-based warning says that a classic one does not.</li>
<li>Thresholds that matter locally: underpasses, schools, low-lying streets.</li>
<li>Reaching residents: SMS, sirens, social media and door-to-door in practice.</li>
</ul>
<h2>Who should attend</h2>
<p>Civil protection officers, municipal engineers and anyone responsible for warning residents.
The session is in English and lasts ninety minutes, with time for questions.</p>
<p>Background reading: the <a href="https://public.wmo.int/en/our-mandate/focus-areas/natural-hazards-and-disaster-risk-reduction">WMO
guidance on multi-hazard impact-based forecasting</a>.</p>
""",
    ),
    PostSpec(
        author="member",
        category="policy",
        title="Putting flood risk maps into municipal spatial plans",
        tags=("flood-risk-mapping", "NBS"),
        body_html="""
<p>Flood hazard and risk maps exist for most areas of potentially significant flood risk, yet
they are still rarely binding in local spatial plans. This note proposes a few practical steps
for planning authorities in the Adriatic-Ionian region.</p>
<h2>Recommendations</h2>
<ul>
<li>Adopt the flood hazard maps as an official layer of the municipal plan.</li>
<li>Restrict new sensitive uses (schools, hospitals) in the high-probability zone.</li>
<li>Require on-site retention or nature-based solutions for new developments.</li>
</ul>
<h2>Why it matters</h2>
<p>Every building permitted in a flood-prone area today is a damage claim tomorrow. Binding
maps give planners a clear legal basis to say no, or to say yes with conditions.</p>
<p>The <a href="https://www.eea.europa.eu/en/topics/in-depth/climate-change-impacts-risks-and-adaptation">European
Environment Agency</a> publishes regular overviews of how member states integrate flood risk
into planning.</p>
""",
    ),
    PostSpec(
        author="admin",
        category="resources",
        title="Checklist: preparing a local flood emergency plan",
        tags=("civil-protection", "early-warning"),
        body_html="""
<p>This checklist helps municipalities review or prepare their local flood emergency plan. It
is based on the plans of the URBANFLOODS pilot municipalities and on national civil protection
guidance.</p>
<h2>Before the flood season</h2>
<ul>
<li>Update the contact list of the emergency team and test it.</li>
<li>Check the warning chain from the national service to residents.</li>
<li>Inspect and clear the critical culverts and storm drains.</li>
<li>Agree evacuation routes and shelters with the neighbouring municipalities.</li>
</ul>
<h2>During and after an event</h2>
<p>Keep a log of every decision with its time. After the event, hold a short debriefing within
two weeks and update the plan with what went wrong.</p>
<p>A printable version of the checklist is available from the
<a href="https://civil-protection-humanitarian-aid.ec.europa.eu/what/civil-protection_en">EU
Civil Protection Mechanism</a> resources page.</p>
""",
    ),
    PostSpec(
        author="admin",
        category="resources",
        title="Reading guide: the Floods Directive and national flood risk management plans",
        tags=("flood-risk-mapping",),
        knowbase_links=(("document", 1),),
        body_html="""
<p>The KNOWBASE holds the main legal and policy documents on flood management in the partner
countries. This guide suggests an order in which to read them.</p>
<h2>Start with the framework</h2>
<p>The Floods Directive (2007/60/EC) sets the three-step cycle every member state follows:
preliminary flood risk assessment, flood hazard and risk maps, and flood risk management
plans, reviewed every six years.</p>
<h2>Then the national level</h2>
<ol>
<li>The national transposition law, which names the competent authorities.</li>
<li>The flood risk management plan for your river basin district.</li>
<li>The programme of measures, with the budget and the responsible bodies.</li>
</ol>
<p>The linked KNOWBASE document is a good starting point; the
<a href="https://water.europa.eu/freshwater">WISE Freshwater portal</a> has the reported plans of
every member state.</p>
""",
    ),
    PostSpec(
        author="admin",
        category="best-practices",
        locale="el",
        title="Λύσεις βασισμένες στη φύση για την αντιπλημμυρική προστασία της Κοζάνης",
        tags=("NBS", "urban-drainage"),
        body_html="""
<p>Ο Δήμος Κοζάνης δοκιμάζει, στο πλαίσιο του έργου URBANFLOODS, λύσεις βασισμένες στη φύση για
τη μείωση της επιφανειακής απορροής σε δύο γειτονιές με συχνά προβλήματα πλημμύρας.</p>
<h2>Τι εφαρμόστηκε</h2>
<ul>
<li>Φυτεμένες τάφροι κατά μήκος δύο κεντρικών δρόμων.</li>
<li>Διαπερατά πλακόστρωτα σε χώρους στάθμευσης.</li>
<li>Μικρός κήπος βροχής στην αυλή ενός σχολείου.</li>
</ul>
<h2>Πρώτα αποτελέσματα</h2>
<p>Στις πρώτες καταιγίδες της χρονιάς οι κάτοικοι ανέφεραν λιγότερα λιμνάζοντα νερά, ενώ οι
μετρήσεις στάθμης στο δίκτυο ομβρίων δείχνουν μικρότερες αιχμές.</p>
<p>Περισσότερες πληροφορίες για το έργο στον
<a href="https://www.interreg-ipa-adrion.eu/">ιστότοπο του προγράμματος Interreg IPA ADRION</a>.</p>
""",
    ),
    PostSpec(
        author="newbie",
        category="best-practices",
        title="Cleaning storm drains before the autumn rains: a municipal routine",
        tags=("urban-drainage",),
        body_html="""
<p>Many of the street floods in our municipality are not caused by extreme rain at all, but by
blocked storm drains. Here is the routine our maintenance crew follows every September.</p>
<h2>The routine</h2>
<ol>
<li>Map the drains that blocked last year and inspect them first.</li>
<li>Remove leaves and sediment from gullies and grates.</li>
<li>Check the outlets to the stream for debris.</li>
</ol>
<h2>Involving residents</h2>
<p>We ask residents to report blocked drains through the municipal app and to keep the grates
in front of their houses clear of leaves.</p>
<p>The <a href="https://www.epa.gov/npdes/stormwater-maintenance">US EPA stormwater maintenance
pages</a> have useful inspection checklists.</p>
""",
    ),
)


# --- summary ----------------------------------------------------------------------------------


@dataclass
class SeedRow:
    created: bool
    cells: tuple[str, ...]


@dataclass
class SeedSummary:
    users: list[SeedRow] = field(default_factory=list)
    posts: list[SeedRow] = field(default_factory=list)
    knowbase_reachable: bool | None = None  # None: no link needed resolving
    warnings: list[str] = field(default_factory=list)


USER_HEADERS = ("EMAIL", "PASSWORD", "ROLE", "TRUSTED", "ORGANISATION")
POST_HEADERS = ("CATEGORY", "STATUS", "LOCALE", "AUTHOR", "KB LINKS", "TITLE")


def _table(headers: Sequence[str], rows: Iterable[SeedRow]) -> list[str]:
    body = [("created" if row.created else "exists", *row.cells) for row in rows]
    head = ("", *headers)
    widths = [max(len(str(r[i])) for r in [head, *body]) for i in range(len(head))]
    return [
        "  ".join(str(cell).ljust(width) for cell, width in zip(r, widths, strict=True)).rstrip()
        for r in [head, *body]
    ]


def format_summary(summary: SeedSummary) -> str:
    created = sum(row.created for row in summary.users + summary.posts)
    lines = ["Accounts", *_table(USER_HEADERS, summary.users), ""]
    lines += ["Posts", *_table(POST_HEADERS, summary.posts), ""]
    kb = {True: "reachable", False: "unreachable (placeholder titles)", None: "not called"}
    lines.append(f"KNOWBASE: {kb[summary.knowbase_reachable]}. Rows created: {created}.")
    return "\n".join(lines)


# --- KNOWBASE ---------------------------------------------------------------------------------


class _ResolvedTitles:
    """Stands in for ``KnowbaseClient`` in ``crud.knowbase_link.replace_links``: answers
    ``resolve_links`` from titles fetched (or made up) once, up front."""

    def __init__(self, titles: Titles) -> None:
        self._titles = titles

    async def resolve_links(self, items: Iterable[tuple[str, int]]) -> Titles:
        keys = [(kb_type, int(kb_id)) for kb_type, kb_id in items]
        return {key: self._titles[key] for key in keys}


def _placeholder(kb_type: str, kb_id: int) -> dict[str, str | None]:
    return {"title_en": f"KNOWBASE {kb_type} {kb_id} (placeholder)", "title_local": None}


async def _resolve_titles(
    knowbase: KnowbaseClient | None, keys: list[LinkKey], summary: SeedSummary
) -> Titles:
    """Real titles where the KNOWBASE answers; placeholders (with a warning) otherwise."""
    titles: Titles = {}
    if knowbase is None:
        summary.knowbase_reachable = False
        summary.warnings.append("no KNOWBASE client: links stored with placeholder titles")
    else:
        try:
            titles = await knowbase.resolve_links(keys)
            summary.knowbase_reachable = True
        except (KnowbaseUnavailable, KnowbaseError) as exc:
            summary.knowbase_reachable = False
            summary.warnings.append(
                f"KNOWBASE unreachable at {settings.KNOWBASE_BASE_URL} "
                f"({type(exc).__name__}: {exc}); links stored with placeholder titles"
            )
    for kb_type, kb_id in keys:
        if titles.get((kb_type, kb_id)) is None:
            if summary.knowbase_reachable:
                summary.warnings.append(
                    f"KNOWBASE {kb_type} {kb_id} not found; stored with a placeholder title"
                )
            titles[(kb_type, kb_id)] = _placeholder(kb_type, kb_id)
    return titles


# --- seed -------------------------------------------------------------------------------------


def _refuse_in_prod() -> None:
    if settings.ENV == "prod":
        raise SeedRefused("refusing to seed demo data with ENV=prod")


async def _reference_data(
    db: AsyncSession,
) -> tuple[dict[str, Category], dict[str, int], dict[str, int]]:
    """Blog categories by slug, partner organisation ids by short name, expertise ids by slug
    (all seeded by the migrations). Raises ``SeedError`` if anything the seed needs is
    missing."""
    categories: dict[str, Category] = {}
    for slug in sorted({spec.category for spec in POSTS}):
        category = await crud_category.get_category(db, kind=CategoryKind.BLOG, slug=slug)
        if category is None or category.is_archived:
            raise SeedError(f"blog category {slug!r} is missing or archived (run the migrations)")
        categories[slug] = category

    wanted_orgs = {spec.organisation for spec in ACCOUNTS if spec.organisation}
    rows = await db.execute(
        select(Organisation.short_name, Organisation.id).where(
            Organisation.short_name.in_(wanted_orgs), Organisation.is_partner.is_(True)
        )
    )
    organisations = {short: org_id for short, org_id in rows.all()}
    if missing := wanted_orgs - set(organisations):
        raise SeedError(f"partner organisations missing: {', '.join(sorted(missing))}")

    wanted_tags = {slug for spec in ACCOUNTS for slug in spec.expertise}
    rows = await db.execute(
        select(ExpertiseTag.slug, ExpertiseTag.id).where(ExpertiseTag.slug.in_(wanted_tags))
    )
    expertise = {slug: tag_id for slug, tag_id in rows.all()}
    if missing := wanted_tags - set(expertise):
        raise SeedError(f"expertise tags missing: {', '.join(sorted(missing))}")
    return categories, organisations, expertise


async def _ensure_account(
    db: AsyncSession,
    spec: AccountSpec,
    *,
    organisations: dict[str, int],
    expertise: dict[str, int],
    summary: SeedSummary,
) -> User:
    user = await crud_user.get_user_by_email(db, email=spec.email)
    created = user is None
    if user is None:
        user = await crud_user.create_user(
            db,
            email=spec.email,
            password=spec.password,
            display_name=spec.display_name,
            organisation_id=organisations[spec.organisation] if spec.organisation else None,
            organisation_other=spec.organisation_other,
            country=spec.country,
            expertise_ids=[expertise[slug] for slug in spec.expertise],
        )
        await crud_user.mark_verified(db, user=user)
        await crud_user.set_role(db, user=user, role=spec.role)
        await crud_user.set_trusted(db, user=user, trusted=spec.trusted)
        await crud_audit.log_action(
            db,
            actor_id=None,
            action="admin.seed_dev_account",
            target_type="user",
            target_id=user.id,
            metadata={"role": spec.role, "trusted": spec.trusted},
        )
    organisation = spec.organisation or f"other: {spec.organisation_other}"
    summary.users.append(
        SeedRow(
            created,
            (
                spec.email,
                spec.password,
                str(user.role),
                "yes" if user.trusted_at else "no",
                organisation,
            ),
        )
    )
    return user


async def _existing_post(db: AsyncSession, *, author: User, title: str) -> Post | None:
    stmt = select(Post).where(Post.author_id == author.id, Post.title == title).limit(1)
    return (await db.scalars(stmt)).first()


def _event_at(now: datetime, in_days: int | None) -> datetime | None:
    """10:00 UTC, ``in_days`` days from now (always in the future for ``in_days >= 1``)."""
    if in_days is None:
        return None
    return (now + timedelta(days=in_days)).replace(hour=10, minute=0, second=0, microsecond=0)


async def seed(
    db: AsyncSession, *, knowbase: KnowbaseClient | None, now: datetime | None = None
) -> SeedSummary:
    """Create whatever is missing. Flushes only; the caller owns the transaction."""
    _refuse_in_prod()
    now = now or datetime.now(UTC)
    summary = SeedSummary()
    categories, organisations, expertise = await _reference_data(db)

    users: dict[str, User] = {}
    for spec in ACCOUNTS:
        users[spec.key] = await _ensure_account(
            db, spec, organisations=organisations, expertise=expertise, summary=summary
        )

    existing = {
        spec: await _existing_post(db, author=users[spec.author], title=spec.title)
        for spec in POSTS
    }
    link_keys = list(
        dict.fromkeys(
            key for spec in POSTS if existing[spec] is None for key in spec.knowbase_links
        )
    )
    titles = await _resolve_titles(knowbase, link_keys, summary) if link_keys else {}
    resolver = _ResolvedTitles(titles)

    for spec in POSTS:
        post = existing[spec]
        created = post is None
        if post is None:
            post = await crud_post.create_post(
                db,
                author=users[spec.author],
                category_id=categories[spec.category].id,
                title=spec.title,
                body_html=spec.body_html,
                locale=spec.locale,
                event_at=_event_at(now, spec.event_in_days),
                event_url=spec.event_url,
                tag_names=spec.tags,
                knowbase_links=spec.knowbase_links,
                knowbase=cast(KnowbaseClient, resolver),
                now=now,
            )
        summary.posts.append(
            SeedRow(
                created,
                (
                    spec.category,
                    str(post.status),
                    post.locale,
                    spec.author,
                    str(len(spec.knowbase_links)),
                    spec.title,
                ),
            )
        )
    return summary


# --- command line -----------------------------------------------------------------------------


async def _run() -> SeedSummary:
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    knowbase = KnowbaseClient()
    try:
        async with AsyncSessionLocal(bind=engine) as db, db.begin():
            return await seed(db, knowbase=knowbase)
    finally:
        await knowbase.aclose()
        await engine.dispose()


def _describe(exc: BaseException) -> str:
    if isinstance(exc, AppError):
        fields = ", ".join(f"{k}={v}" for k, v in (exc.fields or {}).items())
        return f"{exc.code}: {fields or exc.message}"
    if isinstance(exc, SeedError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.seed_dev", description=__doc__.split("\n")[0]
    )
    parser.parse_args(argv)
    try:
        _refuse_in_prod()
        summary = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 - any failure: nothing was committed, exit 1
        print(f"error: seed failed, nothing was written ({_describe(exc)})", file=sys.stderr)
        return 1
    # Printed only once the transaction has committed.
    print(format_summary(summary))
    for warning in summary.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

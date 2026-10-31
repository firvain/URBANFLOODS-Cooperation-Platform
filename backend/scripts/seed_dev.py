"""Development seed: demo personas and content. Never for production.

    cd backend && uv run python -m scripts.seed_dev [--reset]

Creates, if missing, twelve fictional personas at ``@urbanfloods.example`` that cover every
account state (a superadmin, two admins, trusted members, untrusted members, a free-text
organisation, an unverified, a banned and an anonymised account, a minimal profile; one shared
password, see ``backend/README.md``), eleven blog posts (every blog category, a Greek post, one
pending post, two admin-only Resources posts, KNOWBASE links on two posts), comments, and four
forum threads with replies. Existing accounts (by email; the anonymised one by its seed audit
row) and posts/threads (by title, among the demo accounts' content) are left untouched, so
running it again changes nothing.

``--reset`` first hard-deletes every demo account (``@urbanfloods.example``, plus the seeded
anonymised one) with everything it authored: posts, threads, replies, comments, reports, uploads
(rows, and their files once committed); comments and replies by other accounts under a deleted
post or thread go with it (counted in a warning). Then it seeds afresh. Accounts outside the demo
domain and their own content stay.

Everything goes through the crud layer (sanitisation, slugs, tag counts, the trust model) in one
transaction: on any error nothing is written, the error goes to stderr and the exit code is 1.
KNOWBASE titles are resolved through the real proxy; if it is unreachable the links are stored
with placeholder titles and a warning is printed. Refuses to run unless ``ENV`` is ``dev`` or
``test``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, delete, func, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.exceptions import AppError
from app.crud import audit as crud_audit
from app.crud import category as crud_category
from app.crud import comment as crud_comment
from app.crud import post as crud_post
from app.crud import reply as crud_reply
from app.crud import thread as crud_thread
from app.crud import user as crud_user
from app.crud.tag import recount_tag_usage
from app.db.enums import CategoryKind, ContentType, UserRole
from app.db.models import (
    Attachment,
    AuditLog,
    Category,
    Comment,
    ExpertiseTag,
    KnowbaseLink,
    Organisation,
    Post,
    Reply,
    Report,
    Thread,
    User,
    post_tags,
    thread_tags,
)
from app.db.session import AsyncSessionLocal
from app.services import images
from app.services.knowbase import KnowbaseClient, KnowbaseError, KnowbaseUnavailable

LinkKey = tuple[str, int]
Titles = dict[LinkKey, dict[str, str | None] | None]
UploadFiles = list[tuple[str, str | None]]

# The one password of every demo account (documented in backend/README.md, never printed).
PASSWORD = "Urbanfloods-2026"
DEMO_DOMAIN = "@urbanfloods.example"
SEED_ACTION = "admin.seed_dev_account"
RESET_ACTION = "admin.seed_dev_reset"
ALLOWED_ENVS = frozenset({"dev", "test"})
# The e2e suite's anchor post (frontend/e2e: blog, forum and a11y specs).
GREEN_ROOFS_SLUG = "green-roofs-and-retention-basins-what-two-years-of-pilot-data-show"


class SeedError(Exception):
    """The seed cannot run (missing reference data, rejected input): exit code 1."""


class SeedRefused(SeedError):
    """``ENV`` is not ``dev`` or ``test``."""


# --- accounts ---------------------------------------------------------------------------------


# The member notifications a demo persona switches on (``AccountSpec.notifications_on``).
MEMBER_NOTIFICATIONS = (
    "reply_to_my_thread",
    "comment_on_my_post",
    "reply_to_my_reply",
    "moderation_decisions",
)


@dataclass(frozen=True)
class AccountSpec:
    key: str
    email: str
    display_name: str
    role: UserRole = UserRole.MEMBER
    verified: bool = True
    trusted: bool = False
    banned: bool = False  # deactivated after its content is written
    anonymise: bool = False  # ``anonymise_user`` after its content is written
    organisation: str | None = None  # partner short name (docs/partners.md)
    organisation_other: str | None = None
    country: str | None = None
    locale: str = "en"
    bio: str | None = None
    expertise: tuple[str, ...] = ()  # expertise tag slugs
    show_email: bool = False
    show_in_directory: bool = True
    # Member notifications (replies, comments, moderation decisions) are off by default for new
    # accounts since 2026-10-31. The demo personas opt in so the e2e suite (forum.spec.ts: the
    # reply email to the editor, the notifications-tab switches) and the manual QA in Mailpit
    # keep working; the "minimal" persona keeps the defaults of a fresh account. Production
    # never runs this seed.
    notifications_on: bool = True


ACCOUNTS: tuple[AccountSpec, ...] = (
    AccountSpec(
        key="superadmin",
        email="eleni.papadopoulou@urbanfloods.example",
        display_name="Eleni Papadopoulou",
        role=UserRole.SUPERADMIN,
        trusted=True,
        organisation="UOWM",
        country="GR",
        locale="el",
        bio="Lead partner coordinator at the University of Western Macedonia. Hydraulic "
        "engineer working on flood hazard mapping for small Greek towns.",
        expertise=("flood-risk-mapping", "hydraulic-modelling", "gis-remote-sensing"),
    ),
    AccountSpec(
        key="admin_si",
        email="matej.kovacic@urbanfloods.example",
        display_name="Matej Kovačič",
        role=UserRole.ADMIN,
        trusted=True,
        organisation="DCMS",
        country="SI",
        locale="sl",
        bio="Project manager at the Development Centre Murska Sobota; moderates the platform "
        "and organises the partner meetings.",
        expertise=("civil-protection", "community-engagement"),
    ),
    AccountSpec(
        key="admin_mk",
        email="aleksandar.stojanovski@urbanfloods.example",
        display_name="Aleksandar Stojanovski",
        role=UserRole.ADMIN,
        trusted=True,
        organisation="FCSE-UKIM",
        country="MK",
        locale="mk",
        bio="Researcher at the Faculty of Computer Science and Engineering in Skopje, working "
        "on decision support and early-warning data pipelines.",
        expertise=("data-science-dss", "early-warning-systems", "gis-remote-sensing"),
    ),
    AccountSpec(
        key="member_it",
        email="giulia.romano@urbanfloods.example",
        display_name="Giulia Romano",
        trusted=True,
        organisation="MC",
        country="IT",
        locale="it",
        bio="Urban planner at the Municipality of Macerata, leading the pilot on green roofs "
        "and sustainable drainage in the historic centre.",
        expertise=("urban-planning", "nature-based-solutions", "green-blue-infrastructure"),
        show_email=True,
    ),
    AccountSpec(
        key="member_hr",
        email="ivana.babic@urbanfloods.example",
        display_name="Ivana Babić",
        trusted=True,
        organisation="RDA Porin",
        country="HR",
        locale="hr",
        bio="Climate adaptation advisor at the Rijeka Development Agency PORIN.",
        expertise=("climate-adaptation", "policy-governance", "economics-insurance"),
    ),
    AccountSpec(
        key="member_rs",
        email="nikola.petrovic@urbanfloods.example",
        display_name="Nikola Petrović",
        trusted=True,
        organisation="RDA Backa",
        country="RS",
        locale="sr",
        bio="Water engineer at the Regional Development Agency Backa, Novi Sad.",
        expertise=("hydrology", "river-basin-management"),
        show_in_directory=False,
    ),
    AccountSpec(
        key="newbie_al",
        email="arben.hoxha@urbanfloods.example",
        display_name="Arben Hoxha",
        organisation="HydrowaterAL",
        country="AL",
        locale="sq",
        expertise=("water-supply-sewerage",),
    ),
    AccountSpec(
        key="newbie_ba",
        email="amra.hadzic@urbanfloods.example",
        display_name="Amra Hadžić",
        organisation_other="City of Zenica",
        country="BA",
        locale="bs",
        expertise=("civil-protection",),
    ),
    AccountSpec(
        key="unverified",
        email="dimitris.karagiannis@urbanfloods.example",
        display_name="Dimitris Karagiannis",
        verified=False,
        organisation_other="Municipality of Florina",
        country="GR",
        locale="el",
    ),
    AccountSpec(
        key="banned",
        email="sara.conti@urbanfloods.example",
        display_name="Sara Conti",
        trusted=True,
        banned=True,
        organisation="Modica",
        country="IT",
        locale="en",
        expertise=("meteorology",),
    ),
    AccountSpec(
        key="anonymised",
        email="kostas.nikolaidis@urbanfloods.example",
        display_name="Kostas Nikolaidis",
        trusted=True,
        anonymise=True,
        organisation="DEYAK",
        country="GR",
        locale="el",
        expertise=("water-supply-sewerage", "environmental-engineering"),
    ),
    AccountSpec(
        key="minimal",
        email="petra.vidmar@urbanfloods.example",
        display_name="Petra Vidmar",
        notifications_on=False,
    ),
)


# --- content ----------------------------------------------------------------------------------


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
        author="admin_si",
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
        author="member_it",
        category="best-practices",
        title="Green roofs and retention basins: what two years of pilot data show",
        tags=("NBS", "urban-drainage"),
        knowbase_links=(("measure", 14), ("measure", 17)),
        body_html="""
<p>Two years ago the Sarajevo pilot, run by our partners at the Hydro-Engineering Institute,
combined green roofs on public buildings with a small retention basin at the lowest point of the
catchment. In Macerata we are now planning the same combination, so this post summarises what
the monitoring data shows and what we would do differently.</p>
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
        author="admin_mk",
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
        author="member_hr",
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
        author="superadmin",
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
        author="admin_mk",
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
        author="superadmin",
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
        author="newbie_ba",
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
    PostSpec(
        author="member_rs",
        category="best-practices",
        title="Reopening the old drainage canals of a Vojvodina lowland town",
        tags=("urban-drainage", "flood-risk-mapping"),
        body_html="""
<p>Many towns in Vojvodina were built next to a dense network of drainage canals dug for
agriculture. As the towns grew, some canals were piped or filled in, and the streets above them
are now the first to flood after heavy rain.</p>
<h2>What we did</h2>
<ul>
<li>Mapped the historic canals from cadastral maps of the 1960s and compared them with today.</li>
<li>Reopened a 400-metre stretch as a green channel with gentle, planted banks.</li>
<li>Agreed a maintenance plan with the public water management company.</li>
</ul>
<h2>First results</h2>
<p>During the spring storms the reopened stretch carried water that previously ponded in two
residential streets. Residents now use the banks as a walking path, which helped a lot with
acceptance.</p>
<p>The <a href="https://www.icpdr.org/">International Commission for the Protection of the Danube
River</a> publishes good examples of floodplain and canal restoration in the basin.</p>
""",
    ),
    PostSpec(
        author="banned",
        category="news",
        title="Rain gauges on school roofs: a citizen-science start in Modica",
        tags=("early-warning", "citizen-science"),
        body_html="""
<p>Five primary schools in Modica now host a simple tipping-bucket rain gauge on their roof. The
pupils read the data every morning and compare it with the regional weather service.</p>
<h2>Why schools</h2>
<ul>
<li>They are spread across the town, so the gauges cover several small catchments.</li>
<li>Teachers use the readings in maths and science lessons.</li>
<li>Families learn what a warning threshold means in their own street.</li>
</ul>
<h2>Next steps</h2>
<p>The municipality will compare the school readings with the street-flooding reports from the
last two autumns, to see whether local thresholds can be set.</p>
<p>The <a href="https://www.globe.gov/">GLOBE programme</a> offers free protocols for school
weather observations.</p>
""",
    ),
    PostSpec(
        author="anonymised",
        category="best-practices",
        title="Level sensors in a combined sewer network: lessons from the first season",
        tags=("urban-drainage", "early-warning"),
        body_html="""
<p>Last year twelve ultrasonic level sensors were installed in the combined sewer network of
Kozani, at the points where overflows into the streets were reported most often.</p>
<h2>What worked</h2>
<ul>
<li>Battery-powered sensors with mobile data: no cabling, installed in a day each.</li>
<li>A simple dashboard for the operations team, with alarms at two levels.</li>
</ul>
<h2>What did not</h2>
<p>Two sensors drifted after fat deposits built up on the housing, and one lost its signal
under a parked lorry. Regular cleaning is now part of the monthly inspection round.</p>
<p>The <a href="https://www.iwa-network.org/">International Water Association</a> has useful
material on smart sewer monitoring.</p>
""",
    ),
)


# Comments on the posts above, by post title: (author key, body html), oldest first.
COMMENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "Green roofs and retention basins: what two years of pilot data show": (
        (
            "member_rs",
            "<p>Very useful. Did you measure how long the roofs took to recover their storage "
            "between storms?</p>",
        ),
        (
            "superadmin",
            "<p>We saw the same saturation effect in Kozani. Sizing the basin for the long "
            "event is the key lesson.</p>",
        ),
        (
            "anonymised",
            "<p>Sediment in the basin is our problem too; a settling chamber at the inlet "
            "helped a lot.</p>",
        ),
    ),
    "Putting flood risk maps into municipal spatial plans": (
        (
            "admin_si",
            "<p>In Slovenia the hazard maps are already binding for new permits; happy to share "
            "the regulation.</p>",
        ),
        (
            "member_it",
            "<p>Macerata is revising its plan next year, so this comes at the right time.</p>",
        ),
    ),
    "Webinar: impact-based early warning for small municipalities": (
        ("newbie_ba", "<p>Will a recording be available for colleagues who cannot attend?</p>"),
    ),
    "Reopening the old drainage canals of a Vojvodina lowland town": (
        (
            "banned",
            "<p>Lovely example. How did you convince the owners of the plots along the canal?</p>",
        ),
    ),
}


@dataclass(frozen=True)
class ReplySpec:
    author: str  # AccountSpec.key
    body_html: str
    parent: int | None = None  # index of an earlier top-level reply in the same thread


@dataclass(frozen=True)
class ThreadSpec:
    author: str  # AccountSpec.key
    category: str  # forum category slug
    title: str
    body_html: str
    tags: tuple[str, ...]
    replies: tuple[ReplySpec, ...]
    pinned: bool = False


THREADS: tuple[ThreadSpec, ...] = (
    ThreadSpec(
        author="admin_si",
        category="general",
        title="Welcome: introduce yourself and your organisation",
        pinned=True,
        tags=("introductions",),
        body_html="""
<p>Welcome to the URBANFLOODS Cooperation Platform. Please introduce yourself in a reply: who
you are, where you work and which flood topics you would like to discuss with the other
partners.</p>
<p>I am the project manager at the Development Centre Murska Sobota and one of the moderators.</p>
""",
        replies=(
            ReplySpec(
                "member_it",
                "<p>Hello from Macerata! I lead our green roofs pilot and I am keen to compare "
                "notes on sustainable drainage in historic centres.</p>",
            ),
            ReplySpec(
                "newbie_al",
                "<p>Arben from Hydrowater-Albania here. We work on water supply and sewerage "
                "networks in Tirana and Durrës.</p>",
            ),
            ReplySpec(
                "newbie_ba",
                "<p>Hi all, I work in civil protection for the City of Zenica. Our main issue is "
                "flash flooding from the hills around the town.</p>",
            ),
            ReplySpec(
                "minimal",
                "<p>Hello! I joined to follow the discussions on early warning.</p>",
            ),
        ),
    ),
    ThreadSpec(
        author="member_it",
        category="measures",
        title="Permeable paving in historic centres: has anyone made it work?",
        tags=("NBS", "urban-drainage"),
        body_html="""
<p>Our heritage office is wary of permeable paving in the old town: it fears that the stone
must change and that the joints will clog. Has anyone installed permeable paving in a protected
historic centre? Which materials did the heritage authority accept?</p>
""",
        replies=(
            ReplySpec(
                "member_hr",
                "<p>In Rijeka we used wide, gravel-filled joints between the original stones. "
                "The heritage office accepted it because the stone itself did not change.</p>",
            ),
            ReplySpec(
                "member_rs",
                "<p>How often do you have to clean the joints? That is what worries our "
                "maintenance company.</p>",
                parent=0,
            ),
            ReplySpec(
                "superadmin",
                "<p>The KNOWBASE has a measure on permeable surfaces with two Greek examples; "
                "worth a look before you meet the heritage office.</p>",
            ),
            ReplySpec(
                "banned",
                "<p>We tried it in a car park in Modica, but not yet in the old town.</p>",
            ),
        ),
    ),
    ThreadSpec(
        author="member_rs",
        category="early-warning",
        title="How dense should a rain-gauge network be for a small urban catchment?",
        tags=("early-warning", "rain-gauges"),
        body_html="""
<p>We are planning gauges for a town of about 40,000 inhabitants with three small urban
catchments. The national service has one gauge in the area. How many gauges per square
kilometre do you use, and at what time resolution?</p>
""",
        replies=(
            ReplySpec(
                "admin_mk",
                "<p>For convective storms one gauge per 2 to 4 square kilometres at 5-minute "
                "resolution is a reasonable start. Weather radar helps fill the gaps.</p>",
            ),
            ReplySpec(
                "anonymised",
                "<p>Place at least one gauge next to the sewer sensors, so you can relate "
                "rainfall to water levels directly.</p>",
            ),
            ReplySpec(
                "newbie_al",
                "<p>Thank you, this is useful for our network in Durrës as well.</p>",
                parent=0,
            ),
        ),
    ),
    ThreadSpec(
        author="member_hr",
        category="policy",
        title="Flood insurance in the partner countries: who pays after an event?",
        tags=("insurance", "policy"),
        body_html="""
<p>In Croatia most households have no flood cover, and after an event the state and the
municipalities end up paying. How does it work in your countries? Are there public-private
schemes we could learn from?</p>
""",
        replies=(
            ReplySpec(
                "superadmin",
                "<p>In Greece private flood cover is rare too; compensation goes through state "
                "relief programmes after each declared emergency.</p>",
            ),
            ReplySpec(
                "admin_si",
                "<p>Slovenia has discussed a mandatory scheme for years. I can share the latest "
                "proposal in English.</p>",
            ),
            ReplySpec(
                "member_hr",
                "<p>Thank you, Matej, that would be very helpful.</p>",
                parent=1,
            ),
        ),
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
    threads: list[SeedRow] = field(default_factory=list)
    replies_created: int = 0
    comments_created: int = 0
    knowbase_reachable: bool | None = None  # None: no link needed resolving
    # ``--reset`` only: rows deleted, by kind.
    reset: dict[str, int] | None = None
    # ``(storage_path, thumb_path)`` of the uploads ``--reset`` deleted: removed after commit.
    files: UploadFiles = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def rows_created(self) -> int:
        tops = sum(row.created for row in self.users + self.posts + self.threads)
        return tops + self.replies_created + self.comments_created


USER_HEADERS = ("EMAIL", "NAME", "ROLE", "STATE", "ORGANISATION")
POST_HEADERS = ("CATEGORY", "STATUS", "LOCALE", "AUTHOR", "KB LINKS", "TITLE")
THREAD_HEADERS = ("CATEGORY", "STATUS", "AUTHOR", "REPLIES", "TITLE")


def account_state(user: User) -> str:
    """The account's state in words, as the summary table and the README show it."""
    if user.deleted_at is not None:
        return "anonymised"
    parts = ["banned"] if not user.is_active else []
    parts.append("verified" if user.is_verified else "unverified")
    parts.append("trusted" if user.trusted_at is not None else "untrusted")
    if not user.show_in_directory:
        parts.append("hidden from directory")
    if user.show_email:
        parts.append("shows email")
    return ", ".join(parts)


def _table(headers: Sequence[str], rows: Iterable[SeedRow]) -> list[str]:
    body = [("created" if row.created else "exists", *row.cells) for row in rows]
    head = ("", *headers)
    widths = [max(len(str(r[i])) for r in [head, *body]) for i in range(len(head))]
    return [
        "  ".join(str(cell).ljust(width) for cell, width in zip(r, widths, strict=True)).rstrip()
        for r in [head, *body]
    ]


def format_summary(summary: SeedSummary) -> str:
    """The tables printed after commit. Never a password or a hash."""
    lines: list[str] = []
    if summary.reset is not None:
        labels = {"kept_authors_children": "comments/replies by other accounts"}
        deleted = ", ".join(
            f"{count} {labels.get(kind, kind)}" for kind, count in summary.reset.items()
        )
        lines += [f"Reset: deleted {deleted}.", ""]
    lines += ["Accounts", *_table(USER_HEADERS, summary.users), ""]
    lines += ["Posts", *_table(POST_HEADERS, summary.posts), ""]
    lines += ["Threads", *_table(THREAD_HEADERS, summary.threads), ""]
    kb = {True: "reachable", False: "unreachable (placeholder titles)", None: "not called"}
    lines.append(
        f"KNOWBASE: {kb[summary.knowbase_reachable]}. Rows created: {summary.rows_created} "
        f"(replies {summary.replies_created}, comments {summary.comments_created})."
    )
    lines.append("Demo accounts password: see README (backend/README.md).")
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


# --- demo accounts ----------------------------------------------------------------------------


def _refuse_outside_dev() -> None:
    if settings.ENV not in ALLOWED_ENVS:
        raise SeedRefused(f"refusing to seed demo data with ENV={settings.ENV} (dev/test only)")


def _seed_audit_target() -> Any:
    """``users.id = audit_log.target_id`` for the seed's own account rows."""
    return and_(
        AuditLog.action == SEED_ACTION,
        AuditLog.target_type == "user",
        AuditLog.target_id == User.id,
    )


async def demo_user_ids(db: AsyncSession) -> list[int]:
    """Every demo account: the ``@urbanfloods.example`` addresses, plus seeded accounts that
    were anonymised since (their address is now ``deleted-<id>@invalid``; the seed's audit row
    still names them). Nothing else: other accounts, anonymised or not, are never demo data."""
    by_email = select(User.id).where(User.email.ilike(f"%{DEMO_DOMAIN}"))
    anonymised = (
        select(User.id)
        .join(AuditLog, _seed_audit_target())
        .where(User.deleted_at.is_not(None), User.email.like("deleted-%@invalid"))
    )
    return sorted((await db.scalars(union(by_email, anonymised))).all())


async def _find_account(db: AsyncSession, spec: AccountSpec) -> User | None:
    user = await crud_user.get_user_by_email(db, email=spec.email)
    if user is None and spec.anonymise:
        stmt = (
            select(User)
            .join(AuditLog, _seed_audit_target())
            .where(
                AuditLog.metadata_["persona"].astext == spec.key,
                User.deleted_at.is_not(None),
                User.email.like("deleted-%@invalid"),
            )
            .order_by(User.id.desc())
            .limit(1)
        )
        user = (await db.scalars(stmt)).first()
    if user is None:
        return None
    return await crud_user.get_user_by_id(db, user_id=user.id)


async def _create_account(
    db: AsyncSession,
    spec: AccountSpec,
    *,
    organisations: dict[str, int],
    expertise: dict[str, int],
    now: datetime,
) -> User:
    """A new account in its pre-content state: banning and anonymising come after its content
    (``_finalise_account``)."""
    user = await crud_user.create_user(
        db,
        email=spec.email,
        password=PASSWORD,
        display_name=spec.display_name,
        organisation_id=organisations[spec.organisation] if spec.organisation else None,
        organisation_other=spec.organisation_other,
        country=spec.country,
        locale=spec.locale,
        expertise_ids=[expertise[slug] for slug in spec.expertise],
    )
    await crud_user.update_profile(
        db,
        user=user,
        changes={
            "bio": spec.bio,
            "show_email": spec.show_email,
            "show_in_directory": spec.show_in_directory,
        },
    )
    if spec.notifications_on:
        preferences = await crud_user.get_notification_preferences(db, user=user)
        for name in MEMBER_NOTIFICATIONS:
            setattr(preferences, name, True)
        await db.flush()
    if spec.verified:
        await crud_user.mark_verified(db, user=user, now=now)
    await crud_user.set_role(db, user=user, role=spec.role)
    await crud_user.set_trusted(db, user=user, trusted=spec.trusted, now=now)
    await crud_audit.log_action(
        db,
        actor_id=None,
        action=SEED_ACTION,
        target_type="user",
        target_id=user.id,
        metadata={
            "persona": spec.key,
            "role": spec.role,
            "verified": spec.verified,
            "trusted": spec.trusted,
            "banned": spec.banned,
            "anonymised": spec.anonymise,
        },
    )
    return user


async def _finalise_account(db: AsyncSession, spec: AccountSpec, user: User, now: datetime) -> None:
    if spec.banned:
        await crud_user.set_active(db, user=user, active=False, now=now)
    if spec.anonymise:
        await crud_user.anonymise_user(db, user=user, now=now)


def _user_row(spec: AccountSpec, user: User, *, created: bool) -> SeedRow:
    if user.organisation_id is not None and user.organisation is not None:
        organisation = user.organisation.short_name
    elif user.organisation_other:
        organisation = f"other: {user.organisation_other}"
    else:
        organisation = "-"
    return SeedRow(
        created,
        (str(user.email), user.display_name, str(user.role), account_state(user), organisation),
    )


# --- reset ------------------------------------------------------------------------------------


async def _ids(db: AsyncSession, stmt: Any) -> list[int]:
    return list((await db.scalars(stmt)).all())


async def reset_demo_data(db: AsyncSession, summary: SeedSummary) -> None:
    """Hard-delete every demo account and what it authored, in foreign-key order. Records the
    counts in ``summary.reset`` and the deleted uploads' paths in ``summary.files`` (removed
    from disk by the caller once the transaction has committed). Flushes only."""
    counts = dict.fromkeys(
        (
            "users",
            "posts",
            "threads",
            "replies",
            "comments",
            "reports",
            "attachments",
            "kept_authors_children",
        ),
        0,
    )
    summary.reset = counts
    user_ids = await demo_user_ids(db)
    if not user_ids:
        return
    post_ids = await _ids(db, select(Post.id).where(Post.author_id.in_(user_ids)))
    thread_ids = await _ids(db, select(Thread.id).where(Thread.author_id.in_(user_ids)))
    reply_ids = await _ids(
        db,
        select(Reply.id).where(or_(Reply.author_id.in_(user_ids), Reply.thread_id.in_(thread_ids))),
    )
    comment_ids = await _ids(
        db,
        select(Comment.id).where(
            or_(Comment.author_id.in_(user_ids), Comment.post_id.in_(post_ids))
        ),
    )
    # Other accounts' replies and comments under a demo thread or post go with it.
    for model, ids in ((Reply, reply_ids), (Comment, comment_ids)):
        kept = await db.scalar(
            select(func.count())
            .select_from(model)
            .where(model.id.in_(ids), model.author_id.is_not(None))
            .where(model.author_id.not_in(user_ids))
        )
        counts["kept_authors_children"] += kept or 0
    tag_ids = await _ids(
        db, select(post_tags.c.tag_id).where(post_tags.c.post_id.in_(post_ids))
    ) + await _ids(db, select(thread_tags.c.tag_id).where(thread_tags.c.thread_id.in_(thread_ids)))
    uploads = (
        await db.execute(
            select(Attachment.id, Attachment.storage_path, Attachment.thumb_path).where(
                Attachment.uploader_id.in_(user_ids)
            )
        )
    ).all()

    targets = [
        (ContentType.POST, post_ids),
        (ContentType.THREAD, thread_ids),
        (ContentType.REPLY, reply_ids),
        (ContentType.COMMENT, comment_ids),
    ]
    on_deleted = [
        and_(Report.content_type == kind, Report.content_id.in_(ids))
        for kind, ids in targets
        if ids
    ]
    counts["reports"] = await _delete(
        db, Report, or_(Report.reporter_id.in_(user_ids), *on_deleted)
    )
    await _delete(
        db,
        KnowbaseLink,
        or_(
            and_(
                KnowbaseLink.content_type == ContentType.POST,
                KnowbaseLink.content_id.in_(post_ids),
            ),
            and_(
                KnowbaseLink.content_type == ContentType.THREAD,
                KnowbaseLink.content_id.in_(thread_ids),
            ),
        ),
    )
    # Second-level replies first, so their parent's ``ON DELETE SET NULL`` has nothing to do.
    counts["replies"] = await _delete(
        db, Reply, and_(Reply.id.in_(reply_ids), Reply.parent_reply_id.is_not(None))
    )
    counts["replies"] += await _delete(db, Reply, Reply.id.in_(reply_ids))
    counts["comments"] = await _delete(db, Comment, Comment.id.in_(comment_ids))
    counts["posts"] = await _delete(db, Post, Post.id.in_(post_ids))
    counts["threads"] = await _delete(db, Thread, Thread.id.in_(thread_ids))
    await recount_tag_usage(db, tag_ids=tag_ids)
    counts["attachments"] = await _delete(
        db, Attachment, Attachment.id.in_([row.id for row in uploads])
    )
    # Sessions, email tokens, notification preferences and expertise rows cascade.
    counts["users"] = await _delete(db, User, User.id.in_(user_ids))

    summary.files.extend((row.storage_path, row.thumb_path) for row in uploads)
    if counts["kept_authors_children"]:
        summary.warnings.append(
            f"{counts['kept_authors_children']} comment(s) or reply(ies) by accounts outside "
            f"{DEMO_DOMAIN} were deleted with the demo post or thread they answered"
        )
    await crud_audit.log_action(
        db, actor_id=None, action=RESET_ACTION, target_type="user", metadata=dict(counts)
    )


async def _delete(db: AsyncSession, model: type[Any], where: Any) -> int:
    """ORM bulk delete (``synchronize_session='fetch'``: deleted objects leave the session).
    Returns the number of rows."""
    stmt = delete(model).where(where).execution_options(synchronize_session="fetch")
    result = await db.execute(stmt)
    return cast(int, getattr(result, "rowcount", 0) or 0)


# --- seed -------------------------------------------------------------------------------------


async def _category_map(
    db: AsyncSession, kind: CategoryKind, slugs: Iterable[str]
) -> dict[str, Category]:
    categories: dict[str, Category] = {}
    for slug in sorted(set(slugs)):
        category = await crud_category.get_category(db, kind=kind, slug=slug)
        if category is None or category.is_archived:
            raise SeedError(
                f"{kind.value} category {slug!r} is missing or archived (run the migrations)"
            )
        categories[slug] = category
    return categories


async def _reference_data(
    db: AsyncSession,
) -> tuple[dict[str, Category], dict[str, Category], dict[str, int], dict[str, int]]:
    """Blog and forum categories by slug, partner organisation ids by short name, expertise ids
    by slug (all seeded by the migrations). Raises ``SeedError`` if anything the seed needs is
    missing."""
    blog = await _category_map(db, CategoryKind.BLOG, (spec.category for spec in POSTS))
    forum = await _category_map(db, CategoryKind.FORUM, (spec.category for spec in THREADS))

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
    return blog, forum, organisations, expertise


async def _existing(
    db: AsyncSession, model: type[Any], *, title: str, author_ids: list[int]
) -> Any:
    """A demo account's post or thread with this title (whoever of them wrote it)."""
    stmt = (
        select(model)
        .where(model.title == title, model.author_id.in_(author_ids))
        .order_by(model.id)
        .limit(1)
    )
    return (await db.scalars(stmt)).first()


def _event_at(now: datetime, in_days: int | None) -> datetime | None:
    """10:00 UTC, ``in_days`` days from now (always in the future for ``in_days >= 1``)."""
    if in_days is None:
        return None
    return (now + timedelta(days=in_days)).replace(hour=10, minute=0, second=0, microsecond=0)


async def _seed_posts(
    db: AsyncSession,
    *,
    users: dict[str, User],
    categories: dict[str, Category],
    knowbase: KnowbaseClient | None,
    now: datetime,
    summary: SeedSummary,
) -> None:
    author_ids = await demo_user_ids(db)
    existing = {
        spec: await _existing(db, Post, title=spec.title, author_ids=author_ids) for spec in POSTS
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
            # Comments come with a new post only, so a rerun never duplicates them.
            for author, body_html in COMMENTS.get(spec.title, ()):
                await crud_comment.create_comment(
                    db, post=post, author=users[author], body_html=body_html, now=now
                )
                summary.comments_created += 1
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


async def _seed_threads(
    db: AsyncSession,
    *,
    users: dict[str, User],
    categories: dict[str, Category],
    now: datetime,
    summary: SeedSummary,
) -> None:
    author_ids = await demo_user_ids(db)
    for spec in THREADS:
        thread = await _existing(db, Thread, title=spec.title, author_ids=author_ids)
        created = thread is None
        if thread is None:
            thread = await crud_thread.create_thread(
                db,
                author=users[spec.author],
                category_id=categories[spec.category].id,
                title=spec.title,
                body_html=spec.body_html,
                tag_names=spec.tags,
                now=now,
            )
            if spec.pinned:
                await crud_thread.set_pinned(db, thread=thread, pinned=True)
            # Replies come with a new thread only, so a rerun never duplicates them.
            reply_ids: list[int] = []
            for reply_spec in spec.replies:
                parent = None if reply_spec.parent is None else reply_ids[reply_spec.parent]
                reply = await crud_reply.create_reply(
                    db,
                    thread=thread,
                    author=users[reply_spec.author],
                    body_html=reply_spec.body_html,
                    parent_reply_id=parent,
                    now=now,
                )
                reply_ids.append(reply.id)
                summary.replies_created += 1
        summary.threads.append(
            SeedRow(
                created,
                (
                    spec.category,
                    str(thread.status),
                    spec.author,
                    str(len(spec.replies)),
                    spec.title,
                ),
            )
        )


async def seed(
    db: AsyncSession,
    *,
    knowbase: KnowbaseClient | None,
    now: datetime | None = None,
    reset: bool = False,
) -> SeedSummary:
    """Create whatever is missing (after deleting all demo data first with ``reset``). Flushes
    only; the caller owns the transaction and removes ``summary.files`` after commit."""
    _refuse_outside_dev()
    now = now or datetime.now(UTC)
    summary = SeedSummary()
    if reset:
        await reset_demo_data(db, summary)
    blog, forum, organisations, expertise = await _reference_data(db)

    users: dict[str, User] = {}
    created: set[str] = set()
    for spec in ACCOUNTS:
        user = await _find_account(db, spec)
        if user is None:
            user = await _create_account(
                db, spec, organisations=organisations, expertise=expertise, now=now
            )
            created.add(spec.key)
        users[spec.key] = user

    await _seed_posts(db, users=users, categories=blog, knowbase=knowbase, now=now, summary=summary)
    await _seed_threads(db, users=users, categories=forum, now=now, summary=summary)

    # Banned and anonymised states last: their content was written while they were active.
    for spec in ACCOUNTS:
        if spec.key in created:
            await _finalise_account(db, spec, users[spec.key], now)
    for spec in ACCOUNTS:
        user = await crud_user.get_user_by_id(db, user_id=users[spec.key].id)
        assert user is not None
        summary.users.append(_user_row(spec, user, created=spec.key in created))
    return summary


# --- command line -----------------------------------------------------------------------------


async def _run(*, reset: bool) -> SeedSummary:
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    knowbase = KnowbaseClient()
    try:
        async with AsyncSessionLocal(bind=engine) as db, db.begin():
            summary = await seed(db, knowbase=knowbase, reset=reset)
    finally:
        await knowbase.aclose()
        await engine.dispose()
    # Only once the deletions have committed.
    for storage_path, thumb_path in summary.files:
        images.delete_files(settings.UPLOAD_DIR, storage_path, thumb_path)
    return summary


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
    parser.add_argument(
        "--reset",
        action="store_true",
        help=f"first delete every {DEMO_DOMAIN} account and everything it authored",
    )
    args = parser.parse_args(argv)
    try:
        _refuse_outside_dev()
        summary = asyncio.run(_run(reset=args.reset))
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

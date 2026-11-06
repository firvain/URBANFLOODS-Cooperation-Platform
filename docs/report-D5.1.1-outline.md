# Outline: D.5.1.1 report

This is the outline for the written part of deliverable D.5.1.1 "Cooperation Platform and Report
for Enhanced Resilience to Flood Risks", which the application form describes as "a digital
platform for stakeholder collaboration and knowledge exchange based on KNOWBASE, along with a
succinct report detailing the platform's development and functionality". Each section lists what
to write and where the facts are. Numbers the authors must fill in are marked `[TBD]`; points to
confirm are marked `[CHECK]`.

Last updated: 2026-10-31

## Front matter

- Project: URBANFLOODS (IPA-ADRION00374), Interreg IPA ADRION; project period 01/09/2024 – 31/08/2027.
- Work package 5, Activity 5.1 "URBANFLOODS Cooperation Platform"; deliverable D.5.1.1, Period 6
  (months 31–36).
- Responsible partner: LP1 University of Western Macedonia (UOWM); coordinator Prof. Malamati
  Louta (louta@uowm.gr). Contributions: all PPs.
- Version, date, authors, reviewers `[TBD]`. Platform URL: https://cooperation.urbanfloods.app.
  Source code: https://github.com/firvain/URBANFLOODS-Cooperation-Platform (MIT).
- EU co-funding statement and disclaimer (as in the platform footer).

## 1. Executive summary (½ page)

What was built, for whom, how it builds on the KNOWBASE, headline figures (members `[TBD]`,
organisations `[TBD]`, countries `[TBD]`, posts/threads/replies `[TBD]` at the reporting date),
and how it will run after the project.

## 2. Purpose and reference to the application form

- Activity 5.1 text: a digital tool for collaboration, knowledge exchange and best-practice
  transfer among stakeholders in flood prevention and impact mitigation; access upon
  registration to categorised information (measures, actions, policy recommendations tailored to
  local conditions) compiled in the KNOWBASE; blog format; a dynamic forum for interaction,
  learning and collaboration.
- Output 5.1 "URBANFLOODS Cooperation Framework", indicator RCO87 "Organisations cooperating
  across borders", target 22 organisations.
- Cross-cutting commitments: accessibility (screen readers, navigation, alt text), FAIR,
  GDPR, durability after the project, the MoU among PPs and APs.
- Requirements presented at the 3rd Project Meeting (Murska Sobota, January 2026; see
  [requirements-3rd-project-meeting.md](requirements-3rd-project-meeting.md)): WCAG 2.1, DSS
  link, matchmaking, events, FAIR metadata (JSON-LD), open export formats, RCO87 tracking.
- Interpretation of "access upon registration": everything published is publicly readable
  (FAIR); registration is required to post, reply, comment and report ([PLAN.md](PLAN.md),
  decision "Access model").

## 3. Requirements traceability

Evidence columns: backend test files (`backend/tests/`), end-to-end specs (`frontend/e2e/`) and
platform pages. Test counts per area `[TBD]` at the final run (totals on 2026-10-31: 1613 backend
tests collected in 53 files; 1017 vitest tests in 60 files; Playwright 31 tests in 4 specs, plus 4
opt-in accessibility tests in `a11y.spec.ts`).

| AF / meeting commitment | Implemented feature | Evidence |
|---|---|---|
| Registration-based access | open sign-up, email verification, Turnstile, consent audited; public read | `test_auth_register.py`, `test_auth_session.py`; `auth.spec.ts`; `/register`, `/login` |
| Categorised KNOWBASE information (measures, actions, policy) | KNOWBASE proxy with cache; KNOWBASE picker in the post and thread editor; KNOWBASE link cards on posts and threads; measure and document pages with "mentioned in" lists; browsing by country, level and subject happens on the KNOWBASE itself (header entry and home card link to it; decision 2026-10-31) | `test_knowbase_proxy.py`, `test_knowbase_links.py`; `blog.spec.ts` tests 2–3; `/knowbase/measures/{id}`, `/knowbase/documents/{id}` |
| Built on the KNOWBASE, which stays untouched | server-side read-only proxy, `GET` to allow-listed public routes only | `services/knowbase.py`; [architecture.md](architecture.md#6-knowbase-proxy-and-caching) |
| Blog format | posts with categories, tags, cover image, rich text, events (`event_at`, `event_url`), admin-only "Resources" category | `test_posts.py`, `test_categories.py`, `test_tags.py`, `test_uploads.py`; `blog.spec.ts`; `/blog` |
| Dynamic forum | threads, replies with one nesting level, comments on posts, pin/lock, email notifications | `test_threads.py`, `test_replies.py`, `test_comments.py`, `test_notifications.py`; `forum.spec.ts`; `/forum` |
| Transnational cooperation among PPs and stakeholders | 22 seeded partner organisations in the partnership section of the About page; members directory (verified members only) with expertise, country and organisation filters; member profiles; suggested collaborators | `test_organisations.py`, `test_members.py`, `test_expertise.py`; `auth.spec.ts` test 6; `/about#partnership`, `/network`, `/u/{id}` |
| Safe, low-maintenance moderation | trust after first approval, emails to authors on approval and rejection, reports with auto-hide, soft delete and restore, permanent delete, Moderate menu on post and thread pages, members' Uploads tab, audit log, admin area | `test_moderation.py`, `test_moderation_api.py`, `test_moderation_purge.py`, `test_moderation_notifications.py`, `test_reports.py`, `test_crud_audit.py`; `moderation.spec.ts`; `/admin/*` |
| Search | full-text search over posts and threads, typo-tolerant titles | `test_search.py`; `/search` |
| Accessibility (WCAG 2.1 AA) | semantic landmarks, skip link, focus management, labelled forms, required alt text, accessible editor toolbar, eslint a11y rules, axe scans | `a11y.spec.ts` (`E2E_A11Y=1`), `test_uploads.py` (alt text); accessibility statement draft `docs/legal/accessibility-statement.md`, page `/accessibility`; increment 5d done (axe: 23 pages, 0 violations); manual audit `[TBD]` |
| FAIR | JSON/CSV exports, Frictionless data package, Atom feeds, sitemap, OpenAPI, schema.org JSON-LD, CC BY 4.0 | `test_export.py`, `test_feeds.py`; [fair-data.md](fair-data.md); `/open-data` `[CHECK: page live]` |
| GDPR | data minimisation, consent record, self-service export (profile, own content in every status, uploads, reports, sessions, audit rows) and anonymising deletion, permanent delete of content on request, unverified-account purge, no IPs stored, privacy policy | `test_auth_gdpr.py`, `test_gdpr_export.py`, `test_moderation_purge.py`, `test_maintenance.py`; `/privacy`, `/terms` |
| Multilingual (9 project locales) | UI in vue-i18n; English complete; content tagged with its language | increment 5f done (all public and member texts in 9 locales; admin area English) `[CHECK: partner confirmation of the translations]` |
| Link to the Unified DSS | navigation link and home card (`VITE_DSS_URL`) | `/` |
| RCO87 tracking | admin stats CSV with a `rco87` section | `test_admin_stats.py`; `moderation.spec.ts` test 4 |
| Durability after the project | Docker, documentation, admin digest, `AUTO_APPROVE_AFTER_DAYS`, CLI, zero paid services | `test_digest.py`, `test_scheduler.py`, `test_cli.py`; [admin-handbook.md](admin-handbook.md) |

## 4. Development approach (½ page)

Requirements sources (AF, 3rd meeting); stack (FastAPI, PostgreSQL, Vue 3, Nuxt UI, Docker);
conventions mirrored from the KNOWBASE; test-driven increments with review before each commit;
CI on every push ([testing.md](testing.md)). Timeline of milestones M0–M6 `[TBD dates]`.

## 5. Architecture summary (1 page)

System context diagram, backend layers, data model and the content/user state machines, KNOWBASE
caching, email, scheduler, security controls, single-worker constraint. Source:
[architecture.md](architecture.md). Hosting: same server as the KNOWBASE, behind Cloudflare and
host nginx, ports 3002/8002, database not exposed `[CHECK after M6]`.

## 6. Functionality and user guide pointers (1–2 pages, with screenshots `[TBD]`)

- Visitors: home (with "Project at a Glance"), blog, forum, About with the partnership
  (`/about#partnership`), KNOWBASE measure and document pages linked from contributions, search,
  open data, terms, privacy and accessibility pages; links out to the KNOWBASE and the Unified DSS.
- Members: registration and verification, profile and expertise, members directory and profiles
  (`/network`, `/u/{id}`, verified members only), writing posts and threads, replying and
  commenting, KNOWBASE links via the editor picker, images with alt text, the Uploads tab,
  notification settings (including emails on decisions about their posts and discussions), data
  export and account deletion.
- Admins: queue, reports, users, categories, tags, audit log, dashboard and CSV export, the
  Moderate menu on post and thread pages (hide, unhide, delete, restore, delete permanently)
  ([moderation-guide.md](moderation-guide.md), [admin-handbook.md](admin-handbook.md)).
- Developers and reusers: [api.md](api.md), [fair-data.md](fair-data.md).

## 7. Accessibility compliance summary

Target WCAG 2.1 AA. Measures built in; automated checks (axe in Playwright, eslint plugin);
manual checks (keyboard, screen reader `[TBD: tool and date]`); known non-conformities from the
accessibility statement `[TBD]`; feedback channel.

## 8. GDPR compliance summary

Controller UOWM; processors (hosting `[CHECK]`, Brevo for email (EU), Cloudflare); data collected and
why; consent at registration; rights and how they are exercised (self-service, louta@uowm.gr);
retention (unverified accounts 30 days, sessions/tokens, audit log `[CHECK]`); no analytics, only
the strictly necessary session cookie, no cookie banner; no IP addresses in the database. Source:
`docs/legal/privacy-policy.md` (draft, under UOWM review).

## 9. Indicators the platform can report

From the dashboard and `/api/v1/admin/stats/export.csv` for any date range
([admin-handbook.md](admin-handbook.md#stats-csv-export)):

| Indicator | Source | Value at reporting date |
|---|---|---|
| Registered members, by country | `users_by_country` | `[TBD]` |
| Registered members, by organisation (partner / other) | `users_by_organisation` | `[TBD]` |
| Published posts, threads, replies, comments | `content` | `[TBD]` |
| Contributors; members who signed in | `active_users` | `[TBD]` |
| RCO87: organisations cooperating (partners / others / countries) | `rco87` | `[TBD]` of target 22 |
| KNOWBASE items linked from contributions | `knowbase_links` in the JSON exports | `[TBD]` |

State the counting rules (registration date in range, published content created in range,
contribution = published post, thread, reply or comment).

## 10. Sustainability plan

- Operation after 31/08/2027, at least until 31/08/2032 (five years after the project ends, per
  the subsidy contract): owner `[CHECK: UOWM]`, minimum admin team (at least two
  superadmins and admins from several partners) `[TBD names/organisations]`.
- Low-attention moderation: daily or weekly admin digest; report auto-hide;
  `AUTO_APPROVE_AFTER_DAYS` safety valve `[CHECK: agreed value]`.
- Maintenance: automatic purge of expired sessions, tokens, unverified accounts and orphan
  images; Docker images; migrations on start; documented CLI.
- Backups: nightly database dump and uploads archive with 14-day retention (M6)
  `[CHECK after 6a]`.
- Costs: zero paid services (open-source stack, existing project server, Cloudflare free tier,
  Brevo free plan for email); hosting cost of the shared server `[TBD]`.
- Link to the MoU for long-term cooperation and to D.5.3.x sustainability deliverables.
- Data preservation: optional Zenodo deposit of the final export `[CHECK]`.

## 11. Known limitations and next steps

- Single backend worker (in-memory rate limits, cache, scheduler).
- Translations beyond English partial at `[CHECK]`.
- No native mobile app (responsive web only); no OAuth sign-in.
- DSS integration is a link only (no API available).
- No XML version of the bulk exports (Atom and sitemap only).
- Managing organisations has no admin page (API only). Restoring or permanently deleting a reply,
  a comment or an item whose page has been left is done through the API; reported items can be
  restored from the Reports page.
- Changing the account email address has no form (API only).
- Admin digest "send now" only from the command line.
- Email sending limit of the Brevo free plan (300 messages/day).
- `[TBD]` items from user feedback and the accessibility audit.

## Annexes

- A. API reference: [api.md](api.md) and `/api/v1/openapi.json`.
- B. Documentation set: [architecture.md](architecture.md), [api.md](api.md),
  [moderation-guide.md](moderation-guide.md), [admin-handbook.md](admin-handbook.md),
  [fair-data.md](fair-data.md), [testing.md](testing.md), `deployment.md` (M6), legal texts in
  `docs/legal/` (terms of use, privacy policy, accessibility statement, open data).
- C. Test summary: final CI run link, test counts, e2e run date `[TBD]`.
- D. Screenshots `[TBD]`.

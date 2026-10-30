# URBANFLOODS Cooperation Platform — Implementation Plan

## Context

Deliverable D.5.1.1 (Activity 5.1, WP5) of the Interreg IPA ADRION project URBANFLOODS requires a "Cooperation Platform": a registration-based, blog-like hub with a forum, built on top of the existing URBANFLOODS KNOWBASE, for stakeholders to exchange knowledge and best practices on urban flood management. Spec: `IPA-ADRION00374_V4.0.md` lines ~2120-2140, plus cross-cutting commitments (accessibility, FAIR, GDPR, 9 locales, must survive post-project with few active admins).

The KNOWBASE (`~/URBANFLOODS-Knowbase`, live at knowbase.urbanfloods.app on server 95.179.190.87) is a delivered output and **must not be modified**. The platform is a **new, separate app** in `/Users/firvain/Projects/URBANFLOODS_Cooperation_Platform` (currently only the AF markdown; not yet a git repo). It will eventually run on the same server beside KNOWBASE. **Nothing is deployed to the server without explicit permission for that step.**

## Decisions already made (do not re-open)

| Topic | Decision |
|---|---|
| Stack | FastAPI (py3.11+, SQLAlchemy 2 async, Pydantic v2, uv, ruff) + Vue 3 / Nuxt UI v4 / Pinia / vue-router / vue-i18n / ofetch / Vite + Postgres 16 + Docker Compose. Mirror KNOWBASE conventions. |
| KNOWBASE integration | Backend proxies KNOWBASE REST API server-to-server with TTL cache. Browser never calls KNOWBASE (its CORS allows only its own origin, GET only). No DB access. |
| Registration | Open sign-up, email verification. Roles: member / admin / superadmin. |
| Posting model | "Trusted after first approval": first post or thread of a member goes to a moderation queue; approval marks the user trusted and they post freely after. Replies/comments by verified users are immediate. Report button everywhere; auto-hide after N distinct reports; soft delete only; admins get email digests; any admin can promote others. |
| Hostname | cooperation.urbanfloods.app (Cloudflare A record already created, proxied). |
| Email | Gmail SMTP, urbanfloods@gmail.com with app password via env vars. |
| Content language | One language per post/thread, tagged with a locale; UI translated in 9 locales (en complete first, others fall back). |
| Licence | CC BY 4.0 for user contributions (in terms + FAIR export metadata). |
| Attachments | Images only (JPEG/PNG/WebP ≤5 MB, re-encoded to WebP via Pillow). |
| Repo | github.com/firvain/URBANFLOODS-Cooperation-Platform, public. |
| KNOWBASE deep links | KNOWBASE has no per-item URL (modal detail). Platform renders its own `/knowbase/measures/:id` and `/knowbase/documents/:id` pages from proxied data and links out to KNOWBASE list pages. |
| Account deletion | Anonymise user (email/display name/password wiped), keep content as "Deleted user". Stated in terms. |
| Organisations | Seeded `organisations` table with the 22 PPs/APs from the AF (name, short name, country, type PP/AP, website). User picks one or "other" + free text. Public `/partners` page. Needed for Output 5.1 indicator (organisations cooperating) and MoU evidence. |
| Resources | No new feature: an admin-only blog category "Resources" (training material, deliverables, strategy, action plans, policy briefs) with link cards. Documents stay on the project site. |
| Reporting stats | Admin stats with date range + CSV export: users by country/organisation, posts, threads, replies, active users. For project progress reports. |
| Approval safety valve | `AUTO_APPROVE_AFTER_DAYS` (default 0 = off). When set, pending content older than N days is auto-approved by the scheduler and the author becomes trusted. For the post-project phase when admin attention drops. |
| Access model | Public read of everything published (FAIR). Registration required to post, reply, comment, report. The D.5.1.1 report states this reading of "access upon registration" explicitly. |
| Scope line | **Core** (required for D.5.1.1): M0–M4, 5a, 5c–5e, 5g, M6. **Extended** (if time remains): 5b feeds/sitemap/CSV, 5f full translations, tag merge, sessions UI, email change, per-type notification prefs, JSON-LD. Core first, always. |
| Ports on server | frontend 127.0.0.1:3002, backend 127.0.0.1:8002, Postgres NOT published. Taken: 3001/8001/5433 (KNOWBASE), 9443 (Portainer), 3000/8000 referenced by old app. |
| 3rd-meeting commitments | See `docs/requirements-3rd-project-meeting.md`. Decisions 2026-10-30: **DSS** = nav link + home card to the DSS web app (no API yet; `DSS_URL` env); **matchmaking** = expertise tags on profiles, members directory under Collaboration Network filterable by expertise/country/organisation, suggested collaborators on home, contact via opt-in "show my email"; **events** = optional `event_at`/`event_url` on posts, Events category + upcoming widget. WCAG 2.1 AA stated explicitly; JSON-LD promoted to core; XML export added; RCO87 (organisations cooperating) reported in admin stats export. |
| Theme | **Light mode only** (user decision 2026-10-30). No dark mode, no system-preference switching; Nuxt UI colour mode forced to light. |
| Branding | Official logos and favicon from https://urbanfloods.interreg-ipa-adrion.eu (Interreg IPA ADRION + URBANFLOODS lock-up, Interreg programme logo) stored under `frontend/src/assets/logos/` and `frontend/public/`; EU co-funding disclaimer in the footer as on the project site. Same brand palette as KNOWBASE (#11395c / #97c137). |

## Architecture

```
Browser → Cloudflare → host nginx (cooperation.urbanfloods.app, certbot) → 127.0.0.1:3002 frontend nginx
   /        → SPA
   /api/    → backend:8000 (FastAPI)
   /static/ → backend:8000 (uploads)
FastAPI → asyncpg → postgres (internal only)
FastAPI → httpx → KNOWBASE https://knowbase.urbanfloods.app/api/v1 (cachetools TTLCache + stale-on-error)
FastAPI → aiosmtplib STARTTLS → smtp.gmail.com:587
```

Same-origin in prod (`VITE_API_BASE_URL=""`), so cookies are first-party; CORS only for Vite dev (`http://localhost:5173`). Measure photos are `<img src="https://knowbase.urbanfloods.app/static/measures/photos/...">` (images are not CORS-bound).

### Key library choices (backend)
- Auth: **hand-rolled**, opaque server-side sessions (`sessions` table, SHA-256 hashed token, 30-day sliding), cookie `uf_session` HttpOnly/Secure/SameSite=Lax. `argon2-cffi` for passwords. Rejected fastapi-users (fights the crud/endpoint layering, harder to maintain long-term). No JWT (need instant revocation for bans/GDPR).
- CSRF: SameSite=Lax + middleware checking `Origin`/`Referer` against allowed hosts + required `X-Requested-With: XMLHttpRequest` header on unsafe methods.
- HTML sanitisation: `nh3` (allow-list tuned to Tiptap output; `href` schemes http/https/mailto). Plain-text extraction for FTS.
- Email: `aiosmtplib` + Jinja2 templates (`templates/email/<locale>/`, fallback en). `EMAIL_ENABLED=false` + in-memory outbox in tests; Mailpit in dev compose.
- Rate limiting: `slowapi` in-memory (single worker), keyed by `CF-Connecting-IP` when `TRUST_PROXY_HEADERS`.
- Bot check: Cloudflare Turnstile on register / forgot / resend (`TURNSTILE_ENABLED=false` in dev/test).
- Uploads: `python-multipart` + Pillow; re-encode to WebP, strip EXIF, max 1920px + 480px thumb; stored `UPLOAD_DIR/YYYY/MM/<uuid>.webp`; alt text required.
- Migrations: Alembic (async env). FTS generated columns and extensions as raw `op.execute`.
- Scheduler: APScheduler 3.x `AsyncIOScheduler` in lifespan (gated by `ENABLE_SCHEDULER`): daily admin digest, token cleanup, orphan upload sweep, purge unverified accounts >30 days. Also `python -m app.cli digest` for manual runs.
- Cache: `cachetools.TTLCache` (lists 15 min, detail 6 h, lookups 24 h) + stale dict served on upstream error with header `X-Knowbase-Cache: stale`; per-key asyncio.Lock.
- Logging: `structlog` (JSON in prod) + request-id middleware.
- Tests: pytest, pytest-asyncio, testcontainers[postgres] (or `docker-compose.test.yml` on 5434 via `TEST_DATABASE_URL`), httpx ASGITransport, respx (mock KNOWBASE), freezegun.

### Frontend additions over KNOWBASE
`@tiptap/vue-3` + starter-kit + link + image + placeholder, `dompurify` (defence in depth before `v-html`), `vitest`, `@vue/test-utils`, `@playwright/test`, `@axe-core/playwright`, `eslint-plugin-vuejs-accessibility`. Verify exact versions with context7/npm at M0.

## Data model (Postgres; Alembic migrations)

Conventions: integer PKs, `created_at/updated_at timestamptz`, soft delete via `deleted_at` + `status`, PG ENUM types. Mixins: `TimestampMixin`, `SoftDeleteMixin`, `ContentMixin` (body_html, body_text, status, hidden_reason, report_count).

Enums: `user_role(member|admin|superadmin)`, `content_status(pending|published|hidden|deleted)`, `hidden_reason(auto_reports|admin|rejected)`, `content_type(post|thread|reply|comment)`, `category_kind(blog|forum)`, `kb_type(document|measure)`, `token_purpose(verify_email|reset_password|change_email)`, `report_reason(spam|abuse|off_topic|misinformation|other)`, `report_status(open|resolved|dismissed)`.

| Table | Key columns |
|---|---|
| `organisations` | id, name, short_name, country CHAR(2), type (PP/AP/other), website, is_partner BOOL, sort_order. Seeded from AF partner list (section B) in migration `0002`. |
| `users` | email CITEXT unique, password_hash, display_name, organisation_id FK NULL, organisation_other TEXT NULL, country CHAR(2), locale, bio, avatar_attachment_id, role, is_verified, is_active (false=banned), trusted_at, last_login_at, deleted_at, **show_email BOOL default false, show_in_directory BOOL default true** |
| `expertise_tags` / `user_expertise` | seeded controlled vocabulary (hydrology, civil protection, urban planning, NBS, GIS, policy, water utilities, …) + junction; free-text additions by admins only |
| `sessions` | id UUID, user_id, token_hash unique, expires_at, last_seen_at, user_agent, revoked_at |
| `email_tokens` | user_id, purpose, token_hash unique, new_email, expires_at (verify 48h / reset 1h / change 24h), used_at |
| `notification_preferences` | user_id PK, reply_to_my_thread, comment_on_my_post, reply_to_my_reply, admin_digest, digest_frequency |
| `categories` | kind, slug, name, name_i18n JSONB, description, sort_order, is_archived, admin_only BOOL; unique (kind, slug) |
| `tags` / `post_tags` / `thread_tags` | slug unique, name (trigram idx), usage_count; junction `Table` objects |
| `posts` | author_id, category_id, title(200), slug unique, excerpt(500), body_html, body_text, cover_attachment_id, locale, **event_at timestamptz NULL, event_url TEXT NULL**, status, hidden_reason, report_count, comment_count, published_at, approved_by, approved_at, deleted_at, `fts` generated (title A, body B, simple title) — GIN fts, trigram title, idx (status, published_at desc) |
| `threads` | as posts minus excerpt/cover/comment_count; + is_pinned, is_locked, reply_count, last_activity_at |
| `replies` | thread_id, author_id, parent_reply_id (one level, enforced by app check + DB trigger), ContentMixin, fts(body) |
| `comments` | post_id, author_id, ContentMixin |
| `attachments` | uploader_id, storage_path unique, thumb_path, original_filename, mime, size_bytes, width, height, alt_text(300), deleted_at |
| `knowbase_links` | content_type (post/thread), content_id, kb_type, kb_id, cached_title_en, cached_title_local, cached_at, sort_order; unique (content_type, content_id, kb_type, kb_id) |
| `reports` | reporter_id, content_type, content_id, reason, details(1000), status, resolved_by, resolved_at; unique (reporter, type, id) |
| `audit_log` | actor_id, action (e.g. `moderation.approve`, `user.promote`, `auth.consent`), target_type, target_id, metadata JSONB |
| `digest_runs` | kind, ran_at, window_start, window_end, recipients, items |

State machines:
- User: registered → (verify) verified (trusted_at NULL) → (first post/thread approved, or admin trust) trusted. Admin ban = is_active false + revoke sessions.
- Post/Thread: create by untrusted → `pending`; by trusted → `published`. pending → approve → published (+ user.trusted_at). pending → reject → hidden(rejected). published → N distinct reports → hidden(auto_reports). admin hide/unhide. author/admin delete → deleted (soft). admin restore.
- Replies/comments: created `published` by any verified active user; same hide/delete transitions.
- Single `visible_to(user)` filter: public sees published; author sees own non-deleted; admin sees all non-deleted (plus deleted with flag).

## API surface (`/api/v1`, list routes end with `/`, `{total, items}` pagination like KNOWBASE)

- **auth**: register (turnstile, 5/h), verify-email, resend-verification (202 always), login (10/15min), logout, password/forgot (202), password/reset (revokes all sessions), me GET/PATCH, me/password, me/email, me/notifications GET/PUT, me/sessions GET + DELETE/{id}, me/export (GDPR JSON), DELETE me (anonymise).
- **users**: GET /users/{id} public profile; /users/{id}/activity.
- **organisations**: GET /organisations/ (public; partners first), admin POST/PATCH; GET /organisations/{id} with member count and recent activity (feeds `/partners` page).
- **admin stats**: GET /admin/stats (counts, pending, open reports, cache status) and GET /admin/stats/export.csv?from=&to= (users by country/organisation, posts, threads, replies, active users in range).
- **categories/tags**: public GET; admin POST/PATCH/DELETE (archive if content); tags merge.
- **posts/comments**: GET /posts/ (q, category, tag, author_id, locale, status, sort), GET /posts/{slug}, POST (verified; status by trust; sanitise; tags find-or-create; knowbase_links validated via proxy), PATCH/DELETE (author/admin); /posts/{id}/comments/ GET + POST (verified, 30/h); /comments/{id} PATCH/DELETE.
- **threads/replies**: GET /threads/ (pinned first, sort activity|newest), GET /threads/{slug}, POST, PATCH/DELETE, admin pin/unpin/lock/unlock; /threads/{id}/replies/ GET (one-level nesting) + POST (verified, 60/h, 423 if locked); /replies/{id} PATCH/DELETE.
- **reports/moderation**: POST /reports/ (verified, 20/day; auto-hide at `REPORT_AUTO_HIDE_THRESHOLD`); admin: /moderation/queue/, /moderation/reports/ (+resolve/dismiss), /moderation/{type}/{id}/approve|reject|hide|unhide|delete|restore, /moderation/log/.
- **admin**: /admin/users/ list + PATCH, promote/demote/ban/unban/trust/untrust/resend-verification (superadmin-only for superadmin role changes; last superadmin protected), /admin/stats, /admin/digest/send-now, /admin/knowbase/cache/clear.
- **knowbase proxy**: GET /knowbase/documents/ + /{id}, /knowbase/measures/ + /{id}, /knowbase/lookups/{name}, /knowbase/measures/lookups/{name} (allow-listed), /knowbase/{kb_type}/{id}/mentions/, /knowbase/status.
- **search**: GET /search/ (q, type=all|posts|threads) — plainto_tsquery on fts OR trigram ilike on title, ts_rank order, ts_headline snippets.
- **uploads**: POST /uploads/images/ (verified, 30/day, alt_text required), DELETE /uploads/{id}.
- **export (FAIR)**: /export/posts.json|csv, /export/threads.json, /export/datapackage.json (CC BY 4.0), /feeds/posts.atom, /feeds/threads.atom, /sitemap.xml.
- **health**: /health, /health/ready. OpenAPI at `/api/v1/openapi.json` kept enabled in prod (documented API = FAIR).

## Frontend

Routes (lazy, `meta.title` i18n key, `meta.auth: user|verified|admin`): `/` home; `/blog`, `/blog/category/:slug`, `/blog/tag/:slug`, `/blog/new`, `/blog/:slug`, `/blog/:slug/edit`; `/forum`, `/forum/c/:slug`, `/forum/new`, `/forum/t/:slug`; `/knowbase`, `/knowbase/measures`, `/knowbase/measures/:id`, `/knowbase/documents`, `/knowbase/documents/:id`; `/search`; `/u/:id`; `/login`, `/register`, `/verify-email`, `/forgot-password`, `/reset-password`; `/account` (tabs); `/admin`, `/admin/queue|reports|users|categories|tags|log`; `/about`, `/privacy`, `/terms`, `/accessibility`, `/open-data`; 404.

Component folders: `layout/`, `auth/`, `blog/`, `forum/`, `comments/`, `editor/` (RichTextEditor Tiptap, EditorToolbar, ImageUploadDialog, KnowbaseLinkPicker), `knowbase/`, `moderation/` (ReportButton, StatusBadge, ModerationActions), `admin/`, `common/` (Pagination, EmptyState, ConfirmDialog, SafeHtml, DateTime, UserAvatar).

Stores: auth, posts, threads, comments, replies, categories, tags, knowbase, moderation, admin, ui. Services: one file per resource, typed from `src/types/api-schema.ts` via `npm run gen:types` (openapi-typescript against `/api/v1/openapi.json`). `services/api.ts`: ofetch with `credentials:'include'`, `X-Requested-With` header, 401 → auth store clear, 429 → toast.

Composables: `useQueryFilters` (URL-synced, as KNOWBASE `useFilters`), `usePagination`, `usePageHead` (title/description/og/canonical/JSON-LD), `useRichEditor`, `useLocale` (localStorage + `<html lang>`), `useFocusOnRouteChange`.

i18n: same shape as KNOWBASE `i18n/index.ts` (9 locales, `legacy:false`, fallback en). Backend errors are codes (`detail.code`) translated client-side. Content carries its own `locale` → `lang` attr on rendered article.

Accessibility (from M0): skip link, landmarks, one h1, focus to h1 on route change + live region, labelled forms with aria-describedby, alt text required on uploads, Tiptap toolbar as real buttons with aria-pressed, visible focus rings, reduced-motion, contrast (secondary #97c137 only for backgrounds), `eslint-plugin-vuejs-accessibility`, axe in e2e, `/accessibility` statement page.

## Repository layout

```
URBANFLOODS_Cooperation_Platform/
├── CLAUDE.md  README.md  .gitignore  .env.example  .env.prod.example
├── docker-compose.yml (dev: postgres, mailpit, backend --reload, frontend vite)
├── docker-compose.test.yml  docker-compose.prod.yml  deploy.sh
├── .github/workflows/ci.yml
├── backend/
│   ├── pyproject.toml  uv.lock  Dockerfile  alembic.ini  .env.example
│   ├── alembic/env.py  alembic/versions/
│   ├── app/main.py  app/cli.py
│   ├── app/core/   config.py security.py logging.py deps.py rate_limit.py csrf.py exceptions.py
│   ├── app/db/     session.py models.py mixins.py enums.py
│   ├── app/crud/   user session token post thread reply comment category tag report moderation attachment knowbase_link audit search export
│   ├── app/services/ email.py knowbase.py sanitize.py images.py turnstile.py digest.py scheduler.py slugs.py
│   ├── app/api/v1/ schemas/ deps.py endpoints/{auth,users,posts,comments,threads,replies,categories,tags,reports,moderation,admin,knowbase,search,uploads,export,health}.py
│   ├── app/templates/email/en/*.html|txt  feeds/atom.xml
│   ├── uploads/ (gitignored)
│   └── tests/ conftest.py factories.py test_*.py
├── frontend/ (package.json, vite.config.ts, Dockerfile.prod, nginx.prod.conf, src/, e2e/)
├── docker/postgres/init.sql (pg_trgm, citext)  docker/nginx-host-config.template
├── scripts/ backup.sh restore.sh seed_dev.py
└── docs/ architecture.md api.md deployment.md moderation-guide.md admin-handbook.md accessibility-statement.md fair-data.md privacy-policy.md report-D5.1.1-outline.md
```

CLAUDE.md for the new repo: overview + relation to KNOWBASE (API only, never modify), commands, layering rules (thin endpoints → crud keyword-only `(total, items)` → schemas Base/Summary/Detail/Paginated), every status change writes audit_log, every HTML body through `services/sanitize.py`, never raw `v-html` outside `SafeHtml`, auth deps + trust state machine, Alembic workflow, frontend conventions, testing expectations, "never deploy without explicit permission", ports 3002/8002, do-not list (no KNOWBASE DB, no Postgres host port, no sensitive-data fields, no analytics).

Reference files to copy patterns from: `~/URBANFLOODS-Knowbase/backend/app/main.py`, `backend/app/core/config.py`, `backend/app/db/session.py`, `backend/app/crud/document.py` (search), `backend/Dockerfile`, `frontend/src/main.ts`, `frontend/src/services/api.ts`, `frontend/src/i18n/index.ts`, `frontend/src/composables/useFilters.ts`, `frontend/nginx.prod.conf`, `frontend/Dockerfile.prod`, `docker-compose.prod.yml`, `nginx-host-config.template`, `CLAUDE.md`.

## Env vars (`core/config.py`)

`ENV`, `DATABASE_URL`, `PROJECT_NAME`, `API_V1_PREFIX`, `ALLOWED_ORIGINS`, `ENABLE_DOCS`, `SECRET_KEY`, `FRONTEND_URL`, `COOKIE_SECURE`, `SESSION_COOKIE_NAME=uf_session`, `SESSION_TTL_DAYS=30`, `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_FROM_NAME`, `EMAIL_ENABLED`, `KNOWBASE_BASE_URL=https://knowbase.urbanfloods.app`, `KNOWBASE_PUBLIC_URL`, `KNOWBASE_TIMEOUT_SECONDS=5`, `KNOWBASE_CACHE_TTL_LIST=900`, `KNOWBASE_CACHE_TTL_DETAIL=21600`, `TURNSTILE_ENABLED`, `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`, `UPLOAD_DIR`, `MAX_UPLOAD_MB=5`, `REPORT_AUTO_HIDE_THRESHOLD=3`, `ENABLE_SCHEDULER`, `DIGEST_HOUR_UTC=6`, `RATE_LIMIT_ENABLED`, `TRUST_PROXY_HEADERS`, `LOG_LEVEL`, `LOG_JSON`, `CONTENT_LICENSE_URL`. Frontend: `VITE_API_BASE_URL`, `VITE_TURNSTILE_SITE_KEY`, `VITE_KNOWBASE_PUBLIC_URL`.

## Working method (mandatory)

**Roles.** Fable 5.1 (this session) designs, writes the increment spec and the failing-test list, reviews every diff, and commits. **Opus 5.5 implements** via the Agent tool (`model: "opus"`), one increment per agent run, with a brief that contains: the increment goal, the exact test files/cases to make pass, the files it may touch, the KNOWBASE reference files to mirror, and the rule "do not touch anything outside the listed files; do not deploy; do not commit".

**TDD loop per increment (red → green → refactor):**
1. Fable writes or specifies the tests first (backend pytest, frontend vitest, Playwright e2e where a user flow is involved). Tests are committed red if they are hand-written by Fable, otherwise the Opus brief says "write these tests first and run them to confirm they fail, then implement".
2. Opus 5.5 implements the minimum to go green, runs the full suite (`uv run pytest`, `npm run test`, `npm run lint && npm run type-check`), and reports the test output verbatim.
3. Fable reviews the diff (`git diff`, plus `/code-review` at medium for anything touching auth, moderation, sanitisation, uploads or the KNOWBASE proxy), requests fixes via SendMessage to the same agent if needed.
4. Fable commits with a conventional message (`feat(auth): register endpoint with email verification`), ending with the Co-Authored-By line. Push after every increment. **Never squash a milestone into one commit.**

**Increment size.** One increment = one endpoint group or one view or one model + migration, roughly 1–3 test files, mergeable in isolation. Milestones below are split into lettered increments; each is its own agent run and commit. Never implement a whole milestone in one shot.

**Playwright.** Used from M1 onward for user flows (register/verify/login, post lifecycle, moderation), run against the dev compose stack with Mailpit; axe checks added in M5. E2E specs live in `frontend/e2e/` and are part of the milestone's definition of done.

**Docs lookup.** When unsure about a library API or version (Nuxt UI v4, Tiptap 3, Alembic async, slowapi, nh3, testcontainers, Playwright), query **context7** (`resolve-library-id` then `query-docs`) before writing code. The Opus brief says the same.

**Definition of done for an increment:** tests green locally, lint/type-check clean, reviewed by Fable, `PROGRESS.md` updated, committed and pushed, no KNOWBASE file touched, nothing deployed.

**Plan and progress live in the repo (first thing created in 0a):**
- `docs/PLAN.md` — this plan, verbatim, kept current. Any change of scope or decision is edited here first, then implemented.
- `PROGRESS.md` at repo root — the single source of truth across sessions. Structure:
  1. **Targets**: the deliverable (D.5.1.1), the hard constraints (KNOWBASE untouched, no deploy without permission, TDD, Opus 5.5 implements / Fable reviews), and the decisions table from this plan.
  2. **Milestone board**: one row per lettered increment (0a … 6x) with columns `Status (todo / in progress / done)`, `Commit`, `Tests`, `Notes`. Updated in the same commit as the increment.
  3. **Session log**: dated entries (absolute dates) with what was done, what is blocked, and the exact next increment to start. The last entry's "Next" line is where the following session begins.
  4. **Open questions / decisions pending** for the user.
- CLAUDE.md in the repo instructs: read `PROGRESS.md` first in every session; update it before every commit; never start an increment that is not the next one on the board without noting why.

## Milestones (each independently verifiable; lettered items are the commit-sized increments)

**M0 — Scaffold, Docker, CI.** Verify: `docker compose up` serves SPA that calls `/health`; CI green.
- 0a `git init`, .gitignore, README, CLAUDE.md, `docs/PLAN.md` (this plan), `PROGRESS.md` (targets + milestone board with every increment as todo + first session-log entry), `gh repo create firvain/URBANFLOODS-Cooperation-Platform --public`, first push.
- 0b Backend skeleton: pyproject, Dockerfile, config, logging, session, main.py lifespan, `/health` + `tests/test_health.py` (red first), conftest with testcontainers/compose-test DB.
- 0c Alembic async init + `0001_extensions` (pg_trgm, citext) + test that migrations apply to head on empty DB.
- 0d Frontend skeleton: Vite + Nuxt UI + router + i18n (9 locale files) + layout + HomeView + api.ts + vitest smoke test.
- 0e Dev compose (postgres, mailpit, backend --reload, frontend vite) + `docker-compose.test.yml` + GitHub Actions CI.

**M1 — Auth + email.** Verify: register → Mailpit link → verify → login → `/auth/me`; reset flow; Playwright `auth.spec.ts`.
- 1a Models Organisation (seeded with 22 PPs/APs from AF section B) / User / Session / EmailToken / NotificationPreference / AuditLog + migration + model tests.
- 1b `core/security.py` (argon2, session tokens, cookie helpers) + unit tests.
- 1c `services/email.py` + Jinja templates + outbox fixture + Mailpit dev wiring; `services/turnstile.py` (stubbed in test).
- 1d Endpoints register / verify-email / resend (202 always) + crud user/token + tests.
- 1e Endpoints login / logout / me GET+PATCH / sessions + `core/deps.py` role deps + tests (cookie flags, revoke).
- 1f Password forgot/reset + change password/email + tests (reset revokes all sessions).
- 1g `core/csrf.py` + `core/rate_limit.py` middleware + tests (403 without header/origin, 429).
- 1h Admin users endpoints (list/promote/demote/ban/trust) + organisations endpoints + `cli create-superadmin` + last-superadmin protection tests.
- 1i GDPR: `/auth/me/export`, `DELETE /auth/me` anonymise + tests.
- 1j Frontend: auth store/service, Login/Register/Verify/Forgot/Reset views, router guards, vitest for store.
- 1k Frontend: AccountView (profile with organisation picker/password/notifications/data), LocaleSwitcher, public `/partners` page (PartnersView).
- 1l Playwright `e2e/auth.spec.ts` (register → Mailpit API → verify → login → account page).

**M2 — Blog + KNOWBASE proxy.** Verify: trusted user publishes post with cover + linked measure; public sees it; KNOWBASE browser works from cache; Playwright `blog.spec.ts`.
- 2a Models Category/Tag/post_tags/Post/Attachment/KnowbaseLink + migration (FTS generated column, trigram idx) + model tests.
- 2b `services/sanitize.py` (nh3) + `services/slugs.py` + tests (script/onerror/javascript: stripped, slug uniqueness).
- 2c `services/knowbase.py` proxy + TTL/stale cache + `/knowbase/*` endpoints + respx tests (cache hit, stale on timeout, unknown lookup 404).
- 2d Categories + tags crud/endpoints (public GET, admin writes, archive, merge) + tests.
- 2e Posts crud/endpoints (list with visibility filter, detail, create with trust→status, update, soft delete, knowbase_links validation) + tests.
- 2f `services/images.py` + uploads endpoints + StaticFiles `/static/uploads` + tests (size/type/alt limits, EXIF stripped).
- 2g `scripts/seed_dev.py` (categories incl. admin-only "Resources", superadmin, sample posts) + `npm run gen:types`. Categories carry `admin_only BOOL` (members cannot post in them).
- 2h Frontend: knowbase store/service/views (KnowbaseView, MeasureDetailView, DocumentDetailView, status banner).
- 2i Frontend: editor components (Tiptap RichTextEditor, toolbar, ImageUploadDialog, KnowbaseLinkPicker) + vitest.
- 2j Frontend: BlogListView, PostDetailView (SafeHtml), PostEditorView, posts/categories/tags stores.
- 2k Playwright `e2e/blog.spec.ts` (trusted user creates post with image + KNOWBASE link; public sees it).

**M3 — Forum + comments.** Verify: thread → reply → nested reply; comment on post; locked thread rejects; Playwright `forum.spec.ts`.
- 3a Models Thread/thread_tags/Reply/Comment + migration (one-level trigger, counters) + tests.
- 3b Threads crud/endpoints (list pinned-first, detail, create, update, delete, admin pin/lock) + tests.
- 3c Replies crud/endpoints (one-level nesting 400, locked 423, counters, deleted keeps children) + tests.
- 3d Comments crud/endpoints + tests.
- 3e Notification emails (reply to my thread / comment on my post / reply to my reply) honouring preferences + tests.
- 3f Frontend: ForumListView, ThreadDetailView, ThreadEditorView, forum components, threads/replies stores.
- 3g Frontend: comments components + store on PostDetailView; notifications tab wired.
- 3h Playwright `e2e/forum.spec.ts`.

**M4 — Moderation + admin UI.** Verify: untrusted first post pending + invisible publicly; admin approves → visible + trusted; 3 reports auto-hide; digest in Mailpit; Playwright `moderation.spec.ts`.
- 4a Models Report/DigestRun + migration + tests.
- 4b `crud/moderation.py` state machine (approve/reject/hide/unhide/delete/restore + audit) + full transition-matrix tests.
- 4c Reports endpoint + auto-hide at threshold (distinct reporters) + dismiss resets + tests.
- 4d Moderation + admin endpoints (queue, reports, log, stats, cache clear) + permission matrix tests.
- 4e `services/digest.py` + `services/scheduler.py` (APScheduler jobs incl. `AUTO_APPROVE_AFTER_DAYS` sweep, off by default) + `cli digest` + freezegun tests.
- 4d also includes `/admin/stats/export.csv` with date range (users by country/organisation, content counts, active users) + tests.
- 4f Frontend: ReportButton/ReportDialog/StatusBadge/pending banner on posts, threads, replies, comments.
- 4g Frontend: admin views (Dashboard, Queue, Reports, Users, Categories, Tags, Log) + moderation/admin stores.
- 4h Playwright `e2e/moderation.spec.ts` (first post pending → approve → trusted → second post immediate; 3 reports hide).

**M5 — Search, i18n, a11y, FAIR, docs.** Verify: search ranks; axe passes; exports and feeds validate; docs complete.
- 5a `crud/search.py` + `/search/` endpoint + tests (title hit ranks above body, trigram typo).
- 5b Export endpoints (JSON/CSV/datapackage CC BY 4.0, Atom feeds, sitemap) + tests (published only, feedparser).
- 5c Frontend: SearchView + header search box + `usePageHead` (title/og/canonical/JSON-LD).
- 5d Accessibility pass: skip link, focus-on-route-change, live region, aria on forms/editor/pagination, `eslint-plugin-vuejs-accessibility`, contrast fixes; axe in Playwright on home/post/thread/register/editor.
- 5e Static pages (/about, /privacy, /terms, /accessibility, /open-data) + consent checkbox text.
- 5f Translation pass: `en.json` complete; other 8 locales nav/auth/common minimum, TODO keys marked.
- 5g `docs/*.md` incl. `report-D5.1.1-outline.md`, admin handbook, moderation guide.

**M6 — Production deployment (ONLY on explicit request).** `docker-compose.prod.yml` (3002/8002, no DB port, volumes, healthchecks on IPv4 `127.0.0.1`, logging), `.env.prod.example`, `deploy.sh` (alembic upgrade in backend entrypoint), `docker/nginx-host-config.template` for cooperation.urbanfloods.app (security headers, CSP allowing challenges.cloudflare.com + knowbase images, `client_max_body_size 6m`), `scripts/backup.sh` (pg_dump + uploads tar, 14-day retention, user crontab), `docs/deployment.md` listing the sudo steps the user runs (`ln -s`, `certbot --nginx -d cooperation.urbanfloods.app`, `nginx -t && reload`), Turnstile site creation, Gmail app password, first `create-superadmin`. Note: Certbot behind Cloudflare proxy may need the record flipped to DNS-only briefly.

## Security & GDPR checklist

Cookies HttpOnly/Secure/SameSite=Lax, revocable sessions; CSRF via origin check + custom header; argon2id, min 10 chars, common-password list, generic errors, auth rate limits, constant 202 on forgot/resend; tokens 32-byte random, hashed at rest, single use; nh3 server + DOMPurify client; links `rel="nofollow noopener"`; uploads re-encoded (kills polyglots, strips EXIF/GPS), random names, nosniff; HSTS, CSP, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy; authorisation tests for every mutating endpoint; audit log for moderation/role changes; no IPs stored in DB; Postgres not published; secrets only in `.env.prod` (chmod 600); Dependabot. GDPR: data minimisation (email, display name, optional organisation/country, locale; bio with notice), consent checkbox at registration (timestamped in audit_log), self-service export + anonymising deletion, unverified accounts purged after 30 days, privacy page naming UOWM as controller and Google/Cloudflare as processors, notification emails opt-out links. **No cookie banner needed** (only strictly necessary session cookie + localStorage locale; no analytics).

## Known risks

Gmail 500/day cap and possible spam-foldering (mitigated by digests; any SMTP swaps in via env). Single-worker constraint for APScheduler / in-memory cache and rate limit (documented; Redis only if ever scaled). Spam via open registration (Turnstile + verification + first-post approval + auto-hide). KNOWBASE API drift (loose proxy schemas `extra="allow"`, cached titles). 9-locale UI translation is incremental.

## Verification (end-to-end)

1. `docker compose up` locally → http://localhost:5173 loads, `/health` ok, Mailpit at :8025.
2. Playwright smoke flow (M5) green: register → verify via Mailpit → first post pending → admin approve → public visible → user trusted → second post immediate → report ×3 hides → digest email.
3. `uv run pytest` ≥80% coverage on crud/ and services/; `npm run lint && npm run type-check && npm run test`.
4. axe scan passes on home, post, thread, register, editor.
5. `/export/datapackage.json` validates; `/feeds/posts.atom` parses; `/api/v1/openapi.json` served.
6. Deployment (M6, on request only): `curl -sI https://cooperation.urbanfloods.app` returns 200 via Cloudflare; KNOWBASE containers untouched (`docker ps` shows same uptime).

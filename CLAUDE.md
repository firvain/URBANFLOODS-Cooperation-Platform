# CLAUDE.md — URBANFLOODS Cooperation Platform

Guidance for Claude when working in this repository. This file is the source of truth for
process and conventions; `docs/PLAN.md` is the source of truth for scope and architecture;
`PROGRESS.md` is the source of truth for what is done and what comes next.

## 0. Start of every session

1. Read `PROGRESS.md`. The last session-log entry's **Next** line is where you start.
2. Read the relevant milestone section of `docs/PLAN.md`.
3. Do not start an increment that is not the next one on the board without noting why in the log.

## 1. What this project is

The **Cooperation Platform** is deliverable D.5.1.1 of the Interreg IPA ADRION project
URBANFLOODS (IPA-ADRION00374). It is a registration-based blog + forum hub for flood-management
stakeholders, built **on top of** the URBANFLOODS KNOWBASE.

The KNOWBASE is a separate, delivered, live application
(repo `~/URBANFLOODS-Knowbase`, https://knowbase.urbanfloods.app, containers
`urbanfloods-knowbase-*-prod` on the shared server). **It must never be modified**: no code
changes, no container restarts, no database access, no env changes. This platform consumes its
public REST API only, server-to-server, through `backend/app/services/knowbase.py`.

## 2. Hard rules

- **Never deploy to the server without explicit permission for that specific step.** Reading
  and inspecting over `ssh knowbase` is fine. Nothing that changes server state is.
- **Never touch the KNOWBASE** (see §1).
- **TDD.** Tests first. Red → green → refactor. No implementation without a failing test.
- **Fable 5.1 designs and reviews; Opus 5.5 implements.** Implementation runs as an Agent
  (`model: "opus"`) with a tight brief: goal, tests to make pass, files it may touch, reference
  files to mirror, and "do not commit, do not deploy, do not touch other files". Fable reviews the
  diff (`/code-review` medium for auth, moderation, sanitisation, uploads, KNOWBASE proxy),
  then commits.
- **One increment, one commit.** Increments are the lettered items in `docs/PLAN.md`
  (0a, 0b, …). Never squash a milestone. Never implement a whole milestone in one run.
- **Update `PROGRESS.md` in the same commit** as the increment (board row + session log).
- **Use context7** (`resolve-library-id` → `query-docs`) whenever unsure about a library API.
- **No paid services.** Everything must stay free/open source.
- Commit messages: conventional (`feat(auth): …`, `test(posts): …`, `chore: …`), ending with
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## 3. Stack and commands

Backend (Python 3.11+, `uv`):
```bash
cd backend
uv sync --all-extras
uv run fastapi dev app/main.py          # http://localhost:8000
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe"
uv run pytest                           # needs Docker (testcontainers) or TEST_DATABASE_URL
uv run ruff check . --fix && uv run ruff format .
```

Frontend (Node 22, npm):
```bash
cd frontend
npm ci
npm run dev                             # http://localhost:5173
npm run gen:types                       # openapi-typescript from http://localhost:8000/api/v1/openapi.json
npm run lint && npm run type-check
npm run test                            # vitest
npm run e2e                             # playwright against dev compose stack
```

Whole stack: `docker compose up --build` (postgres, mailpit, backend --reload, frontend vite).

## 4. Backend conventions (mirroring KNOWBASE)

Layering, strictly:
```
api/v1/endpoints/<resource>.py   thin routes: parse → call crud → return schema; raise HTTPException
crud/<resource>.py               async funcs, keyword-only args, return ORM objects or (total, items)
api/v1/schemas/<resource>.py     Pydantic: XBase(from_attributes) / XSummary / XDetail / PaginatedX{total, items}
db/models.py                     explicit declarative models (no reflection); junctions as Table objects
services/<concern>.py            side-effecting helpers: email, knowbase proxy, sanitize, images, digest
core/                            config, security, deps, csrf, rate_limit, logging, exceptions
```

- Every HTML body passes through `services/sanitize.py` (nh3) before storage. No exceptions.
- Every status or role change writes an `audit_log` row via `crud/audit.py`.
- All content listing goes through the single `visible_to(user)` filter in `crud/visibility.py`.
- Pagination: `skip`/`limit` query params, `{total, items}` response, count via subquery.
- Eager loading: `joinedload` for many-to-one, `selectinload` for many-to-many. No N+1.
- Full-text search: `plainto_tsquery('english')` on the generated `fts` column OR trigram
  `ILIKE` on titles, ordered by `ts_rank`.
- Settings only via `core/config.py` (`pydantic-settings`). Never read `os.environ` elsewhere.
- Errors returned to clients are **codes** (`detail: {"code": "auth.invalid_credentials"}`),
  translated on the frontend.
- Migrations: Alembic. Autogenerate, then hand-edit extensions, enums, generated columns and
  triggers as `op.execute`. Never edit an applied migration.
- Logging: `structlog` via `core/logging.py`. Never log passwords, tokens, or bodies.

## 5. Frontend conventions (mirroring KNOWBASE)

- Components by feature folder (`components/blog`, `components/forum`, …). Nuxt UI components
  first; do not hand-build what `U*` provides.
- State: Pinia setup stores for shared data; URL query for filters and page
  (`composables/useQueryFilters.ts`); `ref` for local UI state.
- All API calls through `services/<resource>.ts`, typed from the generated
  `src/types/api-schema.ts`. **Never hand-write API types.**
- `services/api.ts` sends `credentials: 'include'` and `X-Requested-With: XMLHttpRequest`
  (CSRF defence). 401 clears the auth store; 429 shows a toast.
- User HTML is rendered only through `components/common/SafeHtml.vue` (DOMPurify). Never raw
  `v-html` elsewhere.
- All user-facing text through vue-i18n keys. `en.json` is complete; other locales fall back.
- Accessibility is not optional: labelled form fields, `aria-describedby` for errors, skip link,
  focus to `h1` on route change, real `<button>`s with `aria-label`/`aria-pressed` in the editor
  toolbar, alt text required on images, visible focus rings. `eslint-plugin-vuejs-accessibility`
  must pass.

## 6. Auth and trust model (summary; details in docs/PLAN.md)

- Roles: `member`, `admin`, `superadmin`. Opaque session cookie `uf_session`
  (HttpOnly, Secure in prod, SameSite=Lax). argon2id passwords.
- Dependencies in `core/deps.py`: `get_current_user` (optional), `require_user`,
  `require_verified`, `require_admin`, `require_superadmin`.
- Trust: verified member's **first** post/thread → `pending` until an admin approves; approval sets
  `users.trusted_at`; trusted members publish immediately. Replies and comments never need approval.
- Content status: `pending | published | hidden | deleted`. Soft delete only.
- Reports from `REPORT_AUTO_HIDE_THRESHOLD` distinct users auto-hide content.

## 7. Testing expectations

- Backend: pytest with a real Postgres (testcontainers, or `TEST_DATABASE_URL` pointing at
  `docker-compose.test.yml` on port 5434). Migrations applied once per session; per-test
  transaction rollback. `EMAIL_ENABLED=false` with the outbox fixture; `TURNSTILE_ENABLED=false`;
  KNOWBASE mocked with `respx`. Every mutating endpoint has owner/admin/superadmin authorisation
  tests. Target ≥80% coverage on `crud/` and `services/`.
- Frontend: vitest for stores, composables, `SafeHtml`, editor output. Playwright e2e per
  milestone in `frontend/e2e/`, run against the dev compose stack using the Mailpit API to read
  verification links. axe checks from M5.
- CI (`.github/workflows/ci.yml`) must be green before a commit is considered done.

## 8. Deployment (live since 2026-10-31)

Live at https://cooperation.urbanfloods.app on the KNOWBASE server (`ssh knowbase`, user
`urbanfloods`, no passwordless sudo). Repo clone `~/URBANFLOODS-Cooperation-Platform`, secrets in
its `.env.prod` (mode 600, never printed or committed). Ports: frontend `127.0.0.1:3002`, backend
`127.0.0.1:8002`, Postgres **not** published. Runbook: `docs/deployment.md`; current state and next
steps: the last session-log entry of `PROGRESS.md`.

- **Redeploy routine:** CI green on `main` first, then
  `ssh knowbase 'cd ~/URBANFLOODS-Cooperation-Platform && ./deploy.sh'` (pull, backup, build,
  start, wait for health; never `down`; migrations run in the backend entrypoint). Afterwards check
  that the `urbanfloods-knowbase-*` containers are unchanged. Deploy only with the owner's go.
- `ssh knowbase …` is allowed for Claude by a project permission rule; anything needing `sudo`
  (host nginx, certbot) is run by the owner from commands or a script Claude prepares.
- Nightly backups 03:15 via `scripts/backup.sh` to `~/backups/cooperation` (user crontab).

## 9. Do-not list

- No KNOWBASE DB access, ever. No KNOWBASE code or container changes, ever.
- No Postgres host port in prod compose.
- No sensitive personal data fields (health, ethnicity, politics, etc.). No IP addresses in the DB.
- No analytics or third-party scripts except Cloudflare Turnstile.
- No paid APIs or services.
- No deploy, restart, or server-state change without explicit permission.

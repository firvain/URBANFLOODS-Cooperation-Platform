# Testing

This document explains how to run the platform's automated tests: the backend suite (pytest
against a real Postgres), the frontend unit tests (vitest), the end-to-end tests (Playwright
against the development stack, with Mailpit for email), and what CI runs on every push. The
project works test-first: every increment lands with its tests (see the root `CLAUDE.md`).

Last updated: 2026-10-31

## 1. Backend (pytest)

```bash
cd backend
uv sync --all-extras
uv run pytest                                  # whole suite
uv run pytest tests/test_moderation.py -q      # one file
uv run pytest --cov=app --cov-report=term-missing
uv run ruff check . && uv run ruff format --check .
```

The suite needs a real PostgreSQL 16. Two ways:

1. **testcontainers** (default): with Docker running and `TEST_DATABASE_URL` unset, the session
   starts a throwaway Postgres container.
2. **Compose test database**:

   ```bash
   docker compose -f docker-compose.test.yml up -d --wait      # Postgres on localhost:5434, tmpfs
   cd backend && TEST_DATABASE_URL=postgresql+asyncpg://test:test@localhost:5434/test uv run pytest
   docker compose -f docker-compose.test.yml down -v
   ```

If neither is available, database tests are skipped with a reason (pure unit tests still run).
Migrations are applied once per session; each test runs in a transaction that is rolled back.
Email uses an in-memory outbox (`EMAIL_ENABLED=false`), Turnstile is disabled, the KNOWBASE is
mocked with `respx`, time with `freezegun`. On 2026-10-31, `uv run pytest --collect-only`
collects 1459 tests in 50 files.

## 2. Frontend (vitest, lint, types)

```bash
cd frontend
npm ci
npm run test          # vitest run (happy-dom)
npm run test:watch    # watch mode
npm run lint:check    # eslint incl. eslint-plugin-vuejs-accessibility (npm run lint fixes)
npm run type-check    # vue-tsc
npm run build-only    # production build
```

API types in `src/types/api-schema.ts` are generated, never hand-written:
`npm run gen:types` (needs the backend on `http://localhost:8000`).

## 3. Development data

The e2e tests and manual testing use the development seed: twelve demo personas covering every
account state (one password, `Urbanfloods-2026`), eleven blog posts with comments and four forum
threads with replies.

```bash
docker compose up --build -d
docker compose exec backend python -m scripts.seed_dev            # create what is missing
docker compose exec backend python -m scripts.seed_dev --reset    # delete all demo data, reseed
```

The e2e suite logs in as four of them (`frontend/e2e/helpers/demo.ts`):

| e2e name | Account | Role |
|---|---|---|
| `ADMIN` | `eleni.papadopoulou@urbanfloods.example` | superadmin, trusted |
| `EDITOR` | `matej.kovacic@urbanfloods.example` | admin, trusted |
| `MEMBER` | `giulia.romano@urbanfloods.example` | member, trusted |
| `NEWBIE` | `arben.hoxha@urbanfloods.example` | member, verified, not trusted |

The seed is idempotent and refuses to run unless `ENV` is `dev` or `test`. All personas and what
each is for: [backend/README.md](../backend/README.md#development-seed).

## 4. End-to-end (Playwright)

Prerequisites:

- the development stack running (`docker compose up --build`): frontend `:5173`, backend `:8000`,
  Mailpit `:8025`; the dev compose sets `EMAIL_ENABLED=true` (to Mailpit),
  `TURNSTILE_ENABLED=false`, `RATE_LIMIT_ENABLED=true`, `ENABLE_SCHEDULER=false`;
- the development seed loaded (section 3);
- a Playwright browser: `cd frontend && npx playwright install chromium`.

```bash
cd frontend
npm run e2e                     # all specs, Chromium, one worker, files in order
npm run e2e -- forum            # one spec
npm run e2e:ui                  # interactive runner
npm run e2e:report              # open the last HTML report
E2E_A11Y=1 npm run e2e -- a11y  # include the axe WCAG 2.1 AA scans
```

Targets can be overridden with `E2E_BASE_URL`, `E2E_API_URL`, `E2E_MAILPIT_URL` and
`E2E_FRONTEND_URL`. The browser locale is pinned to `en-GB` so English strings match.

| Spec | Tests | Verifies |
|---|---|---|
| `auth.spec.ts` | 8 | register → verification link read from the Mailpit API → verified and signed in; change password; log out; log in; partners page; wrong-password error; forgot/reset password via email |
| `blog.spec.ts` | 7 | public list, filters and post page with KNOWBASE links; trusted member writes a post with formatting, tags, cover image and a KNOWBASE link, edits and deletes it; untrusted member's post stays pending and private; unsaved-changes guard |
| `forum.spec.ts` | 8 | reply notification email; trusted member's thread published; reply, nested reply, edit, delete; admin pin/lock; untrusted member's thread pending; comments on posts; notification preferences persist |
| `moderation.spec.ts` | 6 | first post pending → approve → author trusted; reject with reason in the audit log; three distinct reports auto-hide, dismiss and unhide; dashboard numbers, KNOWBASE state and CSV download; digest email via `docker compose exec backend python -m app.cli digest --force` (skipped when the compose backend is not running); trust toggle and role-menu gating |
| `a11y.spec.ts` | 3 | axe WCAG 2.1 AA on public pages, a forum thread, the admin dashboard and queue; skipped unless `E2E_A11Y=1` |

`moderation.spec.ts` is increment 4h; on 2026-10-31 it is in the working tree but not yet
committed. [CHECK]

Each spec creates titles with a per-run suffix and cleans up after itself (deletes what it
created, dismisses its reports, removes the newbie's trust), so runs are repeatable.

### Rate-limit budget per full run

The dev backend enforces the real limits, keyed by client IP, in memory:

| Limit | Budget | Used by one full run |
|---|---|---|
| `auth.login` | 10 per 15 min (one more every 90 s) | 12 (auth 2, blog 2, forum 4, moderation 4); 14 with `E2E_A11Y=1` |
| `auth.register` | 5 per hour | 1 (auth) |
| `auth.password_forgot` | 3 per hour | 1 (auth) |
| `auth.me_password` | 10 per hour | 1 (auth) |

A full run therefore relies on the login bucket refilling while the specs run; the moderation
spec waits once for `Retry-After` on a 429. Running the full suite twice in a row within about
15 minutes, or three times within an hour, exhausts the budgets. The buckets live in the backend
process: `docker compose restart backend` resets them.

## 5. Continuous integration

`.github/workflows/ci.yml`, on every push to `main` and every pull request:

| Job | Steps |
|---|---|
| Backend (ruff + pytest) | Python 3.11 via uv; `uv sync --all-extras --frozen`; `ruff check`; `ruff format --check`; `pytest --cov=app` against a Postgres 16 service container (`TEST_DATABASE_URL`); coverage XML uploaded as an artifact |
| Frontend (lint, types, vitest, build) | Node 22; `npm ci`; `lint:check`; `type-check`; `test`; `build-only` |
| Docker images build | on `main` only, after both jobs: builds the backend image and the frontend dev image (no push) |

Playwright does not run in CI; run it locally against the dev stack before closing a milestone.
An increment is done only when CI is green.

# Testing

This document explains how to run the platform's automated tests: the backend suite (pytest
against a real Postgres), the frontend unit tests (vitest), the end-to-end tests (Playwright
against the development stack, with Mailpit for email), the production-mode smoke test
(Playwright against the real production stack), and what CI runs on every push. The
project works test-first: every increment lands with its tests (see the root `CLAUDE.md`).

Last updated: 2026-11-02

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
collects 1613 tests in 53 files, including the 11 tests of the development seed
(`tests/test_seed_dev.py`).

## 2. Frontend (vitest, lint, types)

```bash
cd frontend
npm ci
npm run test          # vitest run (happy-dom)
npm run test:watch    # watch mode
npm run lint:check    # eslint incl. eslint-plugin-vuejs-accessibility (npm run lint fixes)
npm run type-check    # vue-tsc; on a fresh clone run `npm run build-only` (or `npm run test`) once before it:
                      # the Nuxt UI Vite plugin generates the gitignored components.d.ts and auto-imports.d.ts
npm run build-only    # production build
```

On 2026-10-31, `npm run test` passes 1017 tests in 60 files.

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

`--reset` hard-deletes every `@urbanfloods.example` account and the seeded anonymised account,
with everything they authored (posts, threads, replies, comments, reports, uploads), then
reseeds. Accounts with other addresses and their content are kept. Run it before a full e2e run
and whenever manual testing has drifted the data.

The e2e suite logs in as four of them (`frontend/e2e/helpers/demo.ts`):

| e2e name | Account | Role |
|---|---|---|
| `ADMIN` | `eleni.papadopoulou@urbanfloods.example` | superadmin, trusted |
| `EDITOR` | `matej.kovacic@urbanfloods.example` | admin, trusted |
| `MEMBER` | `giulia.romano@urbanfloods.example` | member, trusted |
| `NEWBIE` | `arben.hoxha@urbanfloods.example` | member, verified, not trusted |

The other eight personas cover the remaining account states for manual testing: a second admin,
another trusted member, a member hidden from the directory, an untrusted member with the seeded
pending post and a free-text organisation, an unverified account, a banned account, an anonymised
"Deleted user" and a minimal profile. The seed is idempotent and refuses to run unless `ENV` is
`dev` or `test`. All personas and what each is for:
[backend/README.md](../backend/README.md#development-seed).

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
| `auth.spec.ts` | 9 | register → verification link read from the Mailpit API → verified and signed in; change password; change the email address through the link sent to the new address; log out; log in with the new address; `/partners` opens the partnership section of About with the live organisations; wrong-password error; forgot/reset password via email |
| `blog.spec.ts` | 7 | public list, filters and post page with KNOWBASE links; trusted member writes a post with formatting, tags, cover image and a KNOWBASE link, edits and deletes it; untrusted member's post stays pending and private; unsaved-changes guard |
| `forum.spec.ts` | 8 | reply notification email; trusted member's thread published; reply, nested reply, edit, delete; admin pin/lock; untrusted member's thread pending; comments on posts; notification preferences persist |
| `moderation.spec.ts` | 8 | first post pending → approve → author trusted; reject with reason in the audit log; three distinct reports auto-hide, dismiss and unhide; dashboard numbers, KNOWBASE state and CSV download; digest email via `docker compose exec backend python -m app.cli digest --force` (skipped when the compose backend is not running); trust toggle and role-menu gating; Moderate menu on a post: hide with a reason, unhide, delete permanently; Uploads tab: an image used by a post cannot be deleted, purging the post removes it |
| `a11y.spec.ts` | 4 | axe WCAG 2.1 AA, one `h1` and `lang="en"` on 25 pages: 11 public pages, the forum list and a thread, 3 member pages (account, network, editor) and the 9 admin pages; skipped unless `E2E_A11Y=1` |

A full `npm run e2e` therefore runs 32 tests (auth 9, blog 7, forum 8, moderation 8) and skips the
4 accessibility tests.

Each spec creates titles with a per-run suffix and cleans up after itself (deletes what it
created, dismisses its reports, removes the newbie's trust), so runs are repeatable.

### Rate-limit budget per full run

The dev backend enforces the real limits, keyed by client IP, in memory:

| Limit | Budget | Used by one full run |
|---|---|---|
| `auth.login` | 10 per 15 min (one more every 90 s) | 12 (auth 2, blog 2, forum 4, moderation 4); 15 with `E2E_A11Y=1` (a11y 3); blog needs a third (admin) login only if the newbie is trusted when it starts |
| `auth.register` | 5 per hour | 1 (auth) |
| `auth.password_forgot` | 3 per hour | 1 (auth) |
| `auth.password_reset` | 10 per hour | 1 (auth) |
| `auth.me_password` | 10 per hour | 1 (auth) |
| `auth.me_email` | 5 per hour | 1 (auth) |

Counted from the specs: auth logs in through the form in tests 5 and 7 (the wrong password counts
too; the verification link and the password reset sign in without `auth.login`); blog logs in the
member and the newbie once through the API; forum logs in the editor, member, admin and newbie
through the form; moderation logs in the admin, newbie, member and editor through the API; a11y
logs in the editor, the member and the admin through the API.

A full run therefore relies on the login bucket refilling while the specs run; the moderation
spec waits once for `Retry-After` on a 429 (the other specs do not retry). With `E2E_A11Y=1` the
a11y spec runs first (files run in alphabetical order), so the 15 logins come sooner: restart the
backend first, or run the a11y spec on its own (`E2E_A11Y=1 npm run e2e -- a11y`, 3 logins).
Running the full suite twice in a row within about 15 minutes, or three times within an hour,
exhausts the budgets. The buckets live in the backend process: `docker compose restart backend`
resets them.

## 5. Continuous integration

`.github/workflows/ci.yml`, on every push to `main` and every pull request:

| Job | Steps |
|---|---|
| Backend (ruff + pytest) | Python 3.11 via uv; `uv sync --all-extras --frozen`; `ruff check`; `ruff format --check`; `pytest --cov=app` against a Postgres 16 service container (`TEST_DATABASE_URL`); coverage XML uploaded as an artifact |
| Frontend (lint, types, vitest, build) | Node 22; `npm ci`; `lint:check`; `build-only` (generates `components.d.ts`); `type-check`; `test` |
| Docker images build | on `main` only, after both jobs: builds the backend image, the frontend dev image and the frontend production image (no push) |
| Production-mode smoke test | after both jobs, on every push and pull request: Node 22, `npm ci`, `npx playwright install --with-deps chromium`, `scripts/smoke.sh` (section 6); on failure the Playwright report and the container logs are uploaded as artifacts |

The development e2e suite (section 4) does not run in CI; run it locally against the dev stack
before closing a milestone. The smoke suite (section 6) does.
An increment is done only when CI is green.

## 6. Production-mode smoke test

The suites above run with the production protections switched off: Turnstile disabled, no CSP,
the Vite dev server instead of nginx, email into an outbox. Bugs that live only in the production
configuration slipped through that way (on 2026-11-01 "resend verification" and "forgot
password" always failed because only the register form sent a Turnstile token; earlier, `.webp`
uploads were served with the wrong MIME type only by the production image). The smoke test
starts the **real production stack** and drives it with a short Playwright suite, so such bugs
fail CI before `deploy.sh`.

**What runs.** `docker-compose.prod.yml` (nginx with the built SPA, the backend image, Postgres)
plus the override `docker-compose.smoke.yml` with the test values in `.env.smoke` (committed, no
secrets). The override only adds a Mailpit service and renames the project, containers, images,
volumes and network (`ufsmoke*`), so a run can never touch the development or production stack.
Everything else is production: `ENV=prod`, Secure cookies, `TRUST_PROXY_HEADERS`, Turnstile on
(Cloudflare's official test keys: the widget renders and always passes, and the backend still
calls Cloudflare's siteverify, so a form that sends no token fails), real SMTP sending (to
Mailpit), the nginx CSP and headers, migrations in the backend entrypoint on an empty database,
the real KNOWBASE public API (GET only).

```bash
cd frontend && npm ci && npx playwright install chromium && cd ..
scripts/smoke.sh                  # build, start, create the superadmin, run, always `down -v`
scripts/smoke.sh -- auth          # only the specs matching "auth" (arguments after -- go to Playwright)
SMOKE_KEEP=1 scripts/smoke.sh     # keep the stack afterwards (http://localhost:3002, Mailpit :8026)
scripts/smoke.sh --down           # remove a kept stack
```

`scripts/smoke.sh` needs Docker, Node 22 and free ports 127.0.0.1:3002, :8002 (the production
ports, so it refuses to run on the production server) and :8026 (Mailpit's API; the development
stack's Mailpit keeps :8025, so both stacks can run side by side; override with
`SMOKE_MAILPIT_PORT`). It creates a superadmin with the backend CLI
(`python -m app.cli create-superadmin`) with a random per-run password, runs
`npm run e2e:smoke` (Playwright project `smoke`, only `frontend/e2e/smoke/*.smoke.spec.ts`;
`npm run e2e` never runs these and the smoke run never runs the development specs), prints the
container logs on failure (`SMOKE_LOG_DIR` also writes them to files) and always tears the stack
down with `down -v` (the `:smoke`-tagged images stay, so the next build is cached). On
2026-11-02 a local run took 47 s with warm Docker caches (stack healthy after about 30 s, the 10
tests 16 s); cold image builds, as in CI, add a few minutes.

The suite creates its own data (no seed) and stays inside the real rate limits (3 registrations,
3 logins, 1 password reset request and 1 resend per run), so it runs without retries.

| Spec | Tests | Verifies |
|---|---|---|
| `auth.smoke.spec.ts` | 4 | 1. register through the form: the Turnstile widget renders, submit waits for the token, the request carries it, 201; verification email in Mailpit, link, verify button, signed in. 2. log in and out through the UI; `uf_session` is Secure, HttpOnly, SameSite=Lax and is gone after logout. 3. forgot password through the form (token sent, 202) → email → reset page → signed in → log in with the new password. 4. resend verification from the anonymous form on `/verify-email` (token sent, 202) → a second verification email |
| `content.smoke.spec.ts` | 2 | 5. a new member's first post with a cover image (PNG upload) is pending and invisible to anonymous visitors; the cover loads in the page and is served through nginx `/static/uploads/…webp` as `image/webp` with exactly one `nosniff`. 6. the superadmin approves it in `/admin/queue`; the post and its cover are public |
| `public.smoke.spec.ts` | 4 | 7. `/` and a hashed `/assets/` bundle carry the CSP (Turnstile, KNOWBASE images, no framing) and every nginx security header; the home page boots with one `h1`. 8. `/feeds/posts.atom` and `/feeds/threads.atom` (200, `application/atom+xml`), `/sitemap.xml`, `/robots.txt` with its `Sitemap:` line, `/api/v1/openapi.json`. 9. `/knowbase/measures` renders its `h1`, then the measures or its error state (KNOWBASE unreachable), never a blank page. 10. client routes fall back to the SPA (its "Page not found"), a missing `/assets/` file is a real 404 |

**CSP guard.** Every browser context of every smoke test is watched (`e2e/smoke/fixtures.ts`):
any console message about a Content Security Policy violation, and any `securitypolicyviolation`
event in a document of our origin, fails the test. Messages located inside
`challenges.cloudflare.com` are ignored: Cloudflare's Turnstile iframe logs CSP noise of its own,
which our policy neither causes nor can fix.

### Development vs production settings

| Concern | Development stack and pytest | Production | Production value covered by |
|---|---|---|---|
| Turnstile | off (`TURNSTILE_ENABLED=false`, no site key: no widget, forms send no token) | on: widget on register, resend verification and forgot password; backend verifies every token with Cloudflare | smoke 1, 3, 4 (widget, token in the request, 201/202); the deliberate removal of the forgot-password token fails smoke 3 with 400 `auth.captcha_failed` |
| Session cookie | `COOKIE_SECURE=false` | `uf_session` Secure, HttpOnly, SameSite=Lax | smoke 2 |
| CSP and security headers | none (Vite dev server) | `frontend/nginx.conf`: CSP, `nosniff`, `X-Frame-Options: DENY`, Referrer-Policy, Permissions-Policy (HSTS from the host nginx) | smoke 7, and the CSP guard on all 10 tests |
| Web server and proxy paths | Vite on :5173, backend on :8000 (cross-origin, CORS) | one origin: nginx serves the built SPA and proxies `/api/`, `/static/`, `/feeds/`, `/sitemap.xml`, `/robots.txt`, `/docs`, `/health` | every smoke test runs through :3002; smoke 7, 8, 10 |
| Proxy headers | `TRUST_PROXY_HEADERS=false` | `true`: scheme from `X-Forwarded-Proto` (CSRF origin check), client IP from `CF-Connecting-IP` (rate limits, Turnstile) | every form POST behind nginx (smoke 1-6); `CF-Connecting-IP` from Cloudflare is not (no Cloudflare in front) |
| Email transport | pytest: in-memory outbox; dev: SMTP to Mailpit | SMTP to Brevo (STARTTLS on 587, login) | smoke 1, 3, 4, 5 send real SMTP from the production image to Mailpit; TLS, login and delivery through Brevo are not covered |
| KNOWBASE | pytest: mocked with `respx`; dev: real public API | real public API, server-to-server through the backend proxy | smoke 9 |
| Upload serving | pytest: test client; dev: backend directly | backend image's static files behind nginx `/static/` (7-day cache, one `nosniff`) | smoke 5, 6 (`image/webp`, WebP bytes, loads in the page) |
| Build and runtime | Vite dev build, `ENV=dev`, hot reload | `vite build` with baked `VITE_*`, `ENV=prod`, single uvicorn worker, scheduler on | all smoke tests (the production images) |
| Migrations | applied once per pytest session / by the dev entrypoint | backend entrypoint on every start | the smoke stack starts from an empty database |
| Rate limits | on (dev), per test where needed (pytest) | on | the smoke suite runs inside the real budgets |

Not covered anywhere automatically: the host nginx (TLS, HSTS), Cloudflare in front of the
origin, the production Turnstile keys and hostname, real delivery through Brevo, `deploy.sh` and
backups. Those stay on the manual production smoke test
([deployment.md §7](deployment.md#7-smoke-test-on-production)).

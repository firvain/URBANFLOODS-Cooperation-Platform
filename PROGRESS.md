# PROGRESS — URBANFLOODS Cooperation Platform

Single source of truth across sessions. **Read this first. Update it in the same commit as every
increment.** Full plan: [`docs/PLAN.md`](docs/PLAN.md).

## 1. Targets

**Deliverable:** D.5.1.1 "Cooperation Platform and Report for Enhanced Resilience to Flood Risks"
(IPA-ADRION00374, WP5, Activity 5.1, lead UOWM). Due Period 6 (project months 31–36; project runs 01/09/2024 – 31/08/2027, so the hard deadline is **31 August 2027**). Consists of
the live platform at `cooperation.urbanfloods.app` plus a succinct report on its development and
functionality (`docs/report-D5.1.1-outline.md`).

**What the AF requires:** registration; categorised information (measures, actions, policy
recommendations from the KNOWBASE, tailored to local conditions); blog-like format; a dynamic forum
for interaction, learning and collaboration; built on the KNOWBASE; accessible (screen readers,
keyboard, alt text); FAIR (discoverable, open formats, documented, exportable); GDPR; English with
the 9 project locales; must stay useful after the project with few active admins; supports the MoU
among the 22 partner organisations (Output 5.1 indicator: organisations cooperating across borders).

**Hard constraints**
- KNOWBASE (repo, containers, DB) is never modified. Consumed via its public API only.
- Nothing is deployed to the server without explicit permission for that step.
- TDD. Fable 5.1 designs and reviews; Opus 5.5 implements. One increment = one commit, pushed.
- Everything free/open source.

**Decisions (see PLAN.md for the full table):** FastAPI + Vue 3/Nuxt UI v4 + Postgres, same
conventions as KNOWBASE · backend proxies KNOWBASE API with cache · open sign-up with email
verification · roles member/admin/superadmin · "trusted after first approval" posting model, with
optional `AUTO_APPROVE_AFTER_DAYS` safety valve · reports auto-hide · soft delete ·
cooperation.urbanfloods.app · Gmail SMTP · one language per post · CC BY 4.0 · images only ·
seeded organisations table (22 PPs/APs) + `/partners` page · admin-only "Resources" category · **light mode only** · official logos/favicon from urbanfloods.interreg-ipa-adrion.eu ·
admin stats CSV export · public read, registration to participate · public repo on GitHub.

**Scope line:** Core = M0–M4, 5a, 5c–5e, 5g, M6. Extended = 5b, 5f, tag merge, sessions UI,
email change, per-type notification prefs, JSON-LD. Core first, always.

## 2. Milestone board

Status: `todo` · `in progress` · `done` · `blocked`. Commit = short SHA on `main` (filled in by the following commit, since a commit cannot know its own hash).

### M0 — Scaffold, Docker, CI
| Inc | Scope | Status | Commit | Tests | Notes |
|---|---|---|---|---|---|
| 0a | git init, .gitignore, README, CLAUDE.md, docs/PLAN.md, PROGRESS.md, GitHub repo, first push | done | bf847e2 | — | AF markdown kept out of the public repo (.gitignore) |
| 0b | Backend skeleton: pyproject, Dockerfile, config, logging, session, main.py, `/health` + test, conftest | done | f7ada1c | 10 pytest | testcontainers Postgres; skips DB tests without Docker; sqlalchemy[asyncio] needed for 2.1 |
| 0c | Alembic async init + `0001_extensions` + migration test | done | 034e3d5 | 16 pytest (6 new) | connection-sharing recipe for in-loop migrations; container entrypoint runs `alembic upgrade head`; new revisions need `--rev-id 000N` |
| 0d | Frontend skeleton: Vite + Nuxt UI + router + i18n (9 locales) + layout + HomeView + api.ts + vitest smoke | done | a453987 | 31 vitest | Vite 8, vue-router 5, pinia 4, Nuxt UI 4.12, happy-dom; icons bundled locally; flag-icons not imported globally (628 kB) |
| 0e | Dev compose + compose.test + GitHub Actions CI | done | 8fe7b93 | stack verified e2e; actionlint clean | `docker compose up --build`; test DB on 5434; CI backend on py3.11 + frontend + docker build |

### M1 — Auth + email
| Inc | Scope | Status | Commit | Tests | Notes |
|---|---|---|---|---|---|
| 1a | Models Organisation (seeded 22 PPs/APs) / User / Session / EmailToken / NotificationPreference / AuditLog + migration | done | a178ddd | 25 pytest (9 new) | naming convention on metadata; enums owned by migrations; `avatar_attachment_id` FK deferred to 2a |
| 1b | `core/security.py` argon2 + session tokens + cookie helpers | done | 8654679 | 61 pytest | + crud/session (revoke scoped by user), crud/token (atomic consume), crud/audit (strips secret-like keys) |
| 1c | `services/email.py` + templates + outbox fixture + Mailpit; `services/turnstile.py` | done | 2360b6e | 40 pytest | `*_url` context values must be site-relative paths; en templates: verify_email, reset_password, change_email, welcome; el: verify_email |
| 1d | register / verify-email / resend endpoints | done | 83761bd | 41 pytest (167 total) | uniform error body `detail.{code,message,fields}`; `DbTx` commits before response; verified live against Mailpit |
| 1e | login / logout / me / sessions + `core/deps.py` | done | 520b765 | 70 pytest (237 total) | code-review medium: 9 findings fixed (pool starvation, re-login revokes old session, `AppError(keep_changes)` mechanism, eager-load chain, touch gated 5 min); rate limit deferred to 1g |
| 1f | password forgot/reset + change password/email | done | a33567c | 47 pytest | reset/change cancel pending CHANGE_EMAIL tokens; email confirm cancels VERIFY/RESET tokens (takeover defence) |
| 1g | CSRF + rate-limit middleware | done | | 55 pytest | hand-written GCRA limiter (no slowapi), per-route table + 300/min guard; CSRF origin check on every unsafe request + X-Requested-With when a cookie is present |
| 1h | admin users + organisations endpoints + `cli create-superadmin` | done | 537543b | 116 pytest (400 total) | last-superadmin guard; superadmin-only for superadmin changes; `python -m app.cli create-superadmin` |
| 1i | GDPR export + anonymising delete | done | | 18 pytest (473 total) | + GET/PUT /me/notifications; export excludes hashes and actor ids |
| 1j | FE auth store/service/views + guards | done | bf59061 | 70 vitest (101 total) | login/register/verify/forgot/reset views, UserMenu, UnverifiedBanner, open-redirect guard, 401/429 API hooks; hand-typed auth types until `gen:types` |
| 1j-b | FE branding: light mode only, official logos + favicon from the project site, footer disclaimer | done | 634c2e4 | 60 vitest (161 total) | `ui({ colorMode: false })`; footer: 4 columns + green accent + statement + disclaimer + LinkedIn; flex page shell; About page facts; logo-size interpretation in docs/branding.md |
| 1k | FE AccountView + PartnersView (KNOWBASE About-page style, see docs/about-partners-style.md) + About facts | done | d8a235e | 41 vitest (202 total) | partner logos + flags, no short-name badges (user), Macerata coat of arms recoloured navy; Account tabs profile/password/sessions |
| 1m | Expertise tags (seeded vocabulary) + user_expertise + show_email/show_in_directory + members directory API (`/members/`, filters) | todo | | | from 3rd-meeting commitments (matchmaking) |
| 1n | FE Collaboration Network page: members directory + suggested collaborators widget; DSS nav link + home card (`VITE_DSS_URL`) | done | b68461e | 35 vitest (246 total) | /network, /u/:id, suggested on Home for verified users, expertise picker + visibility switches in Account; nav Home·Partners·Network·Unified DSS·About |
| 1l | Playwright `auth.spec.ts` | done | d0971d3 | 8 e2e | register→Mailpit→verify→account→password change→logout→login→partners; forgot/reset; a11y spec opt-in (`E2E_A11Y=1`): contrast issues on /partners, /about, /register for M5 |

### M2 — Blog + KNOWBASE proxy
| Inc | Scope | Status | Commit | Tests | Notes |
|---|---|---|---|---|---|
| 1o | Expertise asked at registration (backend: `expertise_ids` on register; FE: optional picker on the form, 'complete your profile' nudge after verification and on empty Network cards) | done | 43bcd21 (backend) | 8 pytest + 21 vitest (309 total) | collapsible picker on sign-up; CompleteProfileBanner on verify/home/network; own-card link; suggestions widget hidden until expertise is set |
| 2a | Models Category/Tag/Post/Attachment/KnowbaseLink + migration (FTS, trigram) | done | 317b387 | 21 pytest | migration 0004; `sa.Computed` tsvector; seeded 9 categories |
| 2b | `services/sanitize.py` (nh3) + `services/slugs.py` | done | a258d05 | 91 pytest | | | |
| 2c | `services/knowbase.py` proxy + cache + `/knowbase/*` endpoints | done | 2b4e995 | 61 pytest (694 total) | | | |
| 2d | categories + tags endpoints | done | 5db7103 | 39 pytest | | | |
| 2e | posts endpoints (visibility, trust→status, knowbase_links) | done | | 56 pytest (852 total) | `crud/visibility.py` shared rule; FTS + trigram; mentions route; moderation transitions left to 4b | | | |
| 2f | `services/images.py` + uploads + static mount | done | a8f704e | 62 pytest (796 total) | WebP re-encode, EXIF stripped, avatars; orphan sweep + export/delete of attachments deferred to M4 | | | |
| 2g | `scripts/seed_dev.py` + `npm run gen:types` | done | 8977626 | 5 pytest (857 total) | demo accounts `*@urbanfloods.example` (see backend/README.md); api-schema.ts generated (services not rewired yet) | | | |
| 2h | FE knowbase store/views | done | bda74dc | 40 vitest | | | |
| 2i | FE editor components (Tiptap) | done | c8f50fb | 50 vitest (399 total) | Tiptap 3.32 (already a Nuxt UI dependency, lazy chunk ≈131 kB gzip); tables skipped; happy-dom NodeIterator shim | | | |
| 2j | FE blog views + stores | done | a18244d | 72 vitest (471 total) | list/detail/editor on generated types; header collapses to burger below xl (overflow fix) | | | |
| 2k | Playwright `blog.spec.ts` | done | 151f1de | 7 e2e (15 total) | **M2 complete.** a11y findings (M5): contrast on /partners h3, /about labels, /register placeholders, avatar initials; mailto label mismatch | | | |

### M3 — Forum + comments
| Inc | Scope | Status | Commit | Tests | Notes |
|---|---|---|---|---|---|
| 3a | Models Thread/Reply/Comment + migration (one-level trigger, counters) | done | 8710d19 | 28 pytest (885 total) | migration 0005; nesting + counter triggers | | | |
| 3b | threads endpoints + admin pin/lock | done | 1ceb637 | 52 pytest | tag usage now counts threads too | | | |
| 3c | replies endpoints | done | 374abf7 | 29 pytest (996 total) | one-level nesting via trigger mapped to 422; placeholders for invisible parents; merge_tags moves thread_tags | | | |
| 3d | comments endpoints | done | 88157ae | 30 pytest | | | |
| 3e | notification emails honouring preferences | in progress | | | |
| 3f | FE forum views + stores | done | | 84 vitest (555 total) | threads list/detail/editor, replies tree with optimistic insert, compact editor prop, shared .content-prose | | | |
| 3g | FE comments + notifications tab | in progress | | | |
| 3h | Playwright `forum.spec.ts` | todo | | | |

### M4 — Moderation + admin UI
| Inc | Scope | Status | Commit | Tests | Notes |
|---|---|---|---|---|---|
| 4a | Models Report/DigestRun + migration | todo | | | |
| 4b | `crud/moderation.py` state machine + audit | todo | | | |
| 4c | reports endpoint + auto-hide | todo | | | |
| 4d | moderation + admin endpoints incl. stats CSV export | todo | | | |
| 4e | digest + scheduler (+ AUTO_APPROVE_AFTER_DAYS sweep) + `cli digest` | todo | | | |
| 4f | FE report/status components | todo | | | |
| 4g | FE admin views | todo | | | |
| 4h | Playwright `moderation.spec.ts` | todo | | | |

### M5 — Search, i18n, a11y, FAIR, docs
| Inc | Scope | Status | Commit | Tests | Notes |
|---|---|---|---|---|---|
| 5a | search crud + endpoint | todo | | | core |
| 5b | export endpoints, Atom, sitemap | todo | | | extended |
| 5c | FE SearchView + header search + `usePageHead` | todo | | | core |
| 5d | accessibility pass + axe in Playwright | todo | | | core |
| 5e | static pages + consent text | in progress | 26107dc (5e-a) | 5e-a: 42 vitest | 5e-a done: /terms, /privacy from docs/legal markdown via a Vite plugin that strips reviewer notes at build time; marked + dompurify added; /about, /accessibility, /open-data still to do |
| 5f | translation pass (8 locales) | todo | | | extended |
| 5g | docs incl. `report-D5.1.1-outline.md`, admin handbook, moderation guide | todo | | | core |

### M6 — Production deployment (only on explicit request)
| Inc | Scope | Status | Commit | Tests | Notes |
|---|---|---|---|---|---|
| 6a | `docker-compose.prod.yml`, `.env.prod.example`, `deploy.sh`, backup script | todo | | | files only, no deploy |
| 6b | `docker/nginx-host-config.template`, `docs/deployment.md` | todo | | | |
| 6c | First deployment to server | blocked | | | needs explicit user permission |

## 3. Session log

### 2026-10-30
- Read the AF (Activity 5.1 / D.5.1.1), surveyed the KNOWBASE repo and its live deployment,
  set up `ssh knowbase` access, created the Cloudflare A record for cooperation.urbanfloods.app
  (resolves; 502 expected until nginx + cert exist).
- Agreed stack, integration approach (backend proxy of KNOWBASE API), posting model, licence,
  attachments, hostname, email, repo visibility. Plan written and approved → `docs/PLAN.md`.
- Working method fixed: TDD, Opus 5.5 implements, Fable reviews, one increment per commit.
- 0a done (bf847e2). 0b done: backend skeleton, 10 tests green against testcontainers Postgres.
  `docs/partners.md` extracted from the AF (22 organisations + homepages) for 1a.
- User: "use as many agents as needed" → 0d (frontend) runs in parallel with 0b.
- 0c done: Alembic async, `0001_extensions` (pg_trgm, citext), test DB migrated to head per session, Docker entrypoint migrates then execs.
- 0d done: frontend skeleton, 31 vitest green, lint/type-check/build clean. 1a started in parallel.
- 1a done: 6 auth tables + 4 enums, migration 0002 seeds the 22 organisations, autogenerate clean. 0e in progress.
- 0e done: M0 complete. Dependencies for 1b/1c committed ahead (1b13bd9). 1b and 1c running in parallel.
- 1c done (email service, 16 templates, Turnstile). Note for 1d: pass `verify_url='/verify-email?token=...'` style paths; `aclose_client()` for Turnstile still needs wiring into the lifespan.
- 1b done (126 tests total). 1d (backend registration endpoints) and 1j (frontend auth) started in parallel.
- 1d done. Dev stack is up locally (localhost:5173 / :8000/docs / :8025). 1e started; 1j still running.
- 1j done. 3rd-meeting presentation reviewed → DSS link-out, matchmaking (1m/1n), events on posts added to plan (6b5962a).
- 1e, 1j-b (branding, footer redesign, illustrated logo in footer), 1f, 1h done. Partner logos collected from SharePoint into frontend/public/partners. 1k in progress.
- 1k done: Partners (live from /organisations/), About (real facts), Account (profile/password/sessions). Footer: illustrated logo (small); header 384 px; 'flood management' wording rule.
- 1g, 1i, 1l done → **M1 core complete** (473 backend tests, 211 vitest, 8 e2e). Footer restyled like the KNOWBASE footer; Partners page compact; About = project only.
- 1m, 1n done → **M1 fully complete** incl. 3rd-meeting additions. Terms of Use + Privacy Policy drafts in docs/legal. M2 deps committed (068adb3).
- **Next:** M2 in parallel: 2a (blog models + migration 0004), 2b (sanitize + slugs), 2c (KNOWBASE proxy); frontend 5e-a (legal pages /terms, /privacy from docs/legal markdown).

## 4. Open questions / decisions pending
- Terms of Use draft v1 in `docs/legal/terms-of-use.md` needs UOWM legal review: age threshold (15/16), KNOWBASE data licence, jurisdiction. Contact for everything (incl. data requests): louta@uowm.gr (user, 2026-10-31). Privacy Policy draft v1 in `docs/legal/privacy-policy.md` (2026-10-31): review DPO naming, audit-log retention per subsidy contract, hosting description, Cloudflare/Google DPAs, age threshold.
- None blocking. Turnstile site key and Gmail app password are needed before M1 can be tested
  end-to-end against real services (dev uses Mailpit and `TURNSTILE_ENABLED=false`).

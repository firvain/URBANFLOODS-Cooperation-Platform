# PROGRESS — URBANFLOODS Cooperation Platform

Single source of truth across sessions. **Read this first. Update it in the same commit as every
increment.** Full plan: [`docs/PLAN.md`](docs/PLAN.md).

## 1. Targets

**Deliverable:** D.5.1.1 "Cooperation Platform and Report for Enhanced Resilience to Flood Risks"
(IPA-ADRION00374, WP5, Activity 5.1, lead UOWM). Due Period 6 (project months 31–36). Consists of
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
seeded organisations table (22 PPs/APs) + `/partners` page · admin-only "Resources" category ·
admin stats CSV export · public read, registration to participate · public repo on GitHub.

**Scope line:** Core = M0–M4, 5a, 5c–5e, 5g, M6. Extended = 5b, 5f, tag merge, sessions UI,
email change, per-type notification prefs, JSON-LD. Core first, always.

## 2. Milestone board

Status: `todo` · `in progress` · `done` · `blocked`. Commit = short SHA on `main` (filled in by the following commit, since a commit cannot know its own hash).

### M0 — Scaffold, Docker, CI
| Inc | Scope | Status | Commit | Tests | Notes |
|---|---|---|---|---|---|
| 0a | git init, .gitignore, README, CLAUDE.md, docs/PLAN.md, PROGRESS.md, GitHub repo, first push | done | bf847e2 | — | AF markdown kept out of the public repo (.gitignore) |
| 0b | Backend skeleton: pyproject, Dockerfile, config, logging, session, main.py, `/health` + test, conftest | done | | 10 pytest | testcontainers Postgres; skips DB tests without Docker; sqlalchemy[asyncio] needed for 2.1 |
| 0c | Alembic async init + `0001_extensions` + migration test | todo | | | |
| 0d | Frontend skeleton: Vite + Nuxt UI + router + i18n (9 locales) + layout + HomeView + api.ts + vitest smoke | in progress | | | running in parallel with 0b |
| 0e | Dev compose + compose.test + GitHub Actions CI | todo | | | |

### M1 — Auth + email
| Inc | Scope | Status | Commit | Tests | Notes |
|---|---|---|---|---|---|
| 1a | Models Organisation (seeded 22 PPs/APs) / User / Session / EmailToken / NotificationPreference / AuditLog + migration | todo | | | partner list from AF section B |
| 1b | `core/security.py` argon2 + session tokens + cookie helpers | todo | | | |
| 1c | `services/email.py` + templates + outbox fixture + Mailpit; `services/turnstile.py` | todo | | | |
| 1d | register / verify-email / resend endpoints | todo | | | |
| 1e | login / logout / me / sessions + `core/deps.py` | todo | | | |
| 1f | password forgot/reset + change password/email | todo | | | |
| 1g | CSRF + rate-limit middleware | todo | | | |
| 1h | admin users + organisations endpoints + `cli create-superadmin` | todo | | | |
| 1i | GDPR export + anonymising delete | todo | | | |
| 1j | FE auth store/service/views + guards | todo | | | |
| 1k | FE AccountView + LocaleSwitcher + PartnersView | todo | | | |
| 1l | Playwright `auth.spec.ts` | todo | | | |

### M2 — Blog + KNOWBASE proxy
| Inc | Scope | Status | Commit | Tests | Notes |
|---|---|---|---|---|---|
| 2a | Models Category/Tag/Post/Attachment/KnowbaseLink + migration (FTS, trigram) | todo | | | |
| 2b | `services/sanitize.py` (nh3) + `services/slugs.py` | todo | | | |
| 2c | `services/knowbase.py` proxy + cache + `/knowbase/*` endpoints | todo | | | |
| 2d | categories + tags endpoints | todo | | | |
| 2e | posts endpoints (visibility, trust→status, knowbase_links) | todo | | | |
| 2f | `services/images.py` + uploads + static mount | todo | | | |
| 2g | `scripts/seed_dev.py` + `npm run gen:types` | todo | | | |
| 2h | FE knowbase store/views | todo | | | |
| 2i | FE editor components (Tiptap) | todo | | | |
| 2j | FE blog views + stores | todo | | | |
| 2k | Playwright `blog.spec.ts` | todo | | | |

### M3 — Forum + comments
| Inc | Scope | Status | Commit | Tests | Notes |
|---|---|---|---|---|---|
| 3a | Models Thread/Reply/Comment + migration (one-level trigger, counters) | todo | | | |
| 3b | threads endpoints + admin pin/lock | todo | | | |
| 3c | replies endpoints | todo | | | |
| 3d | comments endpoints | todo | | | |
| 3e | notification emails honouring preferences | todo | | | |
| 3f | FE forum views + stores | todo | | | |
| 3g | FE comments + notifications tab | todo | | | |
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
| 5e | static pages + consent text | todo | | | core |
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
- **Next:** review and commit 0d when its agent reports; then 0c (Alembic) and 0e (compose + CI).

## 4. Open questions / decisions pending
- None blocking. Turnstile site key and Gmail app password are needed before M1 can be tested
  end-to-end against real services (dev uses Mailpit and `TURNSTILE_ENABLED=false`).

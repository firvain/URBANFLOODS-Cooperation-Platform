# URBANFLOODS Cooperation Platform

A registration-based knowledge-sharing hub with a blog and a forum for stakeholders in flood
management across the Adriatic-Ionian region. Built on top of the
[URBANFLOODS KNOWBASE](https://knowbase.urbanfloods.app) (consumed read-only through its public API).

Deliverable **D.5.1.1** of the Interreg IPA ADRION project **URBANFLOODS** (IPA-ADRION00374),
Work Package 5, Activity 5.1. Lead partner: University of Western Macedonia (UOWM).

> Status: in development. See [`PROGRESS.md`](PROGRESS.md) for the milestone board and
> [`docs/PLAN.md`](docs/PLAN.md) for the full architecture and implementation plan.

## What it does

- **Blog**: partners and trusted members publish articles, best practices, news and resources.
- **Forum**: threaded discussions, one level of nested replies, comments on blog posts.
- **KNOWBASE browser**: measures, policies and legislation from the KNOWBASE, with link cards
  inside posts and threads.
- **Registration** with email verification. New members' first post is approved by a partner
  admin, after which they post freely. Reports auto-hide abusive content.
- **Public read, open data**: everything published is readable without an account and exported
  under CC BY 4.0 (FAIR).
- **Accessible** (WCAG-oriented) and translated UI in the 9 project languages.

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, SQLAlchemy 2 (async), Pydantic v2, Alembic, PostgreSQL 16 |
| Frontend | Vue 3, Nuxt UI v4, Pinia, vue-router, vue-i18n, Tiptap, Vite |
| Tests | pytest + testcontainers, vitest, Playwright (+ axe) |
| Runtime | Docker Compose; host nginx + Let's Encrypt; Cloudflare DNS/Turnstile |

Everything used is free and open source.

## Quick start (development)

```bash
cp .env.example .env
docker compose up --build
```

- Frontend: http://localhost:5173
- API docs: http://localhost:8000/docs
- Mailpit (captured email): http://localhost:8025

Seed demo data (idempotent; refuses `ENV=prod`): demo accounts and eight sample blog posts.

```bash
docker compose cp backend/scripts backend:/app/scripts
docker compose exec backend python -m scripts.seed_dev
```

Log in as `admin@urbanfloods.example` / `Admin-Dev-Pass-2026` (superadmin), or `editor@`,
`member@` or `newbie@` with `Editor-`, `Member-` or `Newbie-Dev-Pass-2026`. See
[`backend/README.md`](backend/README.md#development-seed) for the accounts and for running it
from the host with `uv`.

See [`docs/`](docs/) for architecture, API, deployment and the admin handbook.

## Licence

Code: MIT. User contributions on the platform: CC BY 4.0.

Co-funded by the European Union under the Interreg IPA ADRION programme.

# URBANFLOODS Cooperation Platform

A registration-based knowledge-sharing hub with a blog and a forum for flood-management
stakeholders across the Adriatic-Ionian region. Built on top of the
[URBANFLOODS KNOWBASE](https://knowbase.urbanfloods.app), which it reads through its public API
and never modifies.

Deliverable **D.5.1.1** of the Interreg IPA ADRION project **URBANFLOODS** (IPA-ADRION00374),
Work Package 5, Activity 5.1. Lead partner: University of Western Macedonia (UOWM).

> **Status (2026-10-31):** in development, not yet deployed. M0–M3 complete; M4 moderation and
> admin area implemented (end-to-end spec in progress); M5 search API, exports and feeds done,
> search UI, accessibility pass, static pages and translations under way; M6 deployment not
> started. Board: [`PROGRESS.md`](PROGRESS.md). Plan: [`docs/PLAN.md`](docs/PLAN.md).

## What it does

- **Blog**: partners and trusted members publish articles, best practices, events and resources.
- **Forum**: threaded discussions with one level of nested replies; comments on blog posts.
- **KNOWBASE library**: measures, policies and legislation from the KNOWBASE, with link cards
  inside posts and threads.
- **Collaboration network**: partner organisations and a members directory by expertise.
- **Registration** with email verification. A new member's first post or thread is approved by
  an admin, after which they publish freely. Reports hide abusive content automatically.
- **Open data**: everything published is readable without an account and exported under
  CC BY 4.0 (JSON, CSV, data package, Atom, sitemap).
- **Accessible** (WCAG 2.1 AA target); UI in the 9 project languages (English complete).

## Documentation

| Document | For |
|---|---|
| [Architecture](docs/architecture.md) | system context, data model, state machines, jobs, security |
| [API](docs/api.md) | how to call the REST API; every route |
| [Moderation guide](docs/moderation-guide.md) | admins: queue, reports, trust, digest |
| [Admin handbook](docs/admin-handbook.md) | admins and operators: accounts, stats export, GDPR, CLI, maintenance |
| [FAIR data](docs/fair-data.md) | identifiers, formats, licence, metadata |
| [Testing](docs/testing.md) | pytest, vitest, Playwright, CI |
| [D.5.1.1 report outline](docs/report-D5.1.1-outline.md) | structure of the deliverable report |
| [Legal texts](docs/legal/) | terms of use, privacy policy, accessibility statement, open data (drafts) |

## Quick start (development)

Requires Docker.

```bash
cp .env.example .env            # optional: every value has a default
docker compose up --build
docker compose exec backend python -m scripts.seed_dev    # demo accounts and posts
```

- Frontend: http://localhost:5173
- API docs: http://localhost:8000/docs
- Mailpit (captured email): http://localhost:8025

Log in as `admin@urbanfloods.example` / `Admin-Dev-Pass-2026` (superadmin); the other demo
accounts are listed in [`backend/README.md`](backend/README.md#development-seed). Running the
backend or frontend outside Docker: see the root [`CLAUDE.md`](CLAUDE.md) (section 3).

## Stack

FastAPI, SQLAlchemy 2 (async), Alembic, PostgreSQL 16 · Vue 3, Nuxt UI v4, Pinia, vue-i18n,
Tiptap, Vite · pytest + testcontainers, vitest, Playwright + axe · Docker Compose, host nginx,
Cloudflare. Everything used is free and open source.

## Licence

Code: MIT. User contributions on the platform: CC BY 4.0.

Co-funded by the European Union under the Interreg IPA ADRION programme.

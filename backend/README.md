# Backend (FastAPI)

Conventions, commands and layering are in the root [`CLAUDE.md`](../CLAUDE.md) and
[`docs/PLAN.md`](../docs/PLAN.md).

```bash
uv sync --all-extras
uv run fastapi dev app/main.py     # http://localhost:8000 (needs DATABASE_URL, SECRET_KEY: see .env.example)
uv run pytest                      # Docker (testcontainers) or TEST_DATABASE_URL
```

## Development seed

`scripts/seed_dev.py` creates demo accounts and eight blog posts (all blog categories, one Greek
post, one pending post, two admin-only Resources posts, KNOWBASE links on two posts). It is
idempotent (existing rows are left alone), runs in one transaction, and refuses to run with
`ENV=prod`.

```bash
# from backend/, against the compose Postgres on localhost:5432
DATABASE_URL=postgresql+asyncpg://cooperation:cooperation_dev_password@localhost:5432/cooperation_db \
SECRET_KEY=dev uv run python -m scripts.seed_dev

# (scripts/ is part of the image and bind-mounted in dev)
docker compose exec backend python -m scripts.seed_dev
```

| Email | Password | Role | Notes |
|---|---|---|---|
| `admin@urbanfloods.example` | `Admin-Dev-Pass-2026` | superadmin | UOWM, trusted |
| `editor@urbanfloods.example` | `Editor-Dev-Pass-2026` | admin | DCMS, trusted |
| `member@urbanfloods.example` | `Member-Dev-Pass-2026` | member | HEIS, trusted (publishes directly) |
| `newbie@urbanfloods.example` | `Newbie-Dev-Pass-2026` | member | other organisation, not trusted (has one pending post) |

All accounts are verified. `.example` is a reserved TLD (RFC 2606), so these addresses can never
be delivered to; `.local`/`.test` would be rejected by the login form's email validation. KNOWBASE link
titles come from the live KNOWBASE API when it is reachable; otherwise placeholder titles are
stored and a warning is printed.

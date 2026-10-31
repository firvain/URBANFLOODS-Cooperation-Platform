# Backend (FastAPI)

Conventions, commands and layering are in the root [`CLAUDE.md`](../CLAUDE.md) and
[`docs/PLAN.md`](../docs/PLAN.md).

```bash
uv sync --all-extras
uv run fastapi dev app/main.py     # http://localhost:8000 (needs DATABASE_URL, SECRET_KEY: see .env.example)
uv run pytest                      # Docker (testcontainers) or TEST_DATABASE_URL
```

Test setup details (compose test database, coverage, CI): [`docs/testing.md`](../docs/testing.md).

## Development seed

`scripts/seed_dev.py` creates twelve fictional personas covering every account state, eleven
blog posts (all blog categories, one Greek post, one pending post, two admin-only Resources posts,
KNOWBASE links on two posts) with comments, and four forum threads with replies (one nested, one
thread pinned). It is idempotent (existing accounts and posts/threads are left alone), runs in one
transaction, and refuses to run unless `ENV` is `dev` or `test`.

`--reset` first hard-deletes every `@urbanfloods.example` account (and the seeded anonymised
one) with everything it authored: posts, threads, replies, comments, reports, uploads (rows and
files). Comments and replies by other accounts under a deleted demo post or thread go with it
(the script warns with a count). Accounts outside the demo domain and their own content are kept.
Use it after manual or e2e testing has drifted the data, or after changing the seed.

```bash
# from backend/, against the compose Postgres on localhost:5432
DATABASE_URL=postgresql+asyncpg://cooperation:cooperation_dev_password@localhost:5432/cooperation_db \
SECRET_KEY=dev uv run python -m scripts.seed_dev [--reset]

# (scripts/ is part of the image and bind-mounted in dev)
docker compose exec backend python -m scripts.seed_dev [--reset]
```

Every demo account's password is **`Urbanfloods-2026`** (the script never prints it). The
e2e suite logs in as the four accounts marked **e2e** (`frontend/e2e/helpers/demo.ts`).
Member notifications are off by default for new accounts, so the seed switches them on for every
persona except Petra Vidmar (the minimal one keeps the defaults of a fresh account): the e2e
suite and the manual QA read reply, comment and approval emails in Mailpit.

| Name | Email | Role | State | Use it for |
|---|---|---|---|---|
| Eleni Papadopoulou | `eleni.papadopoulou@urbanfloods.example` | superadmin | verified, trusted; UOWM (GR), locale `el` | **e2e `ADMIN`**: everything, incl. promoting to superadmin |
| Matej Kovačič | `matej.kovacic@urbanfloods.example` | admin | verified, trusted; DCMS (SI), locale `sl` | **e2e `EDITOR`**: moderation queue, reports, users (no superadmin actions) |
| Aleksandar Stojanovski | `aleksandar.stojanovski@urbanfloods.example` | admin | verified, trusted; FCSE-UKIM (MK), locale `mk` | a second admin (digest recipients, admin-only Resources posts) |
| Giulia Romano | `giulia.romano@urbanfloods.example` | member | verified, trusted, shows email; Macerata (IT), locale `it`, bio, 3 expertise tags | **e2e `MEMBER`**: publishes directly; author of the green-roofs post |
| Ivana Babić | `ivana.babic@urbanfloods.example` | member | verified, trusted; RDA Porin (HR), locale `hr` | trusted author of posts and a thread |
| Nikola Petrović | `nikola.petrovic@urbanfloods.example` | member | verified, trusted, **hidden from the directory**; RDA Backa (RS), locale `sr` | members directory opt-out |
| Arben Hoxha | `arben.hoxha@urbanfloods.example` | member | verified, **untrusted**; Hydrowater-Albania (AL), locale `sq`, 1 expertise tag | **e2e `NEWBIE`**: first post or thread waits for approval (has none yet) |
| Amra Hadžić | `amra.hadzic@urbanfloods.example` | member | verified, untrusted; free-text organisation "City of Zenica" (BA), locale `bs` | has the pending post in the moderation queue; non-partner organisation |
| Dimitris Karagiannis | `dimitris.karagiannis@urbanfloods.example` | member | **unverified**; free-text "Municipality of Florina" (GR), locale `el` | login of an unverified account, resend verification (maintenance purges it after `UNVERIFIED_PURGE_DAYS`, 30; rerun the seed to bring it back) |
| Sara Conti | `sara.conti@urbanfloods.example` | member | **banned** (inactive), verified, trusted; Modica (IT) | banned login; her published post, reply and comment stay attributed |
| Deleted user | (was `kostas.nikolaidis@urbanfloods.example`, now `deleted-<id>@invalid`) | member | **anonymised** (GDPR erasure) | content shown as "Deleted user"; cannot log in |
| Petra Vidmar | `petra.vidmar@urbanfloods.example` | member | verified, untrusted; no organisation, no expertise | a minimal profile |

`.example` is a reserved TLD (RFC 2606), so these addresses can never be delivered to;
`.local`/`.test` would be rejected by the login form's email validation. KNOWBASE link titles come
from the live KNOWBASE API when it is reachable; otherwise (or for an id the KNOWBASE does not
have) placeholder titles are stored and a warning is printed.

## Operator commands

```bash
python -m app.cli create-superadmin --email X --display-name Y [--password Z] [--organisation-id N]
python -m app.cli promote --email X --to admin|superadmin
python -m app.cli digest [--force]     # admin moderation digest now
python -m app.cli maintenance          # expired sessions/tokens, unverified purge, orphan uploads, auto-approve
```

Run them in the container (`docker compose exec backend …`) or here with `uv run`. What each
does and when to use it: [`docs/admin-handbook.md`](../docs/admin-handbook.md#11-command-line-tools).

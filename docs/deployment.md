# Deployment runbook

How to put the Cooperation Platform on the production server and keep it running. Follow the
steps in order. Each step says who runs it:

- **[owner, sudo]**: needs `sudo` (password) on the server; run by the owner.
- **[ssh user]**: runs as `urbanfloods` over `ssh knowbase`, no sudo.

Before any first start, section 6 "Go / no-go for deployment" of the
[QA checklist](qa-checklist.md#6-go--no-go-for-deployment) must be green or decided. Accounts
and day-to-day operation are in the [admin handbook](admin-handbook.md).

Last updated: 2026-10-31

## 0. Rules

- **The KNOWBASE is never touched.** It runs on the same server (`urbanfloods-knowbase-*-prod`,
  ports 127.0.0.1:3001/8001, nginx site `knowbase.urbanfloods.app`). No restarts, no edits to its
  nginx site, no `docker compose down` (or any compose command) in its folder, no access to its
  database. Every command below runs in `~/URBANFLOODS-Cooperation-Platform` or on the
  `cooperation.urbanfloods.app` site only.
- **Nothing runs on the server without the owner's go**, given for that specific step.
- **Secrets never go into chat, issues or commits.** They live only in `~/URBANFLOODS-Cooperation-Platform/.env.prod` on the
  server (chmod 600) and in the owner's local copy.
- **Check before and after every session on the server [ssh user]:**

  ```bash
  docker ps --format 'table {{.Names}}\t{{.Status}}' | grep knowbase   # note the "Up ..." times
  curl -sI https://knowbase.urbanfloods.app | head -1                   # HTTP/2 200
  ```

  After the session the KNOWBASE containers must show the same uptime (no restart) and the
  site must still answer 200. If not, stop and tell the owner.

## 1. One-time prerequisites

| Item | State |
|---|---|
| Cloudflare DNS: `A cooperation.urbanfloods.app` → server, proxied (orange cloud) | done |
| Turnstile widget "cooperation-platform" (Managed, hostname `cooperation.urbanfloods.app`) | done; keys in the owner's local `.env.prod` |
| Brevo SMTP key "cooperation-platform"; sender `noreply@cooperation.urbanfloods.app` (domain authenticated, DKIM + DMARC); reply-to `urbanfloods@uowm.gr`; free plan 300 emails/day | done |
| Decisions: legal pages accepted, `AUTO_APPROVE_AFTER_DAYS=5`, `ENABLE_DOCS=true`, contact `louta@uowm.gr` | done (2026-10-31) |

Clone the repository **[ssh user]**:

```bash
git clone https://github.com/firvain/URBANFLOODS-Cooperation-Platform.git ~/URBANFLOODS-Cooperation-Platform
cd ~/URBANFLOODS-Cooperation-Platform
git checkout <tag or commit that passed the go/no-go>
```

## 2. `.env.prod` [ssh user]

```bash
cd ~/URBANFLOODS-Cooperation-Platform
cp .env.prod.example .env.prod && chmod 600 .env.prod
nano .env.prod
```

Fill in (the example file lists every variable with its production value; these need a real one):

| Variable | Value |
|---|---|
| `POSTGRES_PASSWORD` (and the same in `DATABASE_URL` if the file spells it out) | new random value: `openssl rand -base64 32 \| tr -d '/+='` |
| `SECRET_KEY` | new random value: `openssl rand -hex 32` |
| `SMTP_USER` | the Brevo SMTP login |
| `SMTP_PASSWORD` | the Brevo SMTP key "cooperation-platform" |
| `TURNSTILE_SITE_KEY`, `VITE_TURNSTILE_SITE_KEY` | the widget's site key (same value; the second is baked into the frontend at build time) |
| `TURNSTILE_SECRET_KEY` | the widget's secret key |
| `ALLOWED_ORIGINS`, `FRONTEND_URL` | `https://cooperation.urbanfloods.app` |
| `AUTO_APPROVE_AFTER_DAYS` | `5` |
| `ENABLE_DOCS` | `true` |

Check that `ENV=prod`, `COOKIE_SECURE=true`, `EMAIL_ENABLED=true`, `TURNSTILE_ENABLED=true`,
`TRUST_PROXY_HEADERS=true`, `ENABLE_SCHEDULER=true` and `LOG_JSON=true` are set as in the example.
The password and secret key are generated on the server; type the Brevo and Turnstile values
from the owner's local copy. Changing `VITE_*` values needs a rebuild (`./deploy.sh`).

## 3. First start [ssh user]

```bash
cd ~/URBANFLOODS-Cooperation-Platform
./deploy.sh
```

`deploy.sh` backs up the database if one already exists, builds the images, starts the stack with
`up -d`, waits for the healthchecks and runs curl checks. It never runs `down`. The backend
entrypoint applies the database migrations before the server starts.

Then check:

```bash
curl -sI http://127.0.0.1:3002/ | head -1            # HTTP/1.1 200 OK (the SPA)
curl -s http://127.0.0.1:8002/health/ready           # {"status":"ok","database":"ok"}
curl -s http://127.0.0.1:3002/health                 # proxied to the backend: "env":"prod"
docker compose --env-file .env.prod -f docker-compose.prod.yml ps   # all healthy
```

Do **not** run the dev seed; it refuses unless `ENV` is dev or test.

## 4. Host nginx and TLS [owner, sudo]

The site file is `docker/nginx-host-config.template`. It only adds TLS and HSTS and proxies
everything to the frontend container on 127.0.0.1:3002; the container proxies the API, feeds,
sitemap, robots.txt and uploads to the backend and sets the other security headers and the CSP.

```bash
cd ~/URBANFLOODS-Cooperation-Platform
sudo cp docker/nginx-host-config.template /etc/nginx/sites-available/cooperation.urbanfloods.app
sudo ln -s /etc/nginx/sites-available/cooperation.urbanfloods.app /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d cooperation.urbanfloods.app
```

Certbot adds `listen 443 ssl`, the certificate lines and an HTTP → HTTPS redirect server. Then
uncomment the `Strict-Transport-Security` line in the site file and reload:

```bash
sudo nano /etc/nginx/sites-available/cooperation.urbanfloods.app
sudo nginx -t && sudo systemctl reload nginx
```

`nginx -t` must pass before every reload; if it fails, fix or remove the new site and never touch
the KNOWBASE site file. A reload does not interrupt the KNOWBASE.

**Cloudflare notes.**

- With the proxy on, the HTTP-01 challenge usually passes through Cloudflare on port 80. If
  certbot fails (for example because "Always Use HTTPS" redirects the challenge), set the record
  to **DNS only** (grey cloud), run certbot again, then turn the proxy back on.
- Once the certificate exists, the SSL/TLS encryption mode for this hostname must be
  **Full (strict)**. The mode is zone-wide and also applies to the KNOWBASE: if the zone is
  already on Full (strict), nothing to do; otherwise set it for `cooperation.urbanfloods.app`
  only with a Configuration Rule rather than changing the zone setting.
- Certbot renews automatically (systemd timer, already in place for the KNOWBASE); check with
  `sudo certbot renew --dry-run`.

## 5. Superadmins and admins [ssh user]

```bash
cd ~/URBANFLOODS-Cooperation-Platform
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend \
  python -m app.cli create-superadmin --email someone@uowm.gr --display-name "Name Surname"
```

The password is prompted for (not echoed, not logged). Create a **second superadmin from another
partner** the same way, so the platform never depends on one person. Then name admins from
several partners (sustainability after the project). A person registers normally, verifies the
email, and is promoted in the admin area (`/admin/users`) or from the shell:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend \
  python -m app.cli promote --email partner@example.org --to admin   # or --to superadmin
```

Roles and rules: [admin handbook §1–2](admin-handbook.md#1-accounts-and-roles).

## 6. Backups [ssh user]

`scripts/backup.sh` writes a `pg_dump` (gzip) of the database and a tar archive of the uploads
volume to `~/backups/cooperation/` and deletes files older than 14 days. Run it once by hand,
then schedule it with `crontab -e`:

```cron
30 3 * * * /home/urbanfloods/URBANFLOODS-Cooperation-Platform/scripts/backup.sh >> /home/urbanfloods/backups/cooperation/backup.log 2>&1
```

Copy a backup off the server from time to time (for example `scp knowbase:backups/cooperation/<file> .`
on the owner's machine); a backup on the same disk does not survive a lost server.

**Test restore, once, before go-live** (into a throwaway database; the live one is not touched).
Use the `POSTGRES_USER` value from `.env.prod` (default `cooperation`) and the newest dump file:

```bash
DB=urbanfloods-cooperation-db-prod; U=cooperation
F=$(ls -t ~/backups/cooperation/*.sql.gz | head -1)
docker exec -i $DB psql -U $U -d postgres -c 'CREATE DATABASE restore_test'
gunzip -c "$F" | docker exec -i $DB psql -U $U -d restore_test -q -v ON_ERROR_STOP=1
docker exec -i $DB psql -U $U -d restore_test -c 'SELECT count(*) FROM users'
docker exec -i $DB psql -U $U -d postgres -c 'DROP DATABASE restore_test'
```

The count must match the live database. For the uploads, `tar -tzf` the newest archive and check
that it lists image files. Record the date of the test in the go/no-go checklist.

## 7. Smoke test on production

From the [QA checklist §6 "After first start"](qa-checklist.md#6-go--no-go-for-deployment):

1. Register with a real inbox → the verification email arrives (check spam) → verify.
2. Write a first post → it is **pending** → an admin approves it → the author gets the email and
   is now trusted.
3. Devtools → Cookies: `uf_session` is HttpOnly, **Secure**, SameSite=Lax (X-S4).
4. `curl -sI https://cooperation.urbanfloods.app` → 200, with `strict-transport-security`,
   `content-security-policy` (allowing `challenges.cloudflare.com` and `knowbase.urbanfloods.app`),
   `x-frame-options: DENY`, `x-content-type-options`, `referrer-policy`, `permissions-policy` (X-S8).
5. The Turnstile widget renders on `/register` and `/login`, and registration succeeds.
6. Served by the backend: `curl -s https://cooperation.urbanfloods.app/feeds/posts.atom | head -3`
   (Atom XML), `/sitemap.xml` (XML with production URLs), `/robots.txt` (with the sitemap line),
   `/api/v1/openapi.json` (JSON).
7. A post with a KNOWBASE link card: the card shows the measure title and opens its page.
8. Re-run the KNOWBASE check from §0.

## 8. Updating later [ssh user]

Only deploy a commit whose CI run on `main` is green, **including the "Production-mode smoke
test" job** (the production stack with Turnstile, CSP and nginx, see
[testing.md §6](testing.md#6-production-mode-smoke-test)).

```bash
cd ~/URBANFLOODS-Cooperation-Platform
git pull
./deploy.sh            # backup, build, up -d, health; migrations run in the backend entrypoint
```

Useful commands (all from the repository folder):

```bash
C="docker compose --env-file .env.prod -f docker-compose.prod.yml"
$C ps                                  # status and health
$C logs -f backend                     # JSON logs; also: frontend, db
$C logs --since 1h backend | grep -i error
$C restart backend                     # restart one service only
$C exec backend python -m app.cli digest --force       # send the admin digest now
$C exec backend python -m app.cli maintenance          # run the maintenance sweeps once
```

**Rollback.** Check out the previous tag or commit and deploy it without pulling:

```bash
git checkout <previous tag or commit>
./deploy.sh --no-pull
```

Migrations are forward-only. If the release being rolled back added a migration, the old code may
not run against the new schema; then restore the database from the backup `deploy.sh` made just
before the update (§6, restoring into the live database after stopping the backend), or fix
forward. Return to `main` with `git checkout main` before the next `git pull`.

## 9. Hardening and housekeeping

- **Only Cloudflare should reach the origin** (owner decision). The backend trusts
  `CF-Connecting-IP` for rate limits and Turnstile; a request sent straight to the server's IP
  could forge that header. Restrict ports 80/443 to Cloudflare's ranges
  (<https://www.cloudflare.com/ips/>) **[owner, sudo]**:

  ```bash
  sudo ufw allow OpenSSH                       # keep SSH open before enabling anything
  for ip in $(curl -s https://www.cloudflare.com/ips-v4) $(curl -s https://www.cloudflare.com/ips-v6); do
    sudo ufw allow proto tcp from "$ip" to any port 80,443
  done
  sudo ufw status numbered                      # then remove any broad "80,443 ALLOW Anywhere" rule
  ```

  This applies to the whole host, so the KNOWBASE would also be reachable only through
  Cloudflare; confirm that first. The ranges change rarely; re-check them once a year. The
  container ports are bound to 127.0.0.1 and are not affected.
- **Disk**: `df -h /` and `docker system df` monthly. `deploy.sh` removes this project's old
  untagged images after every update with
  `docker image prune -f --filter label=com.docker.compose.project=urbanfloods-cooperation-prod`.
  Never run a prune **without** that filter: the Docker daemon is shared, so a bare
  `docker image prune` also deletes the KNOWBASE's images. Do **not** run
  `docker system prune --volumes` or `docker volume prune`: they can delete the database and
  uploads volumes, and other projects' volumes on this host.
- **Logs**: container logs rotate (json-file, 10 MB × 3 per service, set in the compose file).
  Host nginx logs (`/var/log/nginx/cooperation.urbanfloods.app.*.log`) rotate with logrotate.
- **One backend worker**: the scheduler (digest, maintenance, auto-approve), the KNOWBASE cache
  and the rate limiter live in one process. Do not add uvicorn workers or scale the backend
  service.
- **Email**: Brevo's free plan allows 300 emails/day; the Brevo dashboard shows usage and
  bounces. Problems: [admin handbook](admin-handbook.md).
- **Monitor**: the daily admin digest arriving; `curl -s http://127.0.0.1:8002/health/ready`;
  disk space; the backup log (`~/backups/cooperation/backup.log`) and a new file each day.

### Refuse unknown hostnames [owner, sudo]

Without a catch-all, a request for a name this server does not host is answered by the first
HTTPS site (the platform) or by Ubuntu's stock nginx page. `docker/nginx-catch-all.sh` replaces
the stock `default` site with a catch-all that refuses such requests (TLS handshake rejected on
443, connection closed on 80). It runs `nginx -t` first, restores the previous state if the test
fails, and checks that both live sites still answer:

```bash
sudo ~/URBANFLOODS-Cooperation-Platform/docker/nginx-catch-all.sh          # install
sudo ~/URBANFLOODS-Cooperation-Platform/docker/nginx-catch-all.sh --undo   # restore default
```

## 10. What lives where

| Thing | Where |
|---|---|
| Code | `~/URBANFLOODS-Cooperation-Platform` (user `urbanfloods`) |
| Secrets | `~/URBANFLOODS-Cooperation-Platform/.env.prod` (chmod 600, never committed) |
| Containers | `urbanfloods-cooperation-frontend-prod`, `-backend-prod`, `-db-prod` |
| Ports | frontend `127.0.0.1:3002` (SPA + proxy), backend `127.0.0.1:8002` (curl checks); Postgres not published |
| Volumes | database data and uploads (named volumes, see `docker-compose.prod.yml`; `docker volume ls`) |
| Backups | `~/backups/cooperation/` (14 days), log `backup.log`, crontab of `urbanfloods` |
| Host nginx site | `/etc/nginx/sites-available/cooperation.urbanfloods.app` (symlinked in `sites-enabled`); source `docker/nginx-host-config.template` |
| TLS certificate | `/etc/letsencrypt/live/cooperation.urbanfloods.app/` (certbot) |
| Logs | `docker compose ... logs <service>`; `/var/log/nginx/cooperation.urbanfloods.app.{access,error}.log` |
| KNOWBASE (do not touch) | `urbanfloods-knowbase-*-prod`, 127.0.0.1:3001/8001, site `knowbase.urbanfloods.app` |

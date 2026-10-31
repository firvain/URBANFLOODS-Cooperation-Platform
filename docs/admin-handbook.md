# Admin handbook

This handbook is for the people who run the Cooperation Platform: admins who manage accounts and
the content catalogue, and the operator who has shell access to the server. It covers roles,
account actions, categories and tags, the dashboard and the reporting export, the KNOWBASE
cache, GDPR requests, email problems, logs, the command-line tools and the scheduled
maintenance. Day-to-day content moderation is in the [moderation guide](moderation-guide.md);
deployment will be in `docs/deployment.md` (increment M6, not written yet).

Last updated: 2026-10-31

## 1. Accounts and roles

| Role | Can |
|---|---|
| member | read; once verified: write posts and threads (reviewed until trusted), replies, comments, report content, upload images |
| admin | everything a member can, publish without review, moderate (queue, reports, hide/unhide/delete), manage users (within the rules below), categories, tags, organisations, see stats and the audit log |
| superadmin | everything an admin can, plus grant or remove the superadmin role and ban/demote other superadmins |

Account flags shown on the Users page (`/admin/users`): **verified** (email confirmed),
**trusted** (posts without review), **active** (false = banned), **deleted** (anonymised).

### First superadmin

On a fresh installation, create the first superadmin from the server shell (see
[section 11](#11-command-line-tools)):

```bash
docker compose exec backend python -m app.cli create-superadmin \
  --email someone@example.org --display-name "Platform Admin"
```

The password is prompted for. Running it for an existing address makes that account a verified,
trusted superadmin and keeps its password.

## 2. Promoting and demoting

On the Users page, open the row menu.

| Action | Who may do it |
|---|---|
| Make admin (member → admin) | any admin |
| Make member (admin → member) | any admin |
| Make superadmin (admin → superadmin) | superadmin only |
| Demote to admin (superadmin → admin) | superadmin only |

Rules enforced by the API: nobody can change their own role; the last active superadmin cannot be
demoted, banned or deleted; demotion goes one step at a time. From the shell,
`python -m app.cli promote --email X --to admin|superadmin` raises a role (it never demotes).
Every change is audited (`admin.promote`, `admin.demote`).

Keep at least two superadmins and several admins from different partners, so the platform does
not depend on one person.

## 3. Banning

**Ban** sets the account inactive and signs it out of every session; the person cannot sign in.
Their existing content stays as it is; hide or delete items separately if needed. **Unban**
reactivates the account (trust mark and role are kept). Any admin can ban members and other
admins; only a superadmin can ban a superadmin; nobody can ban themselves; the last superadmin
cannot be banned. Audited as `admin.ban` / `admin.unban`.

## 4. Trust

**Trust** marks a member as trusted: their posts and threads publish without review. **Remove
trust** sends their next post or thread back to the queue. Trust is also granted automatically
when an admin approves a member's first item (see the [moderation guide](moderation-guide.md#1-the-trust-model)).
Audited as `admin.trust` / `admin.untrust` (automatic ones as `user.trusted`).

## 5. Resending a verification email

For an unverified account, the row menu offers **Resend verification**. A new link is emailed and
older links stop working. If sending fails the page shows an error (`admin.email_not_sent`); see
[section 9](#9-when-email-fails). Members can also request a new link themselves (after registering, or from the banner shown
to unverified members; 3 per hour). Unverified member accounts are deleted automatically after
`UNVERIFIED_PURGE_DAYS` (30) days.

## 6. Categories, tags and organisations

### Categories (`/admin/categories`)

Nine categories are seeded by migration 0004:

| Kind | Slug | Name | Admin only |
|---|---|---|---|
| blog | `news` | News | no |
| blog | `best-practices` | Best practices | no |
| blog | `events` | Events | no |
| blog | `resources` | Resources | **yes** |
| blog | `policy` | Policy and recommendations | no |
| forum | `general` | General discussion | no |
| forum | `measures` | Measures and solutions | no |
| forum | `early-warning` | Early warning and data | no |
| forum | `policy` | Policy and governance | no |

- **Create** and **edit**: name, slug (derived from the name when empty), description, sort
  order, *admin only*. The interface translates seeded categories by kind and slug; a new
  category shows its stored name in every language.
- **Admin only**: members cannot post in it (used for "Resources": training material,
  deliverables, strategy, action plans, policy briefs, as link cards to the project site).
- **Archive** hides a category from lists; its posts stay and old links keep working. There is no
  hard delete. **Unarchive** brings it back.
- Visitors may need to reload the page to see category changes (the list is cached per browser
  session).

### Tags (`/admin/tags`)

Authors create tags by typing them. Admins can:

- **Merge** a tag into another (typos, duplicates): its posts and threads move to the target tag
  and the source tag is deleted.
- **Delete** a tag: it is removed from every post and thread.

### Organisations

The 22 project partners (lead partner, PPs and APs) are seeded by migration 0002 and shown on
`/partners`. Members pick one of them, or "other" with a free-text name. There is no admin page
for organisations: add or edit them through the API (`POST /api/v1/organisations/`,
`PATCH /api/v1/organisations/{id}`) from `/docs` while signed in as an admin.

## 7. The dashboard (`/admin`)

- **Users**: total (not deleted), verified, trusted, admins, new in the last 30 days.
- **Content**: published posts and threads, replies, comments, pending items; open reports.
- **KNOWBASE**: reachable or not, last success, last error, cache sizes; **Clear cache** button.
- **Reporting export**: choose a date range and download the CSV (next section).

### Stats CSV export

`GET /api/v1/admin/stats/export.csv?from=YYYY-MM-DD&to=YYYY-MM-DD` (both days inclusive, UTC).
Defaults: from the project start (2024-09-01) to today. The file
`urbanfloods-cooperation-stats-<from>-<to>.csv` contains five sections, separated by a blank
line, each with a name row and a header row:

| Section | Columns | Meaning |
|---|---|---|
| `users_by_country` | country, count | accounts registered in the range (not deleted) by profile country; `unknown` if none given |
| `users_by_organisation` | organisation, is_partner, count | the same accounts by organisation; free-text organisations grouped as `Other`, none as `Unspecified` |
| `content` | metric, count | published posts, threads, replies and comments **created** in the range |
| `active_users` | metric, count | `contributors`: distinct authors of that content; `logged_in`: distinct accounts with a sign-in (`auth.login` audit row) in the range |
| `rco87` | organisation, is_partner, country, contributions | organisations whose members contributed published content in the range, with the number of contributions; free-text organisations appear as their own rows; contributors with no organisation are left out |

**RCO87** is the Interreg programme output indicator "Organisations cooperating across borders".
URBANFLOODS Output 5.1 ("URBANFLOODS Cooperation Framework") reports it with a target of 22
organisations. The `rco87` section gives the evidence: which organisations, from which
countries, actively cooperated on the platform in the period. Count the rows (optionally only
those with `is_partner = True`, or with contributions above a threshold agreed by the
partnership) for the progress report. Each export is audited (`admin.stats_export`).

## 8. KNOWBASE cache

The platform shows KNOWBASE measures and documents from an in-memory cache (lists 15 minutes,
details 6 hours, lookups 24 hours). If the KNOWBASE is down, the last good copy is served and the
pages show a notice that cached data is being shown.

**Clear cache** (dashboard, or `POST /api/v1/admin/knowbase/cache/clear`) empties every cache,
including the stale copies. Use it when the KNOWBASE team has published corrections that should
appear at once. Do **not** clear it while the KNOWBASE is unreachable: with no stale copy left,
the KNOWBASE pages and new KNOWBASE links answer "temporarily unavailable" until it is back.
Restarting the backend has the same effect as clearing. Audited as `admin.knowbase_cache_clear`.

The platform never changes the KNOWBASE. Problems with KNOWBASE content go to the KNOWBASE team.

## 9. When email fails

Symptoms: members report missing verification or reset emails; resend shows an error; the digest
does not arrive.

1. Check the backend log for `email.send_failed`, `auth.email_not_sent`, `admin.email_not_sent`,
   `notification.failed`, `digest.failed` / `digest.failed_all` (section 10).
2. Check the settings: `EMAIL_ENABLED=true`, `SMTP_HOST`/`SMTP_PORT` (default
   `smtp-relay.brevo.com:587`, STARTTLS), `SMTP_USER` (the SMTP login shown on Brevo's
   *SMTP & API* page), `SMTP_PASSWORD` (a Brevo **SMTP key**), `SMTP_FROM` (must stay on the
   authenticated domain `cooperation.urbanfloods.app`), `SMTP_FROM_NAME`, `SMTP_REPLY_TO`. With
   `EMAIL_ENABLED=false` nothing is sent and each message is only logged as `email.not_sent`.
3. Check Brevo's transactional **logs** page (sent, delivered, bounced, blocked per message) and
   the account's daily quota: the free plan sends 300 emails per day. An authentication error
   means the SMTP key was revoked or mistyped: create a new key on the *SMTP & API* page (one per
   environment), put it in `.env.prod`, restart the backend, then delete the old key. Any other
   SMTP server can be used by changing the `SMTP_*` settings.
4. After fixing: account changes were saved even though the email failed, so ask members to use
   *Resend verification* or *Forgot password* again (or use the admin resend). A digest whose
   emails all failed is retried the next day; send it now with `python -m app.cli digest`.

## 10. Logs

The backend writes structured logs (structlog) to standard output; read them with
`docker logs <backend container>` (development: `urbanfloods-cooperation-backend`; production
container name set in M6 [CHECK]). `LOG_JSON=true` gives one JSON object per line;
`LOG_LEVEL` sets the level (default `INFO`). Every response carries an `X-Request-ID` header that
also appears in the log lines of that request, so a member can quote it when reporting an error.

Logs never contain passwords, tokens, request bodies, or IP addresses (rate-limit events carry a
keyed hash of the IP). Exception: with `EMAIL_ENABLED=false` the `email.not_sent` line includes
the recipient address (`services/email.py`, `LoggingBackend`). [CHECK]

The audit log (`/admin/log`) is the record of who did what; the container log is for errors and
operations.

## 11. Command-line tools

Run inside the backend container (`docker compose exec backend …`) or from `backend/` with
`uv run …` and the production `DATABASE_URL`:

| Command | Does |
|---|---|
| `python -m app.cli create-superadmin --email X --display-name Y [--password Z] [--organisation-id N]` | create a verified, trusted superadmin, or make an existing account one |
| `python -m app.cli promote --email X --to admin\|superadmin` | raise an existing user's role |
| `python -m app.cli digest [--force]` | send the admin digest now; prints `recipients=N items=M`; exit 1 if every email failed |
| `python -m app.cli maintenance` | run the maintenance sweeps once; prints `step=count` per step; exit 1 if a step failed (`-1`) |
| `alembic upgrade head` | apply database migrations (the container entrypoint does this on start) |
| `python -m scripts.seed_dev` | development demo data only; refuses `ENV=prod` |

The CLI commands write audit rows with no actor.

## 12. Routine maintenance

With `ENABLE_SCHEDULER=true` (run it in one backend process only), two jobs run daily in UTC:

| Time (default) | Job | Removes or changes |
|---|---|---|
| 05:00 (`DIGEST_HOUR_UTC` − 1) | maintenance | sessions expired or revoked more than 7 days ago; email tokens expired or used more than 7 days ago; unverified **member** accounts older than `UNVERIFIED_PURGE_DAYS` (30) days, hard-deleted with their sessions, tokens and preferences (audit `maintenance.purge_unverified`, count only); uploaded images older than `ORPHAN_UPLOAD_HOURS` (24) hours that are no cover, no avatar and not used in any post, thread, reply or comment body (any status), rows and files (audit `maintenance.orphan_uploads`); pending posts/threads older than `AUTO_APPROVE_AFTER_DAYS` days are approved (only when > 0) |
| 06:00 (`DIGEST_HOUR_UTC`) | admin digest | nothing removed; emails admins ([moderation guide](moderation-guide.md#5-the-admin-digest)) |

Not purged by any job: content (soft-deleted items stay), reports, digest runs and the audit log.
Database and upload backups are planned for M6 (`scripts/backup.sh`, 14-day retention). [CHECK after 6a]

## 13. GDPR requests

The University of Western Macedonia is the data controller; the contact for every data request is
**louta@uowm.gr** (see the draft [Privacy Policy](legal/privacy-policy.md)).

### Self-service (preferred)

Members do this themselves under **Account → Data**:

- **Export**: a JSON file with the profile, organisation, expertise, notification preferences,
  every session (incl. revoked) and every audit row they made or that is about them. Password
  hashes and tokens are never included. The `content` lists (posts, threads, replies, comments)
  in the export are currently always empty (`ExportContent` placeholder in
  `backend/app/api/v1/schemas/auth.py`); a member's published content is available in the public
  exports. [CHECK]
- **Delete account** (current password required): the account is anonymised. Email replaced by a
  placeholder, display name set to "Deleted user", password cleared, organisation, country, bio
  and avatar removed, role set to member, trust cleared, hidden from the members directory,
  notification preferences and expertise deleted, every session revoked and every pending email
  link invalidated. Posts, threads, replies and comments stay public, attributed to
  "Deleted user". Images embedded in posts stay; an unused avatar image is removed by the next
  orphan sweep. The last superadmin cannot delete their account.

### Manual requests

If a person writes instead (to louta@uowm.gr or an admin):

1. Verify that the request comes from the account's email address.
2. Access: ask them to use Account → Data → Export, or the operator produces the same export.
3. Erasure: ask them to use Delete account. There is no admin function to anonymise someone
   else's account; if the person cannot sign in, ban the account at once and let the operator
   perform the anonymisation (same fields as above) in the database. [CHECK]
4. Removal of specific content: hide it, then edit or delete it (see the
   [moderation guide](moderation-guide.md#personal-data-complaints)).
5. Keep a note of the request and the date it was handled.

## 14. Settings reference

All settings are environment variables read by `backend/app/core/config.py` (defaults shown).

| Setting | Default | Purpose |
|---|---|---|
| `ENV` | `dev` | `dev`, `test` or `prod` |
| `DATABASE_URL` | required | `postgresql+asyncpg://…` |
| `SECRET_KEY` | required | key for the IP hash in rate-limit log lines |
| `ALLOWED_ORIGINS` | `http://localhost:5173` | CORS and CSRF allow-list (comma list or JSON) |
| `FRONTEND_URL` | `http://localhost:5173` | absolute links in emails, feeds, exports |
| `ENABLE_DOCS` | `true` | serve `/docs` and `/api/v1/openapi.json` |
| `COOKIE_SECURE` | `false` | set `true` in production |
| `SESSION_COOKIE_NAME`, `SESSION_TTL_DAYS` | `uf_session`, `30` | session cookie |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | `smtp-relay.brevo.com`, `587`, empty, empty | outgoing mail (Brevo SMTP login and SMTP key) |
| `SMTP_FROM`, `SMTP_FROM_NAME` | `noreply@cooperation.urbanfloods.app`, `URBANFLOODS Cooperation Platform` | sender |
| `SMTP_REPLY_TO` | `urbanfloods@uowm.gr` | `Reply-To` header (empty = none) |
| `EMAIL_ENABLED` | `false` | actually send email |
| `KNOWBASE_BASE_URL`, `KNOWBASE_PUBLIC_URL` | `https://knowbase.urbanfloods.app` | KNOWBASE API and public links |
| `KNOWBASE_TIMEOUT_SECONDS` | `5.0` | upstream timeout |
| `KNOWBASE_CACHE_TTL_LIST`, `KNOWBASE_CACHE_TTL_DETAIL` | `900`, `21600` | cache lifetimes (s) |
| `TURNSTILE_ENABLED`, `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` | `false`, empty, empty | bot check |
| `UPLOAD_DIR`, `UPLOAD_URL_PREFIX` | `uploads`, `/static/uploads` | image storage |
| `MAX_UPLOAD_MB`, `UPLOAD_MAX_PX`, `UPLOAD_THUMB_PX` | `5`, `1920`, `480` | image limits |
| `REPORT_AUTO_HIDE_THRESHOLD` | `3` | distinct reports that hide content (0 = off) |
| `AUTO_APPROVE_AFTER_DAYS` | `0` | auto-approve pending items after N days (0 = off) |
| `ENABLE_SCHEDULER`, `DIGEST_HOUR_UTC` | `false`, `6` | scheduled jobs |
| `UNVERIFIED_PURGE_DAYS`, `ORPHAN_UPLOAD_HOURS` | `30`, `24` | maintenance thresholds |
| `RATE_LIMIT_ENABLED`, `TRUST_PROXY_HEADERS` | `true`, `false` | rate limits; trust `CF-Connecting-IP` / `X-Forwarded-Proto` (set `true` behind Cloudflare and nginx) |
| `LOG_LEVEL`, `LOG_JSON` | `INFO`, `false` | logging |
| `CONTENT_LICENSE_URL` | CC BY 4.0 URL | licence link in exports |
| `CONTACT_EMAIL` | `louta@uowm.gr` | project contact named in emails (e.g. a rejected post) |

Frontend build variables: `VITE_API_BASE_URL` (empty in production, same origin),
`VITE_TURNSTILE_SITE_KEY`, `VITE_DSS_URL`.

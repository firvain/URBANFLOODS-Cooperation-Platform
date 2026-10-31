# Admin handbook

This handbook is for the people who run the Cooperation Platform: admins who manage accounts and
the content catalogue, and the operator who has shell access to the server. It covers roles,
account actions, categories, tags, organisations and expertise areas, the dashboard and the
reporting export, the KNOWBASE cache, GDPR requests, email problems, logs, the command-line tools
and the scheduled maintenance. Day-to-day content moderation is in the
[moderation guide](moderation-guide.md); deployment in [docs/deployment.md](deployment.md).

Last updated: 2026-10-31

## 1. Accounts and roles

| Role | Can |
|---|---|
| member | read; once verified: write posts and threads (reviewed until trusted), replies, comments, report content, upload images |
| admin | everything a member can, publish without review, moderate (queue, reports, hide/unhide/delete/restore, delete permanently), manage users (within the rules below), categories, tags, organisations, expertise areas, see stats and the audit log |
| superadmin | everything an admin can, plus grant or remove the superadmin role and ban/demote other superadmins |

Account flags shown on the Users page (`/admin/users`): **verified** (email confirmed),
**trusted** (posts without review), **active** (false = banned), **deleted** (anonymised).

### First superadmin

On a fresh installation, create the first superadmin from the server shell (see
[section 11](#11-command-line-tools)):

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend \
  python -m app.cli create-superadmin --email someone@example.org --display-name "Platform Admin"
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

## 6. Categories, tags, organisations and expertise areas

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

### Organisations (`/admin/organisations`)

The 22 project partners (lead partner, PPs and APs) are seeded by migration 0002 and shown in the
partnership section of the About page (`/about#partnership`; the old `/partners` address
redirects there). Members pick one of them, or "other" with a free-text name.

- The list shows every organisation, partners first (then by type and order), with its short
  name, country, type, partner flag and number of (verified, active) members.
- **Create** and **edit**: name (unique), short name, country, type (*Project partner*,
  *Associated partner* or *Other*), website (an `http://` or `https://` address; empty removes
  it), order, and *Project partnership* (shown on the About page).
- There is no delete: members belong to organisations. Changes are audited as
  `organisation.created` and `organisation.updated`.

If the page is unavailable, the same changes can be made through the API
(`POST /api/v1/organisations/`, `PATCH /api/v1/organisations/{id}`) with curl, as shown in
[API calls from the command line](#api-calls-from-the-command-line). The Swagger page (`/docs`)
does not work for this: its *Try it out* sends the session cookie but not the
`X-Requested-With: XMLHttpRequest` header, so the CSRF check answers 403 `security.csrf` for every
POST, PATCH or DELETE made while signed in (`backend/app/core/csrf.py` exempts only the docs
pages themselves, not the API calls made from them).

### Expertise areas (`/admin/expertise`)

The 22 expertise areas members tag their profiles with (and filter the Collaboration Network by)
are seeded by migration 0003. The page lists active and deactivated areas.

- **Create** and **edit**: label (2 to 80 characters), slug (derived from the label when empty;
  the interface translates seeded areas by slug, so a new area shows its English label in every
  language), order.
- **Deactivate** instead of deleting: members who have the area keep it on their profiles (and
  can keep it when they save their profile), but nobody can pick it any more and it leaves the
  Network filter. **Reactivate** brings it back.
- Changes are audited as `expertise.created` and `expertise.updated` (target type
  `expertise_tag`). The API fallback is `POST /api/v1/expertise/` and
  `PATCH /api/v1/expertise/{id}`.

## 7. The dashboard (`/admin`)

- **Users**: total (not deleted), verified, trusted, admins, new in the last 30 days.
- **Content**: published posts and threads, replies, comments, pending items; open reports.
- **KNOWBASE**: reachable or not, last success, last error, cache sizes (lists, details, lookups,
  stale copies); **Clear cache** button.
- **Moderation digest**: **Send digest now** emails the digest at once to every admin who has it
  switched on, even when nothing is pending (`POST /api/v1/admin/digest/send`, the same as
  `python -m app.cli digest --force`). A toast gives the number of recipients and items, or warns
  when every email failed; each use writes an `admin.digest_sent` audit row.
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

The platform has no KNOWBASE library pages of its own: browsing by country, level or subject
happens on the KNOWBASE itself (the header entry and the home card link to
knowbase.urbanfloods.app). KNOWBASE data appears in three places only: the KNOWBASE picker in the
post and discussion editor, the link cards on posts and discussions, and the item pages
`/knowbase/measures/{id}` and `/knowbase/documents/{id}` with their "Mentioned in" list. All of it
goes through the backend proxy and its in-memory cache (lists and searches 15 minutes, details
6 hours, lookups 24 hours). Link cards show the title stored when the link was saved, so they do
not depend on the KNOWBASE being up.

If the KNOWBASE is down, the proxy serves the last good copy (stale) where it has one. The item
pages and the picker show no notice when they do; only the admin **dashboard** shows the
KNOWBASE state (reachable, last success, last error, number of stale copies). An item with no
copy in the cache shows a load error with *Try again*, and saving a post with a new KNOWBASE link
answers "The KNOWBASE cannot be reached".

**Clear cache** (dashboard, or `POST /api/v1/admin/knowbase/cache/clear`) empties every cache,
including the stale copies. Use it when the KNOWBASE team has published corrections that should
appear at once. Do **not** clear it while the KNOWBASE is unreachable: with no stale copy left,
the item pages, the picker and new KNOWBASE links answer "temporarily unavailable" until it is
back. Restarting the backend has the same effect as clearing. Audited as
`admin.knowbase_cache_clear`.

The platform never changes the KNOWBASE. Problems with KNOWBASE content go to the KNOWBASE team.

## 9. When email fails

The platform sends: the verification link, the welcome email, password reset links, the
email-change confirmation, reply and comment notifications, the **decision emails** to authors
when a post or discussion is approved or rejected (see the
[moderation guide](moderation-guide.md#emails-to-the-author)) and the admin digest. Messages come
from `SMTP_FROM` through Brevo's SMTP relay and carry a `Reply-To` header set to `SMTP_REPLY_TO`
(default `urbanfloods@uowm.gr`; empty = no header), so answers reach a monitored address instead
of the no-reply sender. Templates exist in English, with Greek versions of the verification and
reply-to-discussion emails; every other language receives English. Notifications and decision
emails respect each member's switches under Account → Notifications.

To keep the mail out of junk folders, every message carries `Auto-Submitted: auto-generated`
(RFC 3834: automated mail, auto-responders stay quiet), and links in the HTML part never show a web
or email address as their text. The emails a member can switch off (reply and comment
notifications, decision emails, the admin digest) also carry `List-Unsubscribe` and
`List-Unsubscribe-Post: List-Unsubscribe=One-Click` (RFC 8058), so mail clients offer an
"Unsubscribe" button. It POSTs to `/api/v1/notifications/unsubscribe` with a signed token naming the
member and the one switch to turn off; no sign-in is needed, the switch is turned off at once and
the change is audited as `notifications.unsubscribed` (`via: list-unsubscribe`). The member can
switch it back on under Account → Notifications. Changing `SECRET_KEY` invalidates the links in
emails already sent (the in-body link to the notification settings keeps working). Brevo rewrites
every link through its click-tracking domain; this cannot be switched off on the free plan, so
anonymous tracking is enabled in the Brevo account: clicks are counted without being tied to a
recipient.

Symptoms: members report missing verification or reset emails; resend shows an error; the digest
or a decision email does not arrive.

1. Check the backend log for `email.send_failed`, `auth.email_not_sent`, `admin.email_not_sent`,
   `notification.failed` (its `kind` is `moderation_decision` for decision emails),
   `digest.failed` / `digest.failed_all` (section 10).
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
   emails all failed is retried the next day; send it now with **Send digest now** on the
   dashboard (or `python -m app.cli digest --force`).

## 10. Logs

The backend writes structured logs (structlog) to standard output; read them with
`docker logs <backend container>` (development: `urbanfloods-cooperation-backend`; production
container name set in M6 [CHECK]). `LOG_JSON=true` gives one JSON object per line;
`LOG_LEVEL` sets the level (default `INFO`). Every response carries an `X-Request-ID` header that
also appears in the log lines of that request, so a member can quote it when reporting an error.

Logs never contain passwords, tokens, request bodies, or IP addresses (rate-limit events carry a
keyed hash of the IP). With `EMAIL_ENABLED=false` the `email.not_sent`
line names the template and a keyed hash of the recipient address, not the address itself
(`services/email.py`, `LoggingBackend`).

The audit log (`/admin/log`) is the record of who did what; the container log is for errors and
operations.

## 11. Command-line tools

Run inside the backend container (in production
`docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend …`, in dev
`docker compose exec backend …`) or from `backend/` with `uv run …` and the right `DATABASE_URL`:

| Command | Does |
|---|---|
| `python -m app.cli create-superadmin --email X --display-name Y [--password Z] [--organisation-id N]` | create a verified, trusted superadmin, or make an existing account one |
| `python -m app.cli promote --email X --to admin\|superadmin` | raise an existing user's role |
| `python -m app.cli digest [--force]` | send the admin digest now; prints `recipients=N items=M`; exit 1 if every email failed |
| `python -m app.cli maintenance` | run the maintenance sweeps once; prints `step=count` per step; exit 1 if a step failed (`-1`) |
| `alembic upgrade head` | apply database migrations (the container entrypoint does this on start) |
| `python -m scripts.seed_dev [--reset]` | development demo data only (`--reset` deletes every `@urbanfloods.example` account and its content first); refuses unless `ENV` is `dev`/`test` |

The CLI commands write audit rows with no actor.

### API calls from the command line

A few admin functions have no page: restoring or permanently deleting a deleted item, a reply or
a comment, and deleting another member's image (organisations have a page now, but the calls
below still work as a fallback). Call the API with curl.
Sign in once into a cookie jar, then send every POST, PATCH or DELETE with the session cookie
**and** the `X-Requested-With: XMLHttpRequest` header (the CSRF check rejects a signed-in write
without it). The login is rate limited like the sign-in form (10 per 15 minutes). Ids come from
the audit log (`/admin/log`: the target column shows, for example, `reply #123`).

```bash
BASE=https://cooperation.urbanfloods.app        # development: http://localhost:8000
printf 'Password: '; stty -echo; read -r PW; stty echo; echo   # bash and zsh; not in the history
curl -s -c jar -H 'Content-Type: application/json' \
  -d "{\"email\":\"admin@example.org\",\"password\":\"$PW\"}" "$BASE/api/v1/auth/login"
unset PW

# add an organisation (country: ISO 3166-1 alpha-2; type: PP, AP or other)
curl -s -b jar -H 'X-Requested-With: XMLHttpRequest' -H 'Content-Type: application/json' \
  -d '{"name":"Municipality of Example","short_name":"Example","country":"GR","type":"other","website":"https://example.org","is_partner":false}' \
  "$BASE/api/v1/organisations/"

# change one field of organisation 23 (omitted fields are kept; "website": null clears it)
curl -s -b jar -X PATCH -H 'X-Requested-With: XMLHttpRequest' -H 'Content-Type: application/json' \
  -d '{"website":"https://www.example.org"}' "$BASE/api/v1/organisations/23"

# restore, or delete permanently, a deleted reply (type: post, thread, reply or comment)
curl -s -b jar -X POST -H 'X-Requested-With: XMLHttpRequest' "$BASE/api/v1/moderation/reply/123/restore"
curl -s -b jar -X POST -H 'X-Requested-With: XMLHttpRequest' "$BASE/api/v1/moderation/reply/123/purge"

# delete image 45 (409 uploads.in_use while any content, deleted content included, uses it)
curl -s -b jar -X DELETE -H 'X-Requested-With: XMLHttpRequest' "$BASE/api/v1/uploads/45"

# sign out and remove the cookie jar
curl -s -b jar -X POST -H 'X-Requested-With: XMLHttpRequest' "$BASE/api/v1/auth/logout"; rm jar
```

Every change is audited (`organisation.created`, `organisation.updated`, `moderation.restore`,
`moderation.purge`, `upload.deleted`). The full list of routes is in [api.md](api.md).

## 12. Routine maintenance

With `ENABLE_SCHEDULER=true` (run it in one backend process only), two jobs run daily in UTC:

| Time (default) | Job | Removes or changes |
|---|---|---|
| 05:00 (`DIGEST_HOUR_UTC` − 1) | maintenance | sessions expired or revoked more than 7 days ago; email tokens expired or used more than 7 days ago; unverified **member** accounts older than `UNVERIFIED_PURGE_DAYS` (30) days, hard-deleted with their sessions, tokens and preferences (audit `maintenance.purge_unverified`, count only); uploaded images older than `ORPHAN_UPLOAD_HOURS` (24) hours that are no cover, no avatar and not used in any post, thread, reply or comment body (any status), rows and files (audit `maintenance.orphan_uploads`); pending posts/threads older than `AUTO_APPROVE_AFTER_DAYS` days are approved (only when > 0) |
| 06:00 (`DIGEST_HOUR_UTC`) | admin digest | nothing removed; emails admins ([moderation guide](moderation-guide.md#5-the-admin-digest)) |

Not purged by any job: content (soft-deleted items stay until an admin uses *Delete permanently*,
see the [moderation guide](moderation-guide.md#delete-permanently)), reports, digest runs and the
audit log.
Database and upload backups are planned for M6 (`scripts/backup.sh`, 14-day retention). [CHECK after 6a]

## 13. GDPR requests

The University of Western Macedonia is the data controller; the contact for every data request is
**louta@uowm.gr** (see the draft [Privacy Policy](legal/privacy-policy.md)).

### Self-service (preferred)

Members do this themselves under **Account → Your data**:

- **Export**: a JSON file `urbanfloods-account-<id>-<date>.json` (`GET /api/v1/auth/me/export`,
  `format_version` 2; schema in `backend/app/api/v1/schemas/account_export.py`). It contains:
  - `user`: id, email, display name, organisation (id, name, short name) or the free-text
    organisation, country, language, bio, role, verified, trusted since, created, updated, last
    sign-in, expertise areas, and the *show email* and *show in directory* choices;
  - `notification_preferences`: every switch (replies, comments, replies to replies, admin
    digest, decisions on my posts and discussions) and the digest frequency;
  - `sessions`: every session, revoked and expired ones included (created, last seen, expiry,
    browser description, revoked); never the token;
  - `audit_log`: every audit row the member made or that is about them or their content (action,
    target, details, time); the actor is left out and keys that could name an admin are removed;
  - `content`: the member's posts, threads, replies and comments in **every** status (pending,
    published, hidden, deleted), oldest first, with the HTML and plain text, status, hidden
    reason and dates; posts and threads also with title, address, language, category, tags and
    KNOWBASE links; posts with excerpt, cover image id and event date/link; threads with
    pinned/locked; replies with their thread and parent reply; comments with their post;
  - `attachments`: the member's uploads (deleted ones too, until purged) with public URL and
    thumbnail URL, original file name, type, size, dimensions, alt text and dates; never the
    storage path;
  - `reports_made`: the reports the member filed (content, reason, details, status, dates), never
    who resolved them;
  - `exported_at`, `format_version` and `licence_note`.

  Never included: password hashes, tokens, the address of a pending email change, or the
  identity of the admins who acted. Each export is audited (`auth.data_exported`).
- **Delete account** (current password required): the account is anonymised. Email replaced by a
  placeholder, display name set to "Deleted user", password cleared, organisation, country, bio
  and avatar removed, role set to member, trust cleared, hidden from the members directory,
  notification preferences and expertise deleted, every session revoked and every pending email
  link invalidated. Posts, threads, replies and comments stay public, attributed to
  "Deleted user". The member's own uploads that no content uses (not a cover, not in any text),
  the avatar included, are deleted with their files at once; images used by their contributions
  stay with them and keep their original file name. The last superadmin cannot delete their
  account.

### Manual requests

If a person writes instead (to louta@uowm.gr or an admin):

1. Verify that the request comes from the account's email address.
2. Access: ask them to use Account → Your data → Export, or the operator produces the same export.
3. Erasure: ask them to use Delete account. There is no admin function to anonymise someone
   else's account; if the person cannot sign in, ban the account at once and let the operator
   perform the anonymisation (same fields as above) in the database. [CHECK]
4. Removal of specific content: hide it, then edit it or delete it permanently, and check its
   images (see the [moderation guide](moderation-guide.md#personal-data-complaints)).
5. Rectification: members correct their profile themselves under Account → Profile. Changing the
   **email address** exists in the API only (`POST /api/v1/auth/me/email` with the current
   password, then `POST /api/v1/auth/email/confirm` with the token); the interface has no form for
   it. The confirmation email links to `/confirm-email?token=…`, which has no page in the
   frontend (it shows "not found"), so the change can only be completed by sending the token to
   `POST /api/v1/auth/email/confirm` (body `{"token": "…"}`). [CHECK: add a page or keep as a known
   limitation]
6. Keep a note of the request and the date it was handled.

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

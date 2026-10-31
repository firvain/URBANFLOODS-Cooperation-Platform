# API

This document explains how to call the Cooperation Platform's REST API and lists every route
with who may call it, its rate limit and its purpose. The table was produced by reading the
endpoint modules in `backend/app/api/v1/endpoints/` and the app factory in `backend/app/main.py`;
the machine-readable contract is the OpenAPI document. Architecture and limits are explained in
[architecture.md](architecture.md); reuse of the open data is described in [fair-data.md](fair-data.md).

Last updated: 2026-10-31

## 1. Basics

| Item | Value |
|---|---|
| Base URL (production, after M6) | `https://cooperation.urbanfloods.app/api/v1` |
| Base URL (development) | `http://localhost:8000/api/v1` |
| OpenAPI document | `/api/v1/openapi.json` |
| Interactive docs (Swagger UI) | `/docs` |
| Probes, feeds, sitemap | mounted **without** the `/api/v1` prefix |

The OpenAPI document and `/docs` are served when `ENABLE_DOCS=true` (the default). PLAN.md keeps
them enabled in production as part of the FAIR commitment; `core/config.py` carries the comment
"disable in production". [CHECK: decide for the production env file]

List routes end with `/`. JSON everywhere except the CSV/Atom/XML exports and file uploads
(`multipart/form-data`).

### Authentication

- Sign in with `POST /api/v1/auth/login` (`{"email", "password"}`). The response sets the
  `uf_session` cookie (HttpOnly, SameSite=Lax, Secure in production, 30-day sliding expiry).
  Send it back on every request (`credentials: 'include'` in a browser).
- Every unsafe request (`POST`, `PUT`, `PATCH`, `DELETE`) that carries the cookie must also send
  `X-Requested-With: XMLHttpRequest`, otherwise 403 `security.csrf`. An `Origin` or `Referer`
  header, if present, must be an allowed origin, otherwise 403 `security.csrf_origin`.
- Read-only public endpoints need no cookie and no header (curl works).
- There are no API keys or bearer tokens.

### Errors

Every error has the same body; clients translate `code`, `message` is an English fallback:

```json
{"detail": {"code": "auth.not_authenticated", "message": "Please sign in.",
            "fields": {"body.email": "value_error"}}}
```

`fields` appears only on validation errors. Common codes:

| Status | Code | Meaning |
|---|---|---|
| 401 | `auth.not_authenticated` | no valid session |
| 403 | `auth.email_not_verified` | the route needs a verified address |
| 403 | `auth.forbidden` | role or ownership does not allow it |
| 403 | `security.csrf`, `security.csrf_origin` | CSRF checks failed |
| 404 | `<resource>.not_found` | missing or not visible to the caller |
| 409 | `moderation.invalid_transition` | status change not allowed from the current status |
| 422 | `validation.failed` | invalid input; see `fields` |
| 429 | `rate.limited` | over a rate limit; honour `Retry-After` (seconds) |
| 503 | `knowbase.unavailable` | KNOWBASE down and nothing cached |
| 500 | `server.error` | unexpected error (quote `X-Request-ID` when reporting) |

### Pagination

List endpoints take `skip` (offset, default 0) and `limit` (page size; the maximum is per route,
for example 50 for posts, threads and search, 100 for comments and members, 200 for admin lists)
and answer `{"total": <int>, "items": [...]}`.

### Response headers

`X-Request-ID` on every response; `X-Knowbase-Cache: hit|miss|stale` on KNOWBASE proxy responses;
`ETag`/`Last-Modified` on the bulk exports (send `If-None-Match` to get 304); `Retry-After` on 429.

## 2. Who may call

| Label | Meaning |
|---|---|
| public | anyone, no session |
| public+ | anyone; a signed-in caller may see more (own pending content; admins see hidden content) |
| user | signed in (verified or not) |
| verified | signed in, email verified, account active |
| admin | verified admin or superadmin |

Every route under `/api/` also counts against `api.default` (300/min per IP); the Limit column
lists the additional route limit.

## 3. Routes

### Health (no prefix)

| Method | Path | Who | Limit | Purpose |
|---|---|---|---|---|
| GET | `/health` | public | – | liveness; does not touch the database |
| GET | `/health/ready` | public | – | readiness: database answers, else 503 |

### Auth and account (`/api/v1/auth`)

| Method | Path | Who | Limit | Purpose |
|---|---|---|---|---|
| POST | `/register` | public | 5/h | create an unverified account (Turnstile, `accept_terms`), email a verification link |
| POST | `/verify-email` | public | – | consume a verification token, verify and sign in |
| POST | `/resend-verification` | public | 3/h | new verification link; always 202 |
| POST | `/login` | public | 10/15 min | start a session (unverified users may sign in) |
| POST | `/logout` | public | – | end the current session; always 204 |
| GET | `/me` | user | – | own account |
| PATCH | `/me` | user | – | update own profile |
| GET | `/me/sessions` | user | – | own active sessions |
| DELETE | `/me/sessions/{session_id}` | user | – | sign out one session |
| POST | `/password/forgot` | public | 3/h | email a reset link; always 202 |
| POST | `/password/reset` | public | 10/h | set a new password with a token; signs out every session |
| POST | `/me/password` | user | 10/h | change password; other sessions signed out |
| POST | `/me/email` | user | 5/h | request an email change (link to the new address) |
| POST | `/email/confirm` | public | 10/h | confirm an email change with a token |
| GET | `/me/notifications` | user | – | email notification preferences |
| PUT | `/me/notifications` | user | – | replace notification preferences |
| GET | `/me/export` | user | – | GDPR export of own data (JSON download) |
| DELETE | `/me` | user | – | delete own account (anonymise); the last superadmin cannot |

### Organisations, expertise, members

| Method | Path | Who | Limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/organisations/` | public | – | all organisations, project partners first |
| GET | `/api/v1/organisations/{organisation_id}` | public | – | one organisation with its member count |
| POST | `/api/v1/organisations/` | admin | – | add an organisation |
| PATCH | `/api/v1/organisations/{organisation_id}` | admin | – | update an organisation |
| GET | `/api/v1/expertise/` | public | – | active expertise tags |
| GET | `/api/v1/members/` | verified | – | members directory (`q`, `expertise_ids`, `country`, `organisation_id`) |
| GET | `/api/v1/members/suggested` | verified | – | up to six members sharing the most expertise |
| GET | `/api/v1/members/{member_id}` | verified | – | one directory member's profile |

### Categories and tags

| Method | Path | Who | Limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/categories/` | public+ | – | categories by kind; `include_archived` for admins |
| GET | `/api/v1/categories/{kind}/{slug}` | public | – | one category (archived too) |
| POST | `/api/v1/categories/` | admin | – | add a category |
| PATCH | `/api/v1/categories/{category_id}` | admin | – | update (incl. `admin_only`, `is_archived`) |
| DELETE | `/api/v1/categories/{category_id}` | admin | – | archive (never a hard delete) |
| GET | `/api/v1/tags/` | public | – | tags, most used first; `q` filters |
| DELETE | `/api/v1/tags/{tag_id}` | admin | – | delete a tag (removed from every item) |
| POST | `/api/v1/tags/{tag_id}/merge` | admin | – | merge into `target_id` |

Tags are created implicitly when a post or thread names them; there is no tag create route.

### Blog posts and comments

| Method | Path | Who | Limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/posts/` | public+ | – | posts visible to the caller (`q`, category, tag, author, locale, sort; `status` for admins) |
| GET | `/api/v1/posts/{slug}` | public+ | – | one post |
| POST | `/api/v1/posts/` | verified | 20/h | write a post; `published` if trusted or admin, else `pending` |
| PATCH | `/api/v1/posts/{post_id}` | verified (author or admin) | – | edit; status unchanged |
| DELETE | `/api/v1/posts/{post_id}` | verified (author or admin) | – | soft delete |
| GET | `/api/v1/posts/{post_id}/comments/` | public+ | – | comments, oldest first |
| POST | `/api/v1/posts/{post_id}/comments/` | verified | 30/h | comment on a published post (published at once) |
| PATCH | `/api/v1/comments/{comment_id}` | verified (author within 24 h, or admin) | – | edit a comment |
| DELETE | `/api/v1/comments/{comment_id}` | verified (author or admin) | – | soft delete |

### Forum threads and replies

| Method | Path | Who | Limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/threads/` | public+ | – | threads, pinned first, then latest activity (`sort=newest`) |
| GET | `/api/v1/threads/mentions/{kb_type}/{kb_id}/` | public+ | – | threads linking a KNOWBASE item |
| GET | `/api/v1/threads/{slug}` | public+ | – | one thread |
| POST | `/api/v1/threads/` | verified | 20/h | open a thread; `published` if trusted or admin, else `pending` |
| PATCH | `/api/v1/threads/{thread_id}` | verified (author or admin; locked: admin only) | – | edit |
| DELETE | `/api/v1/threads/{thread_id}` | verified (author or admin) | – | soft delete |
| POST | `/api/v1/threads/{thread_id}/pin` | admin | – | pin (idempotent) |
| POST | `/api/v1/threads/{thread_id}/unpin` | admin | – | unpin |
| POST | `/api/v1/threads/{thread_id}/lock` | admin | – | lock: no replies, no author edits |
| POST | `/api/v1/threads/{thread_id}/unlock` | admin | – | unlock |
| GET | `/api/v1/threads/{thread_id}/replies/` | public+ | – | top-level replies with their nested replies |
| POST | `/api/v1/threads/{thread_id}/replies/` | verified | 60/h | reply (one nesting level via `parent_reply_id`); 423 if locked |
| PATCH | `/api/v1/replies/{reply_id}` | verified (author within 24 h while unlocked, or admin) | – | edit |
| DELETE | `/api/v1/replies/{reply_id}` | verified (author or admin) | – | soft delete; child replies stay |

### Uploads

| Method | Path | Who | Limit | Purpose |
|---|---|---|---|---|
| POST | `/api/v1/uploads/images/` | verified | 30/day | upload JPEG/PNG/WebP ≤ 5 MiB with required `alt_text`; re-encoded to WebP |
| GET | `/api/v1/uploads/mine/` | user | – | own uploads, each with `used_in` (content using it, any status) |
| DELETE | `/api/v1/uploads/{attachment_id}` | user (uploader or admin) | – | delete an upload; 409 `uploads.in_use` while a cover or body uses it (for the uploader's own delete, content with status `deleted` does not count) |
| GET | `/static/uploads/...` | public | – | the image files (no prefix) |

### KNOWBASE proxy (`/api/v1/knowbase`)

Read-only, cached copies of the KNOWBASE public API (see [architecture.md](architecture.md#6-knowbase-proxy-and-caching)).
The frontend uses the list endpoints for the editor's link picker search, and the detail and
mentions endpoints for the item pages; it has no library pages since 2026-10-31 (browsing happens
on the KNOWBASE site), so the lookup endpoints currently have no frontend caller.

| Method | Path | Who | Limit | Purpose |
|---|---|---|---|---|
| GET | `/documents/` | public | – | legal and policy documents (KNOWBASE filters) |
| GET | `/documents/{document_id}` | public | – | one document |
| GET | `/measures/` | public | – | flood-management measures with absolute `photo_url` |
| GET | `/measures/{measure_id}` | public | – | one measure |
| GET | `/measures/lookups/{name}` | public | – | measure filter options (`categories`, `levels-of-application`, `scales`, `keywords`) |
| GET | `/levels/`, `/subjects/`, `/keyword-labels/` | public | – | document vocabularies |
| GET | `/lookups/{name}` | public | – | document filter options (`countries`, `levels`, `subjects`, `keywords`) |
| GET | `/status` | public | – | reachability and cache sizes (no upstream call) |
| GET | `/{kb_type}/{kb_id}/mentions/` | public+ | – | posts linking a KNOWBASE document or measure |

### Reports and moderation

| Method | Path | Who | Limit | Purpose |
|---|---|---|---|---|
| POST | `/api/v1/reports/` | verified | 20/day | report published content (once per item; not own content) |
| GET | `/api/v1/reports/` | admin | – | reports, newest first, with a content summary |
| GET | `/api/v1/reports/{report_id}` | admin | – | one report |
| POST | `/api/v1/reports/{report_id}/resolve` | admin | – | close as acted upon |
| POST | `/api/v1/reports/{report_id}/dismiss` | admin | – | close without action |
| GET | `/api/v1/moderation/queue/` | admin | – | pending posts and threads, oldest first |
| GET | `/api/v1/moderation/log/` | admin | – | audit rows; `action` ending in `.` is a prefix; `actor_id`, `target_type` |
| POST | `/api/v1/moderation/{content_type}/{content_id}/approve` | admin | – | publish pending; author becomes trusted |
| POST | `.../reject` | admin | – | hide pending as rejected (optional reason) |
| POST | `.../hide` | admin | – | hide published (optional reason) |
| POST | `.../unhide` | admin | – | publish hidden again (from rejected = approval) |
| POST | `.../delete` | admin | – | soft delete |
| POST | `.../restore` | admin | – | restore deleted (to `pending` if never approved) |
| POST | `.../purge` | admin | – | delete permanently from any status: comments/replies, tag and KNOWBASE links, images nothing else uses; open reports resolved (one `report.resolve` audit row each, `purge: true`); audit `moderation.purge` (counts and the deleted attachments' ids and uploaders, never a body or path) |

`content_type` is `post`, `thread`, `reply` or `comment`.

### Administration (`/api/v1/admin`)

| Method | Path | Who | Limit | Purpose |
|---|---|---|---|---|
| GET | `/users/` | admin | – | all accounts incl. deleted ones (filters: `q`, role, verified, trusted, active, organisation_id) |
| GET | `/users/{user_id}` | admin | – | one account |
| PATCH | `/users/{user_id}` | admin | – | change role, active and/or trust (same rules as below) |
| POST | `/users/{user_id}/promote` | admin (`to=superadmin`: superadmin) | – | raise role |
| POST | `/users/{user_id}/demote` | admin (superadmin target: superadmin) | – | lower role one step |
| POST | `/users/{user_id}/ban` | admin (superadmin target: superadmin) | – | deactivate and sign out everywhere |
| POST | `/users/{user_id}/unban` | admin | – | reactivate |
| POST | `/users/{user_id}/trust` | admin | – | mark trusted |
| POST | `/users/{user_id}/untrust` | admin | – | clear trusted mark |
| POST | `/users/{user_id}/resend-verification` | admin | – | email a new verification link (502 if sending fails) |
| GET | `/stats` | admin | – | dashboard counts and KNOWBASE proxy status |
| GET | `/stats/export.csv` | admin | – | reporting CSV for `from`..`to` (see [admin-handbook.md](admin-handbook.md#stats-csv-export)) |
| POST | `/knowbase/cache/clear` | admin | – | empty the KNOWBASE proxy caches |

### Search

| Method | Path | Who | Limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/search/` | public+ | 60/min | posts and threads matching `q` (2–200 chars), `type` (all, posts or threads), `locale`; ranked, with highlighted snippets |

### Open data: exports, feeds, sitemap

These are the endpoints intended for reuse (FAIR). All are public, need no account, and contain
published content only, never email addresses. Licence: CC BY 4.0.

| Method | Path | Who | Limit | Purpose |
|---|---|---|---|---|
| GET | `/api/v1/export/posts.json` | public | – | every published post with published comments and KNOWBASE links (streamed; ETag) |
| GET | `/api/v1/export/threads.json` | public | – | every published thread with published replies and KNOWBASE links |
| GET | `/api/v1/export/posts.csv` | public | – | one row per published post, no bodies |
| GET | `/api/v1/export/datapackage.json` | public | – | Frictionless Data Package (v2) descriptor of the three exports |
| GET | `/feeds/posts.atom` | public | – | Atom feed, 20 newest posts |
| GET | `/feeds/threads.atom` | public | – | Atom feed, 20 newest threads |
| GET | `/sitemap.xml` | public | – | static pages and every published post and thread |
| GET | `/robots.txt` | public | – | allows crawling; excludes `/account` and `/admin` |

Public read endpoints (`/posts/`, `/threads/`, `/categories/`, `/tags/`, `/search/`,
`/organisations/`, `/knowbase/*`) return the same published content for anonymous callers.

## 4. Example

```bash
# anonymous read
curl -s 'http://localhost:8000/api/v1/posts/?limit=5' | jq '.total, .items[].title'

# signed-in write (cookie jar + CSRF header)
curl -s -c jar -H 'Content-Type: application/json' \
  -d '{"email":"member@urbanfloods.example","password":"Member-Dev-Pass-2026"}' \
  http://localhost:8000/api/v1/auth/login
curl -s -b jar -H 'X-Requested-With: XMLHttpRequest' http://localhost:8000/api/v1/auth/me
```

The demo account exists only after the development seed ([testing.md](testing.md#3-development-data)).

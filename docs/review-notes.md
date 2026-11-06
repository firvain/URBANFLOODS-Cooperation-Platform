# Review notes

For anyone reviewing this code for bugs (including `/code-review` and `/security-review` runs).
It lists what is **deliberate**, what is **already known**, and where the **risk** sits, so a review
spends its time on real defects. When a finding contradicts something here, say so explicitly
rather than re-reporting it as new.

Context: `CLAUDE.md` (conventions, hard rules), `docs/PLAN.md` (scope and architecture),
`docs/architecture.md`, `docs/testing.md` (including the dev-vs-production settings table, §6),
`PROGRESS.md` (history and decisions).

## Where the risk is (review these first)

| Area | Code | Why it matters |
|---|---|---|
| Authentication and sessions | `backend/app/api/v1/endpoints/auth.py`, `core/security.py`, `core/deps.py`, `crud/session.py`, `core/session_cookie.py`, `frontend/src/stores/auth.ts`, `frontend/src/services/api.ts` | opaque `uf_session` cookie, argon2id, email verification, password reset, email change, sliding expiry and cookie refresh |
| CSRF and CORS | `core/csrf.py`, `main.py` | the frontend sends `X-Requested-With`; unsafe methods without it are refused |
| Bot protection | `services/turnstile.py`, `frontend/src/components/auth/TurnstileWidget.vue` and the four forms that use it | production runs Turnstile on; the 2026-11-01 bug (7d) lived here |
| Authorisation and visibility | `crud/visibility.py` (`visible_to`), the `require_*` dependencies, every mutating endpoint | owner / admin / superadmin rules, content status `pending/published/hidden/deleted` |
| Moderation and trust | `crud/moderation.py`, `crud/reports.py`, scheduler jobs (auto-approve, auto-hide, purge) | trust after first approval, auto-hide after reports, the 7-day bin, permanent delete |
| HTML sanitisation | `services/sanitize.py` (nh3), `frontend/src/components/common/SafeHtml.vue` (DOMPurify) | every stored body passes nh3; the only `v-html` is SafeHtml |
| Uploads | `endpoints/uploads.py`, `services/images.py` | re-encoded to WebP, metadata stripped, size/pixel limits, served by nginx with `nosniff` |
| KNOWBASE proxy | `services/knowbase.py` | read-only GETs to allow-listed public routes, cache; the KNOWBASE must never be modified |
| GDPR | `crud/user.py` (`export_user_data`, `anonymise_user`), maintenance purges | export completeness, erasure on deletion, no IP addresses stored |
| Production-only configuration | `docker-compose.prod.yml`, `frontend/nginx.conf` (CSP and headers), `deploy.sh`, `.env.prod.example` | covered by the smoke test (7g) for most settings; see the table in `docs/testing.md` §6 |

## Deliberate decisions (not bugs)

- **Published content is publicly readable.** The AF says "upon registration"; the platform reads
  that as registration for taking part (posting, commenting, reporting, the members directory),
  with reading open for dissemination and FAIR reuse (PLAN "Access model").
- **Resend verification without a Turnstile token** is allowed only for a signed-in, unverified
  member resending to their own address (7d). The session proves a browser; the route is rate
  limited per IP (10/hour). Everything else needs a token.
- **Forms keep submit disabled until a Turnstile token arrives** when a site key is set (7d). If
  a browser blocks the Cloudflare script, the button stays disabled without a message: known
  follow-up, not yet built.
- **The KNOWBASE is browsed on its own site**; the platform shows item pages, link cards and one
  read-only list ("Flood Management Measures", `/knowbase/measures`, 7c). No search, documents
  list or country filter on the platform by design. The KNOWBASE has no address for a single
  item, so the platform does not link to one.
- **Measure names are title-cased with the KNOWBASE's own rule** (`utils/knowbase.measureTitle`:
  capital after start, space or "("), so "And" is capitalised and "Re-meandering" is not. This
  mirrors the KNOWBASE site on purpose.
- **Free-text "other" fields** (`organisation_other`, `expertise_other`) are searchable but are not
  filters and are not used for suggested collaborators.
- **Email:** Brevo rewrites links for click tracking and this cannot be switched off for SMTP;
  no URL is used as link text in templates. Member notifications are opt-in; no welcome email.
  The verification and email-change pages need a button press because institutional mail
  scanners open links automatically.
- **Single backend worker:** rate limits, the KNOWBASE cache and the scheduler are in-process.
  Acceptable at this scale; documented.
- **No XML bulk export** (JSON, CSV, Frictionless data package and Atom instead). DOIs come from a
  Zenodo deposit at project end, not from the code.
- **No dark mode, no third-party scripts except Cloudflare Turnstile, no analytics, no paid
  services** (CLAUDE.md §9).
- **Auto-approve (`AUTO_APPROVE_AFTER_DAYS`) never publishes** items of banned or erased authors,
  or items with `rejected_at` (rejected, then resubmitted or restored): those wait for an admin
  however long (7i). The sweep locks content and author rows with `SKIP LOCKED`; a locked item
  waits for the next run.
- **Restore puts content back where it was** (7j): an item that was hidden when deleted (by an
  admin, by reports, or rejected) comes back hidden with the same `hidden_reason`, its open
  reports still open; only a restore to `published` dismisses reports (each with a
  `report.dismiss` audit row, `via: "restore"`). A rejected item comes back rejected and its
  author can resubmit it.
- **Children of a hidden reply stay public** (shown under a placeholder for the hidden parent), so
  they can be reported. A reply or comment whose **thread or post** the reporter cannot see cannot
  be reported (404, nothing leaks). Admins may edit or delete replies and comments under a deleted
  thread or post; members get 404 there (`visibility.parent_visible`).
- **Failed password checks are limited per account as well as per IP** (7k): 10 failed logins
  per account per 15 minutes and 10 wrong current passwords per user per hour (change password,
  change email, delete account). Known accounts are keyed by user id; an address with no account
  by an HMAC of the trimmed, lower-cased email, counted the same way. Each check is counted before
  the password is verified, so even the right one gets 429 while the bucket is full; the right
  password empties the bucket (only its holder can do that). Accepted lockout: an attacker who
  knows an address can keep it from signing in with a password while they keep guessing (each 429
  asks to retry within 15 minutes); password reset by email still works. When a store is full,
  drained buckets are swept before any active one is evicted; evicting a lockout needs tens of
  thousands of active keys within one window.
- **Per-IP limits on the public auth routes are generous** (7k: register 30/h, login 60/15 min,
  resend verification and forgot password 10/h): NAT and venue Wi-Fi share one address (partners
  register by QR code at meetings). Turnstile and the per-account limits are the main defence.
  Per-IP buckets key IPv6 by /64 (IPv4-mapped addresses as IPv4).
- **A verification link of an already verified address does not sign in** (7k): the token is
  spent, the answer is 400 `auth.already_verified` and no session is created; the page points to
  sign-in. Password reset and change cancel unused verification links, and verify and reset
  revoke the session the browser already holds (whatever account), as login does. The message
  only states the fact ("This address is already verified."); the button carries the action (Log
  in when signed out, back to the home page when signed in).
- **The session cookie is refreshed on successful responses when the sliding expiry moves**
  (7l, at most once a day, by `core/session_cookie.py`): only for status below 400, because an
  error response rolls the touch back, and never on a response that already sets or clears the
  cookie (login, logout, verify, reset, revoking the current session, account deletion). The one
  4xx that commits the touch (`AppError` with `keep_changes`) leaves the cookie up to a day behind
  the stored expiry until the next slide; the server checks `expires_at` on every request.
- **Only a 401 from `GET /auth/me` signs the frontend out** (7l). A 502, network error or 429
  leaves the status `unknown`, not anonymous. An auth-required or admin route still redirects to
  `/login?next=…` (nobody whose session is unknown sees a members' or admin page), and every
  navigation while `unknown` asks again, the redirect included: if that succeeds, the login
  page's guest-only check sends the member on to `next`. A 401 from any request except
  `GET /auth/me` and `POST /auth/login` clears the store, so a 401 to `PATCH` or
  `DELETE /auth/me` does too. The method is the one fetch uses (`options.method` over a
  `Request` object's own).
- **An uploader may delete their image even if another member embeds it** (7m). The uploader
  owns the image; the other member's content then shows a broken image, and a post that had it
  as its cover loses the cover. The uploader's delete and avatar replacement count only the
  uploader's own content that is not deleted; account deletion counts the uploader's own content
  in any status, and deletes their images even when other members embed them. A replaced
  avatar their own live content still uses is only unlinked. The uploads panel lists every use
  (`by_uploader` per use), blocks the delete only for the member's own live content and warns
  in the confirmation when other members use the image. The orphan sweep and the moderators'
  purge count anyone's content and **never delete an image anyone embeds**. A mention of the
  path as text (or a link to it) is not a use. An admin's delete of someone else's upload still
  counts anyone's content (409).
- **The daily upload cap is counted twice** (7m): without a lock before decoding (a fast 409),
  then under a per-member advisory lock after decoding. The lock is not held while decoding,
  but the request keeps its database connection (from authentication) meanwhile; decoding is
  bounded by `UPLOAD_DECODE_CONCURRENCY`.
- **Images in content only from our uploads and the KNOWBASE; the CSP stays strict; the editor
  explains** (7n, owner's decision 2026-11-02). Both sanitisers (backend
  `services/sanitize.py:_allowed_img_src`, frontend `utils/sanitize.ts:allowedImageSrc`) keep an
  `<img>` only when its `src` is a path under `/static/uploads/`, an upload URL on our own origin
  (`FRONTEND_URL` / `window.location.origin`; stored as the relative path) or an **https** URL on
  the KNOWBASE origin. Origins compare scheme, host and port; credentials, backslashes, control
  characters and (in upload paths) literal or percent-encoded dot segments never pass. Every other
  image is dropped (http KNOWBASE images too: the CSP allows https only). The CSP
  (`img-src 'self' data: blob: https://knowbase.urbanfloods.app`) is unchanged, so readers'
  browsers never request third-party images. When a paste, a drop or loaded content (an older post
  opened for editing) loses an image, the editor shows "Images from other websites are not
  allowed. Upload the image instead." in a status region; each paste or load resets it, a repeat
  drop re-renders it (re-announced), an upload clears it.
- **Ids past a column's range and values the client sends that the database refuses answer
  422** (7n). Integer ids in paths, queries, bodies and the KNOWBASE filters use the bounded
  aliases of `api/v1/params.py` (limits in `db/limits.py`: INTEGER ids up to 2³¹−1; reply,
  comment and report ids, and moderation's content ids, up to 2⁶³−1, with a post or thread id
  past INTEGER simply not found); `tests/test_input_bounds.py` fails for any new id parameter
  (or id field of a query model) without an upper bound. What validation misses (a NUL in text,
  a huge `skip`) is caught by a handler registered for `sqlalchemy.exc.DataError` only:
  `db/session.py` raises asyncpg's `DataError` family as that class (the asyncpg dialect leaves
  it a plain `DBAPIError`). Only `CharacterNotInRepertoireError` and asyncpg's own
  argument-encoding `DataError` become 422 `request.invalid_value`; a server-side overflow
  (`NumericValueOutOfRangeError`) or any other data error is our bug and stays a logged 500;
  integrity, operational and other errors never reach the handler.
- **The export ETag covers what the export shows** (7n): count and latest `updated_at` of the
  published content, organisations and the export's categories; an md5 of the id, name,
  organisation and erased flag of the **authors of the exported content** only (not `updated_at`:
  every sign-in bumps it; a registration or a non-author's rename changes nothing), of the tags
  and of the content–tag pairs (a tag-only edit does not bump the content), every value
  `quote_nullable`-d so rows are unambiguous; count and max id of the KNOWBASE links (replaced,
  never updated). One query; `If-None-Match` is compared weakly (nginx turns the strong tag into
  `W/"…"`).
- **Admins can mark an email address verified by hand** (7p), for members they verify in person
  (`POST /admin/users/{id}/verify`, "Mark as verified"). It skips the proof of address ownership
  by design; the confirm dialog asks the admin to check the address with the person. Audited
  (`admin.verify_email`, `{"manual": true}`); does not trust (the first post still needs
  approval); refused for banned and deleted accounts; a superadmin's address needs a superadmin
  (the rule of ban). The sending address shown after registration is a frontend constant
  (`constants/links.ts`, `VERIFICATION_SENDER`) that must equal the backend's `SMTP_FROM`.
- **Admins see soft-deleted content by URL** (with a Deleted badge); lists, search, feeds and
  exports never include it.

## Already known (do not re-report; improvements welcome)

- The accepted limitations in `docs/qa-checklist.md` §5.1.
- `/admin/deleted`: the per-row "Delete permanently" button fails axe
  `label-content-name-mismatch` (WCAG 2.5.3) once the bin has rows (logged 2026-11-01).
- Turnstile script blocked → submit stays disabled without an explanation (see above).
- Upload usage detection scans bodies (a `strpos` filter guarding, through a `CASE`, a Postgres
  regex for a real `<img src="…<UPLOAD_URL_PREFIX>/<path>">` embed, relative or absolute; 7m).
  No index; fine at current scale.
- Partner translations not yet confirmed by native speakers.
- Audit-log retention: sign-in and failed sign-in entries (with the browser description) are kept
  for the life of the Platform, as the privacy policy (v1.4, §3.2) states. A shorter period for
  security events (e.g. 12 months, consent and moderation records kept) is the planned next
  increment (logged 2026-11-06, 7q).

## Out of scope for code review

- The KNOWBASE application (`~/URBANFLOODS-Knowbase`): delivered separately, never modified here.
- Host nginx, TLS/HSTS, Cloudflare in front, and the production server itself (owner-managed).
- `docs/legal/` wording (owner-approved texts).
- Meeting presentations (`docs/*.pptx`, not in git).

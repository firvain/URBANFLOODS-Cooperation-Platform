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
| Authentication and sessions | `backend/app/api/v1/endpoints/auth.py`, `core/security.py`, `core/deps.py`, `crud/session.py` | opaque `uf_session` cookie, argon2id, email verification, password reset, email change |
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
  limited per IP (3/hour). Everything else needs a token.
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
- **Admins see soft-deleted content by URL** (with a Deleted badge); lists, search, feeds and
  exports never include it.

## Already known (do not re-report; improvements welcome)

- The accepted limitations in `docs/qa-checklist.md` §5.1.
- `/admin/deleted`: the per-row "Delete permanently" button fails axe
  `label-content-name-mismatch` (WCAG 2.5.3) once the bin has rows (logged 2026-11-01).
- Turnstile script blocked → submit stays disabled without an explanation (see above).
- Orphan-upload and usage detection by substring scan (fine at current scale).
- Partner translations not yet confirmed by native speakers.

## Out of scope for code review

- The KNOWBASE application (`~/URBANFLOODS-Knowbase`): delivered separately, never modified here.
- Host nginx, TLS/HSTS, Cloudflare in front, and the production server itself (owner-managed).
- `docs/legal/` wording (owner-approved texts).
- Meeting presentations (`docs/*.pptx`, not in git).

# QA checklist: manual test and evaluation before deployment

A manual test and evaluation pass for the Cooperation Platform (D.5.1.1) on the development stack.
A person or a fresh Claude session can follow it from start to finish. It covers what the automated
suites do not: real browsers, real emails, every role and account state, accessibility by hand,
layout, and the AF commitments. Run it once before M6 and again after any large change.

Last updated: 2026-10-31

Conventions: each scenario has an id (`V-03`), the account to use, steps and the expected result.
**AF** names the commitment it evidences (ids in section 5). `[CHECK]` marks something the source
files do not settle; record what you see. Write failures as `FAIL: what happened` next to the
item, and turn each one into a small increment (one commit each, PROGRESS.md updated).

## 1. Purpose and how to use

### 1.1 Fresh stack

```bash
cd /Users/firvain/Projects/URBANFLOODS_Cooperation_Platform
docker compose up --build -d
docker compose exec -T backend python -m scripts.seed_dev --reset   # wipe demo data, reseed
```

| Service | URL |
|---|---|
| Frontend (Vite) | http://localhost:5173 |
| API, Swagger | http://localhost:8000/docs, spec at http://localhost:8000/api/v1/openapi.json |
| Health | http://localhost:8000/health, http://localhost:8000/health/ready |
| Mailpit (all dev email) | http://localhost:8025 |

- The dev backend sends all email to Mailpit (`EMAIL_ENABLED=true`, `SMTP_HOST=mailpit`), with
  Turnstile off, rate limits on, and the scheduler off (so the digest only runs from the CLI).
- `--reset` deletes every `@urbanfloods.example` account and its content, plus the seeded
  anonymised account, then reseeds. Accounts you register with other addresses are kept, so
  delete them yourself (scenario N-09).
- Demo accounts: twelve personas in [backend/README.md](../backend/README.md#development-seed).
  All of them use the password **`Urbanfloods-2026`**. The ones this checklist uses:

| Short name | Email | Role / state |
|---|---|---|
| Eleni | `eleni.papadopoulou@urbanfloods.example` | superadmin, trusted, locale `el` |
| Matej | `matej.kovacic@urbanfloods.example` | admin, trusted, locale `sl` |
| Aleksandar | `aleksandar.stojanovski@urbanfloods.example` | admin, trusted, locale `mk` |
| Giulia | `giulia.romano@urbanfloods.example` | member, trusted, shows email, 3 expertise tags |
| Ivana | `ivana.babic@urbanfloods.example` | member, trusted |
| Nikola | `nikola.petrovic@urbanfloods.example` | member, trusted, **hidden from the directory**, locale `sr` |
| Arben | `arben.hoxha@urbanfloods.example` | member, verified, **untrusted**, no posts yet |
| Amra | `amra.hadzic@urbanfloods.example` | member, untrusted, free-text organisation "City of Zenica", has the **pending** seeded post |
| Dimitris | `dimitris.karagiannis@urbanfloods.example` | **unverified**, free-text "Municipality of Florina" |
| Sara | `sara.conti@urbanfloods.example` | **banned**, her content stays |
| Deleted user | (anonymised; cannot log in) | author of "Level sensors in a combined sewer network…" |
| Petra | `petra.vidmar@urbanfloods.example` | member, untrusted, minimal profile |

Seeded content you will need (from `backend/scripts/seed_dev.py`):

- the post "Green roofs and retention basins: what two years of pilot data show" (Giulia), which
  links to KNOWBASE measures 14 (green roofs) and 17 (detention basins);
- the post "Reading guide: the Floods Directive and national flood risk management plans" (Resources,
  admin only, Aleksandar), which links to KNOWBASE document 1;
- a Greek post "Λύσεις βασισμένες στη φύση για την αντιπλημμυρική προστασία της Κοζάνης" (Eleni);
- the pending post "Cleaning storm drains before the autumn rains: a municipal routine" (Amra);
- an Events post "Webinar: impact-based early warning for small municipalities";
- a post by banned Sara ("Rain gauges on school roofs: a citizen-science start in Modica");
- the pinned thread "Welcome: introduce yourself and your organisation", plus three other threads.

### 1.2 Rate limits during manual testing

The dev backend enforces the real limits per client IP, in memory (`backend/app/core/rate_limit.py`).
These are the ones you will hit:

| Limit | Budget |
|---|---|
| login | 10 per 15 min (one more every 90 s) |
| register | 5 per hour |
| resend verification, forgot password | 3 per hour each |
| reports | 20 per day |
| image uploads | 30 per day |
| posts, threads | 20 per hour each |
| every `/api/` call | 300 per minute |

This checklist switches accounts often, so it needs more than 10 logins. There are three ways round it:

- **Quick reset:** `docker compose restart backend` empties every bucket. It also clears the KNOWBASE cache.
- **Lift the limits for a session:** create `docker-compose.override.yml` next to `docker-compose.yml`
  (Compose merges it automatically):

  ```yaml
  services:
    backend:
      environment:
        RATE_LIMIT_ENABLED: "false"
  ```

  Then run `docker compose up -d backend`. **Delete the file afterwards** and run
  `docker compose up -d backend` again. The file is not gitignored, so never commit it. Turn the
  limits back on before the rate-limit checks (X-S3) and before `npm run e2e`.
- Use a second browser profile for the second role, so you log in less often.

### 1.3 Real-mail test (optional, once)

To check deliverability and how the emails look in a real client, put these in the root `.env`.
Keep the key there only (`.env` is gitignored):

```bash
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USER=<SMTP login from Brevo "SMTP & API">
SMTP_PASSWORD=<the dev SMTP key "cooperation-platform">
SMTP_FROM=noreply@cooperation.urbanfloods.app
SMTP_FROM_NAME=URBANFLOODS Cooperation Platform (dev)
```

Run `docker compose up -d backend` to recreate the container (a plain restart does not re-read
`.env`). Then register with a real inbox (N-01). The demo `.example` addresses can never be
delivered to. Afterwards, remove the lines and run `docker compose up -d backend` again. The free
plan allows 300 emails per day.

## 2. Automated suites to run first

Run all of them on a clean tree with the seed freshly reset. Expected counts as of 2026-10-31:

| Suite | Command | Expected |
|---|---|---|
| Backend | `cd backend && uv run pytest` (Docker for testcontainers, or `TEST_DATABASE_URL=postgresql+asyncpg://test:test@localhost:5434/test` with `docker compose -f docker-compose.test.yml up -d --wait`) | all green. **1607+** (1613 collected on 2026-10-31) |
| Backend lint | `cd backend && uv run ruff check . && uv run ruff format --check .` | clean |
| Coverage | `cd backend && uv run pytest --cov=app --cov-report=term-missing` | ≥ 80 % on `crud/` and `services/` |
| Frontend unit | `cd frontend && npm run test` | **1017 passed, 60 files** (re-run 2026-10-31) |
| Frontend static | `cd frontend && npm run lint:check && npm run type-check && npm run build-only` | clean |
| E2E | `cd frontend && npx playwright install chromium && npm run e2e` | **31 passed** (auth 8, blog 7, forum 8, moderation 8); the 4 a11y tests skipped |
| E2E a11y | `cd frontend && E2E_A11Y=1 npm run e2e -- a11y` | 4 passed, 0 axe violations (23 page scans per PROGRESS 5d) |
| CI | GitHub Actions on `main` | green |

- [ ] Backend green
- [ ] Frontend unit, lint, type-check and build green
- [ ] E2E green (stack up, seed reset, rate limits **on**, no override file)
- [ ] E2E a11y green
- [ ] CI green on the commit under test

Notes:

- One full e2e run uses 12 of the 10-per-15-min login budget (15 with `E2E_A11Y=1`). It works
  because the bucket refills during the run. Do not run it twice within about 15 minutes; if you
  must, run `docker compose restart backend` first. Reset the seed before the run: blog test 1 and
  moderation test 2 assume the seeded state. See [testing.md](testing.md#rate-limit-budget-per-full-run).
- `docs/testing.md` still lists moderation as 6 tests and a11y as 3, and says 4h is uncommitted.
  The spec files have 8 and 4. Update testing.md. [CHECK]

**What a green result proves:** the API rules (authorisation for every mutating endpoint,
moderation state machine, sanitisation, upload validation, GDPR export and deletion, rate limits,
CSRF, KNOWBASE proxy with a mocked upstream) and the main browser flows in Chromium (register →
verify → password, blog and forum lifecycle, pending → approve, reports → auto-hide, dashboard and
CSV, digest email, Moderate menu and purge). The axe scans prove there are no *automatically
detectable* WCAG 2.1 AA violations on the scanned pages, in English, at the default viewport.

**What it does not prove:** that the real KNOWBASE answers as the mocks assume, that emails look
right in a real client or reach an inbox, keyboard-only and screen-reader use, layout at other
widths, the eight other locales, Firefox/Safari, the account states nobody automates (unverified,
banned, anonymised, directory-hidden), account deletion in the UI, and anything about production
(nginx, TLS, headers, Turnstile, Brevo prod key, backups). Sections 3–4 cover those.

## 3. Manual scenarios by role

### 3.1 Visitor (signed out)

| Id | Steps | Expected | AF |
|---|---|---|---|
| V-01 | Open `/` | Hero "URBANFLOODS COOPERATION PLATFORM", the "Project at a Glance" card, cards for Blog, Forum, URBANFLOODS KNOWBASE (links out to knowbase.urbanfloods.app) and URBANFLOODS DSS (links out to https://urbanfloods.finki.ukim.mk/), latest content. Nav: Home · Blog · Forum · KNOWBASE · Network · Unified DSS · About. No suggested-collaborators widget for visitors | AF-4, AF-5, M-2 |
| V-02 | Open `/about`, then `/partners` | About shows the project facts and the `#partnership` section: lead-partner card, partner tiles, associated partners, logos and flags. `/partners` redirects to `/about#partnership` and scrolls below the sticky header | AF-6 |
| V-03 | `/blog`: use the category chips, a tag link (`/blog/tag/<slug>`), a category URL (`/blog/category/news`), the search box and pagination | Only published posts appear. Amra's pending post is absent. The filters update the URL and survive a reload. The Events order shows upcoming events | AF-4, M-4 |
| V-04 | Open the green-roofs post | Body, cover, tags, author card, comments (read only) and KNOWBASE link cards for measures 14 and 17. No comment form; a prompt to sign in instead. Report button absent or asks you to sign in [CHECK] | AF-2, AF-4 |
| V-05 | Click a KNOWBASE link card → `/knowbase/measures/14`. Check its "Mentioned in" list and "Open in the KNOWBASE". Repeat for `/knowbase/documents/1` (from the Reading guide post) | The item page renders the proxied measure/document fields. "Mentioned in" lists the platform posts that link to it. "Open in the KNOWBASE" goes to knowbase.urbanfloods.app. `/knowbase/measures/999999` shows "Measure not found" with a hint | AF-2, AF-3 |
| V-06 | Open the Greek post | The article has `lang="el"` (check in devtools). The rest of the UI stays in the current locale | AF-11 |
| V-07 | `/forum`, a category (`/forum/c/general`), the pinned thread, a thread with a nested reply | The pinned thread is first. Replies nest one level. No reply form for visitors | AF-5 |
| V-08 | `/search?q=flood`; try a typo in a title word (e.g. `drainige`); filter posts / threads | Results with highlighted `<mark>` snippets. The typo still finds the title. The result count is announced. The filters are in the URL | M-12 |
| V-09 | `/network` | A "Sign in to see the members directory" notice with a link to the partners section. No member data. `/u/<any id>` redirects to `/login?next=…` | AF-9 |
| V-10 | `/terms`, `/privacy`, `/accessibility`, `/open-data`; footer links | Each page renders from `docs/legal`. **No `[CHECK` text and no reviewer notes are visible** (search the page). In-page `#` links scroll correctly | AF-7, AF-8, AF-9 |
| V-11 | Switch the language to each of en, el, it, sl, hr, sr, mk, sq, bs | The UI changes at once. sr and mk are in Cyrillic. `<html lang>` follows. The choice survives a reload. Admin texts stay English by design | M-11 |
| V-12 | Open the open-data URLs: `http://localhost:8000/api/v1/export/posts.json`, `/api/v1/export/threads.json`, `/api/v1/export/posts.csv`, `/api/v1/export/datapackage.json`, `http://localhost:8000/feeds/posts.atom`, `/feeds/threads.atom`, `/sitemap.xml`, `/robots.txt` | JSON and CSV contain published items only (no pending, hidden or deleted; no emails). The data package declares CC BY 4.0. The Atom feeds parse (open them in a feed reader or run them through the W3C validator). The sitemap lists public routes and items, and the partners section of About. The links on `/open-data` point at working URLs in dev [CHECK] | AF-8, M-6 |
| V-13 | View the page source/head of a post and a thread | `<title>`, description, canonical, og tags, and JSON-LD (`Article` / `DiscussionForumPosting`; `WebSite` with `SearchAction` on home) | M-5 |
| V-14 | Open `/blog/new`, `/account`, `/admin`, `/admin/users` | The first two go to login with `?next=`. The admin URLs show the 404 page at the same address (they do not confirm that admin pages exist) | AF-1 |
| V-15 | Open a non-existent URL and a non-existent post slug | Friendly 404 / "not found" pages with one `h1` | AF-7 |

### 3.2 New member (register with a fresh address)

Use a real inbox for the real-mail variant (section 1.3). Otherwise use any address such as
`qa-<date>@example.org` and read it in Mailpit. One registration counts against the 5-per-hour limit.

| Id | Steps | Expected | AF |
|---|---|---|---|
| N-01 | `/register`: display name, email, password, organisation "other" + free text, country, locale, open the expertise picker and pick two tags, tick consent (Terms/Privacy links open) | Field errors are announced (password under 10 characters, a common password, missing consent). On success: "Check your email" | AF-1, AF-9 |
| N-02 | Mailpit → the verification email | Subject "Verify your email address for the URBANFLOODS Cooperation Platform". The link goes to `http://localhost:5173/verify-email?token=…`. Reply-To is `urbanfloods@uowm.gr`. Plain-text and HTML parts both present. EU co-funding line in the footer. A user with locale `el` gets the Greek template | AF-1 |
| N-03 | Click the link | Verified and signed in. A welcome email arrives. A "complete your profile" nudge appears if expertise is empty. Opening the link a second time gives a clear "invalid or used" message | AF-1 |
| N-04 | `/account` → Profile: edit bio, organisation, country, expertise, "show my email", "show me in the directory"; save and reload | The values persist. `/network` now shows the directory, and your card shows your expertise. Suggested collaborators appear on Home once expertise is set | AF-6, M-3 |
| N-05 | `/blog/new`: write a first post (Best practices) and save | The post is created as **pending**. The post page shows the pending banner with the contact address. It is not in `/blog` for others (check in a private window). Members cannot choose the Resources category | AF-1 |
| N-06 | `/forum/new`: start a first thread | Also pending, with the same banner | AF-5 |
| N-07 | As an admin (A-01), approve the post. Back as the new member, check Mailpit | Email "Your post “…” is now public", with the newly-trusted sentence. The next thread or post publishes immediately | AF-1 |
| N-08 | Account → Sessions: sign in from a second browser, then revoke it from the first | The revoked session is signed out on its next request | AF-9 |
| N-09 | Keep this account for T-14 (account deletion) | — | — |

### 3.3 Trusted member (Giulia; Ivana as the second author)

| Id | Steps | Expected | AF |
|---|---|---|---|
| T-01 | `/blog/new`: headings, bold/italic, lists, a link, an inline image (alt text required; try saving without it), a cover image, two tags (one new), a KNOWBASE link via the picker (measure and document tabs), locale, an Events date and URL | Publishes immediately. The editor toolbar buttons have names and announce pressed state. The image is re-encoded to WebP (check the `/static/uploads/...webp` URL). The KNOWBASE card shows the live title. The post appears in Events upcoming | AF-2, AF-4, AF-7, M-4 |
| T-02 | Edit the title and body, add or remove a tag, leave without saving | The unsaved-changes guard asks first. The saved edit shows. The slug stays reachable [CHECK] | AF-4 |
| T-03 | Delete the post | Gone from the lists and from the author's view. An admin still sees it as deleted | AF-4 |
| T-04 | `/forum/new`: a thread with a list and a tag; reply to Ivana's thread; reply to a reply; try to reply to the nested reply | Thread published. Nesting stops at one level: the deeper reply attaches to the parent, or no button is offered [CHECK]. Counters update | AF-5 |
| T-05 | Edit and delete your own reply | The deleted reply's children stay with a placeholder | AF-5 |
| T-06 | Comment on Ivana's post; edit; delete | Works. Ivana (Mailpit) receives "… commented on your post" with a link and an opt-out link to `/account?tab=notifications` | AF-5 |
| T-07 | Report Ivana's comment (reason, details). Try to report your own content. Report the same item twice | The report is accepted with a toast. Own content: no button or refused. A second report is refused with a translated message | AF-10 |
| T-08 | Account → Notifications: turn "reply to my thread" off; have Ivana reply to your thread | No email. Turn it on again: the next reply emails you. The "moderation decisions" switch is present | AF-5 |
| T-09 | Account → Data → Export | A JSON download (`format_version` 2) with your profile, expertise, preferences, posts/threads/replies/comments (all statuses), attachments as URLs, reports you made, sessions and audit rows. No password hashes, no tokens, no admin ids | AF-9 |
| T-10 | Account → Uploads | Lists your images with "used in". You cannot delete an image that a post uses (error message). An unused image can be deleted | AF-9 |
| T-11 | Upload rejection (in the editor image dialog): a 6 MB JPEG, a PDF renamed `.jpg`, an animated GIF/WebP, a huge-pixel PNG | Translated errors for `uploads.too_large`, `uploads.invalid_image` / `uploads.unsupported_type`, `uploads.animated` and `uploads.too_large_pixels`. A phone JPEG (MPO) is accepted | AF-9 |
| T-12 | `/network`: filter by expertise, country, organisation; open Giulia's own card and Ivana's profile `/u/<id>` | Filters work. Giulia's email shows (she opted in). Admin badges appear on admin profiles and cards. Profiles list published contributions with counts and links to author-filtered blog/forum lists | AF-6, M-3 |
| T-13 | Header user menu → Log out | Signed out. The `uf_session` cookie is gone | AF-1 |
| T-14 | **Throwaway account only** (the N-01 account): Account → Data → Delete account. First try a wrong password, then the right one | Wrong password: refused. Right one: signed out. Its content now shows "Deleted user". Logging in with the old address fails. The avatar and unused uploads are removed. Mailpit receives no further mail for it | AF-9 |

### 3.4 Admin (Matej; Eleni where a superadmin is needed)

| Id | Steps | Expected | AF |
|---|---|---|---|
| A-01 | `/admin/queue` | Amra's seeded pending post plus anything from N-05/N-06, oldest first. **Approve** one: it is published, the author becomes trusted and gets the "now public" email. **Reject** another with a reason: the author sees the "not approved" banner and gets an email naming `louta@uowm.gr`, without the reason | AF-10 |
| A-02 | `/admin/reports`: filter open; resolve one, dismiss one; content row menu: hide / unhide / delete / **Restore** | Resolve and dismiss leave the content's status unchanged. Unhide dismisses the open reports. Restore brings deleted content back (to pending if it was never approved). Each action appears in `/admin/log` | AF-10 |
| A-03 | Auto-hide: have three distinct members (Giulia, Ivana, Petra) report one published reply | After the third report the reply is hidden (`auto_reports`). The log shows `moderation.auto_hidden` with no actor. Unhide restores it | AF-10 |
| A-04 | On a post page and a thread page, use the **Moderate** menu: hide with a reason, unhide, delete, restore, then **Delete permanently** (type DELETE) | Each works from the page. Purge removes the item, its comments/replies and the images only it used. Its reports are resolved. The audit row holds counts only | AF-9, AF-10 |
| A-05 | Pin, lock, unlock and unpin a thread | Locked: the reply form is gone and API replies get 423. Pinned: listed first | AF-5 |
| A-06 | Edit another member's post (admin edit) | Saved; audited | AF-10 |
| A-07 | `/admin/users`: search; **Trust / Remove trust** on Petra; **Ban** Petra, try to log in as Petra, then **Unban**; **Resend verification** for Dimitris | Remove trust: her next post is pending. Ban: her sessions are revoked and login shows "This account has been disabled…". Unban keeps role and trust. A new verification email arrives in Mailpit for Dimitris | AF-10 |
| A-08 | As Matej, open a superadmin's row (Eleni) | No "Make superadmin", no demote or ban of a superadmin. Matej cannot change his own role or ban himself | AF-10 |
| A-09 | `/admin/categories`: create a blog category, edit it, mark it admin only, archive and unarchive | Archive hides it from lists but its posts stay reachable. Public lists may need a reload (per-session cache) | AF-4 |
| A-10 | `/admin/tags`: merge a duplicate tag into another; delete a tag | Content moves to the target tag; deleted tags vanish from content | AF-4 |
| A-11 | `/admin` dashboard | User, content, pending and report counts match what you did. The KNOWBASE state (Reachable, last success, cache sizes). **Clear KNOWBASE cache** shows a count | AF-3, AF-10 |
| A-12 | Dashboard: download the CSV for a date range | `urbanfloods-cooperation-stats-<from>-<to>.csv` with five sections: `users_by_country`, `users_by_organisation`, `content`, `active_users`, `rco87`. Free-text organisations appear as their own `rco87` rows once they have published content (e.g. after Amra is approved). Audited `admin.stats_export` | AF-6, M-8 |
| A-13 | Digest: `docker compose exec backend python -m app.cli digest --force` | Prints `recipients=N items=M`. Mailpit: "[URBANFLOODS Cooperation] Moderation digest: … pending, … reports" to the admins whose digest switch is on, with links to `/admin/queue` and `/admin/reports`. Without `--force` and nothing pending: no email | AF-10 |
| A-14 | `docker compose exec backend python -m app.cli maintenance` | Prints `step=count` per step, exit 0 | AF-10 |
| A-15 | `/admin/log`: chips `moderation.`, `admin.`, `report.`, `auth.`; filter by actor and target type | Every action from A-01–A-14 is present with its actor (empty for system and CLI actions). Reasons are visible only here | AF-10 |
| A-16 | Organisations via the API: the handbook says to use `POST/PATCH /api/v1/organisations/` from `/docs` while signed in | Swagger requests carrying the session cookie but no `X-Requested-With` header should get 403 `security.csrf`. Confirm and record; the handbook may need another method (curl with the header) [CHECK] | AF-10 |

### 3.5 Superadmin (Eleni)

Run S-01 **before** anyone else is promoted to superadmin, so Eleni is still the only one.

| Id | Steps | Expected | AF |
|---|---|---|---|
| S-01 | Account → Data → Delete account (correct password) | Refused with "This is the last active superadmin…" (409 `admin.last_superadmin`). Nothing changes | AF-10 |
| S-02 | `/admin/users`: Aleksandar (admin) → **Make superadmin** | Done; audited `admin.promote` | AF-10 |
| S-03 | As Matej, try to ban or demote Aleksandar | Not offered, or refused | AF-10 |
| S-04 | As Eleni, try to change her own role | Refused (`admin.cannot_change_own_role`) or not offered | AF-10 |
| S-05 | Eleni → Aleksandar **Demote to admin**; then Aleksandar → member and back to admin | One step at a time; audited `admin.demote` | AF-10 |
| S-06 | CLI: `docker compose exec backend python -m app.cli promote --email petra.vidmar@urbanfloods.example --to admin`, then demote her in the UI | Promotion works from the CLI (it never demotes); the audit row has no actor | AF-10 |

### 3.6 Edge states

| Id | Account | Steps | Expected | AF |
|---|---|---|---|---|
| E-01 | Dimitris (unverified) | Log in; try to post, comment, report; open `/network`; use the banner's resend | Login works, and an unverified banner shows with resend (3 per hour). Actions are refused with a translated "verify your email" message. `/network` shows the verify notice | AF-1 |
| E-02 | Sara (banned) | Log in | "This account has been disabled…". Her post, reply and comment stay visible, attributed to her | AF-10 |
| E-03 | Deleted user | Open "Level sensors in a combined sewer network: lessons from the first season" | Author shown as "Deleted user", with no profile link and no initials leak. Login with `kostas.nikolaidis@…` fails | AF-9 |
| E-04 | Nikola (directory-hidden), viewed by Giulia | Search `/network` for Nikola; open his content's author link | He is absent from the directory. His content stays attributed. His profile page is not found or not listed for others [CHECK] | AF-9 |
| E-05 | Amra / Dimitris (free-text organisation) | View Amra's profile and card | "City of Zenica" shown as the organisation, with no partner flag | AF-6 |
| E-06 | Petra (minimal) | View her profile and card | No empty headings or broken layout with no organisation or expertise | AF-7 |
| E-07 | Arben (untrusted, no content) | Write a post and a thread | Both pending (as N-05). Clean up afterwards | AF-1 |

## 4. Cross-cutting checks

### 4.1 Accessibility (AF-7, M-1)

- [ ] **Keyboard only** (no mouse) on home, blog list, a post with comments, the editor, a thread
  with replies, `/register`, `/account` tabs, `/admin/queue`, `/admin/users` row menu, the report
  dialog and the purge dialog. Check: the skip link is the first Tab stop and jumps to main; focus
  is always visible; dialogs trap focus and give it back on close; Esc closes menus; the editor
  toolbar is reachable and its buttons toggle; no keyboard trap inside the editor.
- [ ] After every route change, focus is on the `h1` and the new page title is announced.
- [ ] **Screen reader spot check** (VoiceOver on macOS, NVDA on Windows if available): landmarks
  and headings list, form labels and error messages (`aria-describedby`), the toolbar's
  `aria-pressed`, search result count live region, toasts, image alt text on a post. Record the
  tool, version and date for report §7.
- [ ] **Zoom 200 %** and **text-only zoom 200 %** at 1280 px: no lost content or horizontal page
  scroll (reflow claim in the accessibility statement §4).
- [ ] `prefers-reduced-motion`: no animations.
- [ ] axe: `E2E_A11Y=1 npm run e2e -- a11y` green (section 2). Also run the axe browser extension
  on pages it does not cover: `/forum/new`, a post editor with content, `/search` with no results,
  `/terms`, `/privacy`, a KNOWBASE item page, `/u/<id>`, the 404 page, one page per non-English
  locale.
- [ ] Known open item (statement §3.1): the hover state of solid green/amber buttons (e.g. Approve)
  is about 4.1:1. Confirm it is still the only finding. Decide: fix before launch, or keep it in
  the statement.

### 4.2 Responsiveness

At **390 px, 768 px, 1280 px and 1536 px** (devtools device toolbar), check home, blog list, post,
editor, forum thread, `/network`, `/about#partnership`, `/account`, `/admin` and `/admin/users`:

- [ ] no horizontal page scroll (tables may scroll inside their own container);
- [ ] the header collapses to the burger below `xl` (1280); the compact locale switcher appears
  below `2xl` (1536); the menus are usable by touch;
- [ ] cards, footer (~160 px) and the "Project at a Glance" card do not overlap;
- [ ] the editor toolbar wraps and stays usable at 390 px.

### 4.3 All nine locales

For each of en, el, it, sl, hr, sr, mk, sq, bs, at 390 px and 1280 px:

- [ ] header, footer, home, `/register`, `/account` and the editor show no overflow or clipping
  (look hardest at the locales with long words: el, sq, mk);
- [ ] plural forms read correctly (sr/hr/bs three forms, sl four) on list counts;
- [ ] dates and times are formatted for the locale;
- [ ] missing keys fall back to English, not raw keys (search the page for `.` key patterns such
  as `post.`);
- [ ] translations flagged for partner confirmation (programme texts, lead-partner address,
  mk university name, "prijava" double meaning, sr KNOWBASE field labels) are listed for the
  partners. See the PROGRESS 2026-10-31 log.

### 4.4 Email content

Collect one of each from Mailpit (or a real inbox, section 1.3): verify_email, welcome,
reset_password, reply_to_thread, reply_to_reply, comment_on_post, content_approved,
content_rejected, admin_digest (change_email has an API but no UI [CHECK]).

- [ ] subject and sender name are correct; `From: noreply@…`, `Reply-To: urbanfloods@uowm.gr`;
- [ ] every link is absolute, points at `FRONTEND_URL` and works (token links single-use);
- [ ] HTML and plain-text parts match; the EU co-funding line and platform link are in the footer;
- [ ] notification emails carry the opt-out link to `/account?tab=notifications`;
- [ ] the rejection names `CONTACT_EMAIL` (louta@uowm.gr) and does not reveal the admin's reason
  or name; the automatic approval wording does not name an admin;
- [ ] Greek templates exist only for verify_email and reply_to_thread (`templates/email/el`); every
  other locale and template falls back to English. Accept or schedule;
- [ ] real inbox: not in spam; DKIM/SPF/DMARC pass in the message headers.

### 4.5 Security quick checks

Use curl against `http://localhost:8000`. Log in with curl first:

```bash
curl -s -c /tmp/uf.jar -H 'Content-Type: application/json' -H 'X-Requested-With: XMLHttpRequest' \
  -d '{"email":"giulia.romano@urbanfloods.example","password":"Urbanfloods-2026"}' \
  http://localhost:8000/api/v1/auth/login
```

- [ ] X-S1 **CSRF header**: `curl -s -b /tmp/uf.jar -X POST http://localhost:8000/api/v1/auth/logout`
  (cookie, no `X-Requested-With`) → 403 `security.csrf`. With `-H 'Origin: https://evil.example'
  -H 'X-Requested-With: XMLHttpRequest'` → 403 `security.csrf_origin`.
- [ ] X-S2 **Sanitisation**: `POST /api/v1/posts/` with
  `body_html` containing `<script>alert(1)</script><img src=x onerror=alert(1)><a href="javascript:alert(1)">x</a>`
  (plus `title` and `category_id` from `GET /api/v1/categories/`). The stored body has no script,
  no `onerror` and no `javascript:` href. Nothing executes on the post page. Delete the post.
- [ ] X-S3 **Rate limits** (limits on): eleven wrong-password logins in a row → the 11th is 429
  with `Retry-After` and a toast in the UI. Then `docker compose restart backend`.
- [ ] X-S4 **Session cookie**: in devtools → Application → Cookies, `uf_session` is HttpOnly and
  SameSite=Lax. Secure is off in dev (`COOKIE_SECURE=false`); it **must** be on in prod (verify after M6).
- [ ] X-S5 **Uploads**: see T-11. Also check that a served upload has `Content-Type: image/webp`
  and `X-Content-Type-Options: nosniff`, and that EXIF/GPS from a phone photo is gone (`exiftool`).
- [ ] X-S6 **Authorisation**: as Giulia, `PATCH` Ivana's post and `POST /api/v1/moderation/post/<id>/hide`
  → 403. As a visitor, `GET /api/v1/members/` → 401.
- [ ] X-S7 **No personal data leak**: exports, feeds, sitemap and public member payloads contain no
  email (except opted-in), role or IP. The backend log (`docker logs urbanfloods-cooperation-backend`)
  has no passwords, tokens or bodies. With `EMAIL_ENABLED=false` the `email.not_sent` line has a
  keyed hash, not the address (1i-b).
- [ ] X-S8 Production-only headers (HSTS, CSP allowing `challenges.cloudflare.com` and KNOWBASE
  images, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy) and Turnstile come from M6
  nginx and env. Check them after deployment with `curl -sI https://cooperation.urbanfloods.app`.

### 4.6 Performance sanity

- [ ] Home, blog list, a post and a thread load in under about 2 s on the dev stack (devtools
  Network, cache disabled). The Tiptap editor chunk loads only on editor routes. Dev Vite is not
  representative, so repeat once on a production build after M6 [CHECK].
- [ ] `/search` answers in well under a second for common terms.
- [ ] Lists use pagination and do not fetch everything (look for `skip`/`limit` in requests).
- [ ] **KNOWBASE unreachable.** Never touch the real KNOWBASE; point the dev backend somewhere
  dead instead. Add to `docker-compose.override.yml`:

  ```yaml
  services:
    backend:
      environment:
        KNOWBASE_BASE_URL: http://127.0.0.1:9      # refused at once; or http://10.255.255.1 for a 5 s timeout
  ```

  Run `docker compose up -d backend`. This also empties the cache. Then check:
  - [ ] posts with KNOWBASE links still render, using the stored link titles;
  - [ ] `/knowbase/measures/14` shows a load error with "Try again", not a blank page or a crash;
  - [ ] saving a post with a new KNOWBASE link shows "The KNOWBASE cannot be reached…";
  - [ ] the admin dashboard shows the KNOWBASE as not reachable, with the last error;
  - [ ] the rest of the site works and is not slowed. With the timeout address, only
    KNOWBASE-dependent requests wait about 5 s.
  - [ ] Stale copies (the KNOWBASE fails *after* the cache is warm) cannot be simulated this way,
    because recreating the backend clears the cache. The `X-Knowbase-Cache: stale` path is covered by
    `backend/tests/test_knowbase_proxy.py`. The admin handbook §8 says the pages show a notice
    when cached data is used, but only the admin dashboard reads the cache state in the frontend
    since the library views were removed [CHECK].

  Remove the override, then run `docker compose up -d backend` again.

## 5. Evaluation sheet

Fill in **Result** (`pass` / `fail` / `partial` / `n/a`) and **Notes** during the run. Ids:
AF = application form (Activity 5.1, D.5.1.1, Output 5.1 and the horizontal principles in
`IPA-ADRION00374_V4.0.md`). M = requirements presented at the 3rd project meeting
([requirements-3rd-project-meeting.md](requirements-3rd-project-meeting.md)) and later decisions.

| Id | Commitment (source) | Verified in | Result | Notes |
|---|---|---|---|---|
| AF-1 | Access "upon registration" (A5.1). Reading: public read, registration to participate (PLAN "Access model") | N-01–N-07, V-14, E-01, E-07 | | |
| AF-2 | Categorised information: measures, actions, policy recommendations from the KNOWBASE (A5.1) | V-04, V-05, T-01 | | Browsing by country happens on the KNOWBASE itself (decision 2026-10-31) |
| AF-3 | Built on top of the KNOWBASE, which stays untouched (D.5.1.1, PLAN) | V-05, A-11, 4.6 | | |
| AF-4 | Blog format (A5.1) | V-03, V-04, T-01–T-03, A-09, A-10 | | |
| AF-5 | Dynamic forum for interaction, learning, collaboration (A5.1) | V-07, N-06, T-04–T-08, A-05 | | |
| AF-6 | Transnational exchange among PPs and stakeholders; Output 5.1 RCO87 target 22 organisations | V-02, N-04, T-12, A-12, E-05 | | |
| AF-7 | Accessibility: screen readers, easy navigation, alt text, clear presentation, feedback (horizontal principles) | 4.1, T-01, V-10, V-15, E-06 | | |
| AF-8 | FAIR: discoverable, clear access, open formats, documentation and metadata (sustainability section) | V-10, V-12, V-13 | | |
| AF-9 | GDPR; no sensitive personal data | V-09, N-08, T-09–T-11, T-14, A-04, E-03, E-04, 4.5 | | |
| AF-10 | Durability with few admins; MoU long-term cooperation (A5.3, sustainability) | T-07, A-01–A-16, S-01–S-06, E-02 | | |
| AF-11 | Information exchange across diverse groups (multilingual) | V-06, V-11, 4.3 | | |
| AF-12 | Platform reachable from the project website | outside the platform | | link from urbanfloods.interreg-ipa-adrion.eu [CHECK] |
| AF-13 | Succinct report on development and functionality (D.5.1.1) | [report-D5.1.1-outline.md](report-D5.1.1-outline.md) | | see doc drift below |
| M-1 | WCAG 2.1 AA | 4.1 | | |
| M-2 | Link to the Unified DSS | V-01 | | link only, no API |
| M-3 | Matchmaking: expertise, directory, suggested collaborators, opt-in email | N-04, T-12 | | |
| M-4 | Events / webinars | V-03, T-01 | | |
| M-5 | JSON-LD metadata | V-13 | | |
| M-6 | Open export formats (CSV, JSON; **XML**) | V-12 | | XML bulk export not implemented (Atom + sitemap only) |
| M-7 | DOI | — | | process at project end (Zenodo deposit) [CHECK] |
| M-8 | RCO87 tracking | A-12 | | |
| M-9 | Documentation, Docker, automated backups | section 2, section 6 | | backups in M6 (6a todo) |
| M-10 | Responsive UI for browser and mobile | 4.2 | | no native app |
| M-11 | Nine project locales | V-11, 4.3 | | |
| M-12 | Search | V-08 | | posts and threads; not members or KNOWBASE |

### 5.1 Known limitations (PROGRESS §4, PLAN M5x "Deferred by decision", session log)

Mark each **accepted** (goes into report §11 as a known limitation) or **to decide** (needs a
decision or an increment before launch).

| Limitation | Accepted / to decide | Notes |
|---|---|---|
| No admin page for organisations (API only); no admin way to add expertise tags | | |
| XML bulk export (3rd meeting) not implemented | | |
| Admin digest "send now" only via CLI (no `/admin/digest/send-now`) | | |
| `ENABLE_DOCS` in production (the open-data page assumes the OpenAPI file is served) | | |
| Data package keywords say "urban flooding" (wording rule: "flood management") | | |
| PLAN.md env-var list and some routes differ from the code (see docs/api.md) | | |
| Restore from the UI: listed as missing in PROGRESS §4, but added by 5h (Moderate menu, admin reports). Verify in A-02/A-04 and close | | |
| Resubmit after rejection; reason shown to the author; ban notice | | |
| Re-reporting after dismissal; `report_count` not recounted when a reporter is anonymised | | |
| Stricter superadmin self-deletion; cooling-off period for deletion | | |
| Admin anonymisation of another account (do after launch) | | |
| Pagination labels in other locales | | |
| Auto-approve age measured from `created_at` (a restored, never-approved item is approved at once) | | |
| Orphan-upload and usage detection by substring scan (fine at current scale) | | |
| Public categories list cached per browser session | | |
| Home suggested-collaborator cards lack the admin badge | | |
| Change email has an API but no UI | | |
| Hover contrast of solid success/warning buttons ~4.1:1 | | |
| Greek email templates only for two messages; others English | | |
| Single backend worker (in-memory rate limits, cache, scheduler) | | |
| Brevo free plan 300 emails/day | | |
| Translations to confirm with partners (see 4.3) | | |
| `AUTO_APPROVE_AFTER_DAYS` value to agree with the partnership | | |
| Alternative registration route besides Turnstile (accessibility statement §3.2) | | |

### 5.2 Documentation drift found while writing this checklist

Fix these as one docs increment before the report is written:

- [ ] `docs/moderation-guide.md` §2–§3: says authors are not emailed (5i emails them) and that
  restore has no button (5h added it, plus purge).
- [ ] `docs/admin-handbook.md` §13: says the export's content lists are empty (fixed in 1i-b);
  §6 mentions `/partners` (now `/about#partnership`); §8 promises a stale-data notice on KNOWBASE
  pages (see 4.6); §6 "use `/docs`" for organisations (see A-16).
- [ ] `docs/report-D5.1.1-outline.md` §3: rows cite `/knowbase`, `/knowbase/measures`,
  `/knowbase/documents` (removed 2026-10-31) and `/partners`; counts "1459 backend, Playwright 32";
  §11 says the export lacks the member's content (fixed); §8 names Google for email (now Brevo).
- [ ] `docs/testing.md`: 1459 collected (now 1613); e2e table (moderation 8, a11y 4); the 4h
  `[CHECK]`.

## 6. Go / no-go for deployment

Every item must be **green** or **explicitly decided** by the owner. M6 steps on the server happen
only with explicit permission for each step. The KNOWBASE is never touched.

**Software**

- [ ] Section 2 all green on the commit to deploy; CI green.
- [ ] Section 3–4: no open `fail` that blocks registration, posting, moderation, GDPR rights or
  accessibility; every other fail is ticketed or accepted.
- [ ] Section 5: every AF row `pass` or `partial` with a note; every limitation marked.
- [ ] Documentation drift (5.2) fixed.

**Legal and content**

- [ ] `[CHECK]` items in `docs/legal/` resolved or accepted by UOWM: terms-of-use (4), privacy-policy
  (10), accessibility-statement (8), open-data (4). Topics: age threshold, KNOWBASE data licence,
  jurisdiction, DPO naming, audit-log retention, hosting description, processor DPAs (Brevo,
  Cloudflare), response period, enforcement body, Turnstile alternative.
- [ ] No `[CHECK` or reviewer note visible on `/terms`, `/privacy`, `/accessibility`, `/open-data` (V-10).
- [ ] Accessibility statement updated with the manual audit results (tool, date, findings).
- [ ] Contact `louta@uowm.gr` and reply-to `urbanfloods@uowm.gr` confirmed.
- [ ] Partner translations confirmed, or English fallback accepted.

**Production configuration (6a, files only until permitted)**

- [ ] `docker-compose.prod.yml`: frontend `127.0.0.1:3002`, backend `127.0.0.1:8002`, **no Postgres
  port**, volumes for the database and uploads, healthchecks on `127.0.0.1`, one backend worker.
- [ ] `.env.prod` (chmod 600, never committed): `ENV=prod`, strong `SECRET_KEY`, `DATABASE_URL` /
  `POSTGRES_PASSWORD`, `ALLOWED_ORIGINS=https://cooperation.urbanfloods.app`,
  `FRONTEND_URL=https://cooperation.urbanfloods.app`, `COOKIE_SECURE=true`, `EMAIL_ENABLED=true`,
  `SMTP_HOST=smtp-relay.brevo.com`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASSWORD` = new Brevo key
  **`cooperation-platform-prod`**, `SMTP_FROM=noreply@cooperation.urbanfloods.app`, `SMTP_REPLY_TO`,
  `CONTACT_EMAIL`, `TURNSTILE_ENABLED=true` + `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` (+ build var
  `VITE_TURNSTILE_SITE_KEY`), `TRUST_PROXY_HEADERS=true`, `ENABLE_SCHEDULER=true` (single worker),
  `ENABLE_DOCS` (decided), `LOG_JSON=true`, `AUTO_APPROVE_AFTER_DAYS` (agreed), `REPORT_AUTO_HIDE_THRESHOLD`,
  `VITE_API_BASE_URL=""`, `VITE_DSS_URL`.
- [ ] Turnstile site created for `cooperation.urbanfloods.app` in Cloudflare.
- [ ] Brevo: domain still authenticated (DKIM, DMARC), prod key created, dev key not reused.
- [ ] `scripts/backup.sh`: pg_dump + uploads archive, 14-day retention, user crontab, **one test
  restore done**.
- [ ] `deploy.sh` reviewed; migrations run in the backend entrypoint.

**Host (6b; the owner runs the sudo steps)**

- [ ] `docker/nginx-host-config.template`: routes `/api/`, `/static/`, `/feeds/`, `/sitemap.xml` and
  `/robots.txt` to the backend; security headers and CSP (`challenges.cloudflare.com`, KNOWBASE
  images); `client_max_body_size 6m`. `frontend/public/robots.txt` removed so the backend's is served.
- [ ] `docs/deployment.md` written, with the owner's steps: nginx site symlink,
  `certbot --nginx -d cooperation.urbanfloods.app` (the Cloudflare record may need DNS-only
  briefly), `nginx -t && systemctl reload nginx`.
- [ ] Before and after: KNOWBASE containers `urbanfloods-knowbase-*-prod` show unchanged uptime
  (read-only `docker ps` over `ssh knowbase`).

**After first start (with permission)**

- [ ] First superadmin via `python -m app.cli create-superadmin`; a second superadmin and admins
  from several partners named (sustainability, report §10).
- [ ] The dev seed is **not** run (it refuses unless `ENV` is dev/test).
- [ ] Smoke test on production: register with a real inbox → verify → first post pending →
  approve → email; X-S4 Secure cookie; X-S8 headers; Turnstile renders; `/feeds/posts.atom`,
  `/sitemap.xml`, `/robots.txt` served by the backend; `curl -sI https://cooperation.urbanfloods.app`
  returns 200.

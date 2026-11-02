# Ultra review triage — 2026-11-02

Three cloud ultra reviews (`/code-review ultra`) were run on `main` at `cfc451d`. The whole repo
was too large for one review, so each area got its own pair of local branches: `review/<area>-base`
is `main` without the area's files, and `review/<area>` is identical to `main`.

| Area | Scope | Findings |
|---|---|---|
| auth | 27 files, +5,018 | 10 |
| moderation | 13 files, +4,044 | 10 |
| content-safety | 14 files, +2,787 | 10 |

Every finding was checked against the code and `docs/review-notes.md`. All three free runs are now
used, so any further ultra review bills usage credits.

Status key: **open** = confirmed, not fixed yet. Update the status column as increments land.

## Fix first

| # | Finding | Code | Verdict | Planned fix | Inc. | Status |
|---|---|---|---|---|---|---|
| 1 | `docker image prune -f` runs across the whole host on every deploy, so it also deletes the KNOWBASE's dangling images (for example a previous image kept for a manual rollback). Running containers are not affected. This breaks the "never touch the KNOWBASE" rule. | `deploy.sh:117` | confirmed | Prune only this compose project's images (`--filter label=com.docker.compose.project=<project>`), or drop the step | 7h | fixed, deployed 2026-11-02 |
| 2a | `auto_approve_stale` publishes pending items of **banned** (`is_active=False`) or **erased** (`deleted_at` set) authors. `_trust_author` skips trusting them but `_approve` still publishes. Production runs `AUTO_APPROVE_AFTER_DAYS=5`. | `crud/moderation.py:983-996` | confirmed | Join `User` in the stale select and require `is_active` and `deleted_at IS NULL` | 7i | fixed (7i), deployed 2026-11-02 |
| 2b | Staleness is measured from `created_at`, and `resubmit` resets nothing, so a rejected item is auto-approved on the next sweep after the author resubmits it. The author then becomes trusted without any admin seeing the edit. | `crud/moderation.py:963-967`, `resubmit` ~485 | confirmed | New nullable `rejected_at` on posts and threads (migration 0011, backfilled from `moderation.reject` audit rows), set by `reject()`. Auto-approve skips items with `rejected_at`; resubmitted items always need an admin | 7i | fixed (7i), deployed 2026-11-02 |
| 2c | The queue's `resubmitted` flag is `moderation_note is not None`, but a reject without a reason stores `None`. | `endpoints/moderation.py:148` | confirmed | Derive the flag from `rejected_at` (same column as 2b) | 7i | fixed (7i), deployed 2026-11-02 |
| 2d | The sweep reads rows without `FOR UPDATE` and approves using the stale status in memory. A concurrent admin reject, hide or delete is overwritten: the item is published and its author trusted. | `crud/moderation.py:983-988` | confirmed (rare) | Load each item with `get_content(..., for_update=True)` and re-check `status == pending` before approving | 7i | fixed (7i), deployed 2026-11-02 |
| 3 | `restore` always goes to `published` (or `pending`). An author can delete their own **hidden** post (`get_editable_post` allows it), and a later admin restore republishes the taken-down content and dismisses its reports. `delete()` keeps `hidden_reason`, so the earlier state is still known. | `crud/moderation.py:466-482`, `_target` ~202 | confirmed | Restore to `hidden` with its reason kept when `hidden_reason` is set; add `restore: {_D: _H}` handling; show "was hidden" on `/admin/deleted`. Also covers the 7i review note: a rejected item deleted and restored would otherwise come back pending and flagged "resubmitted" (`rejected_at` kept); it returns to `hidden(rejected)` instead | 7j | fixed (7j), deployed 2026-11-02 |
| 4a | VERIFY_EMAIL tokens (48 h) sign the holder in (`verify_email` always creates a session, even for an already-verified account), and they survive a password reset or change, which invalidate only CHANGE_EMAIL tokens. | `endpoints/auth.py:211-235, 508-510, 554-556` | confirmed | Invalidate VERIFY_EMAIL tokens in `reset_password` and `change_password`; `verify_email` does not create a session for an account that is already verified | 7k | fixed (7k), deployed 2026-11-02 |
| 4b | `verify_email` and `reset_password` set a new session cookie without revoking the session the browser already holds (`login` does revoke it). This leaves orphan "other device" sessions. | `endpoints/auth.py:232, 515` | confirmed | Revoke `request.state.session` first, as `login` does | 7k | fixed (7k), deployed 2026-11-02 |
| 5 | `DELETE /auth/me` checks the current password but has no `ROUTE_LIMITS` entry, so it only gets `api.default` 300/min. `/me/password` allows 10/h. | `core/rate_limit.py:64-79` | confirmed | Add `("DELETE", f"{_AUTH}/me")`, no looser than `auth.me_password` | 7k | fixed (7k), deployed 2026-11-02 |
| 6 | Sliding session expiry never reaches the browser. `touch_session` extends `expires_at`, but the cookie keeps `Max-Age` from login, so every member is signed out 30 days after logging in, however active. The docs promise a "30-day sliding expiry". | `core/deps.py:99`, `crud/session.py:80-94` | confirmed | When `touch_session` moves `expires_at`, re-set the cookie with the new Max-Age (middleware reading `request.state`) | 7l | fixed (7l), deployed 2026-11-02 |
| 7a | `fetchMe` treats every failure (502 during deploy, network error, 429) as signed out, and the guard only re-fetches while the status is `unknown`. | `frontend/src/stores/auth.ts:53-56`, `router/index.ts:331` | confirmed | Clear only on 401; on other errors keep `unknown` so the next navigation retries | 7l | fixed (7l), deployed 2026-11-02 |
| 7b | The 401 exemption matches the path only, so `PATCH /auth/me` (profile save) and `DELETE /auth/me` returning 401 never clear the store. | `frontend/src/services/api.ts:73-89` | confirmed | Exempt only `GET /auth/me` and `POST /auth/login` (check the method too) | 7l | fixed (7l), deployed 2026-11-02 |
| 8 | Replacing an avatar soft-deletes the old attachment and deletes its files without the `is_used_in_content` check that `delete_upload` makes. An avatar can be a post cover (`_check_cover` accepts any of the author's live attachments) or inline in a body. | `endpoints/uploads.py:134-150` | confirmed | Check `is_used_in_content`; if in use, unlink the avatar only and keep the row and files | 7m | fixed (7m) |
| 9 | No limit on images decoded at once. Up to 40 MP each and about 2 full copies per request (~320 MB). 30 parallel uploads of small near-40 MP PNGs ≈ 10 GB on the server we share with the KNOWBASE. | `services/images.py:127-131`, `endpoints/uploads.py` | plausible (confirmed mechanism) | Process-wide `anyio.CapacityLimiter(1–2)` around `process_image`; `exif_transpose(in_place=True)`, skip `convert` when the mode already matches, thumbnail in place | 7m | fixed (7m) |

## Smaller issues

| # | Finding | Code | Verdict | Planned fix | Inc. | Status |
|---|---|---|---|---|---|---|
| 10 | `list_pending` indexes `loaded[(type, id)]` with no membership check. A purge between the page read and the row load gives KeyError → 500 on the queue and in the admin digest. `list_deleted` already guards this. | `crud/moderation.py:160-176` | confirmed (rare) | Skip page rows missing from `loaded` | 7j | fixed (7j), deployed 2026-11-02 |
| 11 | `_dismiss_open_reports` (used by unhide and restore) closes reports in bulk with no `report.dismiss` audit rows (CLAUDE.md: every status change is audited). | `crud/moderation.py:251-269` | confirmed | `RETURNING` the ids and log one row per report, as the sibling helpers do | 7j | fixed (7j), deployed 2026-11-02 |
| 12 | `create_report` checks only that the reply or comment is published, not that its thread or post is visible, so members can report (and probe for) children of hidden or deleted parents, and push them to auto-hide. Also `get_editable_comment` skips the parent-post check that `get_editable_reply` makes. | `crud/reports.py:81-85`, `crud/comment.py:148` | confirmed | Require `is_visible(parent, user)` in both | 7j | fixed (7j), deployed 2026-11-02 |
| 13 | Unbounded `int` path and query ids reach INTEGER columns; a value above 2³¹−1 → asyncpg DataError → 500. Wider than reported: also `admin.py`, `categories.py`, `organisations.py`, `members.py`, `tags.py`, `expertise.py`, `uploads.py`, `reports.py`. A NUL (`\x00`) in text input → 500 too. | `endpoints/threads.py:66,167,193,239-263`, `posts.py:56,136,163`, others | confirmed | One shared `DbId` Path/Query alias used everywhere; a NUL is rejected with 422 (validator or a handler for `CharacterNotInRepertoireError`) | 7n | open |
| 14 | Export `If-None-Match` is compared exactly, but nginx (`gzip_proxied any`) turns the strong ETag into `W/"…"`, so production never answers 304. | `endpoints/export.py:94-98`, `frontend/nginx.conf:30-34` | confirmed | Weak comparison: strip `W/` before comparing | 7n | open |
| 15 | The export ETag hashes only count and max(`updated_at`) of content, so author renames, account erasure and category or tag renames don't change it. An erased member's name stays in revalidated copies. | `crud/export.py:184-208` | confirmed | Include max(`updated_at`) of users, organisations, categories and tags (and links) in the validator | 7n | open |
| 16 | The CSP `img-src` allows only self, data:, blob: and the KNOWBASE, but both sanitisers keep `<img>` with any http(s) src. External images are stored but blocked in production. | `frontend/nginx.conf:44`, `services/sanitize.py:65-69`, frontend `IMAGE_SRC` | confirmed | **Decided by the owner 2026-11-02:** both sanitisers (backend `_is_allowed_img_src`, frontend `IMAGE_SRC`) keep only `/static/uploads/` and `https://knowbase.urbanfloods.app` images; the CSP stays as it is (no third-party requests from readers' browsers). Check existing production content for external `<img>` before shipping (read-only query) and say in the editor why a pasted external image disappears. Add to review-notes "Deliberate decisions" when shipped | 7n | open, decided |
| 17 | Upload usage detection is `strpos(body_html, storage_path)` over every member's content in any status. A plain-text mention by **another** member blocks the uploader's delete (409) and keeps an erased member's avatar on disk and public. | `crud/attachment.py:118-129` | confirmed (substring scan itself is in review-notes as known; the cross-member and GDPR effect is new) | Count only real embeds (`src="…/static/uploads/<path>"`) and covers; erasure removes the avatar unless it is a cover or embedded by its owner | 7m | fixed (7m) |
| 18 | The daily upload cap is check-then-act: parallel uploads all see the same count and all pass. | `endpoints/uploads.py:173-190` | confirmed | `pg_advisory_xact_lock(user_id)` before the count, re-check before insert | 7m | fixed (7m) |
| 19 | Login brute force is limited per exact client IP only: no per-account counter, and IPv6 is keyed at /128, so a /64 gives unlimited fresh buckets (and evicts other clients from the 50k LRU). | `core/rate_limit.py:152-155` | confirmed | Add a per-account limit (normalised email) for login and current-password checks; collapse IPv6 to /64 in every key | 7k | fixed (7k), deployed 2026-11-02 |

## Cleanups (low priority)

| # | Finding | Code | Plan | Status |
|---|---|---|---|---|
| 20 | Hand-written auth API types (`UserMe`, `RegisterPayload`, …) with a TODO, against the CLAUDE.md rule; already drifted (`avatar_url` missing). | `frontend/src/services/auth.ts:7-92` | Alias to `components['schemas'][...]` | open |
| 21 | Turnstile wiring copied into 4 forms. | `RegisterForm.vue`, `RegisterSuccess.vue`, `ResendVerificationForm.vue`, `ForgotPasswordView.vue` | `useTurnstileGate()` composable, together with the known "script blocked" message follow-up | open |
| 22 | `_error_responses` copied into 17 endpoint modules. | `backend/app/api/v1/endpoints/*.py` | Move to `core/exceptions.py` | open |
| 23 | `backup.sh` takes values after `=` literally; quoted values, CR or inline comments in `.env.prod` would break pg_dump (and deploy step 3). Our file has none today. | `scripts/backup.sh:43-49` | Strip quotes, whitespace and CR, or read from the container | open |

## Not new or deferred

- **Turnstile script blocked → submit disabled without a message** (auth review): already in
  `docs/review-notes.md` "Already known". Fix together with #21.
- **Unbounded children per reply** (`crud/reply.py:115-123`): a public thread page loads every
  child of the top-level replies on the page. Not a problem at current scale. Add to review-notes
  as a known limitation; revisit if a thread grows large.

## Proposed increments

One increment per commit, tests first, each updating `PROGRESS.md`:

| Inc. | Content | Findings |
|---|---|---|
| 7h | Limit the image prune in `deploy.sh` to this project | 1 |
| 7i | Auto-approve gates: inactive or erased authors, `rejected_at` (migration 0011), row lock; resubmitted flag | 2a–2d |
| 7j | Restore keeps hidden; queue KeyError; report-dismiss audit; parent visibility for reports and comment edits | 3, 10–12 |
| 7k | Email tokens and sessions; `DELETE /auth/me` limit; per-account login limit and IPv6 /64 | 4a, 4b, 5, 19 |
| 7l | Session cookie refresh; frontend `fetchMe` and 401 handling | 6, 7a, 7b |
| 7m | Uploads: avatar replace check, decode limiter, real-embed usage, atomic daily cap | 8, 9, 17, 18 |
| 7n | Bounded ids and NUL; export ETag (weak compare, validator); sanitisers keep only uploads and KNOWBASE images (decided) | 13–16 |
| later | Cleanups | 20–23 |

When an increment changes a deliberate decision or known limitation, update
`docs/review-notes.md` in the same commit.

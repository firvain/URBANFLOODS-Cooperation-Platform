# Moderation guide

This guide is for platform admins. It explains in plain language how new members earn the right
to publish, what appears in the moderation queue, what each moderation action does, how reports
and automatic hiding work, what the daily digest contains, and how to handle spam, abuse and
personal-data complaints. It ends with a short checklist. Account management is covered in the
[admin handbook](admin-handbook.md); the technical state machine is in
[architecture.md](architecture.md#31-content-state-machine).

Last updated: 2026-10-31

## 1. The trust model

- Anyone can read published content without an account.
- To write, a person registers and confirms their email address ("verified member").
- A verified member's **blog posts and forum threads** wait for review until one of them has been
  approved by an admin. The first approval marks the member **trusted**; after that their posts
  and threads are published immediately.
- **Replies and comments** by verified members are always published immediately. They are
  handled through reports.
- Admins and superadmins always publish immediately.
- Trust is not removed automatically. If a trusted member misbehaves, use *Remove trust* on the
  Users page (their next post or thread goes back to the queue) or ban the account.

## 2. The queue (`/admin/queue`)

The queue lists every post and thread in status `pending`, oldest first, with type, title,
author and category. An item is pending when:

- it was written by a member who is not (or no longer) trusted; or
- a deleted item that had never been approved was restored (it returns to pending).

Each row has **Approve** and **Reject**. The author sees their pending item with a banner
explaining that it awaits review; nobody else sees it. Authors are not emailed about the
decision. [CHECK: whether an approval/rejection email is wanted]

## 3. Moderation actions

All actions are available through the API (`POST /api/v1/moderation/{type}/{id}/<action>`, see
[api.md](api.md#reports-and-moderation)). In the interface, approve/reject are on the queue page;
hide, unhide and delete are in the row menu of the Reports page; admins can also edit or delete
any post or thread, and pin or lock threads, from its own page. Every action writes an audit row.

| Action | From → to | Effect on the author's trust | Effect on reports |
|---|---|---|---|
| **Approve** | pending → published | author becomes trusted (unless the account is banned or deleted) | none |
| **Reject** | pending → hidden (`rejected`) | author stays untrusted | none |
| **Hide** | published → hidden (`admin`) | unchanged | open reports stay open |
| **Unhide** | hidden → published | if the item was *rejected*, this counts as an approval: author becomes trusted | all open reports on the item are dismissed; report count reset to 0 |
| **Delete** | pending / published / hidden → deleted (soft) | unchanged | open reports stay open |
| **Restore** | deleted → published, or → pending if it was never approved | unchanged | when restored to published: open reports dismissed, count reset |

Notes:

- Reject and hide accept an optional reason (up to 500 characters). It is stored **only in the
  audit log**; the author sees a generic "rejected" or "hidden" banner with the contact address.
- Approve and reject apply to posts and threads only; replies and comments have no pending state.
- Delete is always soft: the row stays in the database with status `deleted` and can be restored.
- **Restore has no button in the interface.** Use `POST /api/v1/moderation/{type}/{id}/restore`
  from the API docs (`/docs`) while signed in as an admin. The Reports page text says deleted
  content "can be restored from the database only", which is outdated. [CHECK]
- An action from a status where it does not apply (for example approving published content)
  answers "invalid transition" and changes nothing.

## 4. Reports and automatic hiding

1. Any verified member can report a **published** post, thread, reply or comment, choosing a
   reason (spam, abuse, off topic, misinformation, other) and optionally adding details (up to
   1000 characters). One report per member per item; members cannot report their own content;
   at most 20 reports per day per network address.
2. The item's *report count* is the number of distinct members with an **open** report on it.
3. When the count reaches `REPORT_AUTO_HIDE_THRESHOLD` (default **3**; `0` turns automatic hiding
   off) the item is hidden with reason `auto_reports`. The audit log shows
   `moderation.auto_hidden` with no actor.
4. Admins review reports at `/admin/reports` (filter by status and content type):
   - **Resolve**: you acted on the report (for example you hid or deleted the content).
   - **Dismiss**: the report was unfounded.
   Both only close the report and recount; **neither changes the content's status**.
5. For an automatically hidden item:
   - reports unfounded → **Unhide** (dismisses every open report on it at once);
   - reports founded → leave it hidden or **Delete** it, then **Resolve** the reports.

## 5. The admin digest

When the scheduler is enabled (`ENABLE_SCHEDULER=true`), every day at `DIGEST_HOUR_UTC`:00 UTC
(06:00 by default) the platform emails every active, verified admin and superadmin whose
*Admin digest* switch is on (Account → Notifications; on by default, frequency daily).

The digest contains:

- the number of pending posts and threads, with up to 50 listed (title, author, date);
- the number of open reports, with the 10 newest listed;
- new members and newly published content since the previous digest (24 hours for the first run);
- links to `/admin/queue`, `/admin/reports` and the notification settings.

Rules:

- If nothing is pending and no report is open, no email is sent (the run is still recorded).
- Admins who chose *weekly* receive it on Mondays only, covering the last 7 days.
- If every email fails, the run is not recorded and the same window is retried the next day.
- To send it now: `python -m app.cli digest` (add `--force` to send even when there is nothing to
  review). See [admin-handbook.md](admin-handbook.md#11-command-line-tools).

## 6. Handling common cases

### Spam

1. Delete the spam items (Reports page or the item's own page).
2. Ban the account on the Users page: it is signed out everywhere and cannot sign in again.
3. Resolve the related reports.
4. If spam comes from many new accounts, check that Turnstile is enabled in production
   (`TURNSTILE_ENABLED=true`) and consider lowering `REPORT_AUTO_HIDE_THRESHOLD`.

### Abuse, harassment, misinformation

1. Hide the item (give a reason; it stays in the audit log).
2. If the author is trusted and this is not a one-off, remove trust; for serious or repeated
   cases, ban.
3. Resolve the reports. If the decision is disputed, contact the author from the address on the
   Users page.

### Personal data complaints

A person asks for their personal data (name, photo, contact details) to be removed from someone
else's post, or a member asks for their own data.

1. **Hide the item at once** so it is no longer public.
2. Ask the author to edit it, or edit it yourself (admins may edit any post, thread, reply or
   comment through the normal edit form).
3. If the content cannot be fixed, delete it.
4. Record what was done (the hide/delete reason is audited) and forward the request to the data
   controller contact, **louta@uowm.gr** (University of Western Macedonia), who answers the
   requester.
5. Soft delete keeps the text in the database. Where full erasure of a third party's data is
   required, the row must be edited or cleared directly in the database by the operator; there is
   no hard-delete function in the platform. [CHECK]

Requests about a member's own account (access, deletion) are self-service; see
[admin-handbook.md](admin-handbook.md#13-gdpr-requests).

## 7. Using the audit log (`/admin/log`)

Every status change, role or trust change, ban, report action, sign-in, consent, data export and
account deletion writes a row: when, action, actor (empty for system actions), target, details.

- Filter by action: an exact name (`moderation.approve`) or a prefix ending in a dot; quick chips
  for `moderation.`, `admin.`, `report.` and `auth.`.
- Filter by actor id and target type (`post`, `thread`, `reply`, `comment`, `user`, `report`, …).
- Useful actions: `moderation.approve|reject|hide|unhide|delete|restore`,
  `moderation.auto_hidden`, `moderation.auto_approved`, `user.trusted`, `admin.promote`,
  `admin.demote`, `admin.ban`, `admin.unban`, `admin.trust`, `admin.untrust`,
  `report.create|resolve|dismiss`, `post.created|updated|deleted` (and the same for threads,
  replies, comments), `auth.login`, `auth.consent`, `auth.account_deleted`,
  `maintenance.purge_unverified`, `maintenance.orphan_uploads`.

Use it to answer "who hid this and why", to check a member's history before a ban, and as
evidence when a decision is challenged.

## 8. The `AUTO_APPROVE_AFTER_DAYS` safety valve

After the project ends, few admins may be active and new members could wait indefinitely.
`AUTO_APPROVE_AFTER_DAYS` (default `0` = off) lets the platform approve on its own:

- when set to N > 0 and the scheduler is enabled, the daily maintenance job approves every post
  and thread that has been pending for more than N days and marks its author trusted;
- the audit log shows `moderation.auto_approved` and `user.trusted` (reason `auto_approve`) with
  no actor;
- the age is measured from the item's creation time, so a never-approved item that is restored
  after N days is approved at the next run;
- reports and automatic hiding keep working after auto-approval.

Set it in the backend environment and restart the backend. A value such as 7 or 14 days keeps a
window for human review while making sure nobody waits forever. [CHECK: value agreed by the
partnership]

## 9. Checklist

Daily (or when the digest arrives):

- [ ] Open `/admin/queue`; approve or reject every pending item.
- [ ] Open `/admin/reports` (status *open*); for each item decide: unhide, keep hidden, hide or
      delete; then resolve or dismiss the reports.
- [ ] Ban obvious spam accounts.

Weekly:

- [ ] Scan `/admin/log` for `moderation.auto_hidden` items still hidden and decide on them.
- [ ] Check the dashboard (`/admin`): KNOWBASE reachable, pending and open-report counts low.

When admin capacity drops (post-project):

- [ ] Confirm at least two admins receive the digest.
- [ ] Agree and set `AUTO_APPROVE_AFTER_DAYS`.

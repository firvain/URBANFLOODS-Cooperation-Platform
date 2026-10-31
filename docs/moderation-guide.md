# Moderation guide

This guide is for platform admins. It explains in plain language how new members earn the right
to publish, what appears in the moderation queue, what each moderation action does (permanent
deletion included), which emails authors receive, how reports and automatic hiding work, what the
daily digest contains, and how to handle spam, abuse and personal-data complaints. It ends with
a short checklist. Account management is covered in the [admin handbook](admin-handbook.md); the
technical state machine is in
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
explaining that it awaits review; nobody else sees it. A pending post or thread can also be
approved from the **Moderate** menu on its own page; rejecting is done on the queue page.

### Rejection notes and resubmission

The reason you type when rejecting is **shown to the author**: it is stored on the item as the
admin's note, appears in the banner on the item's page ("The admin's note: …") and in the
rejection email. Write it for the author (what to fix), not as an internal remark. The author can
then edit the rejected item and press **Resubmit** in the banner: the item goes back to pending
and reappears in the queue with a **Resubmitted** badge, still carrying your earlier note so you
can check it was addressed. Resubmitting does not make the author trusted. Approving (or unhiding)
the item clears the note; rejecting it again replaces the note (or clears it if you give no
reason). Only the author can resubmit, and only an item that was rejected (not one hidden by an
admin or by reports).

### Emails to the author

The author is emailed about each decision, after it has been saved:

- **Approved**: the post or discussion is now public, with a link to it. If this approval made the
  author trusted, the email adds that their posts and discussions are now published without
  review. An approval by the [`AUTO_APPROVE_AFTER_DAYS`](#8-the-auto_approve_after_days-safety-valve)
  sweep says it was published automatically after the review period instead of naming an admin.
- **Rejected**: the item was not approved and only the author and the admins can see it; the
  author can still open it, edit it or delete it. The email gives the contact address
  (`CONTACT_EMAIL`, default louta@uowm.gr) for questions.
- The reason you type when rejecting is in the email (and on the item's page, see
  [above](#rejection-notes-and-resubmission)); the email also says the author can edit the item and
  send it for approval again. A reason given when hiding stays in the audit log only.
- Unhiding a rejected item counts as an approval and sends the approval email. Hide, the unhide of
  any other item, delete, restore and delete permanently send no email.
- No email is sent when an admin decides on their own content, when the author is banned,
  deleted or unverified, or when the author has turned off *Decisions on my posts and
  discussions* (Account → Notifications; off by default for accounts created since 2026-10-31,
  so a new member gets decision emails only after switching it on).
- The decision emails are in English for every interface language.
- One automatic sweep emails at most 100 authors; items beyond that are published without an
  email.

## 3. Moderation actions

All actions are available through the API (`POST /api/v1/moderation/{type}/{id}/<action>`, see
[api.md](api.md#reports-and-moderation)). In the interface:

- the **queue** page has Approve and Reject;
- the **Moderate** menu (admins only) on a post or discussion page offers what applies to its
  current status: Approve (pending), Hide with an optional reason (published), Unhide (hidden),
  Delete or, once deleted, Restore, and **Delete permanently**;
- the row menu of the **Reports** page offers Hide, Unhide, Delete and Restore for the reported
  post, discussion, reply or comment;
- admins can also edit or delete any post or thread, and pin or lock threads, from its own page.

Every action writes an audit row.

| Action | From → to | Effect on the author's trust | Effect on reports |
|---|---|---|---|
| **Approve** | pending → published | author becomes trusted (unless the account is banned or deleted) | none |
| **Reject** | pending → hidden (`rejected`) | author stays untrusted | none |
| **Resubmit** (the author, not an admin) | hidden (`rejected`) → pending | unchanged (untrusted) | none |
| **Hide** | published → hidden (`admin`) | unchanged | open reports stay open |
| **Unhide** | hidden → published | if the item was *rejected*, this counts as an approval: author becomes trusted | all open reports on the item are dismissed; report count reset to 0 |
| **Delete** | pending / published / hidden → deleted (soft) | unchanged | open reports stay open |
| **Restore** | deleted → published, or → pending if it was never approved | unchanged | when restored to published: open reports dismissed, count reset |
| **Delete permanently** | any status → removed from the database | unchanged | open reports on the item and on its comments or replies are resolved; the reports themselves stay |

Notes:

- Reject and hide accept an optional reason (up to 500 characters, plain text). Both go into the
  audit log; a rejection's reason is also shown to the author as the admin's note. A hide reason
  is never shown: the author sees a generic "hidden" banner with the contact address.
- Approve and reject apply to posts and threads only; replies and comments have no pending state.
- Delete is soft: the row stays in the database with status `deleted` and can be restored.
- **Restore**: a deleted post or discussion page cannot be opened again, not even by an admin. So
  Restore in the Moderate menu is there only while the page on which you deleted the item is
  still open. Later, restore a reported item from the row menu of the Reports page. For anything
  else, take the id from the audit log (`moderation.delete`, `post.deleted`, …) and call
  `POST /api/v1/moderation/{type}/{id}/restore` from the command line (see
  [admin-handbook.md](admin-handbook.md#api-calls-from-the-command-line)).
- An action from a status where it does not apply (for example approving published content)
  answers "invalid transition" and changes nothing.

### Delete permanently

**Delete permanently** (in the API: *purge*) cannot be undone. It works from any status. It
removes from the database:

- the post or discussion, with its tags and KNOWBASE links;
- all its comments (post) or all its replies at every level (discussion); purging a reply also
  removes the replies to it;
- the images it used (cover image, images in the text of the item and of the removed comments or
  replies) that no other post, discussion, reply or comment uses, whoever uploaded them. Images
  also used elsewhere stay.

Open reports on the removed items are marked resolved by you (each with a `report.resolve` audit
row); the reports themselves are kept. The audit row `moderation.purge` holds counts, the ids and
uploaders of the removed images and, for a post or discussion, its title (up to 200 characters).
It never holds the text, an image path or a file name.

In the interface, Delete permanently is the last item of the Moderate menu on a post or discussion
page: a dialog lists what will go and enables the button only after you type `DELETE` (the same
word in every language). Afterwards you land on the blog or forum list. Replies, comments and
items whose page can no longer be opened (soft-deleted ones) are purged through the API only:
`POST /api/v1/moderation/{type}/{id}/purge`.

### Uploads

Every member has an **Uploads** tab under Account. It lists their own images with a thumbnail, alt
text, size, date and the content that uses each one (any status). An image still used by a post,
discussion, reply or comment that is not deleted cannot be deleted: the button is disabled with
the reason shown next to it. Images used only by the member's own deleted content can be deleted
(if that content is restored later, the image is missing from it).

Admins have no page for other members' images. Through the API, `DELETE /api/v1/uploads/{id}` works
for an admin on any image, but answers 409 `uploads.in_use` while any content uses it, deleted
content included. Remove the image by editing or purging that content instead. An image that
nothing uses any more is also removed by the next daily maintenance run, once it is older than
`ORPHAN_UPLOAD_HOURS` (24 hours; needs the scheduler, see
[admin-handbook.md](admin-handbook.md#12-routine-maintenance)).

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

1. Delete the spam items (Reports page or the item's own Moderate menu). Use *Delete
   permanently* when the spam contains links or images you do not want to keep.
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

1. **Hide the item at once** (Moderate menu on the page, or the Reports page row menu) so it is no
   longer public. Do not use plain *Delete* for this: a soft-deleted post or discussion page can no
   longer be opened, which makes the next steps harder.
2. If removing a passage is enough, ask the author to edit it, or edit it yourself (admins may
   edit any post, thread, reply or comment through the normal edit form). The platform keeps no
   earlier versions of a text; the `post.updated` audit row records only which fields changed.
3. If the item must go, use **Delete permanently** (see
   [Delete permanently](#delete-permanently)). It removes the text from the database together with
   its comments or replies. If the **title** itself contains the personal data, edit the title
   first: the `moderation.purge` audit row keeps the title. Replies and comments are purged
   through the API.
4. **Check the attachments.** Purge removes only the images nothing else uses. If the photo is also
   used in other content, edit or purge that content too. Once nothing uses the image, the uploader
   can delete it from Account → Uploads; otherwise the next daily maintenance run removes it (see
   [Uploads](#uploads)). An admin cannot look up an image's id from its address in the interface.
   [CHECK]
5. Write any hide reason without repeating the personal data: reasons stay in the audit log. The
   reports on the item, with the reporters' free-text details, are kept.
6. Record what was done and forward the request to the data controller contact,
   **louta@uowm.gr** (University of Western Macedonia), who answers the requester.

Requests about a member's own account (access, deletion) are self-service; see
[admin-handbook.md](admin-handbook.md#13-gdpr-requests).

## 7. Using the audit log (`/admin/log`)

Every status change, role or trust change, ban, report action, sign-in, consent, data export and
account deletion writes a row: when, action, actor (empty for system actions), target, details.

- Filter by action: an exact name (`moderation.approve`) or a prefix ending in a dot; quick chips
  for `moderation.`, `admin.`, `report.` and `auth.`.
- Filter by actor id and target type (`post`, `thread`, `reply`, `comment`, `user`, `report`, …).
- Useful actions: `moderation.approve|reject|resubmit|hide|unhide|delete|restore|purge`,
  `moderation.auto_hidden`, `moderation.auto_approved`, `upload.deleted`, `user.trusted`, `admin.promote`,
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
- the authors are emailed that their item was published automatically (see
  [Emails to the author](#emails-to-the-author));
- the age is measured from the item's creation time, so a never-approved item that is restored
  after N days is approved at the next run;
- reports and automatic hiding keep working after auto-approval.

Set it in the backend environment and restart the backend. A value such as 7 or 14 days keeps a
window for human review while making sure nobody waits forever. [CHECK: value agreed by the
partnership]

## 9. Checklist

Daily (or when the digest arrives):

- [ ] Open `/admin/queue`; approve or reject every pending item.
- [ ] Open `/admin/reports` (status *open*); for each item decide: unhide, keep hidden, hide,
      delete or restore; then resolve or dismiss the reports.
- [ ] Ban obvious spam accounts.

Weekly:

- [ ] Scan `/admin/log` for `moderation.auto_hidden` items still hidden and decide on them.
- [ ] Check the dashboard (`/admin`): KNOWBASE reachable, pending and open-report counts low.

When admin capacity drops (post-project):

- [ ] Confirm at least two admins receive the digest.
- [ ] Agree and set `AUTO_APPROVE_AFTER_DAYS`.

import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
} from '@playwright/test'

import {
  ADMIN,
  API_HEADERS,
  API_URL,
  EDITOR,
  MEMBER,
  NEWBIE,
  anonThreadStatus,
  deleteThreadViaApi,
  loginViaForm,
  type DemoAccount,
} from './helpers/demo'
import { FRONTEND_URL, waitForEmailTo } from './helpers/mailpit'

/**
 * M3 forum, comments and notification emails against the real dev stack and its seeded demo
 * accounts (backend/README.md): the editor's thread gets a reply from the member (→ email to the
 * editor via Mailpit); the trusted member starts a thread, replies, answers the reply, edits and
 * deletes; the admin pins and locks it; the untrusted member's thread waits for approval; the
 * member comments on a seeded post; the notifications tab keeps a switch across a reload.
 * One page per role, logged in once (logins are rate limited) and kept across the tests, which
 * run in order. Titles carry a per-run suffix; afterAll deletes what the run created via the API.
 */
test.describe.configure({ mode: 'serial' })

/** A seeded published post by the member (backend/scripts/seed_dev.py). */
const GREEN_ROOFS_SLUG = 'green-roofs-and-retention-basins-what-two-years-of-pilot-data-show'
const GENERAL = 'General discussion'

const RUN = Date.now().toString(36)
const editorTitle = `E2E editor discussion ${RUN}`
const memberTitle = `E2E member discussion ${RUN}`
const newbieTitle = `E2E pending discussion ${RUN}`
const TAG = `e2e-${RUN}`
const editorReplyText = `A reply to the editor from the member, ${RUN}.`
const topReplyText = `First reply to my own discussion, ${RUN}.`
const nestedReplyText = `An answer to the first reply, ${RUN}.`
const nestedReplyEdited = `An answer to the first reply, edited, ${RUN}.`
const commentText = `An e2e comment on the green roofs post, ${RUN}.`
const commentEdited = `An e2e comment on the green roofs post, edited, ${RUN}.`

let anonContext: BrowserContext
let editorContext: BrowserContext
let memberContext: BrowserContext
let adminContext: BrowserContext
let newbieContext: BrowserContext
let anon: Page
let editor: Page
let member: Page
let admin: Page
let newbie: Page

/** Threads this run created and has not deleted yet, with the session that may delete them. */
const created = new Map<string, BrowserContext>()
/** Every thread slug this run created (checked for 404 after the cleanup). */
const allSlugs: string[] = []
let editorSlug = ''
let memberSlug = ''
let newbieSlug = ''
/** The member's comment while it exists (deleted in the test; afterAll is the safety net). */
let commentId: number | null = null
/** Set while the "comments on my posts" switch may be off (afterAll turns it back on). */
let preferenceChanged = false

async function newPage(browser: Browser): Promise<[BrowserContext, Page]> {
  const context = await browser.newContext()
  return [context, await context.newPage()]
}

/** A success toast (Nuxt UI also mirrors it into a hidden live region, hence `exact`). */
const toast = (page: Page, text: string) => page.getByText(text, { exact: true })

/** The thread the browser is on after creating it, from its URL (`/forum/t/:slug`). */
async function waitForThreadPage(page: Page): Promise<string> {
  await page.waitForURL((url) => /^\/forum\/t\/[^/]+$/.test(url.pathname))
  return decodeURIComponent(new URL(page.url()).pathname.split('/').pop() ?? '')
}

interface NewThread {
  title: string
  /** Paragraph typed first. */
  text: string
  /** Bulleted list items typed after the paragraph. */
  bullets?: string[]
  tags?: string[]
  submit: 'Publish' | 'Send for review'
}

/** "Start a discussion" from the forum list, fill the form in General discussion, submit. */
async function startThread(page: Page, account: DemoAccount, thread: NewThread): Promise<string> {
  await page.goto('/forum')
  await page.getByRole('link', { name: 'Start a discussion' }).click()
  await expect(page).toHaveURL('/forum/new')
  await expect(page.getByRole('heading', { level: 1, name: 'Start a discussion' })).toBeVisible()

  const form = page.getByTestId('thread-form')
  await form.getByLabel('Title', { exact: true }).fill(thread.title)

  const category = form.getByRole('combobox', { name: 'Category' })
  await category.click()
  await page.getByRole('option', { name: GENERAL, exact: true }).click()
  await expect(category).toContainText(GENERAL)

  // The rich-text editor: a contenteditable with role="textbox", labelled "Text".
  const body = form.getByRole('textbox', { name: 'Text', exact: true })
  await body.click()
  await page.keyboard.type(thread.text)
  if (thread.bullets?.length) {
    await page.keyboard.press('Enter')
    const bulleted = form
      .getByRole('toolbar', { name: 'Formatting' })
      .getByRole('button', { name: 'Bulleted list', exact: true })
    await bulleted.click()
    await expect(bulleted).toHaveAttribute('aria-pressed', 'true')
    for (const [i, item] of thread.bullets.entries()) {
      if (i > 0) await page.keyboard.press('Enter')
      await page.keyboard.type(item)
    }
    await expect(body.locator('ul > li')).toHaveCount(thread.bullets.length)
  }

  const tagInput = form.getByRole('textbox', { name: 'Tags' })
  for (const tag of thread.tags ?? []) {
    await tagInput.fill(tag)
    await tagInput.press('Enter')
    await expect(form).toContainText(tag)
  }

  await form.getByRole('button', { name: thread.submit, exact: true }).click()
  const slug = await waitForThreadPage(page)
  created.set(slug, page.context())
  allSlugs.push(slug)
  await expect(page.getByRole('heading', { level: 1, name: thread.title })).toBeVisible()
  await expect(page.getByTestId('thread-author')).toContainText(account.name)
  return slug
}

/** The top-level replies (each `<li>` also holds its children). */
const topReplies = (page: Page) => page.locator('[data-testid="reply-list"] > li')

/** A reply form, by the accessible name of its editor ("Your reply", "Reply to …", …). */
function replyForm(scope: Page | Locator, label: string): Locator {
  const page = 'mainFrame' in scope ? scope : scope.page()
  return scope.getByTestId('reply-form').filter({
    has: page.getByRole('textbox', { name: label, exact: true }),
  })
}

/** Type into a compact editor and submit its form with `button`. */
async function submitEditor(form: Locator, label: string, text: string, button: string) {
  const editor = form.getByRole('textbox', { name: label, exact: true })
  await editor.fill(text)
  await expect(editor).toContainText(text)
  await form.getByRole('button', { name: button, exact: true }).click()
}

/** The id of a saved reply/comment from its `<li id="reply-12">` (optimistic ids are < 0). */
async function savedId(item: Locator, prefix: 'reply' | 'comment'): Promise<number> {
  await expect(item).toHaveAttribute('id', new RegExp(`^${prefix}-\\d+$`))
  return Number((await item.getAttribute('id'))!.slice(prefix.length + 1))
}

/** The button of a reply's own action bar (not those of its children). */
const ownAction = (reply: Locator, name: string) =>
  reply.locator(':scope > article').getByRole('button', { name, exact: true })

/**
 * The API counts a save as an edit only when it comes more than 5 s after creation
 * (`EDIT_GRACE`, backend/app/api/v1/schemas/comment.py), so an edit test waits that long after
 * `savedAt` (the moment the test saw the saved id, i.e. after the server's `created_at`).
 */
const EDIT_GRACE_MS = 5_000
async function waitPastEditGrace(page: Page, savedAt: number) {
  const remaining = savedAt + EDIT_GRACE_MS + 500 - Date.now()
  if (remaining > 0) await page.waitForTimeout(remaining)
}

const commentsTitle = (n: number) =>
  n === 0 ? 'No comments' : n === 1 ? '1 comment' : `${n} comments`

test.beforeAll(async ({ browser }) => {
  ;[anonContext, anon] = await newPage(browser)
  ;[editorContext, editor] = await newPage(browser)
  ;[memberContext, member] = await newPage(browser)
  ;[adminContext, admin] = await newPage(browser)
  ;[newbieContext, newbie] = await newPage(browser)
})

test.afterAll(async () => {
  for (const [slug, context] of created) {
    await deleteThreadViaApi(context.request, slug).catch(() => {})
  }
  if (commentId !== null) {
    await memberContext.request
      .delete(`${API_URL}/api/v1/comments/${commentId}`, { headers: API_HEADERS })
      .catch(() => {})
  }
  if (preferenceChanged) {
    const url = `${API_URL}/api/v1/auth/me/notifications`
    const res = await memberContext.request.get(url, { headers: API_HEADERS })
    if (res.ok()) {
      const prefs = (await res.json()) as Record<string, unknown>
      await memberContext.request.put(url, {
        headers: API_HEADERS,
        data: { ...prefs, comment_on_my_post: true },
      })
    }
  }
  await Promise.all(
    [anonContext, editorContext, memberContext, adminContext, newbieContext].map((c) => c.close()),
  )
  // Nothing this run created is reachable any more.
  for (const slug of allSlugs) await expect.poll(() => anonThreadStatus(slug)).toBe(404)
})

test('1. a reply to the editor’s discussion emails the editor a link to it', async () => {
  await loginViaForm(editor, EDITOR)
  // The notification needs the (default-on) preference; fail clearly if a run left it off.
  const prefs = await editorContext.request.get(`${API_URL}/api/v1/auth/me/notifications`, {
    headers: API_HEADERS,
  })
  expect(((await prefs.json()) as { reply_to_my_thread: boolean }).reply_to_my_thread).toBe(true)

  editorSlug = await startThread(editor, EDITOR, {
    title: editorTitle,
    text: 'Which retention measures worked for you last winter?',
    submit: 'Publish',
  })
  await expect(toast(editor, 'The discussion is published.')).toBeVisible()

  await loginViaForm(member, MEMBER)
  await member.goto(`/forum/t/${editorSlug}`)
  await expect(member.getByRole('heading', { level: 1, name: editorTitle })).toBeVisible()
  const since = new Date()
  await submitEditor(replyForm(member, 'Your reply'), 'Your reply', editorReplyText, 'Post reply')
  const reply = topReplies(member).filter({ hasText: editorReplyText })
  const replyId = await savedId(reply, 'reply')

  const email = await waitForEmailTo(EDITOR.email, {
    subjectIncludes: editorTitle,
    since,
    timeoutMs: 20_000,
  })
  expect(email.Subject).toContain('replied')
  expect(email.Subject).toContain(MEMBER.name)
  expect(email.Text).toContain(editorTitle)
  expect(email.Text).toContain(editorReplyText)
  expect(email.Text).toContain(
    `${FRONTEND_URL.replace(/\/$/, '')}/forum/t/${editorSlug}#reply-${replyId}`,
  )
})

test('2. trusted member: start a discussion with a list and a tag; it is published', async () => {
  memberSlug = await startThread(member, MEMBER, {
    title: memberTitle,
    text: 'How do you maintain green roofs in dry summers?',
    bullets: ['Irrigation schedules', 'Choice of plants'],
    tags: [TAG],
    submit: 'Publish',
  })
  await expect(toast(member, 'The discussion is published.')).toBeVisible()

  await expect(member.getByTestId('post-status')).toHaveCount(0)
  await expect(member.getByTestId('status-hint')).toHaveCount(0)
  const body = member.getByTestId('thread-body')
  await expect(body).toContainText('How do you maintain green roofs in dry summers?')
  await expect(body.locator('ul > li')).toHaveText(['Irrigation schedules', 'Choice of plants'])
  await expect(
    member.getByRole('list', { name: 'Tags' }).getByRole('link', { name: `#${TAG}` }),
  ).toBeVisible()
  await expect(member.getByRole('heading', { level: 2, name: 'No replies' })).toBeVisible()
  await expect.poll(() => anonThreadStatus(memberSlug)).toBe(200)
})

test('3. trusted member: reply, answer the reply, edit the answer, delete the reply', async () => {
  // Top-level reply from the form at the bottom.
  await submitEditor(replyForm(member, 'Your reply'), 'Your reply', topReplyText, 'Post reply')
  const topId = await savedId(topReplies(member).filter({ hasText: topReplyText }), 'reply')
  // By id from here on: the text filters stop matching once a reply is edited or deleted.
  const top = member.locator(`#reply-${topId}`)
  await expect(top.getByTestId('reply-author').first()).toContainText(MEMBER.name)
  await expect(member.getByRole('heading', { level: 2, name: '1 reply' })).toBeVisible()
  // The form empties for the next reply.
  await expect(member.getByRole('textbox', { name: 'Your reply', exact: true })).toHaveText('')

  // Nested reply: "Reply" opens an inline form under the reply; the answer is listed indented.
  const replyButton = top.getByRole('button', { name: `Reply to ${MEMBER.name}` })
  await replyButton.click()
  await expect(replyButton).toHaveAttribute('aria-expanded', 'true')
  const label = `Reply to ${MEMBER.name}`
  await submitEditor(replyForm(top, label), label, nestedReplyText, 'Post reply')
  const children = top.getByTestId('reply-children')
  const childId = await savedId(
    children.getByTestId('reply').filter({ hasText: nestedReplyText }),
    'reply',
  )
  const childSavedAt = Date.now()
  const child = children.locator(`#reply-${childId}`)
  await expect(member.getByRole('textbox', { name: label, exact: true })).toHaveCount(0)
  await expect(member.getByRole('heading', { level: 2, name: '2 replies' })).toBeVisible()
  // One level only: the answer offers no "Reply" of its own.
  await expect(child.getByRole('button', { name: /^Reply to / })).toHaveCount(0)

  // Edit the answer inline → "edited".
  await ownAction(child, 'Edit').click()
  const editForm = replyForm(child, 'Edit your reply')
  await expect(editForm.getByRole('textbox', { name: 'Edit your reply' })).toHaveText(
    nestedReplyText,
  )
  await waitPastEditGrace(member, childSavedAt)
  await submitEditor(editForm, 'Edit your reply', nestedReplyEdited, 'Save')
  await expect(child.getByTestId('reply-body')).toHaveText(nestedReplyEdited)
  await expect(child.getByTestId('reply-edited')).toHaveText('edited')

  // Delete the top-level reply → "[deleted]" placeholder; the answer stays.
  await ownAction(top, 'Delete').click()
  const dialog = member.getByRole('dialog', { name: 'Delete this reply?' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Delete reply' }).click()
  await expect(dialog).toBeHidden()
  await expect(toast(member, 'The reply was deleted.')).toBeVisible()

  await expect(top.locator(':scope > article').getByTestId('reply-deleted')).toHaveText('[deleted]')
  await expect(top.locator(':scope > article')).not.toContainText(topReplyText)
  await expect(top.getByTestId('reply-children')).toContainText(nestedReplyEdited)

  // The same after a fresh load (server state, not the optimistic list).
  await member.reload()
  await expect(top.locator(':scope > article').getByTestId('reply-deleted')).toHaveText('[deleted]')
  await expect(top.locator(`#reply-${childId}`).getByTestId('reply-body')).toHaveText(
    nestedReplyEdited,
  )
})

test('4. admin: pin and lock the member’s discussion, then unlock and unpin it', async () => {
  await loginViaForm(admin, ADMIN)
  await admin.goto(`/forum/t/${memberSlug}`)
  await expect(admin.getByRole('heading', { level: 1, name: memberTitle })).toBeVisible()
  const moderation = admin.getByRole('group', { name: 'Moderation' })

  // Pin → "Pinned" here and first in the forum list.
  await moderation.getByRole('button', { name: 'Pin', exact: true }).click()
  await expect(toast(admin, 'The discussion is pinned.')).toBeVisible()
  await expect(admin.getByTestId('thread-pinned')).toHaveText('Pinned')
  await expect(moderation.getByRole('button', { name: 'Unpin', exact: true })).toBeVisible()

  await admin.goto('/forum')
  await expect(admin.getByTestId('forum-count')).toBeVisible()
  const first = admin.getByTestId('thread-card').first()
  await expect(first.getByRole('heading', { level: 2 })).toHaveText(memberTitle)
  await expect(first.getByTestId('thread-pinned')).toHaveText('Pinned')

  // Lock → the reply form gives way to the locked notice.
  await first.getByRole('link', { name: memberTitle }).click()
  await expect(admin).toHaveURL(`/forum/t/${memberSlug}`)
  await expect(admin.getByTestId('reply-form')).toBeVisible()
  await moderation.getByRole('button', { name: 'Lock', exact: true }).click()
  await expect(toast(admin, 'The discussion is locked.')).toBeVisible()
  await expect(admin.getByTestId('thread-locked')).toHaveText('Locked')
  await expect(admin.getByTestId('locked-notice')).toContainText(
    'This discussion is locked. New replies are not accepted.',
  )
  await expect(admin.getByTestId('reply-form')).toHaveCount(0)

  // The member sees the lock too: no form, no "Reply" on the replies, no editing.
  await member.goto(`/forum/t/${memberSlug}`)
  await expect(member.getByRole('heading', { level: 1, name: memberTitle })).toBeVisible()
  await expect(member.getByTestId('locked-notice')).toBeVisible()
  await expect(member.getByTestId('reply-form')).toHaveCount(0)
  await expect(member.getByTestId('reply-list')).toContainText(nestedReplyEdited)
  await expect(member.getByRole('button', { name: /^Reply to / })).toHaveCount(0)
  await expect(member.getByRole('button', { name: 'Edit', exact: true })).toHaveCount(0)

  // Unlock and unpin.
  await moderation.getByRole('button', { name: 'Unlock', exact: true }).click()
  await expect(toast(admin, 'The discussion is unlocked.')).toBeVisible()
  await expect(admin.getByTestId('locked-notice')).toHaveCount(0)
  await expect(admin.getByTestId('reply-form')).toBeVisible()
  await moderation.getByRole('button', { name: 'Unpin', exact: true }).click()
  await expect(toast(admin, 'The discussion is no longer pinned.')).toBeVisible()
  await expect(admin.getByTestId('thread-pinned')).toHaveCount(0)
  await expect(admin.getByTestId('thread-locked')).toHaveCount(0)

  await member.reload()
  await expect(member.getByRole('heading', { level: 1, name: memberTitle })).toBeVisible()
  await expect(member.getByTestId('reply-form')).toBeVisible()
})

test('5. untrusted member: a new discussion waits for approval and stays private', async () => {
  await loginViaForm(newbie, NEWBIE)
  await newbie.goto('/forum/new')
  await expect(newbie.getByTestId('untrusted-note')).toHaveText(
    'Your first discussion will be reviewed by an admin before it is published.',
  )
  newbieSlug = await startThread(newbie, NEWBIE, {
    title: newbieTitle,
    text: 'A question from a new member, written by an e2e test.',
    submit: 'Send for review',
  })
  await expect(
    toast(newbie, 'The discussion was sent. It will be published once an admin approves it.'),
  ).toBeVisible()
  await expect(newbie.getByTestId('post-status')).toHaveText('Pending approval')
  await expect(newbie.getByTestId('status-hint')).toContainText(
    'Waiting for approval by an admin. Only you and the admins can see this discussion until it is approved.',
  )
  await expect(
    newbie.getByText('Replies open once the discussion is published.', { exact: true }),
  ).toBeVisible()
  await expect(newbie.getByTestId('reply-form')).toHaveCount(0)

  // A fresh anonymous visitor gets "not found", from the page and from the API.
  await anon.goto(`/forum/t/${newbieSlug}`)
  await expect(anon.getByRole('heading', { level: 1, name: 'Discussion not found' })).toBeVisible()
  expect(await anonThreadStatus(newbieSlug)).toBe(404)
})

test('6. comments: write, edit and delete a comment on a seeded post', async () => {
  const res = await fetch(`${API_URL}/api/v1/posts/${GREEN_ROOFS_SLUG}`)
  const { comment_count: before } = (await res.json()) as { comment_count: number }

  await member.goto(`/blog/${GREEN_ROOFS_SLUG}`)
  const section = member.getByTestId('post-comments')
  const heading = section.getByRole('heading', { level: 2 })
  await expect(heading).toHaveText(commentsTitle(before))

  await submitEditor(
    section.getByTestId('comment-form'),
    'Your comment',
    commentText,
    'Post comment',
  )
  commentId = await savedId(
    section.getByTestId('comment').filter({ hasText: commentText }),
    'comment',
  )
  const commentSavedAt = Date.now()
  // By id from here on: the text filter stops matching once the comment is edited.
  const comment = section.locator(`#comment-${commentId}`)
  await expect(comment.getByTestId('comment-author')).toContainText(MEMBER.name)
  await expect(heading).toHaveText(commentsTitle(before + 1))

  // Edit inline → "edited".
  await comment.getByRole('button', { name: 'Edit', exact: true }).click()
  await waitPastEditGrace(member, commentSavedAt)
  await submitEditor(comment, 'Edit your comment', commentEdited, 'Save')
  await expect(comment.getByTestId('comment-body')).toHaveText(commentEdited)
  await expect(comment.getByTestId('comment-edited')).toHaveText('edited')

  // Delete → gone, the count is back.
  await comment.getByRole('button', { name: 'Delete', exact: true }).click()
  const dialog = member.getByRole('dialog', { name: 'Delete this comment?' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Delete comment' }).click()
  await expect(dialog).toBeHidden()
  await expect(toast(member, 'The comment was deleted.')).toBeVisible()
  await expect(comment).toHaveCount(0)
  await expect(heading).toHaveText(commentsTitle(before))
  commentId = null

  // Visitors are invited to log in.
  await anon.goto(`/blog/${GREEN_ROOFS_SLUG}`)
  const anonSection = anon.getByTestId('post-comments')
  await expect(anonSection.getByRole('link', { name: 'Log in to comment' })).toBeVisible()
  await expect(anonSection.getByTestId('comment-form')).toHaveCount(0)
})

test('7. notifications tab: a switch turned off stays off after a reload', async () => {
  const notificationsSwitch = (page: Page) =>
    page.getByRole('switch', { name: 'Comments on my posts' })
  const saved = (page: Page) =>
    page
      .getByTestId('notifications-form')
      .getByText('Your notification preferences have been saved.', { exact: true })

  await member.goto('/account?tab=notifications')
  await expect(member.getByRole('tab', { name: 'Notifications' })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  const toggle = notificationsSwitch(member)
  await expect(toggle).toHaveAttribute('aria-checked', 'true')

  preferenceChanged = true
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-checked', 'false')
  await member.getByRole('button', { name: 'Save preferences' }).click()
  await expect(saved(member)).toBeVisible()

  await member.reload()
  await expect(notificationsSwitch(member)).toHaveAttribute('aria-checked', 'false')
  // The other switches are untouched.
  await expect(member.getByRole('switch', { name: 'Replies to my discussions' })).toHaveAttribute(
    'aria-checked',
    'true',
  )

  await notificationsSwitch(member).click()
  await expect(notificationsSwitch(member)).toHaveAttribute('aria-checked', 'true')
  await member.getByRole('button', { name: 'Save preferences' }).click()
  await expect(saved(member)).toBeVisible()
  const prefs = await memberContext.request.get(`${API_URL}/api/v1/auth/me/notifications`, {
    headers: API_HEADERS,
  })
  expect(((await prefs.json()) as { comment_on_my_post: boolean }).comment_on_my_post).toBe(true)
  preferenceChanged = false
})

test('8. untrusted member: delete the pending discussion', async () => {
  await newbie.goto(`/forum/t/${newbieSlug}`)
  await expect(newbie.getByRole('heading', { level: 1, name: newbieTitle })).toBeVisible()
  await newbie.getByRole('button', { name: 'Delete', exact: true }).click()
  const dialog = newbie.getByRole('dialog', { name: 'Delete this discussion?' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Delete discussion' }).click()
  await newbie.waitForURL((url) => url.pathname === '/forum')
  await expect(toast(newbie, 'The discussion was deleted.')).toBeVisible()
  created.delete(newbieSlug)
  await expect(newbie.getByTestId('forum-count')).toBeVisible()
  await expect(newbie.getByRole('link', { name: newbieTitle })).toHaveCount(0)
})

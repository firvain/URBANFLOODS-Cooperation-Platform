import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import {
  expect,
  test,
  type APIRequestContext,
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
  type DemoAccount,
} from './helpers/demo'
import { waitForEmailTo } from './helpers/mailpit'
import { makePng } from './helpers/png'

/**
 * M4 moderation against the real dev stack and its seeded demo accounts (backend/README.md):
 * the untrusted member's first post waits in the approval queue, the admin approves it (→ the
 * member is trusted and publishes directly), a later post is rejected with an audited reason,
 * three distinct reports hide a post automatically and the admin dismisses / unhides from the
 * reports page, the dashboard numbers and CSV export, the digest email (via the backend CLI in
 * the dev compose stack) and the trust toggle on the users page; then (5h) the Moderate menu on a
 * post page (hide with a reason, unhide, delete permanently) and the account Uploads tab.
 *
 * One browser context per role, logged in once through the API (the UI login is covered by
 * auth.spec.ts; logins are rate limited) and kept across the tests, which run in order. Titles
 * carry a per-run suffix. afterAll deletes every post this run created, dismisses the reports
 * still open on them and removes newbie's trusted mark, so the suite is repeatable.
 */
test.describe.configure({ mode: 'serial' })

const RUN = Date.now().toString(36)
const firstTitle = `E2E first post ${RUN}`
const secondTitle = `E2E trusted second post ${RUN}`
const rejectedTitle = `E2E rejected post ${RUN}`
const rejectReason = `Off-topic for the platform (e2e ${RUN})`
const COMPOSE_FILE = fileURLToPath(new URL('../../docker-compose.yml', import.meta.url))

let anonContext: BrowserContext
let newbieContext: BrowserContext
let adminContext: BrowserContext
let memberContext: BrowserContext
let editorContext: BrowserContext
let anon: Page
let newbie: Page
let admin: Page
let member: Page
let editor: Page

/** Slugs of every post this run created (deleted by the admin in afterAll). */
const createdSlugs = new Set<string>()
let newbieId = 0
let firstSlug = ''
let secondSlug = ''
let secondId = 0
let rejectedSlug = ''

async function newPage(browser: Browser): Promise<[BrowserContext, Page]> {
  const context = await browser.newContext()
  return [context, await context.newPage()]
}

/**
 * Log a browser context in through the API (its pages share the cookie jar). On 429 waits for
 * `Retry-After` and tries again once, so a full `npm run e2e` (12 logins over a few minutes
 * against a 10 per 15 min budget) does not fail on the bucket refill.
 */
async function login(context: BrowserContext, account: DemoAccount): Promise<void> {
  for (let attempt = 0; ; attempt++) {
    const res = await context.request.post(`${API_URL}/api/v1/auth/login`, {
      headers: API_HEADERS,
      data: { email: account.email, password: account.password },
    })
    if (res.status() === 429 && attempt === 0) {
      const wait = Number(res.headers()['retry-after'] ?? '90')
      test.info().annotations.push({ type: 'login', description: `429, waited ${wait}s` })
      await new Promise((resolve) => setTimeout(resolve, (wait + 1) * 1000))
      continue
    }
    expect(res.status(), `login as ${account.email}`).toBe(200)
    return
  }
}

/** A success toast (Nuxt UI also mirrors it into a hidden live region, hence `exact`). */
const toast = (page: Page, text: string) => page.getByText(text, { exact: true })

/** JSON body of an API call made with a logged-in context (asserts the status). */
async function apiJson<T>(
  request: APIRequestContext,
  method: 'GET' | 'POST',
  path: string,
  data?: unknown,
  status = 200,
): Promise<T> {
  const res = await request.fetch(`${API_URL}/api/v1${path}`, {
    method,
    headers: API_HEADERS,
    data,
  })
  expect(res.status(), `${method} ${path}`).toBe(status)
  return (await res.json()) as T
}

interface AdminUser {
  id: number
  email: string
  is_trusted: boolean
}

async function newbieUser(request: APIRequestContext): Promise<AdminUser> {
  const { items } = await apiJson<{ items: AdminUser[] }>(
    request,
    'GET',
    `/admin/users/?q=${encodeURIComponent(NEWBIE.email)}`,
  )
  const user = items.find((u) => u.email === NEWBIE.email)
  if (!user) throw new Error('The seeded newbie account is missing')
  return user
}

/** A post's id by slug (admins see every status). */
async function postId(request: APIRequestContext, slug: string): Promise<number> {
  const post = await apiJson<{ id: number }>(request, 'GET', `/posts/${encodeURIComponent(slug)}`)
  return post.id
}

/** Status of `GET /posts/:slug` for an anonymous client. */
async function anonPostStatus(slug: string): Promise<number> {
  const res = await fetch(`${API_URL}/api/v1/posts/${encodeURIComponent(slug)}`)
  return res.status
}

interface Report {
  id: number
  status: 'open' | 'resolved' | 'dismissed'
  reporter: { display_name: string } | null
  content_id: number
  content: { type: string; id: number; status: string } | null
}

/** Every report (any status) on the given post, from the admin list. */
async function reportsOnPost(request: APIRequestContext, id: number): Promise<Report[]> {
  const { items } = await apiJson<{ items: Report[] }>(
    request,
    'GET',
    '/reports/?content_type=post&limit=100',
  )
  return items.filter((r) => r.content_id === id)
}

/** The post the browser is on after a create, from its URL (`/blog/:slug`). */
async function waitForPostPage(page: Page): Promise<string> {
  await page.waitForURL(
    (url) => /^\/blog\/[^/]+$/.test(url.pathname) && url.pathname !== '/blog/new',
  )
  return decodeURIComponent(new URL(page.url()).pathname.split('/').pop() ?? '')
}

/** Write a post in the editor UI (category News, one paragraph) and submit it. */
async function writePost(
  page: Page,
  title: string,
  submit: 'Publish' | 'Send for review',
): Promise<string> {
  await page.goto('/blog/new')
  await expect(page.getByRole('heading', { level: 1, name: 'Write a post' })).toBeVisible()
  const note = page.getByText(
    'Your first post will be reviewed by an admin before it is published.',
  )
  if (submit === 'Send for review') await expect(note).toBeVisible()
  else await expect(note).toHaveCount(0)

  await page.getByLabel('Title', { exact: true }).fill(title)
  const category = page.getByRole('combobox', { name: 'Category' })
  await category.click()
  await page.getByRole('option', { name: 'News', exact: true }).click()
  await expect(category).toContainText('News')
  await page.getByRole('textbox', { name: 'Text', exact: true }).click()
  await page.keyboard.type(`A short municipal update written by the moderation e2e test, ${RUN}.`)

  await page.getByRole('button', { name: submit, exact: true }).click()
  const slug = await waitForPostPage(page)
  createdSlugs.add(slug)
  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
  return slug
}

/** The approval-queue row of an item, by its title link. */
const queueRow = (page: Page, title: string): Locator =>
  page
    .getByTestId('queue-table')
    .getByRole('row')
    .filter({ has: page.getByRole('link', { name: title, exact: true }) })

test.beforeAll(async ({ browser }) => {
  ;[anonContext, anon] = await newPage(browser)
  ;[newbieContext, newbie] = await newPage(browser)
  ;[adminContext, admin] = await newPage(browser)
  ;[memberContext, member] = await newPage(browser)
  ;[editorContext, editor] = await newPage(browser)
})

test.afterAll(async () => {
  test.setTimeout(120_000)
  const request = adminContext.request
  const loggedIn = (await request.get(`${API_URL}/api/v1/auth/me`, { headers: API_HEADERS })).ok()
  if (loggedIn) {
    for (const slug of createdSlugs) {
      const id = await postId(request, slug).catch(() => 0)
      if (!id) continue
      for (const report of await reportsOnPost(request, id).catch(() => [])) {
        if (report.status === 'open') {
          await request.post(`${API_URL}/api/v1/reports/${report.id}/dismiss`, {
            headers: API_HEADERS,
          })
        }
      }
      await request.post(`${API_URL}/api/v1/moderation/post/${id}/delete`, {
        headers: API_HEADERS,
      })
    }
    // Back to the seeded state: newbie is not trusted (blog.spec.ts relies on it).
    const id = newbieId || (await newbieUser(request).catch(() => null))?.id
    if (id) {
      await request.post(`${API_URL}/api/v1/admin/users/${id}/untrust`, { headers: API_HEADERS })
    }
  }
  await Promise.all(
    [anonContext, newbieContext, adminContext, memberContext, editorContext].map((c) => c.close()),
  )
})

test('1. first post waits for approval; approving it publishes it and trusts the author', async () => {
  test.setTimeout(240_000)
  await login(adminContext, ADMIN)
  // A failed earlier run may have left newbie trusted: start from the seeded state.
  const user = await newbieUser(adminContext.request)
  newbieId = user.id
  if (user.is_trusted) {
    await apiJson(adminContext.request, 'POST', `/admin/users/${newbieId}/untrust`)
  }
  await login(newbieContext, NEWBIE)

  firstSlug = await writePost(newbie, firstTitle, 'Send for review')
  await expect(
    toast(newbie, 'The post was sent. It will be published once an admin approves it.'),
  ).toBeVisible()
  await expect(newbie.getByTestId('post-status')).toHaveText('Pending approval')
  const hint = newbie.getByTestId('status-hint')
  await expect(hint).toContainText(
    'Waiting for approval by an admin. Only you and the admins can see this post until it is approved.',
  )
  await expect(hint).toContainText(
    'After your first approval, what you post is published immediately.',
  )

  await anon.goto(`/blog/${firstSlug}`)
  await expect(anon.getByRole('heading', { level: 1, name: 'Post not found' })).toBeVisible()

  // The queue: the item with its untrusted author (no "Trusted" badge).
  await admin.goto('/admin/queue')
  await expect(admin.getByRole('heading', { level: 1, name: 'Approval queue' })).toBeVisible()
  const row = queueRow(admin, firstTitle)
  await expect(row).toHaveCount(1)
  await expect(row).toContainText(NEWBIE.name)
  await expect(row).toContainText('Post')
  await expect(row.getByText('Trusted', { exact: true })).toHaveCount(0)

  await row.getByRole('button', { name: `Approve “${firstTitle}”` }).click()
  await expect(toast(admin, `“${firstTitle}” is published.`)).toBeVisible()
  await expect(queueRow(admin, firstTitle)).toHaveCount(0)

  await expect.poll(() => anonPostStatus(firstSlug)).toBe(200)
  await anon.goto(`/blog/${firstSlug}`)
  await expect(anon.getByRole('heading', { level: 1, name: firstTitle })).toBeVisible()
  expect((await newbieUser(adminContext.request)).is_trusted).toBe(true)

  // Trusted now: the next post is published at once, without badge or banner.
  secondSlug = await writePost(newbie, secondTitle, 'Publish')
  await expect(toast(newbie, 'The post is published.')).toBeVisible()
  await expect(newbie.getByTestId('post-status')).toHaveCount(0)
  await expect(newbie.getByTestId('status-hint')).toHaveCount(0)
  await expect.poll(() => anonPostStatus(secondSlug)).toBe(200)
  secondId = await postId(adminContext.request, secondSlug)
})

test('2. a rejected post is hidden with the rejected banner; the reason is in the audit log', async () => {
  // Newbie is trusted after test 1: remove the mark so the next post waits again.
  const untrusted = await apiJson<AdminUser>(
    adminContext.request,
    'POST',
    `/admin/users/${newbieId}/untrust`,
  )
  expect(untrusted.is_trusted).toBe(false)

  rejectedSlug = await writePost(newbie, rejectedTitle, 'Send for review')
  await expect(newbie.getByTestId('post-status')).toHaveText('Pending approval')

  await admin.goto('/admin/queue')
  const row = queueRow(admin, rejectedTitle)
  await expect(row).toHaveCount(1)
  await row.getByRole('button', { name: `Reject “${rejectedTitle}”` }).click()
  const dialog = admin.getByRole('dialog', { name: `Reject “${rejectedTitle}”?` })
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('Reason (optional)').fill(rejectReason)
  await dialog.getByRole('button', { name: 'Reject', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(toast(admin, `“${rejectedTitle}” was rejected.`)).toBeVisible()
  await expect(queueRow(admin, rejectedTitle)).toHaveCount(0)

  // The author: hidden badge and the "not approved" banner with the contact line.
  await newbie.goto(`/blog/${rejectedSlug}`)
  await expect(newbie.getByRole('heading', { level: 1, name: rejectedTitle })).toBeVisible()
  await expect(newbie.getByTestId('post-status')).toHaveText('Hidden')
  const hint = newbie.getByTestId('status-hint')
  await expect(hint).toContainText(
    'An admin did not approve this post. Only you and the admins can see it.',
  )
  await expect(hint).toContainText('If you think this is a mistake, contact')
  expect(await anonPostStatus(rejectedSlug)).toBe(404)

  // The audit log, filtered to the moderation actions: the reject row with its reason.
  await admin.goto('/admin/log?action=moderation.')
  await expect(admin.getByRole('heading', { level: 1, name: 'Audit log' })).toBeVisible()
  const logRow = admin.getByTestId('log-table').getByRole('row').filter({ hasText: rejectReason })
  await expect(logRow).toHaveCount(1)
  await expect(logRow).toContainText('moderation.reject')
  await expect(logRow).toContainText(ADMIN.name)
  const rejectedId = await postId(adminContext.request, rejectedSlug)
  await expect(logRow).toContainText(`post #${rejectedId}`)
  const metadata = logRow.locator('dl')
  await expect(metadata.locator('dt', { hasText: 'reason' })).toBeVisible()
  await expect(metadata.locator('dd', { hasText: rejectReason })).toBeVisible()
})

test('3. three distinct reports hide a post; the admin dismisses one and unhides it', async () => {
  // Reports are one per member and item, whatever their status, so a seeded post could be
  // reported only once: the target is newbie's published second post from test 1.
  test.setTimeout(240_000)
  await login(memberContext, MEMBER)
  await member.goto(`/blog/${secondSlug}`)
  await expect(member.getByRole('heading', { level: 1, name: secondTitle })).toBeVisible()

  await member.getByRole('button', { name: 'Report this post' }).click()
  const dialog = member.getByRole('dialog', { name: 'Report this post' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('radio', { name: 'Spam or advertising' }).click()
  await dialog.getByRole('button', { name: 'Send report' }).click()
  await expect(dialog).toBeHidden()
  await expect(toast(member, "Thanks, we'll look at it.")).toBeVisible()
  const reported = member.getByRole('button', { name: 'Reported' })
  await expect(reported).toBeDisabled()

  await member.reload()
  await expect(member.getByRole('heading', { level: 1, name: secondTitle })).toBeVisible()
  await expect(member.getByRole('button', { name: 'Reported' })).toBeDisabled()
  await expect(member.getByRole('button', { name: 'Report this post' })).toHaveCount(0)

  // The same member again: refused.
  const again = await memberContext.request.post(`${API_URL}/api/v1/reports/`, {
    headers: API_HEADERS,
    data: { content_type: 'post', content_id: secondId, reason: 'spam' },
  })
  expect(again.status()).toBe(409)
  expect(((await again.json()) as { detail: { code: string } }).detail.code).toBe(
    'report.already_reported',
  )

  // Two more distinct reporters (through the API): the third report hides the post.
  await login(editorContext, EDITOR)
  const second = await apiJson<{ auto_hidden: boolean }>(
    editorContext.request,
    'POST',
    '/reports/',
    { content_type: 'post', content_id: secondId, reason: 'off_topic' },
    201,
  )
  expect(second.auto_hidden).toBe(false)
  expect(await anonPostStatus(secondSlug)).toBe(200)
  const third = await apiJson<{ auto_hidden: boolean }>(
    adminContext.request,
    'POST',
    '/reports/',
    { content_type: 'post', content_id: secondId, reason: 'misinformation' },
    201,
  )
  expect(third.auto_hidden).toBe(true)
  expect(await anonPostStatus(secondSlug)).toBe(404)
  await anon.goto(`/blog/${secondSlug}`)
  await expect(anon.getByRole('heading', { level: 1, name: 'Post not found' })).toBeVisible()

  // The reports page: three open reports on the post, its content marked hidden.
  const reports = await reportsOnPost(adminContext.request, secondId)
  expect(reports).toHaveLength(3)
  expect(reports.every((r) => r.status === 'open')).toBe(true)
  const memberReport = reports.find((r) => r.reporter?.display_name === MEMBER.name)
  const editorReport = reports.find((r) => r.reporter?.display_name === EDITOR.name)
  if (!memberReport || !editorReport) throw new Error('Missing reports of the member/editor')

  await admin.goto('/admin/reports')
  await expect(admin.getByRole('heading', { level: 1, name: 'Reports' })).toBeVisible()
  const rows = admin
    .getByTestId('reports-table')
    .getByRole('row')
    .filter({ has: admin.getByRole('link', { name: secondTitle, exact: true }) })
  await expect(rows).toHaveCount(3)
  for (const row of await rows.all()) {
    await expect(row).toContainText('Hidden')
    await expect(row).toContainText('Open')
  }

  // Dismiss the member's report.
  const memberRow = rows.filter({ hasText: MEMBER.name })
  await memberRow.getByRole('button', { name: `Actions for report ${memberReport.id}` }).click()
  await admin.getByRole('menuitem', { name: 'Dismiss' }).click()
  await expect(toast(admin, 'Report dismissed.')).toBeVisible()
  await expect(memberRow).toContainText('Dismissed')

  // Unhide the content from the editor's report row.
  const editorRow = rows.filter({ hasText: EDITOR.name })
  await editorRow.getByRole('button', { name: `Actions for report ${editorReport.id}` }).click()
  await admin.getByRole('menuitem', { name: 'Unhide content' }).click()
  const confirm = admin.getByRole('dialog', { name: 'Publish this content again?' })
  await expect(confirm).toBeVisible()
  await confirm.getByRole('button', { name: 'Unhide content' }).click()
  await expect(confirm).toBeHidden()
  await expect(toast(admin, 'The content is published again.')).toBeVisible()
  for (const row of await rows.all()) await expect(row).toContainText('Published')

  await expect.poll(() => anonPostStatus(secondSlug)).toBe(200)
  // Unhiding dismissed the reports that were still open.
  const after = await reportsOnPost(adminContext.request, secondId)
  expect(after.map((r) => r.status)).toEqual(['dismissed', 'dismissed', 'dismissed'])
  expect(after.every((r) => r.content?.status === 'published')).toBe(true)
})

test('4. the dashboard shows the numbers and the KNOWBASE state; the CSV downloads', async () => {
  const stats = await apiJson<{ content: { pending: number }; reports_open: number }>(
    adminContext.request,
    'GET',
    '/admin/stats',
  )
  await admin.goto('/admin')
  await expect(admin.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible()

  const value = async (key: string) =>
    Number(
      ((await admin.getByTestId(`stat-${key}`).locator('dd').textContent()) ?? '').replace(
        /\D/g,
        '',
      ),
    )
  await expect(admin.getByTestId('stat-content-pending')).toContainText('Awaiting approval')
  expect(await value('content-pending')).toBe(stats.content.pending)
  expect(stats.content.pending).toBeGreaterThanOrEqual(0)
  await expect(admin.getByTestId('stat-reports-open')).toContainText('Open reports')
  expect(await value('reports-open')).toBe(stats.reports_open)

  const knowbase = admin.getByTestId('knowbase-status')
  await expect(knowbase.getByRole('heading', { name: 'KNOWBASE connection' })).toBeVisible()
  await expect(knowbase.getByText(/^(Reachable|Unreachable)$/)).toBeVisible()
  await expect(knowbase).toContainText('Last successful request')

  const downloading = admin.waitForEvent('download')
  await admin.getByRole('button', { name: 'Download CSV' }).click()
  const download = await downloading
  expect(download.suggestedFilename()).toMatch(/^urbanfloods-cooperation-stats-.*\.csv$/)
  const csv = readFileSync(await download.path(), 'utf-8')
  expect(csv).toContain('users_by_country')
  expect(csv).toContain('rco87')
})

test('5. the digest command emails the admins a link to the queue', async () => {
  let dockerReady = false
  try {
    const services = execFileSync(
      'docker',
      ['compose', '-f', COMPOSE_FILE, 'ps', '--status', 'running', '--services'],
      { encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] },
    )
    dockerReady = services.split('\n').includes('backend')
  } catch {
    dockerReady = false
  }
  test.skip(!dockerReady, `docker compose (${COMPOSE_FILE}) with a running backend is needed`)

  const since = new Date()
  execFileSync(
    'docker',
    [
      'compose',
      '-f',
      COMPOSE_FILE,
      'exec',
      '-T',
      'backend',
      'python',
      '-m',
      'app.cli',
      'digest',
      '--force',
    ],
    { encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 60_000 },
  )
  for (const account of [ADMIN, EDITOR]) {
    const mail = await waitForEmailTo(account.email, {
      subjectIncludes: 'digest',
      since,
      timeoutMs: 20_000,
    })
    expect(mail.Subject).toContain('Moderation digest')
    expect(mail.Text).toContain('/admin/queue')
  }
})

test('6. users: the superadmin toggles trust; an admin is not offered "Make superadmin"', async () => {
  const menuButton = (page: Page, name: string) =>
    page.getByRole('button', { name: `Actions for ${name}` })
  const usersRow = (page: Page, name: string) =>
    page.getByTestId('users-table').getByRole('row').filter({ hasText: name })
  /** Columns: user, role, verified, trusted, active, created, actions. */
  const trustedCell = (page: Page, name: string) => usersRow(page, name).getByRole('cell').nth(3)

  await admin.goto('/admin/users')
  await expect(admin.getByRole('heading', { level: 1, name: 'Users' })).toBeVisible()
  await admin.getByRole('searchbox', { name: 'Search', exact: true }).fill('newbie')
  await expect(admin).toHaveURL(/[?&]q=newbie(&|$)/)
  await expect(usersRow(admin, NEWBIE.name)).toHaveCount(1)
  await expect(trustedCell(admin, NEWBIE.name)).toHaveText('No')

  await menuButton(admin, NEWBIE.name).click()
  await admin.getByRole('menuitem', { name: 'Mark trusted' }).click()
  let dialog = admin.getByRole('dialog', { name: `Mark ${NEWBIE.name} as trusted?` })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Mark trusted' }).click()
  await expect(dialog).toBeHidden()
  await expect(toast(admin, `${NEWBIE.name} is trusted.`)).toBeVisible()
  await expect(trustedCell(admin, NEWBIE.name)).toHaveText('Yes')

  await menuButton(admin, NEWBIE.name).click()
  await admin.getByRole('menuitem', { name: 'Remove trusted mark' }).click()
  dialog = admin.getByRole('dialog', { name: `Remove the trusted mark from ${NEWBIE.name}?` })
  await dialog.getByRole('button', { name: 'Remove trusted mark' }).click()
  await expect(dialog).toBeHidden()
  await expect(toast(admin, `${NEWBIE.name} is no longer trusted.`)).toBeVisible()
  await expect(trustedCell(admin, NEWBIE.name)).toHaveText('No')
  expect((await newbieUser(adminContext.request)).is_trusted).toBe(false)

  // The superadmin may promote the admin to superadmin (offered, not used)…
  await admin.goto('/admin/users?q=editor')
  await menuButton(admin, EDITOR.name).click()
  await expect(admin.getByRole('menuitem', { name: 'Make superadmin' })).toBeVisible()
  await admin.keyboard.press('Escape')

  // …an admin may not: neither on the superadmin's row nor on their own.
  await editor.goto('/admin/users?q=urbanfloods.example')
  await expect(editor.getByRole('heading', { level: 1, name: 'Users' })).toBeVisible()
  for (const name of [ADMIN.name, EDITOR.name]) {
    await menuButton(editor, name).click()
    const menu = editor.getByRole('menu')
    await expect(menu.getByRole('menuitem').first()).toBeVisible()
    await expect(menu.getByRole('menuitem', { name: 'Make superadmin' })).toHaveCount(0)
    await editor.keyboard.press('Escape')
    await expect(menu).toBeHidden()
  }
})

test('7. the Moderate menu on a post: hide with a reason, unhide, then delete permanently', async () => {
  // Newbie's second post from test 1, published again at the end of test 3.
  test.setTimeout(120_000)
  expect(await anonPostStatus(secondSlug)).toBe(200)
  await admin.goto(`/blog/${secondSlug}`)
  await expect(admin.getByRole('heading', { level: 1, name: secondTitle })).toBeVisible()
  const moderate = admin.getByRole('button', { name: 'Moderate' })

  await moderate.click()
  await admin.getByRole('menuitem', { name: 'Hide', exact: true }).click()
  const hideDialog = admin.getByRole('dialog', { name: 'Hide this content?' })
  await hideDialog.getByLabel('Reason').fill(`Hidden from the menu (e2e ${RUN})`)
  await hideDialog.getByRole('button', { name: 'Hide', exact: true }).click()
  await expect(hideDialog).toBeHidden()
  await expect(toast(admin, 'Hidden from other members.')).toBeVisible()
  await expect(admin.getByTestId('post-status')).toHaveText('Hidden')
  await expect.poll(() => anonPostStatus(secondSlug)).toBe(404)

  await moderate.click()
  await admin.getByRole('menuitem', { name: 'Unhide', exact: true }).click()
  await expect(toast(admin, 'Published again.')).toBeVisible()
  await expect(admin.getByTestId('post-status')).toHaveCount(0)
  await expect.poll(() => anonPostStatus(secondSlug)).toBe(200)

  await moderate.click()
  await admin.getByRole('menuitem', { name: 'Delete permanently' }).click()
  const purge = admin.getByRole('dialog', { name: 'Delete permanently?' })
  await expect(purge).toContainText('All its comments')
  const confirm = purge.getByRole('button', { name: 'Delete permanently' })
  await expect(confirm).toBeDisabled()
  await purge.getByLabel('Type DELETE to confirm').fill('DELETE')
  await confirm.click()
  await admin.waitForURL((url) => url.pathname === '/blog')
  await expect(toast(admin, 'Deleted permanently.')).toBeVisible()
  await expect(admin.getByRole('link', { name: secondTitle, exact: true })).toHaveCount(0)

  const gone = await adminContext.request.get(
    `${API_URL}/api/v1/posts/${encodeURIComponent(secondSlug)}`,
    { headers: API_HEADERS },
  )
  expect(gone.status()).toBe(404)
  const audit = await apiJson<{ items: { metadata: Record<string, unknown> }[] }>(
    adminContext.request,
    'GET',
    `/moderation/log/?action=moderation.purge&target_type=post`,
  )
  expect(audit.items[0]?.metadata).toMatchObject({ content_id: secondId, title: secondTitle })
})

test('8. Uploads tab: an image used by a post cannot be deleted; purging the post removes it', async () => {
  test.setTimeout(120_000)
  const title = `E2E post with an image ${RUN}`
  const alt = `E2E uploaded image ${RUN}`

  // The member (trusted, logged in since test 3) writes a post with a cover image.
  await member.goto('/blog/new')
  await expect(member.getByRole('heading', { level: 1, name: 'Write a post' })).toBeVisible()
  await member.getByLabel('Title', { exact: true }).fill(title)
  const category = member.getByRole('combobox', { name: 'Category' })
  await category.click()
  await member.getByRole('option', { name: 'News', exact: true }).click()
  await member.getByRole('textbox', { name: 'Text', exact: true }).click()
  await member.keyboard.type(`A post with a cover image for the uploads e2e test, ${RUN}.`)
  await member.getByRole('button', { name: 'Add a cover image' }).click()
  const dialog = member.getByRole('dialog', { name: 'Insert image' })
  await dialog.getByLabel('Image file').setInputFiles({
    name: `e2e-upload-${RUN}.png`,
    mimeType: 'image/png',
    buffer: makePng(),
  })
  await dialog.getByLabel('Alternative text').fill(alt)
  await dialog.getByRole('button', { name: 'Upload and insert' }).click()
  await expect(dialog).toBeHidden({ timeout: 20_000 })
  await member.getByRole('button', { name: 'Publish', exact: true }).click()
  const slug = await waitForPostPage(member)
  createdSlugs.add(slug)
  await expect(member.getByRole('heading', { level: 1, name: title })).toBeVisible()

  // Uploads tab: listed with "used in" and a disabled Delete.
  await member.goto('/account?tab=uploads')
  const row = member.getByTestId('upload-row').filter({ hasText: alt })
  await expect(row).toHaveCount(1)
  await expect(row).toContainText('Used in:')
  await expect(row.getByRole('link', { name: title, exact: true })).toHaveAttribute(
    'href',
    `/blog/${slug}`,
  )
  await expect(row.getByRole('button', { name: `Delete image: ${alt}` })).toBeDisabled()

  // The server refuses as well.
  const mine = await apiJson<{ items: { id: number; alt_text: string }[] }>(
    memberContext.request,
    'GET',
    '/uploads/mine/',
  )
  const upload = mine.items.find((u) => u.alt_text === alt)
  if (!upload) throw new Error('The uploaded image is missing from /uploads/mine/')
  const refused = await memberContext.request.delete(`${API_URL}/api/v1/uploads/${upload.id}`, {
    headers: API_HEADERS,
  })
  expect(refused.status()).toBe(409)

  // The admin deletes the post permanently: its only image goes with it.
  const id = await postId(adminContext.request, slug)
  const purged = await apiJson<{ attachments_deleted: number }>(
    adminContext.request,
    'POST',
    `/moderation/post/${id}/purge`,
  )
  expect(purged.attachments_deleted).toBe(1)
  await member.reload()
  await expect(member.getByText('The images you uploaded.', { exact: false })).toBeVisible()
  await expect(member.locator('[aria-busy="true"]')).toHaveCount(0)
  await expect(member.getByTestId('upload-row').filter({ hasText: alt })).toHaveCount(0)
})

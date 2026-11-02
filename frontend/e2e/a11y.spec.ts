import { expect, test, type APIRequestContext, type Browser, type Page } from '@playwright/test'

import { formatViolations, scanA11y } from './a11y'
import {
  ADMIN,
  API_HEADERS,
  API_URL,
  EDITOR,
  MEMBER,
  categoryId,
  deleteThreadViaApi,
  loginViaApi,
  type DemoAccount,
} from './helpers/demo'

/**
 * axe WCAG 2.1 A/AA scan of every page kind (M5, increment 5d). Any violation fails: there is no
 * allow-list. Off by default because it adds ~1 min and three logins (the login limit is 60 per
 * 15 min per IP); run it with `E2E_A11Y=1 npx playwright test a11y`.
 *
 * Besides axe, every scanned view must have exactly one `h1` and `<html lang="en">` (the browser
 * locale is pinned to English in playwright.config.ts).
 */
const PUBLIC_PAGES = [
  '/',
  '/about',
  '/login',
  '/register',
  '/blog',
  // A seeded post with tags and KNOWBASE link cards (backend/scripts/seed_dev.py).
  '/blog/green-roofs-and-retention-basins-what-two-years-of-pilot-data-show',
  '/network',
  // "Flood Management Measures" (7c): the KNOWBASE measures through the proxy.
  '/knowbase/measures',
  '/search?q=flood',
  '/accessibility',
  '/open-data',
]

const MEMBER_PAGES = ['/account', '/network', '/blog/new']

/** Pages whose main widget loads after the h1: wait for it so axe scans it too. */
const READY: Record<string, (page: Page) => ReturnType<Page['locator']>> = {
  // The rich-text editor (a lazy chunk): its editing surface and toolbar.
  '/blog/new': (page) => page.getByRole('textbox', { name: 'Text', exact: true }),
  // The measures load after the h1; with the KNOWBASE unreachable the alert is scanned instead.
  '/knowbase/measures': (page) =>
    page.locator('[data-testid="measure-group"], [role="alert"]').first(),
}

const ADMIN_PAGES = [
  '/admin',
  '/admin/queue',
  '/admin/reports',
  '/admin/deleted',
  '/admin/users',
  '/admin/categories',
  '/admin/tags',
  '/admin/organisations',
  '/admin/expertise',
  '/admin/log',
]

const enabled = () => !!process.env.E2E_A11Y
const SKIP_REASON = 'axe checks run with E2E_A11Y=1'

/** Scan a settled page; returns a report block when axe (or the h1/lang checks) find problems. */
async function scan(page: Page, path: string): Promise<string | null> {
  await page.goto(path)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  // Pages that load data show skeletons first; scan the settled page.
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0)
  const ready = READY[path]
  if (ready) await expect(ready(page)).toBeVisible()

  const problems: string[] = []
  const h1s = await page.locator('h1').count()
  if (h1s !== 1) problems.push(`expected exactly one h1, found ${h1s}`)
  const lang = await page.locator('html').getAttribute('lang')
  if (lang !== 'en') problems.push(`expected <html lang="en">, found ${JSON.stringify(lang)}`)

  const violations = await scanA11y(page)
  const count = violations.reduce((n, v) => n + v.nodes.length, 0)
  console.log(`${path}: ${violations.length} rule(s), ${count} node(s)`)
  if (violations.length) problems.push(formatViolations(violations))
  if (!problems.length) return null
  console.log(problems.join('\n'))
  return `${path}\n${problems.join('\n')}`
}

async function scanAll(page: Page, paths: string[]): Promise<void> {
  const failures: string[] = []
  for (const path of paths) {
    const failure = await scan(page, path)
    if (failure) failures.push(failure)
  }
  expect(failures, failures.join('\n\n')).toEqual([])
}

/** Scan `paths` in a fresh browser context logged in as `account` (one login, through the API). */
async function scanAs(browser: Browser, account: DemoAccount, paths: string[]): Promise<void> {
  const context = await browser.newContext()
  try {
    await loginViaApi(context.request, account)
    await scanAll(await context.newPage(), paths)
  } finally {
    await context.close()
  }
}

test('public pages have no WCAG 2.1 AA violations', async ({ page }) => {
  test.skip(!enabled(), SKIP_REASON)
  await scanAll(page, PUBLIC_PAGES)
})

test.describe('a forum thread', () => {
  // No thread is seeded: the editor opens one (with a tag, a reply and an answer to it) through
  // the API, the forum list (with its card) and the thread are scanned as a visitor, and the
  // thread is deleted again.
  let editor: APIRequestContext
  let slug = ''

  test.beforeAll(async ({ playwright }) => {
    if (!enabled()) return
    editor = await playwright.request.newContext()
    await loginViaApi(editor, EDITOR)
    const res = await editor.post(`${API_URL}/api/v1/threads/`, {
      headers: API_HEADERS,
      data: {
        title: `E2E a11y discussion ${Date.now().toString(36)}`,
        category_id: await categoryId('general'),
        locale: 'en',
        body_html:
          '<p>Which <strong>retention measures</strong> worked for you?</p><ul><li>Basins</li><li>Green roofs</li></ul>',
        tags: ['e2e-a11y'],
      },
    })
    expect(res.status()).toBe(201)
    const thread = (await res.json()) as { id: number; slug: string }
    slug = thread.slug
    const replies = `${API_URL}/api/v1/threads/${thread.id}/replies/`
    const reply = await editor.post(replies, {
      headers: API_HEADERS,
      data: { body_html: '<p>A first reply.</p>' },
    })
    expect(reply.status()).toBe(201)
    const { id: parent } = (await reply.json()) as { id: number }
    const answer = await editor.post(replies, {
      headers: API_HEADERS,
      data: { body_html: '<p>An answer to it.</p>', parent_reply_id: parent },
    })
    expect(answer.status()).toBe(201)
  })

  test.afterAll(async () => {
    if (!editor) return
    if (slug) await deleteThreadViaApi(editor, slug).catch(() => {})
    await editor.dispose()
  })

  test('the forum list and the thread have no WCAG 2.1 AA violations', async ({ page }) => {
    test.skip(!enabled(), SKIP_REASON)
    await scanAll(page, ['/forum', `/forum/t/${slug}`])
  })
})

test('member pages (account, network, the editor) have no WCAG 2.1 AA violations', async ({
  browser,
}) => {
  test.skip(!enabled(), SKIP_REASON)
  await scanAs(browser, MEMBER, MEMBER_PAGES)
})

test('the admin area has no WCAG 2.1 AA violations', async ({ browser }) => {
  // As the seeded superadmin (logged in through the API; the browser context shares the cookie).
  test.skip(!enabled(), SKIP_REASON)
  await scanAs(browser, ADMIN, ADMIN_PAGES)
})

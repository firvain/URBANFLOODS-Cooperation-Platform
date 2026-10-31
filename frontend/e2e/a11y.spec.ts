import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { formatViolations, scanA11y } from './a11y'
import {
  ADMIN,
  API_HEADERS,
  API_URL,
  EDITOR,
  categoryId,
  deleteThreadViaApi,
  loginViaApi,
} from './helpers/demo'

/**
 * axe WCAG 2.1 AA scan of the public pages. Off by default until the M5 accessibility pass;
 * run it with `E2E_A11Y=1 npm run e2e -- a11y`.
 */
const PAGES = [
  '/',
  '/partners',
  '/about',
  '/login',
  '/register',
  '/blog',
  // A seeded post with tags and KNOWBASE link cards (backend/scripts/seed_dev.py).
  '/blog/green-roofs-and-retention-basins-what-two-years-of-pilot-data-show',
]

/** Scan a settled page; returns a report line block when axe finds violations. */
async function scan(page: Page, path: string): Promise<string | null> {
  await page.goto(path)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  // Pages that load data show skeletons first; scan the settled page.
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0)

  const violations = await scanA11y(page)
  const count = violations.reduce((n, v) => n + v.nodes.length, 0)
  console.log(`${path}: ${violations.length} rule(s), ${count} node(s)`)
  if (!violations.length) return null
  console.log(formatViolations(violations))
  return `${path}\n${formatViolations(violations)}`
}

test('public pages have no WCAG 2.1 AA violations', async ({ page }) => {
  test.skip(!process.env.E2E_A11Y, 'axe checks are enabled in M5 (set E2E_A11Y=1)')

  const failures: string[] = []
  for (const path of PAGES) {
    const failure = await scan(page, path)
    if (failure) failures.push(failure)
  }

  expect(failures, failures.join('\n\n')).toEqual([])
})

test.describe('a forum thread', () => {
  // No thread is seeded: the editor opens one (with a tag, a reply and an answer to it) through
  // the API, the forum list (with its card) and the thread are scanned as a visitor, and the
  // thread is deleted again.
  let editor: APIRequestContext
  let slug = ''

  test.beforeAll(async ({ playwright }) => {
    if (!process.env.E2E_A11Y) return
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
    test.skip(!process.env.E2E_A11Y, 'axe checks are enabled in M5 (set E2E_A11Y=1)')

    const failures: string[] = []
    for (const path of ['/forum', `/forum/t/${slug}`]) {
      const failure = await scan(page, path)
      if (failure) failures.push(failure)
    }

    expect(failures, failures.join('\n\n')).toEqual([])
  })
})

test.describe('the admin area', () => {
  // The dashboard and the approval queue, as the seeded superadmin (logged in through the API;
  // the browser context shares the session cookie).
  test('the dashboard and the queue have no WCAG 2.1 AA violations', async ({ browser }) => {
    test.skip(!process.env.E2E_A11Y, 'axe checks are enabled in M5 (set E2E_A11Y=1)')

    const context = await browser.newContext()
    try {
      await loginViaApi(context.request, ADMIN)
      const page = await context.newPage()
      const failures: string[] = []
      for (const path of ['/admin', '/admin/queue']) {
        const failure = await scan(page, path)
        if (failure) failures.push(failure)
      }
      expect(failures, failures.join('\n\n')).toEqual([])
    } finally {
      await context.close()
    }
  })
})

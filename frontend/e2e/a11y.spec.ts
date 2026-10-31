import { expect, test } from '@playwright/test'

import { formatViolations, scanA11y } from './a11y'

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

test('public pages have no WCAG 2.1 AA violations', async ({ page }) => {
  test.skip(!process.env.E2E_A11Y, 'axe checks are enabled in M5 (set E2E_A11Y=1)')

  const failures: string[] = []
  for (const path of PAGES) {
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    // Pages that load data show skeletons first; scan the settled page.
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0)

    const violations = await scanA11y(page)
    const count = violations.reduce((n, v) => n + v.nodes.length, 0)
    console.log(`${path}: ${violations.length} rule(s), ${count} node(s)`)
    if (violations.length) {
      console.log(formatViolations(violations))
      failures.push(`${path}\n${formatViolations(violations)}`)
    }
  }

  expect(failures, failures.join('\n\n')).toEqual([])
})

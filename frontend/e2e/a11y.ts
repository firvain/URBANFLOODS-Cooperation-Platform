import AxeBuilder from '@axe-core/playwright'
import { expect, type Page } from '@playwright/test'

/** WCAG 2.0/2.1 level A and AA rules (the project's target, CLAUDE.md §5). */
export const WCAG_21_AA_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

/**
 * Never scanned: the Vue DevTools overlay that vite-plugin-vue-devtools injects into the dev
 * server only (it is not part of the app or of production builds).
 */
const ALWAYS_EXCLUDED = ['#__vue-devtools-container__']

export interface A11yOptions {
  /** axe rule ids to skip (document why at the call site). */
  disableRules?: string[]
  /** CSS selectors to leave out of the scan (e.g. third-party widgets). */
  exclude?: string[]
}

/** Run axe over the current page; returns the violations (does not assert). */
export async function scanA11y(page: Page, { disableRules = [], exclude = [] }: A11yOptions = {}) {
  let builder = new AxeBuilder({ page }).withTags(WCAG_21_AA_TAGS)
  if (disableRules.length) builder = builder.disableRules(disableRules)
  for (const selector of [...ALWAYS_EXCLUDED, ...exclude]) builder = builder.exclude(selector)
  const { violations } = await builder.analyze()
  return violations
}

/** One line per violation: rule id, impact, node count and the first few targets. */
export function formatViolations(violations: Awaited<ReturnType<typeof scanA11y>>): string {
  return violations
    .map((v) => {
      const targets = v.nodes.slice(0, 3).map((n) => n.target.join(' '))
      return `${v.id} [${v.impact}] ×${v.nodes.length}: ${v.help} — ${targets.join(', ')}`
    })
    .join('\n')
}

/** Assert that axe finds no WCAG 2.1 A/AA violations on the current page. */
export async function expectNoA11yViolations(page: Page, options: A11yOptions = {}) {
  const violations = await scanA11y(page, options)
  expect(violations, formatViolations(violations)).toEqual([])
}

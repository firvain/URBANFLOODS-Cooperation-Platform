import { test as base, expect, type BrowserContext, type Page } from '@playwright/test'

/**
 * The smoke suite's `test`: the standard fixtures plus a Content-Security-Policy guard.
 *
 * Every browser context a smoke test uses (the built-in `context`/`page`, and every context made
 * with the `newPage()` fixture) is watched for CSP violations from our own origin, two ways:
 *
 * - console messages mentioning "Content Security Policy" (Chromium logs every block), except
 *   those located inside challenges.cloudflare.com: Cloudflare's Turnstile iframe logs CSP noise
 *   of its own (seen in production), which our policy neither causes nor can fix;
 * - `securitypolicyviolation` events in documents of our origin (independent of console wording).
 *
 * The guard fails the test at teardown if anything was collected, so a CSP that blocks a script,
 * style, image, frame or request the production build needs fails CI before a deploy.
 */

export const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:3002'
export const OWN_ORIGIN = new URL(BASE_URL).origin
const CLOUDFLARE_ORIGIN = 'https://challenges.cloudflare.com'
const BINDING = '__ufSmokeCspViolation'

export interface CspIssue {
  via: 'console' | 'event'
  text: string
  /** Where it happened: the console message location, or the violating document. */
  url: string
}

interface ViolationEvent {
  directive: string
  blocked: string
  document: string
  source: string
}

const fromCloudflare = (url: string | undefined) => !!url && url.startsWith(CLOUDFLARE_ORIGIN)

async function watchCsp(context: BrowserContext, issues: CspIssue[]): Promise<void> {
  context.on('console', (msg) => {
    const text = msg.text()
    if (!/Content[- ]Security[- ]Policy/i.test(text)) return
    const url = msg.location().url ?? ''
    if (fromCloudflare(url)) return
    issues.push({ via: 'console', text, url })
  })

  await context.exposeBinding(BINDING, (_source, v: ViolationEvent) => {
    // A violation raised by Cloudflare's own script running in our page (Turnstile's api.js) is
    // Cloudflare's noise too; a broken Turnstile fails the auth tests anyway (no token).
    if (fromCloudflare(v.source) || fromCloudflare(v.blocked)) return
    issues.push({
      via: 'event',
      text: `${v.directive} blocked ${v.blocked || '(inline)'}${v.source ? ` from ${v.source}` : ''}`,
      url: v.document,
    })
  })
  await context.addInitScript(
    ({ origin, binding }) => {
      // Our documents only: never instrument Cloudflare's iframe.
      if (location.origin !== origin) return
      document.addEventListener('securitypolicyviolation', (e) => {
        const report = (window as unknown as Record<string, (v: unknown) => void>)[binding]
        report?.({
          directive: e.effectiveDirective,
          blocked: e.blockedURI,
          document: e.documentURI,
          source: e.sourceFile,
        })
      })
    },
    { origin: OWN_ORIGIN, binding: BINDING },
  )
}

interface SmokeFixtures {
  /** CSP violations collected during the test; must be empty when it ends. */
  cspIssues: CspIssue[]
  /** A page in a fresh, watched browser context (no cookies); closed after the test. */
  newPage: () => Promise<Page>
}

export const test = base.extend<SmokeFixtures>({
  cspIssues: [
    async ({}, use) => {
      const issues: CspIssue[] = []
      await use(issues)
      expect(issues, 'Content Security Policy violations from our own origin').toEqual([])
    },
    { auto: true },
  ],

  context: async ({ context, cspIssues }, use) => {
    await watchCsp(context, cspIssues)
    await use(context)
  },

  newPage: async ({ browser, cspIssues }, use) => {
    const contexts: BrowserContext[] = []
    await use(async () => {
      const context = await browser.newContext()
      contexts.push(context)
      await watchCsp(context, cspIssues)
      return context.newPage()
    })
    for (const context of contexts) await context.close()
  },
})

export { expect }

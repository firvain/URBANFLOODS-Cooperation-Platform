import {
  expect,
  type APIRequestContext,
  type Locator,
  type Page,
  type Response,
} from '@playwright/test'

import { BASE_URL } from './fixtures'

/**
 * Helpers for the production-mode smoke suite. Everything goes through the frontend nginx
 * (BASE_URL, :3002), the single origin production serves: SPA, /api, /static, /feeds.
 */

/** The backend's CSRF middleware wants this header on every request carrying the cookie. */
export const API_HEADERS = { 'X-Requested-With': 'XMLHttpRequest' }

/** What Cloudflare's always-passing test site key yields; the test secret accepts only it. */
export const DUMMY_TURNSTILE_TOKEN = 'XXXX.DUMMY.TOKEN.XXXX'

export const VERIFY_SUBJECT = 'Verify your email address'
export const RESET_SUBJECT = 'Reset your password'

/** `/api/v1<path>` through nginx. */
export const apiUrl = (path: string) => `${BASE_URL}/api/v1${path}`

/** The superadmin scripts/smoke.sh creates with the backend CLI before the suite runs. */
export function smokeAdmin(): { email: string; password: string; name: string } {
  const email = process.env.E2E_SMOKE_ADMIN_EMAIL
  const password = process.env.E2E_SMOKE_ADMIN_PASSWORD
  if (!email || !password) {
    throw new Error(
      'E2E_SMOKE_ADMIN_EMAIL / E2E_SMOKE_ADMIN_PASSWORD are not set: run the suite through scripts/smoke.sh',
    )
  }
  return { email, password, name: process.env.E2E_SMOKE_ADMIN_NAME ?? 'Smoke Admin' }
}

/** The header's account dropdown trigger (desktop layout), labelled with the display name. */
export const userMenu = (page: Page, displayName: string) =>
  page.getByRole('banner').getByRole('button', { name: displayName })

/** The header's "Log in" link, shown only when logged out. */
export const loginLink = (page: Page) =>
  page.getByRole('banner').getByRole('link', { name: 'Log in' })

/** A toast (Nuxt UI also mirrors it into a hidden live region, hence `exact`). */
export const toast = (page: Page, text: string) => page.getByText(text, { exact: true })

/**
 * The Turnstile widget rendered (Cloudflare's script loaded under our CSP and drew its iframe in
 * the form) and solved: the form's submit button only enables once the widget has handed over a
 * token, so waiting for it proves the whole client-side Turnstile path works.
 * The iframe lives in a closed shadow root (no locator reaches it), so it is found among the
 * page's frames instead.
 */
export async function expectTurnstileSolved(page: Page, submitName: string): Promise<void> {
  const widget = page.locator('.cf-turnstile')
  await expect(widget, 'the Turnstile widget container is rendered').toBeVisible()
  await expect
    .poll(
      () => page.frames().some((f) => f.url().startsWith('https://challenges.cloudflare.com/')),
      { message: 'Cloudflare drew the Turnstile iframe', timeout: 20_000 },
    )
    .toBe(true)
  await expect
    .poll(async () => (await widget.boundingBox())?.height ?? 0, {
      message: 'the Turnstile widget takes up space in the form',
    })
    .toBeGreaterThan(0)
  await expect(
    page.getByRole('button', { name: submitName }),
    'submit enables once the widget has a token',
  ).toBeEnabled({ timeout: 30_000 })
}

/**
 * Click `submitName` and return the API response of `METHOD /api/v1<path>` it triggers, with the
 * Turnstile token the browser sent (null when the form sent none).
 */
export async function submitAndCapture(
  page: Page,
  submitName: string,
  method: string,
  path: string,
): Promise<{ response: Response; token: string | null }> {
  const [response] = await Promise.all([
    page.waitForResponse(
      (r) => r.request().method() === method && new URL(r.url()).pathname === `/api/v1${path}`,
    ),
    page.getByRole('button', { name: submitName }).click(),
  ])
  const body = (response.request().postDataJSON() ?? {}) as { turnstile_token?: string | null }
  return { response, token: body.turnstile_token ?? null }
}

/** Log in through the form; ends on the home page with the account menu in the header. */
export async function loginViaForm(
  page: Page,
  email: string,
  password: string,
  displayName: string,
): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Log in' }).click()
  await page.waitForURL('/')
  await expect(userMenu(page, displayName)).toBeVisible()
}

/** Log out through the account menu; ends on the home page, logged out. */
export async function logoutViaMenu(page: Page, displayName: string): Promise<void> {
  await userMenu(page, displayName).click()
  await page.getByRole('menuitem', { name: 'Log out' }).click()
  await expect(loginLink(page)).toBeVisible()
}

export interface NewAccount {
  email: string
  password: string
  displayName: string
}

/**
 * Register through the API with the dummy Turnstile token (the backend verifies it against
 * Cloudflare with the test secret). For accounts a test needs but whose registration form is not
 * what it tests; the form itself is covered by the register test.
 */
export async function registerViaApi(
  request: APIRequestContext,
  account: NewAccount,
): Promise<void> {
  const res = await request.post(apiUrl('/auth/register'), {
    headers: API_HEADERS,
    data: {
      email: account.email,
      password: account.password,
      display_name: account.displayName,
      locale: 'en',
      accept_terms: true,
      turnstile_token: DUMMY_TURNSTILE_TOKEN,
    },
  })
  expect(res.status(), `register ${account.email} through the API`).toBe(201)
}

/** Status of an anonymous `GET /api/v1/posts/:slug`. */
export async function anonPostStatus(slug: string): Promise<number> {
  const res = await fetch(apiUrl(`/posts/${encodeURIComponent(slug)}`))
  return res.status
}

/** Whether an <img> has loaded real pixels (decoded, non-zero size). */
export async function imageLoaded(img: Locator): Promise<boolean> {
  return img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)
}

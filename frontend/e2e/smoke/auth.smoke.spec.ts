import { strongPassword, uniqueEmail } from '../helpers/accounts'
import { countEmailsTo, extractLink, waitForEmailTo } from '../helpers/mailpit'
import { expect, test } from './fixtures'
import {
  RESET_SUBJECT,
  VERIFY_SUBJECT,
  expectTurnstileSolved,
  loginViaForm,
  logoutViaMenu,
  registerViaApi,
  submitAndCapture,
  userMenu,
  type NewAccount,
} from './helpers'

/**
 * Production-mode smoke: the account flows behind Cloudflare Turnstile (on, with Cloudflare's
 * test keys), real SMTP to Mailpit, Secure session cookies, all through the production nginx.
 * Every form that needs a Turnstile token is submitted through the UI and the request is checked
 * for the token and the backend's answer: the 2026-11-01 bug (resend verification and forgot
 * password sent no token, so they always failed in production) fails tests 3 and 4.
 *
 * Tests 1-3 share one account and run in order. Rate limits are the real ones: this file uses
 * 2 registrations, 2 logins, 1 password reset request and 1 resend.
 */
test.describe.configure({ mode: 'serial' })

const RUN = Date.now().toString(36)
const SESSION_COOKIE = 'uf_session'

const account: NewAccount = {
  email: uniqueEmail('smoke-auth'),
  password: strongPassword(),
  displayName: `Smoke Tester ${RUN}`,
}
const resetPassword = strongPassword()

test('1. register through the form (Turnstile), then verify through the emailed link', async ({
  page,
}) => {
  await page.goto('/register')
  await expect(page.getByRole('heading', { level: 1, name: 'Create an account' })).toBeVisible()

  await page.getByLabel('Email').fill(account.email)
  await page.getByLabel('Password', { exact: true }).fill(account.password)
  await page.getByLabel('Display name').fill(account.displayName)
  await page.getByRole('checkbox', { name: /I accept the terms of use/ }).check()

  await expectTurnstileSolved(page, 'Create account')
  const { response, token } = await submitAndCapture(
    page,
    'Create account',
    'POST',
    '/auth/register',
  )
  expect(response.status(), `register: ${await response.text()}`).toBe(201)
  expect(token, 'the register form sends the Turnstile token').toBeTruthy()
  await expect(page.getByRole('heading', { level: 1, name: 'Check your email' })).toBeVisible()

  const message = await waitForEmailTo(account.email, { subjectIncludes: VERIFY_SUBJECT })
  await page.goto(extractLink(message, '/verify-email?token='))
  await expect(page.getByRole('heading', { level: 1, name: 'Verify your email' })).toBeVisible()
  await page.getByRole('button', { name: 'Verify my email' }).click()
  await expect(
    page.getByText('Your email address is verified and you are logged in. Welcome!'),
  ).toBeVisible()
  await page.waitForURL('/', { timeout: 15_000 })
  await expect(userMenu(page, account.displayName)).toBeVisible()
})

test('2. log in and out; the session cookie is Secure, HttpOnly and SameSite=Lax', async ({
  page,
  context,
}) => {
  await loginViaForm(page, account.email, account.password, account.displayName)

  const cookie = (await context.cookies()).find((c) => c.name === SESSION_COOKIE)
  expect(cookie, `the ${SESSION_COOKIE} cookie is set`).toBeDefined()
  expect(cookie!.secure, 'Secure').toBe(true)
  expect(cookie!.httpOnly, 'HttpOnly').toBe(true)
  expect(cookie!.sameSite, 'SameSite').toBe('Lax')

  await logoutViaMenu(page, account.displayName)
  await expect
    .poll(async () => (await context.cookies()).some((c) => c.name === SESSION_COOKIE))
    .toBe(false)
})

test('3. forgot password (Turnstile) → emailed link → new password → log in with it', async ({
  page,
}) => {
  await page.goto('/forgot-password')
  await expect(page.getByRole('heading', { level: 1, name: 'Forgot your password' })).toBeVisible()
  await page.getByLabel('Email').fill(account.email)

  await expectTurnstileSolved(page, 'Send reset link')
  const requestedAt = new Date()
  const { response, token } = await submitAndCapture(
    page,
    'Send reset link',
    'POST',
    '/auth/password/forgot',
  )
  expect(response.status(), `forgot password: ${await response.text()}`).toBe(202)
  expect(token, 'the forgot-password form sends the Turnstile token').toBeTruthy()
  await expect(page.getByText(/If an account exists for that address/)).toBeVisible()

  const message = await waitForEmailTo(account.email, {
    subjectIncludes: RESET_SUBJECT,
    since: requestedAt,
  })
  await page.goto(extractLink(message, '/reset-password?token='))
  await expect(page.getByRole('heading', { level: 1, name: 'Choose a new password' })).toBeVisible()
  await page.getByLabel('New password', { exact: true }).fill(resetPassword)
  await page.getByLabel('Confirm new password').fill(resetPassword)
  await page.getByRole('button', { name: 'Save new password' }).click()
  // The reset signs the user in.
  await page.waitForURL('/')
  await expect(userMenu(page, account.displayName)).toBeVisible()

  await logoutViaMenu(page, account.displayName)
  await loginViaForm(page, account.email, resetPassword, account.displayName)
})

test('4. resend verification from the anonymous form (Turnstile): 202 and a second email', async ({
  page,
  request,
}) => {
  const pending: NewAccount = {
    email: uniqueEmail('smoke-resend'),
    password: strongPassword(),
    displayName: `Smoke Resend ${RUN}`,
  }
  await registerViaApi(request, pending)
  await waitForEmailTo(pending.email, { subjectIncludes: VERIFY_SUBJECT })
  expect(await countEmailsTo(pending.email, VERIFY_SUBJECT)).toBe(1)

  // /verify-email without a token: the error state offers the anonymous resend form.
  await page.goto('/verify-email')
  await expect(page.getByText('We could not verify your email address')).toBeVisible()
  await page.getByLabel('Email').fill(pending.email)

  await expectTurnstileSolved(page, 'Send a new link')
  const { response, token } = await submitAndCapture(
    page,
    'Send a new link',
    'POST',
    '/auth/resend-verification',
  )
  expect(response.status(), `resend verification: ${await response.text()}`).toBe(202)
  expect(token, 'the resend form sends the Turnstile token').toBeTruthy()
  await expect(
    page.getByText(
      'If the address belongs to an account that still needs verification, a new link is on its way.',
    ),
  ).toBeVisible()

  await expect
    .poll(() => countEmailsTo(pending.email, VERIFY_SUBJECT), {
      message: 'a second verification email arrives',
      timeout: 15_000,
    })
    .toBe(2)
})

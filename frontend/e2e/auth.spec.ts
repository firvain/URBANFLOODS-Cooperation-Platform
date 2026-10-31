import { expect, test, type Browser, type Page } from '@playwright/test'

import { strongPassword, uniqueEmail } from './helpers/accounts'
import { extractLink, waitForEmailTo } from './helpers/mailpit'

/**
 * M1 auth flow against the real dev stack: register → Mailpit → verify → account → change
 * password → change the email address (link sent to the new address) → log out → log in with
 * the new address → partnership (/partners → /about#partnership); plus wrong-password and
 * forgot-password flows.
 * The tests share one page (and so one session cookie) and run in order.
 */
test.describe.configure({ mode: 'serial' })

const LEAD_PARTNER = 'University of Western Macedonia'
const VERIFY_SUBJECT = 'Verify your email address'
const RESET_SUBJECT = 'Reset your password'

const email = uniqueEmail('auth')
/** The address test 3b switches the account to. */
const newEmail = uniqueEmail('auth-new')
/** The account's address: `email` until test 3b confirms the change, `newEmail` after. */
let accountEmail = email
const displayName = `E2E Tester ${Date.now().toString(36)}`
const firstPassword = strongPassword()
const secondPassword = strongPassword()
const resetPassword = strongPassword()

let page: Page

/** The header's account dropdown trigger (desktop layout), labelled with the display name. */
const userMenu = (p: Page) => p.getByRole('banner').getByRole('button', { name: displayName })
/** The header's "Log in" link, shown only when logged out. */
const loginLink = (p: Page) => p.getByRole('banner').getByRole('link', { name: 'Log in' })

async function login(p: Page, address: string, password: string) {
  await p.goto('/login')
  await p.getByLabel('Email').fill(address)
  await p.getByLabel('Password', { exact: true }).fill(password)
  await p.getByRole('button', { name: 'Log in' }).click()
}

/** A logged-out page in a fresh context (the shared page keeps its session). */
async function freshPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext()
  return context.newPage()
}

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage()
})

test.afterAll(async () => {
  await page.context().close()
})

test('1. register via the form shows "Check your email"', async () => {
  await page.goto('/register')
  await expect(page.getByRole('heading', { level: 1, name: 'Create an account' })).toBeVisible()

  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password', { exact: true }).fill(firstPassword)
  await page.getByLabel('Display name').fill(displayName)

  // Nuxt UI's USelectMenu: a trigger button labelled by the field, then a searchable listbox.
  const organisation = page.getByRole('button', { name: 'Organisation' })
  await organisation.click()
  await page.getByRole('option', { name: LEAD_PARTNER }).click()
  await expect(organisation).toContainText(LEAD_PARTNER)

  await page.getByRole('checkbox', { name: /I accept the terms of use/ }).check()
  await page.getByRole('button', { name: 'Create account' }).click()

  await expect(page.getByRole('heading', { level: 1, name: 'Check your email' })).toBeVisible()
  await expect(page.getByText(`We sent a verification link to ${email}.`)).toBeVisible()
})

test('2. the emailed link verifies the address and logs the user in', async () => {
  const message = await waitForEmailTo(email, { subjectIncludes: VERIFY_SUBJECT })
  const link = extractLink(message, '/verify-email?token=')

  await page.goto(link)
  await expect(page.getByRole('heading', { level: 1, name: 'Verify your email' })).toBeVisible()
  // Nothing is sent until the button is pressed (mail scanners open links but do not click).
  await page.getByRole('button', { name: 'Verify my email' }).click()
  await expect(
    page.getByText('Your email address is verified and you are logged in. Welcome!'),
  ).toBeVisible()

  // The success screen moves on to the home page by itself.
  await page.waitForURL('/', { timeout: 15_000 })
  await expect(userMenu(page)).toBeVisible()
})

test('3. account page: change the password', async () => {
  await userMenu(page).click()
  await page.getByRole('menuitem', { name: 'Account' }).click()
  await expect(page).toHaveURL(/\/account$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Account' })).toBeVisible()

  await page.getByRole('tab', { name: 'Password & email' }).click()
  await expect(page).toHaveURL(/\/account\?tab=password$/)

  // The tab has two sections (password, email address), each with a "Current password" field.
  const panel = page.getByRole('region', { name: 'Password', exact: true })
  await panel.getByLabel('Current password').fill(firstPassword)
  await panel.getByLabel('New password', { exact: true }).fill(secondPassword)
  await panel.getByLabel('Confirm new password').fill(secondPassword)
  await panel.getByRole('button', { name: 'Change password' }).click()

  await expect(panel.getByText('Password changed')).toBeVisible()
  await expect(panel.getByLabel('Current password')).toHaveValue('')
})

test('3b. account page: change the email address through the confirmation link', async () => {
  await page.goto('/account?tab=password')
  const section = page.getByRole('region', { name: 'Email address' })
  await expect(section.getByText(email, { exact: true })).toBeVisible()

  const requestedAt = new Date()
  await section.getByLabel('New email address').fill(newEmail)
  await section.getByLabel('Current password').fill(secondPassword)
  await section.getByRole('button', { name: 'Send confirmation link' }).click()
  await expect(
    section.getByText(`We sent a confirmation link to ${newEmail}.`, { exact: false }),
  ).toBeVisible()

  // The link goes to the new address; the account keeps the old one until it is opened.
  const message = await waitForEmailTo(newEmail, { since: requestedAt })
  await page.goto(extractLink(message, '/confirm-email?token='))
  await expect(
    page.getByRole('heading', { level: 1, name: 'Confirm your new email address' }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Confirm the new address' }).click()
  await expect(page.getByText('Your email address has been changed')).toBeVisible()
  await expect(page.getByText(`Your account now uses ${newEmail}.`)).toBeVisible()
  accountEmail = newEmail

  // The session survives the change (the page offers the account, not the login), and a reload
  // (a fresh GET /auth/me) shows the new address.
  await expect(page.getByRole('link', { name: 'Go to your account' })).toBeVisible()
  await page.goto('/account?tab=password')
  await expect(
    page.getByRole('region', { name: 'Email address' }).getByText(newEmail, { exact: true }),
  ).toBeVisible()
})

test('4. log out via the user menu', async () => {
  await userMenu(page).click()
  await page.getByRole('menuitem', { name: 'Log out' }).click()

  await expect(loginLink(page)).toBeVisible()
  await expect(userMenu(page)).toHaveCount(0)
  // Logging out always returns to the home page.
  await expect(page).toHaveURL('/')
})

test('5. log in with the new password', async () => {
  await login(page, accountEmail, secondPassword)

  await page.waitForURL('/')
  await expect(userMenu(page)).toBeVisible()
  await expect(loginLink(page)).toHaveCount(0)
})

test('6. /partners opens the partnership section of About with the live organisations', async () => {
  await page.goto('/partners')
  await expect(page).toHaveURL(/\/about#partnership$/)
  await expect(page.getByRole('heading', { level: 1, name: 'About URBANFLOODS' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: 'Partnership' })).toBeInViewport()

  const lead = page.getByTestId('lead-partner')
  await expect(lead).toContainText(LEAD_PARTNER)
  await expect(lead.getByText('LEAD', { exact: true })).toBeVisible()

  const tiles = page.getByTestId('partner-tile')
  await expect(tiles.first()).toBeVisible()
  expect(await tiles.count()).toBeGreaterThanOrEqual(20)
})

test('7. a wrong password shows the inline invalid-credentials error', async ({ browser }) => {
  const guest = await freshPage(browser)
  try {
    await login(guest, accountEmail, `${secondPassword}-wrong`)

    await expect(
      guest.getByRole('alert').filter({ hasText: 'Incorrect email or password.' }),
    ).toBeVisible()
    await expect(guest).toHaveURL(/\/login$/)
    await expect(userMenu(guest)).toHaveCount(0)
  } finally {
    await guest.context().close()
  }
})

test('8. forgot password: email link → new password → logged in', async ({ browser }) => {
  const guest = await freshPage(browser)
  try {
    await guest.goto('/login')
    await guest.getByRole('link', { name: 'Forgot your password?' }).click()
    await expect(
      guest.getByRole('heading', { level: 1, name: 'Forgot your password' }),
    ).toBeVisible()

    const requestedAt = new Date()
    await guest.getByLabel('Email').fill(accountEmail)
    await guest.getByRole('button', { name: 'Send reset link' }).click()
    await expect(guest.getByText(/If an account exists for that address/)).toBeVisible()

    const message = await waitForEmailTo(accountEmail, {
      subjectIncludes: RESET_SUBJECT,
      since: requestedAt,
    })
    await guest.goto(extractLink(message, '/reset-password?token='))
    await expect(
      guest.getByRole('heading', { level: 1, name: 'Choose a new password' }),
    ).toBeVisible()

    await guest.getByLabel('New password', { exact: true }).fill(resetPassword)
    await guest.getByLabel('Confirm new password').fill(resetPassword)
    await guest.getByRole('button', { name: 'Save new password' }).click()

    await guest.waitForURL('/')
    await expect(userMenu(guest)).toBeVisible()
  } finally {
    await guest.context().close()
  }

  // Resetting logs out every other session, including the shared page's.
  await page.reload()
  await expect(loginLink(page)).toBeVisible()
})

import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import AccountView from '@/views/AccountView.vue'
import i18n from '@/i18n'
import { callsTo, makeUser, mockApi, reply, replyError, type Handler } from './helpers/api'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'
const EMAIL = 'POST /api/v1/auth/me/email'
const USER = makeUser({ email: 'maria@example.org' })
const NEW_EMAIL = 'maria.new@example.org'

afterEach(unmountAll)

function routes(extra: Record<string, Handler> = {}) {
  return { [ME]: reply(200, USER), ...extra }
}

async function mountPasswordTab() {
  return mountWithApp(AccountView, { path: '/account?tab=password' })
}

/** The email change form (the second form of the tab, after the password form). */
function emailForm(wrapper: VueWrapper) {
  const form = wrapper.findAll('form').find((f) => f.find('input[type="email"]').exists())
  if (!form) throw new Error('no email form')
  return form
}

async function fill(wrapper: VueWrapper, address: string, password: string) {
  const form = emailForm(wrapper)
  await form.find('input[type="email"]').setValue(address)
  await form.find('input[autocomplete="current-password"]').setValue(password)
}

async function submit(wrapper: VueWrapper) {
  await emailForm(wrapper).trigger('submit')
  await flushPromises()
}

function describedText(input: Element): string {
  return (input.getAttribute('aria-describedby') ?? '')
    .split(' ')
    .map((id) => document.getElementById(id)?.textContent ?? '')
    .join(' ')
}

describe('AccountView: email change', () => {
  it('labels the tab "Password & email" and has a heading per section', async () => {
    mockApi(routes())
    const { wrapper } = await mountPasswordTab()
    expect(t('account.tabs.password')).toBe('Password & email')
    const headings = wrapper.findAll('h2').map((h) => h.text())
    expect(headings).toContain(t('account.password.title'))
    expect(headings).toContain(t('account.email.title'))
  })

  it('shows the current address as text and an email input', async () => {
    mockApi(routes())
    const { wrapper } = await mountPasswordTab()
    const form = emailForm(wrapper)
    expect(form.text()).toContain(t('account.email.intro'))
    expect(form.text()).toContain(t('account.email.current'))
    expect(form.text()).toContain('maria@example.org')
    // The current address is text, not a prefilled input.
    expect((form.find('input[type="email"]').element as HTMLInputElement).value).toBe('')
    expect(form.find('input[type="email"]').attributes('autocomplete')).toBe('email')
  })

  it('posts the new address and the password, then shows the "sent" status', async () => {
    const fetchMock = mockApi(
      routes({ [EMAIL]: reply(202, { code: 'auth.email_change_sent', message: 'Sent' }) }),
    )
    const { wrapper, auth } = await mountPasswordTab()
    await fill(wrapper, `  ${NEW_EMAIL} `, 'my password 123')
    await submit(wrapper)

    const calls = callsTo(fetchMock, EMAIL)
    expect(calls).toHaveLength(1)
    expect(calls[0]!.body).toEqual({ new_email: NEW_EMAIL, current_password: 'my password 123' })
    const status = emailForm(wrapper).find('[aria-live="polite"]')
    expect(status.text()).toContain(t('account.email.sent', { email: NEW_EMAIL }))
    // The form is cleared; the account keeps its address until the link is opened.
    const form = emailForm(wrapper)
    expect((form.find('input[type="email"]').element as HTMLInputElement).value).toBe('')
    expect(
      (form.find('input[autocomplete="current-password"]').element as HTMLInputElement).value,
    ).toBe('')
    expect(auth.user?.email).toBe('maria@example.org')
  })

  it('validates the fields on the client', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountPasswordTab()
    await fill(wrapper, 'not-an-address', '')
    await submit(wrapper)
    expect(callsTo(fetchMock, EMAIL)).toHaveLength(0)
    const form = emailForm(wrapper)
    expect(form.text()).toContain(t('errors.fields.invalid'))
    expect(form.text()).toContain(t('errors.fields.required'))
  })

  it('maps auth.invalid_credentials to the password field', async () => {
    mockApi(routes({ [EMAIL]: replyError(400, 'auth.invalid_credentials') }))
    const { wrapper, auth } = await mountPasswordTab()
    await fill(wrapper, NEW_EMAIL, 'wrong password 1')
    await submit(wrapper)
    const password = emailForm(wrapper).find('input[autocomplete="current-password"]')
    expect(password.attributes('aria-invalid')).toBe('true')
    expect(describedText(password.element)).toContain(t('account.password.wrongCurrent'))
    expect(auth.isAuthenticated).toBe(true)
  })

  it('maps fields.new_email = auth.email_same to the email field', async () => {
    mockApi(
      routes({ [EMAIL]: replyError(422, 'validation.failed', { new_email: 'auth.email_same' }) }),
    )
    const { wrapper } = await mountPasswordTab()
    await fill(wrapper, 'maria@example.org', 'my password 123')
    await submit(wrapper)
    const input = emailForm(wrapper).find('input[type="email"]')
    expect(input.attributes('aria-invalid')).toBe('true')
    expect(describedText(input.element)).toContain(t('account.email.same'))
  })

  it('shows any other error in the form alert', async () => {
    mockApi(routes({ [EMAIL]: replyError(500, 'server.error') }))
    const { wrapper } = await mountPasswordTab()
    await fill(wrapper, NEW_EMAIL, 'my password 123')
    await submit(wrapper)
    expect(emailForm(wrapper).find('[role="alert"]').text()).toContain(t('errors.generic'))
  })
})

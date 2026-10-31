import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import ConfirmEmailView from '@/views/ConfirmEmailView.vue'
import i18n from '@/i18n'
import {
  callsTo,
  deferred,
  jsonResponse,
  makeUser,
  mockApi,
  reply,
  replyError,
} from './helpers/api'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const CONFIRM = 'POST /api/v1/auth/email/confirm'
const ME = 'GET /api/v1/auth/me'
const NEW_EMAIL = 'maria.new@example.org'

afterEach(unmountAll)

const confirmButton = (wrapper: VueWrapper) =>
  wrapper.findAll('button').find((b) => b.text().includes(t('auth.confirmEmail.button')))

/** Mounts the page and presses the button, as a person (not a mail scanner) would. */
async function mountAndConfirm(path: string) {
  const mounted = await mountWithApp(ConfirmEmailView, { path })
  await flushPromises()
  await confirmButton(mounted.wrapper)!.trigger('click')
  await flushPromises()
  return mounted
}

describe('ConfirmEmailView', () => {
  it('does not send the token on mount (mail scanners open links but do not click)', async () => {
    const fetchMock = mockApi({ [CONFIRM]: reply(200, makeUser({ email: NEW_EMAIL })) })
    const { wrapper } = await mountWithApp(ConfirmEmailView, { path: '/confirm-email?token=abc' })
    await flushPromises()

    expect(callsTo(fetchMock, CONFIRM)).toHaveLength(0)
    expect(wrapper.text()).not.toContain(t('auth.confirmEmail.success'))
  })

  it('shows the prompt and a real confirm button', async () => {
    mockApi()
    const { wrapper } = await mountWithApp(ConfirmEmailView, { path: '/confirm-email?token=abc' })
    await flushPromises()

    expect(wrapper.find('h1').text()).toBe(t('auth.confirmEmail.title'))
    expect(wrapper.text()).toContain(t('auth.confirmEmail.prompt'))
    const button = confirmButton(wrapper)
    expect(button).toBeDefined()
    expect(button!.attributes('type')).toBe('button')
    expect(button!.attributes('disabled')).toBeUndefined()
  })

  it('posts the token from the query after the click and shows the new address', async () => {
    const fetchMock = mockApi({ [CONFIRM]: reply(200, makeUser({ email: NEW_EMAIL })) })
    const { wrapper } = await mountAndConfirm('/confirm-email?token=abc123')

    expect(callsTo(fetchMock, CONFIRM)).toHaveLength(1)
    expect(callsTo(fetchMock, CONFIRM)[0]?.body).toEqual({ token: 'abc123' })
    expect(wrapper.find('h1').attributes('tabindex')).toBe('-1')
    expect(wrapper.find('h1').text()).toBe(t('auth.confirmEmail.title'))
    const live = wrapper.find('[aria-live="polite"]')
    expect(live.text()).toContain(t('auth.confirmEmail.success'))
    expect(live.text()).toContain(t('auth.confirmEmail.nowUsing', { email: NEW_EMAIL }))
    expect(live.text()).toContain(NEW_EMAIL)
    expect(confirmButton(wrapper)).toBeUndefined()
  })

  it('sends exactly one request when the button is clicked twice quickly', async () => {
    const pending = deferred<Response>()
    const fetchMock = mockApi({ [CONFIRM]: () => pending.promise })
    const { wrapper } = await mountWithApp(ConfirmEmailView, { path: '/confirm-email?token=abc' })
    await flushPromises()

    const button = confirmButton(wrapper)!
    await button.trigger('click')
    await button.trigger('click')
    await flushPromises()
    expect(callsTo(fetchMock, CONFIRM)).toHaveLength(1)
    // While pending the button stays on screen, disabled and showing it is busy.
    expect(confirmButton(wrapper)!.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain(t('auth.confirmEmail.confirming'))

    pending.resolve(jsonResponse(makeUser({ email: NEW_EMAIL })))
    await flushPromises()
    expect(callsTo(fetchMock, CONFIRM)).toHaveLength(1)
    expect(wrapper.text()).toContain(t('auth.confirmEmail.success'))
  })

  it('updates the store when the same user is signed in, and links to the account', async () => {
    mockApi({
      [ME]: reply(200, makeUser({ id: 1 })),
      [CONFIRM]: reply(200, makeUser({ id: 1, email: NEW_EMAIL })),
    })
    const { wrapper, auth } = await mountAndConfirm('/confirm-email?token=abc')

    expect(auth.isAuthenticated).toBe(true)
    expect(auth.user?.email).toBe(NEW_EMAIL)
    const link = wrapper.find('a[href="/account"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain(t('auth.confirmEmail.goToAccount'))
  })

  it('does not sign anyone in when the link is opened signed out', async () => {
    mockApi({ [CONFIRM]: reply(200, makeUser({ email: NEW_EMAIL })) })
    const { wrapper, auth } = await mountAndConfirm('/confirm-email?token=abc')

    expect(auth.isAuthenticated).toBe(false)
    expect(auth.user).toBeNull()
    const link = wrapper.find('a[href="/login"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain(t('auth.confirmEmail.signIn'))
  })

  it('leaves another signed-in user alone', async () => {
    const other = makeUser({ id: 2, email: 'nikos@example.org', display_name: 'Nikos' })
    mockApi({
      [ME]: reply(200, other),
      [CONFIRM]: reply(200, makeUser({ id: 1, email: NEW_EMAIL })),
    })
    const { auth } = await mountAndConfirm('/confirm-email?token=abc')

    expect(auth.user?.id).toBe(2)
    expect(auth.user?.email).toBe('nikos@example.org')
  })

  it('shows the error and the retry hint on 400 (signed out: link to log in)', async () => {
    mockApi({ [CONFIRM]: replyError(400, 'auth.token_invalid') })
    const { wrapper } = await mountAndConfirm('/confirm-email?token=bad')

    const alert = wrapper.find('[role="alert"]')
    expect(alert.text()).toContain(t('auth.confirmEmail.failed'))
    expect(alert.text()).toContain(t('errors.api.auth.token_invalid'))
    expect(wrapper.text()).toContain(t('auth.confirmEmail.retryHint'))
    expect(wrapper.find('a[href="/login"]').exists()).toBe(true)
    expect(confirmButton(wrapper)).toBeUndefined()
  })

  it('links a signed-in user to the password & email tab on error', async () => {
    mockApi({
      [ME]: reply(200, makeUser()),
      [CONFIRM]: replyError(409, 'auth.email_taken'),
    })
    const { wrapper } = await mountAndConfirm('/confirm-email?token=x')

    expect(wrapper.find('[role="alert"]').text()).toContain(t('errors.api.auth.email_taken'))
    expect(wrapper.find('a[href="/account?tab=password"]').exists()).toBe(true)
  })

  it('shows the error without a button or an API call when the token is missing', async () => {
    const fetchMock = mockApi()
    const { wrapper } = await mountWithApp(ConfirmEmailView, { path: '/confirm-email' })
    await flushPromises()
    expect(callsTo(fetchMock, CONFIRM)).toHaveLength(0)
    expect(wrapper.text()).toContain(t('errors.api.auth.token_invalid'))
    expect(confirmButton(wrapper)).toBeUndefined()
    expect(wrapper.text()).not.toContain(t('auth.confirmEmail.prompt'))
  })
})

describe('/confirm-email route', () => {
  it('has a translated title', async () => {
    mockApi()
    const { router } = await mountWithApp(ConfirmEmailView, { path: '/confirm-email' })
    const resolved = router.resolve('/confirm-email?token=a')
    expect(resolved.name).toBe('confirm-email')
    expect(i18n.global.te(resolved.meta.title as string, 'en')).toBe(true)
  })
})

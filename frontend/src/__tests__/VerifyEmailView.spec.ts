import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import VerifyEmailView from '@/views/VerifyEmailView.vue'
import { AUTH_REDIRECT_DELAY_MS } from '@/constants/auth'
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
import { EXPERTISE } from './helpers/members'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const VERIFY = 'POST /api/v1/auth/verify-email'

afterEach(() => {
  unmountAll()
  vi.useRealTimers()
  sessionStorage.clear()
})

const banner = () => document.querySelector('[data-testid="complete-profile-banner"]')

const verifyButton = (wrapper: VueWrapper) =>
  wrapper.findAll('button').find((b) => b.text().includes(t('auth.verify.button')))

/** Mounts the page and presses the button, as a person (not a mail scanner) would. */
async function mountAndVerify(path: string) {
  const mounted = await mountWithApp(VerifyEmailView, { path })
  await flushPromises()
  await verifyButton(mounted.wrapper)!.trigger('click')
  await flushPromises()
  return mounted
}

describe('VerifyEmailView', () => {
  it('does not send the token on mount (mail scanners open links but do not click)', async () => {
    const fetchMock = mockApi({ [VERIFY]: reply(200, makeUser()) })
    const { wrapper } = await mountWithApp(VerifyEmailView, { path: '/verify-email?token=abc' })
    await flushPromises()

    expect(callsTo(fetchMock, VERIFY)).toHaveLength(0)
    expect(wrapper.text()).not.toContain(t('auth.verify.success'))
  })

  it('shows the prompt and a real verify button', async () => {
    mockApi()
    const { wrapper } = await mountWithApp(VerifyEmailView, { path: '/verify-email?token=abc' })
    await flushPromises()

    expect(wrapper.find('h1').text()).toBe(t('auth.verify.title'))
    expect(wrapper.text()).toContain(t('auth.verify.prompt'))
    const button = verifyButton(wrapper)
    expect(button).toBeDefined()
    expect(button!.attributes('type')).toBe('button')
    expect(button!.attributes('disabled')).toBeUndefined()
  })

  it('posts the token from the query after the click and shows success (logged in)', async () => {
    const fetchMock = mockApi({ [VERIFY]: reply(200, makeUser()) })
    const { wrapper, auth } = await mountAndVerify('/verify-email?token=abc123')

    expect(callsTo(fetchMock, VERIFY)).toHaveLength(1)
    expect(callsTo(fetchMock, VERIFY)[0]?.body).toEqual({ token: 'abc123' })
    expect(wrapper.find('h1').attributes('tabindex')).toBe('-1')
    expect(wrapper.text()).toContain(t('auth.verify.success'))
    expect(wrapper.find('[aria-live="polite"]').text()).toContain(t('auth.verify.success'))
    expect(verifyButton(wrapper)).toBeUndefined()
    expect(auth.isAuthenticated).toBe(true)
  })

  it('sends exactly one request when the button is clicked twice quickly', async () => {
    const pending = deferred<Response>()
    const fetchMock = mockApi({ [VERIFY]: () => pending.promise })
    const { wrapper } = await mountWithApp(VerifyEmailView, { path: '/verify-email?token=abc' })
    await flushPromises()

    const button = verifyButton(wrapper)!
    await button.trigger('click')
    await button.trigger('click')
    await flushPromises()
    expect(callsTo(fetchMock, VERIFY)).toHaveLength(1)
    // While pending the button stays on screen, disabled and showing it is busy.
    expect(verifyButton(wrapper)!.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain(t('auth.verify.verifying'))

    pending.resolve(jsonResponse(makeUser()))
    await flushPromises()
    expect(callsTo(fetchMock, VERIFY)).toHaveLength(1)
    expect(wrapper.text()).toContain(t('auth.verify.success'))
  })

  it('redirects home after a short delay', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    mockApi({ [VERIFY]: reply(200, makeUser()) })
    const { router } = await mountAndVerify('/verify-email?token=abc')
    expect(router.currentRoute.value.name).toBe('verify-email')

    await vi.advanceTimersByTimeAsync(AUTH_REDIRECT_DELAY_MS)
    // The push awaits the lazily imported HomeView.
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/'))
  })

  it('does not redirect before the button is pressed', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    mockApi({ [VERIFY]: reply(200, makeUser()) })
    const { router } = await mountWithApp(VerifyEmailView, { path: '/verify-email?token=abc' })
    await flushPromises()

    await vi.advanceTimersByTimeAsync(AUTH_REDIRECT_DELAY_MS * 2)
    expect(router.currentRoute.value.name).toBe('verify-email')
  })

  it('shows the error and a resend form on 400', async () => {
    const fetchMock = mockApi({
      [VERIFY]: replyError(400, 'auth.token_invalid'),
      'POST /api/v1/auth/resend-verification': reply(202, { code: 'ok', message: 'ok' }),
    })
    const { wrapper } = await mountAndVerify('/verify-email?token=bad')

    expect(wrapper.text()).toContain(t('errors.api.auth.token_invalid'))
    expect(verifyButton(wrapper)).toBeUndefined()
    const email = wrapper.find('input[type="email"]')
    expect(email.exists()).toBe(true)

    await email.setValue('maria@example.org')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(callsTo(fetchMock, 'POST /api/v1/auth/resend-verification')[0]?.body).toMatchObject({
      email: 'maria@example.org',
    })
    expect(wrapper.text()).toContain(t('auth.resent'))
  })

  it('shows the error without a button or an API call when the token is missing', async () => {
    const fetchMock = mockApi()
    const { wrapper } = await mountWithApp(VerifyEmailView, { path: '/verify-email' })
    await flushPromises()
    expect(callsTo(fetchMock, VERIFY)).toHaveLength(0)
    expect(wrapper.text()).toContain(t('errors.api.auth.token_invalid'))
    expect(verifyButton(wrapper)).toBeUndefined()
    expect(wrapper.text()).not.toContain(t('auth.verify.prompt'))
  })

  it('invites a new member without expertise to complete the profile', async () => {
    mockApi({ [VERIFY]: reply(200, makeUser()) })
    const { wrapper } = await mountAndVerify('/verify-email?token=abc')
    expect(banner()).not.toBeNull()
    expect(banner()!.querySelector('a[href="/account?tab=profile"]')).not.toBeNull()
    expect(wrapper.text()).toContain(t('auth.verify.redirectingProfile'))
  })

  it('shows no profile invitation when the user already has expertise', async () => {
    mockApi({ [VERIFY]: reply(200, makeUser({ expertise: [EXPERTISE[0]!] })) })
    const { wrapper } = await mountAndVerify('/verify-email?token=abc')
    expect(banner()).toBeNull()
    expect(wrapper.text()).toContain(t('auth.verify.redirecting'))
  })
})

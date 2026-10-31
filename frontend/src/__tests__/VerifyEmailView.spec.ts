import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import VerifyEmailView from '@/views/VerifyEmailView.vue'
import { AUTH_REDIRECT_DELAY_MS } from '@/constants/auth'
import i18n from '@/i18n'
import { callsTo, makeUser, mockApi, reply, replyError } from './helpers/api'
import { EXPERTISE } from './helpers/members'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t

afterEach(() => {
  unmountAll()
  vi.useRealTimers()
  sessionStorage.clear()
})

const banner = () => document.querySelector('[data-testid="complete-profile-banner"]')

describe('VerifyEmailView', () => {
  it('posts the token from the query and shows success (logged in)', async () => {
    const fetchMock = mockApi({ 'POST /api/v1/auth/verify-email': reply(200, makeUser()) })
    const { wrapper, auth } = await mountWithApp(VerifyEmailView, {
      path: '/verify-email?token=abc123',
    })
    await flushPromises()

    expect(callsTo(fetchMock, 'POST /api/v1/auth/verify-email')[0]?.body).toEqual({
      token: 'abc123',
    })
    expect(wrapper.find('h1').attributes('tabindex')).toBe('-1')
    expect(wrapper.text()).toContain(t('auth.verify.success'))
    expect(wrapper.find('[aria-live="polite"]').text()).toContain(t('auth.verify.success'))
    expect(auth.isAuthenticated).toBe(true)
  })

  it('redirects home after a short delay', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    mockApi({ 'POST /api/v1/auth/verify-email': reply(200, makeUser()) })
    const { router } = await mountWithApp(VerifyEmailView, { path: '/verify-email?token=abc' })
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('verify-email')

    await vi.advanceTimersByTimeAsync(AUTH_REDIRECT_DELAY_MS)
    // The push awaits the lazily imported HomeView.
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/'))
  })

  it('shows the error and a resend form on 400', async () => {
    const fetchMock = mockApi({
      'POST /api/v1/auth/verify-email': replyError(400, 'auth.token_invalid'),
      'POST /api/v1/auth/resend-verification': reply(202, { code: 'ok', message: 'ok' }),
    })
    const { wrapper } = await mountWithApp(VerifyEmailView, { path: '/verify-email?token=bad' })
    await flushPromises()

    expect(wrapper.text()).toContain(t('errors.api.auth.token_invalid'))
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

  it('shows the error without calling the API when the token is missing', async () => {
    const fetchMock = mockApi()
    const { wrapper } = await mountWithApp(VerifyEmailView, { path: '/verify-email' })
    await flushPromises()
    expect(callsTo(fetchMock, 'POST /api/v1/auth/verify-email')).toHaveLength(0)
    expect(wrapper.text()).toContain(t('errors.api.auth.token_invalid'))
  })

  it('invites a new member without expertise to complete the profile', async () => {
    mockApi({ 'POST /api/v1/auth/verify-email': reply(200, makeUser()) })
    const { wrapper } = await mountWithApp(VerifyEmailView, { path: '/verify-email?token=abc' })
    await flushPromises()
    expect(banner()).not.toBeNull()
    expect(banner()!.querySelector('a[href="/account?tab=profile"]')).not.toBeNull()
    expect(wrapper.text()).toContain(t('auth.verify.redirectingProfile'))
  })

  it('shows no profile invitation when the user already has expertise', async () => {
    mockApi({
      'POST /api/v1/auth/verify-email': reply(200, makeUser({ expertise: [EXPERTISE[0]!] })),
    })
    const { wrapper } = await mountWithApp(VerifyEmailView, { path: '/verify-email?token=abc' })
    await flushPromises()
    expect(banner()).toBeNull()
    expect(wrapper.text()).toContain(t('auth.verify.redirecting'))
  })
})

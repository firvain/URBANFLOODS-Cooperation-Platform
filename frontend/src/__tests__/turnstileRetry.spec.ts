/**
 * Increment 7d: Turnstile tokens are single-use, so every attempt must carry a fresh one: a second
 * resend after a success, and a registration retried after a failure (the register form reused
 * the spent token until the page was reloaded).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import RegisterForm from '@/components/auth/RegisterForm.vue'
import RegisterSuccess from '@/components/auth/RegisterSuccess.vue'
import ResendVerificationForm from '@/components/auth/ResendVerificationForm.vue'
import i18n from '@/i18n'
import { callsTo, mockApi, ORGANISATIONS, reply, replyError, sequence } from './helpers/api'
import { EXPERTISE_RESPONSE } from './helpers/members'
import { mountWithApp, unmountAll } from './helpers/mount'
import { resetTurnstileStub, turnstileStub } from './helpers/turnstile'

const t = i18n.global.t

vi.mock('@/components/auth/TurnstileWidget.vue', () => import('./helpers/turnstile'))

const RESEND = 'POST /api/v1/auth/resend-verification'
const REGISTER = 'POST /api/v1/auth/register'
const ACCEPTED = reply(202, { code: 'auth.verification_resent', message: 'ok' })
const CAPTCHA_FAILED = replyError(400, 'auth.captcha_failed')

beforeEach(resetTurnstileStub)
afterEach(unmountAll)

const tokens = (fetchMock: Parameters<typeof callsTo>[0], route: string) =>
  callsTo(fetchMock, route).map((r) => (r.body as { turnstile_token: string }).turnstile_token)

describe('a second resend after a success uses a fresh token', () => {
  it('ResendVerificationForm', async () => {
    const fetchMock = mockApi({ [RESEND]: ACCEPTED })
    const { wrapper } = await mountWithApp(ResendVerificationForm, {
      props: { email: 'maria@example.org' },
    })
    for (let i = 0; i < 2; i++) {
      await wrapper.find('form').trigger('submit')
      await flushPromises()
    }
    expect(tokens(fetchMock, RESEND)).toEqual(['tok-1', 'tok-2'])
  })

  it('RegisterSuccess', async () => {
    const fetchMock = mockApi({ [RESEND]: ACCEPTED })
    const { wrapper } = await mountWithApp(RegisterSuccess, { props: { email: 'new@example.org' } })
    const button = () =>
      wrapper.findAll('button').find((b) => b.text() === t('auth.registerSuccess.resend'))!
    for (let i = 0; i < 2; i++) {
      await button().trigger('click')
      await flushPromises()
    }
    expect(tokens(fetchMock, RESEND)).toEqual(['tok-1', 'tok-2'])
  })
})

describe('RegisterForm', () => {
  async function fillAndSubmit(wrapper: VueWrapper) {
    await wrapper.find('input[type="email"]').setValue('new@example.org')
    await wrapper.find('input[autocomplete="new-password"]').setValue('a long enough password')
    await wrapper.find('input[autocomplete="nickname"]').setValue('Nina')
    const terms = wrapper.find('[role="checkbox"]')
    if (terms.attributes('aria-checked') !== 'true') await terms.trigger('click')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
  }

  it('cannot submit until the challenge is solved when Turnstile is on', async () => {
    vi.stubEnv('VITE_TURNSTILE_SITE_KEY', 'site-key')
    turnstileStub.autoSolve = false
    const fetchMock = mockApi({
      'GET /api/v1/organisations/': reply(200, ORGANISATIONS),
      'GET /api/v1/expertise/': reply(200, EXPERTISE_RESPONSE),
      [REGISTER]: reply(201, {
        id: 7,
        email: 'new@example.org',
        display_name: 'N',
        is_verified: false,
      }),
    })
    const { wrapper } = await mountWithApp(RegisterForm, { path: '/register' })
    const submitButton = () => wrapper.find('button[type="submit"]')

    expect(submitButton().attributes('disabled')).toBeDefined()
    expect(submitButton().text()).toBe(t('auth.registerPage.submit'))
    await fillAndSubmit(wrapper)
    expect(callsTo(fetchMock, REGISTER)).toHaveLength(0)

    wrapper.findComponent({ name: 'TurnstileWidget' }).vm.$emit('update:token', 'tok-late')
    await flushPromises()
    expect(submitButton().attributes('disabled')).toBeUndefined()
    await fillAndSubmit(wrapper)
    expect(tokens(fetchMock, REGISTER)).toEqual(['tok-late'])
  })

  it('retries a failed registration with a fresh token', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/organisations/': reply(200, ORGANISATIONS),
      'GET /api/v1/expertise/': reply(200, EXPERTISE_RESPONSE),
      [REGISTER]: sequence(
        CAPTCHA_FAILED,
        reply(201, { id: 7, email: 'new@example.org', display_name: 'Nina', is_verified: false }),
      ),
    })
    const { wrapper } = await mountWithApp(RegisterForm, { path: '/register' })
    await fillAndSubmit(wrapper)
    expect(wrapper.text()).toContain(t('errors.api.auth.captcha_failed'))
    await fillAndSubmit(wrapper)
    expect(tokens(fetchMock, REGISTER)).toEqual(['tok-1', 'tok-2'])
  })
})

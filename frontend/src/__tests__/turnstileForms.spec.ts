/**
 * Increment 7d: the anonymous "resend verification" and "forgot password" forms render the
 * Turnstile widget and send its token (production runs with Turnstile on); every attempt resets
 * the widget so a retry carries a fresh, unused token; submit waits for a solved challenge and for
 * the previous request. The signed-in banner sends none.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import RegisterSuccess from '@/components/auth/RegisterSuccess.vue'
import ResendVerificationForm from '@/components/auth/ResendVerificationForm.vue'
import UnverifiedBanner from '@/components/auth/UnverifiedBanner.vue'
import i18n from '@/i18n'
import ForgotPasswordView from '@/views/ForgotPasswordView.vue'
import {
  callsTo,
  deferred,
  makeUser,
  mockApi,
  reply,
  replyError,
  sequence,
  type Handler,
} from './helpers/api'
import { mountWithApp, unmountAll } from './helpers/mount'
import { resetTurnstileStub, TURNSTILE_STUB_SELECTOR, turnstileStub } from './helpers/turnstile'

const t = i18n.global.t

vi.mock('@/components/auth/TurnstileWidget.vue', () => import('./helpers/turnstile'))

const RESEND = 'POST /api/v1/auth/resend-verification'
const FORGOT = 'POST /api/v1/auth/password/forgot'
const ACCEPTED = reply(202, { code: 'auth.verification_resent', message: 'ok' })
const CAPTCHA_FAILED = replyError(400, 'auth.captcha_failed')

beforeEach(resetTurnstileStub)
afterEach(unmountAll)

function hasWidget(wrapper: VueWrapper) {
  return wrapper.find(TURNSTILE_STUB_SELECTOR).exists()
}

async function submitForm(wrapper: VueWrapper) {
  await wrapper.find('form').trigger('submit')
  await flushPromises()
}

describe('ResendVerificationForm', () => {
  it('renders the widget and sends its token', async () => {
    const fetchMock = mockApi({ [RESEND]: ACCEPTED })
    const { wrapper } = await mountWithApp(ResendVerificationForm, {
      props: { email: 'maria@example.org' },
    })

    expect(hasWidget(wrapper)).toBe(true)
    await submitForm(wrapper)

    expect(callsTo(fetchMock, RESEND)[0]?.body).toEqual({
      email: 'maria@example.org',
      turnstile_token: 'tok-1',
    })
    expect(wrapper.text()).toContain(t('auth.resent'))
  })

  it('shows the captcha error and retries with a fresh token', async () => {
    const fetchMock = mockApi({ [RESEND]: sequence(CAPTCHA_FAILED, ACCEPTED) })
    const { wrapper } = await mountWithApp(ResendVerificationForm, {
      props: { email: 'maria@example.org' },
    })

    await submitForm(wrapper)
    expect(wrapper.find('[role="alert"]').text()).toBe(t('errors.api.auth.captcha_failed'))

    await submitForm(wrapper)
    const bodies = callsTo(fetchMock, RESEND).map((r) => r.body)
    expect(bodies).toMatchObject([{ turnstile_token: 'tok-1' }, { turnstile_token: 'tok-2' }])
    expect(wrapper.text()).toContain(t('auth.resent'))
  })
})

describe('RegisterSuccess', () => {
  function resendButton(wrapper: VueWrapper) {
    return wrapper.findAll('button').find((b) => b.text() === t('auth.registerSuccess.resend'))!
  }

  it('renders the widget and sends its token (registering does not sign in)', async () => {
    const fetchMock = mockApi({ [RESEND]: ACCEPTED })
    const { wrapper } = await mountWithApp(RegisterSuccess, {
      props: { email: 'new@example.org' },
    })

    expect(hasWidget(wrapper)).toBe(true)
    await resendButton(wrapper).trigger('click')
    await flushPromises()

    expect(callsTo(fetchMock, RESEND)[0]?.body).toEqual({
      email: 'new@example.org',
      turnstile_token: 'tok-1',
    })
    expect(wrapper.text()).toContain(t('auth.resent'))
  })

  it('shows the captcha error and retries with a fresh token', async () => {
    const fetchMock = mockApi({ [RESEND]: sequence(CAPTCHA_FAILED, ACCEPTED) })
    const { wrapper } = await mountWithApp(RegisterSuccess, {
      props: { email: 'new@example.org' },
    })

    await resendButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toBe(t('errors.api.auth.captcha_failed'))

    await resendButton(wrapper).trigger('click')
    await flushPromises()
    const bodies = callsTo(fetchMock, RESEND).map((r) => r.body)
    expect(bodies).toMatchObject([{ turnstile_token: 'tok-1' }, { turnstile_token: 'tok-2' }])
  })
})

describe('ForgotPasswordView', () => {
  it('renders the widget and sends its token', async () => {
    const fetchMock = mockApi({ [FORGOT]: ACCEPTED })
    const { wrapper } = await mountWithApp(ForgotPasswordView, { path: '/forgot-password' })

    expect(hasWidget(wrapper)).toBe(true)
    await wrapper.find('input[type="email"]').setValue('maria@example.org')
    await submitForm(wrapper)

    expect(callsTo(fetchMock, FORGOT)[0]?.body).toEqual({
      email: 'maria@example.org',
      turnstile_token: 'tok-1',
    })
    expect(wrapper.text()).toContain(t('auth.forgot.sent'))
  })

  it('shows the captcha error and retries with a fresh token', async () => {
    const fetchMock = mockApi({ [FORGOT]: sequence(CAPTCHA_FAILED, ACCEPTED) })
    const { wrapper } = await mountWithApp(ForgotPasswordView, { path: '/forgot-password' })

    await wrapper.find('input[type="email"]').setValue('maria@example.org')
    await submitForm(wrapper)
    expect(wrapper.text()).toContain(t('errors.api.auth.captcha_failed'))

    await submitForm(wrapper)
    const bodies = callsTo(fetchMock, FORGOT).map((r) => r.body)
    expect(bodies).toMatchObject([{ turnstile_token: 'tok-1' }, { turnstile_token: 'tok-2' }])
    expect(wrapper.text()).toContain(t('auth.forgot.sent'))
  })
})

describe('UnverifiedBanner', () => {
  it('resends for the signed-in user without a widget or token', async () => {
    const fetchMock = mockApi({ [RESEND]: ACCEPTED })
    const { wrapper, auth } = await mountWithApp(UnverifiedBanner)
    auth.$patch({
      user: makeUser({ email: 'maria@example.org', is_verified: false }),
      status: 'authenticated',
    })
    await flushPromises()

    expect(hasWidget(wrapper)).toBe(false)
    const button = wrapper.findAll('button').find((b) => b.text() === t('auth.unverified.resend'))!
    await button.trigger('click')
    await flushPromises()

    expect(callsTo(fetchMock, RESEND)[0]?.body).toEqual({
      email: 'maria@example.org',
      turnstile_token: null,
    })
    expect(wrapper.text()).toContain(t('auth.resent'))
  })
})

/** Turnstile on (site key set) with the challenge not yet solved: the token is null. */
function unsolvedTurnstile() {
  vi.stubEnv('VITE_TURNSTILE_SITE_KEY', 'site-key')
  turnstileStub.autoSolve = false
}

async function solveLate(wrapper: VueWrapper) {
  wrapper.findComponent({ name: 'TurnstileWidget' }).vm.$emit('update:token', 'tok-late')
  await flushPromises()
}

describe('waiting for the challenge when Turnstile is on', () => {
  it('ResendVerificationForm keeps submit disabled until the token arrives', async () => {
    unsolvedTurnstile()
    const fetchMock = mockApi({ [RESEND]: ACCEPTED })
    const { wrapper } = await mountWithApp(ResendVerificationForm, {
      props: { email: 'maria@example.org' },
    })
    const button = () => wrapper.find('button[type="submit"]')

    expect(button().attributes('disabled')).toBeDefined()
    expect(button().text()).toBe(t('auth.verify.resend'))
    await submitForm(wrapper)
    expect(callsTo(fetchMock, RESEND)).toHaveLength(0)

    await solveLate(wrapper)
    expect(button().attributes('disabled')).toBeUndefined()
    await submitForm(wrapper)
    expect(callsTo(fetchMock, RESEND).map((r) => r.body)).toEqual([
      { email: 'maria@example.org', turnstile_token: 'tok-late' },
    ])
  })

  it('RegisterSuccess keeps resend disabled until the token arrives', async () => {
    unsolvedTurnstile()
    const fetchMock = mockApi({ [RESEND]: ACCEPTED })
    const { wrapper } = await mountWithApp(RegisterSuccess, {
      props: { email: 'new@example.org' },
    })
    const button = () =>
      wrapper.findAll('button').find((b) => b.text() === t('auth.registerSuccess.resend'))!

    expect(button().attributes('disabled')).toBeDefined()
    await button().trigger('click')
    await flushPromises()
    expect(callsTo(fetchMock, RESEND)).toHaveLength(0)

    await solveLate(wrapper)
    expect(button().attributes('disabled')).toBeUndefined()
    await button().trigger('click')
    await flushPromises()
    expect(callsTo(fetchMock, RESEND)).toHaveLength(1)
  })

  it('ForgotPasswordView keeps submit disabled until the token arrives', async () => {
    unsolvedTurnstile()
    const fetchMock = mockApi({ [FORGOT]: ACCEPTED })
    const { wrapper } = await mountWithApp(ForgotPasswordView, { path: '/forgot-password' })
    const button = () => wrapper.find('button[type="submit"]')
    await wrapper.find('input[type="email"]').setValue('maria@example.org')

    expect(button().attributes('disabled')).toBeDefined()
    expect(button().text()).toBe(t('auth.forgot.submit'))
    await submitForm(wrapper)
    expect(callsTo(fetchMock, FORGOT)).toHaveLength(0)

    await solveLate(wrapper)
    expect(button().attributes('disabled')).toBeUndefined()
    await submitForm(wrapper)
    expect(callsTo(fetchMock, FORGOT)).toHaveLength(1)
  })
})

describe('ResendVerificationForm while a request is pending', () => {
  it('sends one request for a double submit and shows it is busy', async () => {
    const answer = deferred<Response>()
    const pending: Handler = () => answer.promise
    const fetchMock = mockApi({ [RESEND]: pending })
    const { wrapper } = await mountWithApp(ResendVerificationForm, {
      props: { email: 'maria@example.org' },
    })

    await wrapper.find('form').trigger('submit')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(callsTo(fetchMock, RESEND)).toHaveLength(1)
    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeDefined()

    answer.resolve(await ACCEPTED(callsTo(fetchMock, RESEND)[0]!))
    await flushPromises()
    expect(wrapper.text()).toContain(t('auth.resent'))
    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeUndefined()
  })
})

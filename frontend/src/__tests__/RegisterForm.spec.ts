import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type DOMWrapper } from '@vue/test-utils'

import RegisterForm from '@/components/auth/RegisterForm.vue'
import i18n from '@/i18n'
import { callsTo, mockApi, ORGANISATIONS, reply, replyError, type Handler } from './helpers/api'
import { EXPERTISE_RESPONSE } from './helpers/members'
import { mountWithApp, unmountAll } from './helpers/mount'
import { clickOption, controlFor, openSelect } from './helpers/select'

const t = i18n.global.t

afterEach(unmountAll)

const CREATED = { id: 7, email: 'new@example.org', display_name: 'Nina', is_verified: false }

function routes(extra: Record<string, Handler> = {}) {
  return {
    'GET /api/v1/organisations/': reply(200, ORGANISATIONS),
    'GET /api/v1/expertise/': reply(200, EXPERTISE_RESPONSE),
    ...extra,
  }
}

async function mountForm() {
  const { wrapper } = await mountWithApp(RegisterForm, { path: '/register' })
  return wrapper
}

async function fillRequired(wrapper: Awaited<ReturnType<typeof mountForm>>) {
  await wrapper.find('input[type="email"]').setValue('new@example.org')
  await wrapper.find('input[autocomplete="new-password"]').setValue('a long enough password')
  await wrapper.find('input[autocomplete="nickname"]').setValue('Nina')
}

async function acceptTerms(wrapper: Awaited<ReturnType<typeof mountForm>>) {
  await wrapper.find('[role="checkbox"]').trigger('click')
}

async function submit(wrapper: Awaited<ReturnType<typeof mountForm>>) {
  await wrapper.find('form').trigger('submit')
  await flushPromises()
}

/** Open a Nuxt UI select/select-menu by its accessible label and pick the option with `text`. */
async function pick(trigger: DOMWrapper<Element>, text: string) {
  const el = trigger.element as HTMLElement
  el.focus()
  el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await flushPromises()
  if (!document.querySelector('[role="option"]')) {
    await trigger.trigger('click')
    await flushPromises()
  }
  const option = Array.from(document.querySelectorAll<HTMLElement>('[role="option"]')).find((o) =>
    o.textContent?.includes(text),
  )
  expect(option, `option ${text}`).toBeDefined()
  option!.click()
  await flushPromises()
}

describe('RegisterForm', () => {
  it('requires accept_terms on the client and does not submit', async () => {
    const fetchMock = mockApi(routes())
    const wrapper = await mountForm()
    await fillRequired(wrapper)
    await submit(wrapper)
    expect(wrapper.text()).toContain(t('errors.fields.must_accept'))
    expect(callsTo(fetchMock, 'POST /api/v1/auth/register')).toHaveLength(0)
  })

  it('maps a server fields.password error onto the password field', async () => {
    mockApi(
      routes({
        'POST /api/v1/auth/register': replyError(422, 'validation.failed', {
          password: 'auth.password_too_common',
        }),
      }),
    )
    const wrapper = await mountForm()
    await fillRequired(wrapper)
    await acceptTerms(wrapper)
    await submit(wrapper)

    const message = t('errors.fields.auth.password_too_common')
    expect(wrapper.text()).toContain(message)
    const password = wrapper.find('input[autocomplete="new-password"]')
    expect(password.attributes('aria-invalid')).toBe('true')
    const describedBy = password.attributes('aria-describedby') ?? ''
    const described = describedBy
      .split(' ')
      .map((id) => document.getElementById(id)?.textContent ?? '')
      .join(' ')
    expect(described).toContain(message)
  })

  it('shows an email_taken error on the email field', async () => {
    mockApi(routes({ 'POST /api/v1/auth/register': replyError(409, 'auth.email_taken') }))
    const wrapper = await mountForm()
    await fillRequired(wrapper)
    await acceptTerms(wrapper)
    await submit(wrapper)
    expect(wrapper.find('input[type="email"]').attributes('aria-invalid')).toBe('true')
    expect(wrapper.text()).toContain(t('errors.api.auth.email_taken'))
  })

  it('loads organisations and "Other…" reveals the organisation_other input', async () => {
    const fetchMock = mockApi(routes())
    const wrapper = await mountForm()
    expect(callsTo(fetchMock, 'GET /api/v1/organisations/')).toHaveLength(1)
    expect(wrapper.find('input[name="organisation_other"]').exists()).toBe(false)

    const label = wrapper
      .findAll('label')
      .find((l) => l.text().startsWith(t('auth.fields.organisation')))
    const trigger = wrapper.find(`#${label!.attributes('for')}`)
    expect(trigger.exists()).toBe(true)
    await pick(trigger, t('auth.fields.organisationOtherOption'))

    expect(wrapper.find('input[name="organisation_other"]').exists()).toBe(true)
  })

  it('lists organisations by their full name only', async () => {
    mockApi(routes())
    const wrapper = await mountForm()
    await openSelect(wrapper, t('auth.fields.organisation'))
    const labels = Array.from(document.querySelectorAll('[role="option"]')).map((o) =>
      o.textContent?.trim(),
    )
    expect(labels).toContain('University of Western Macedonia')
    expect(labels).toContain('Macerata Municipality')
    expect(labels.some((l) => /UOWM|\bMC\b/.test(l ?? ''))).toBe(false)
  })

  it('emits `registered` with the email after a successful submit', async () => {
    const fetchMock = mockApi(routes({ 'POST /api/v1/auth/register': reply(201, CREATED) }))
    const wrapper = await mountForm()
    await fillRequired(wrapper)
    await acceptTerms(wrapper)
    await submit(wrapper)

    await vi.waitFor(() => expect(wrapper.emitted('registered')).toBeTruthy())
    expect(wrapper.emitted('registered')![0]).toEqual(['new@example.org'])
    const body = callsTo(fetchMock, 'POST /api/v1/auth/register')[0]!.body
    expect(body).toMatchObject({
      email: 'new@example.org',
      password: 'a long enough password',
      display_name: 'Nina',
      accept_terms: true,
      locale: 'en',
      organisation_id: null,
    })
  })

  it('has a password show/hide toggle with aria-pressed', async () => {
    mockApi(routes())
    const wrapper = await mountForm()
    const toggle = wrapper.find('button[aria-pressed]')
    expect(toggle.attributes('aria-pressed')).toBe('false')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-pressed')).toBe('true')
    expect(wrapper.find('input[autocomplete="new-password"]').attributes('type')).toBe('text')
  })

  it('links to the terms and privacy pages', async () => {
    mockApi(routes())
    const wrapper = await mountForm()
    expect(wrapper.find('a[href="/terms"]').exists()).toBe(true)
    expect(wrapper.find('a[href="/privacy"]').exists()).toBe(true)
  })

  describe('expertise areas', () => {
    const label = () => t('auth.expertiseLabel', { max: 8 })
    const labelled = (wrapper: Awaited<ReturnType<typeof mountForm>>) =>
      wrapper.findAll('label').some((l) => l.text().startsWith(label()))
    it('shows the picker straight away, without a toggle to open it', async () => {
      mockApi(routes())
      const wrapper = await mountForm()
      expect(labelled(wrapper)).toBe(true)
      expect(label()).toBe('Areas of expertise (optional, up to 8)')
      // The old fold-out toggle is gone.
      expect(wrapper.text()).not.toContain('Add your areas of expertise')
    })

    it('sends the chosen areas as sorted expertise_ids', async () => {
      const fetchMock = mockApi(routes({ 'POST /api/v1/auth/register': reply(201, CREATED) }))
      const wrapper = await mountForm()
      await fillRequired(wrapper)
      await openSelect(wrapper, label())
      await clickOption('Urban planning')
      await clickOption('Hydrology')
      expect(controlFor(wrapper, label()).textContent).toContain('Hydrology')
      await acceptTerms(wrapper)
      await submit(wrapper)

      const body = callsTo(fetchMock, 'POST /api/v1/auth/register')[0]!.body
      expect(body).toMatchObject({ expertise_ids: [1, 3] })
    })

    it('sends no expertise_ids when none are chosen', async () => {
      const fetchMock = mockApi(routes({ 'POST /api/v1/auth/register': reply(201, CREATED) }))
      const wrapper = await mountForm()
      await fillRequired(wrapper)
      await acceptTerms(wrapper)
      await submit(wrapper)

      const body = callsTo(fetchMock, 'POST /api/v1/auth/register')[0]!.body as object
      expect(body).not.toHaveProperty('expertise_ids')
    })

    it('sends the trimmed free-text "other" area as expertise_other', async () => {
      const fetchMock = mockApi(routes({ 'POST /api/v1/auth/register': reply(201, CREATED) }))
      const wrapper = await mountForm()
      await fillRequired(wrapper)
      await wrapper.find('input[name="expertise_other"]').setValue('  Coastal engineering  ')
      await acceptTerms(wrapper)
      await submit(wrapper)

      const body = callsTo(fetchMock, 'POST /api/v1/auth/register')[0]!.body
      expect(body).toMatchObject({ expertise_other: 'Coastal engineering' })
    })

    it('sends expertise_other as null when it is blank', async () => {
      const fetchMock = mockApi(routes({ 'POST /api/v1/auth/register': reply(201, CREATED) }))
      const wrapper = await mountForm()
      await fillRequired(wrapper)
      await wrapper.find('input[name="expertise_other"]').setValue('   ')
      await acceptTerms(wrapper)
      await submit(wrapper)

      const body = callsTo(fetchMock, 'POST /api/v1/auth/register')[0]!.body
      expect(body).toMatchObject({ expertise_other: null })
    })

    it('maps a server fields.expertise_other error onto the text input', async () => {
      mockApi(
        routes({
          'POST /api/v1/auth/register': replyError(422, 'validation.failed', {
            expertise_other: 'string_too_long',
          }),
        }),
      )
      const wrapper = await mountForm()
      await fillRequired(wrapper)
      await wrapper.find('input[name="expertise_other"]').setValue('Coastal engineering')
      await acceptTerms(wrapper)
      await submit(wrapper)

      const input = wrapper.find('input[name="expertise_other"]').element
      expect(input.getAttribute('aria-invalid')).toBe('true')
      const described = (input.getAttribute('aria-describedby') ?? '')
        .split(' ')
        .map((id) => document.getElementById(id)?.textContent ?? '')
        .join(' ')
      expect(described).toContain(t('errors.fields.string_too_long'))
    })

    it('maps a server fields.expertise_ids error onto the picker', async () => {
      mockApi(
        routes({
          'POST /api/v1/auth/register': replyError(422, 'validation.failed', {
            expertise_ids: 'not_found',
          }),
        }),
      )
      const wrapper = await mountForm()
      await fillRequired(wrapper)
      await openSelect(wrapper, label())
      await clickOption('Hydrology')
      await acceptTerms(wrapper)
      await submit(wrapper)

      const control = controlFor(wrapper, label())
      expect(control.getAttribute('aria-invalid')).toBe('true')
      const described = (control.getAttribute('aria-describedby') ?? '')
        .split(' ')
        .map((id) => document.getElementById(id)?.textContent ?? '')
        .join(' ')
      expect(described).toContain(t('errors.fields.invalid'))
    })
  })
})

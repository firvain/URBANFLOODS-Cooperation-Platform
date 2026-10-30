import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import LoginForm from '@/components/auth/LoginForm.vue'
import i18n from '@/i18n'
import { callsTo, makeUser, mockApi, reply, replyError } from './helpers/api'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t

afterEach(unmountAll)

async function fillAndSubmit(wrapper: Awaited<ReturnType<typeof mountWithApp>>['wrapper']) {
  await wrapper.find('input[type="email"]').setValue('maria@example.org')
  await wrapper.find('input[autocomplete="current-password"]').setValue('correct horse battery')
  await wrapper.find('form').trigger('submit')
  await flushPromises()
}

describe('LoginForm', () => {
  it('has labelled email and password fields', async () => {
    const { wrapper } = await mountWithApp(LoginForm, { path: '/login' })
    for (const selector of ['input[type="email"]', 'input[autocomplete="current-password"]']) {
      const id = wrapper.find(selector).attributes('id')
      expect(id).toBeTruthy()
      expect(wrapper.find(`label[for="${id}"]`).exists()).toBe(true)
    }
  })

  it('submits email and password to /auth/login', async () => {
    const fetchMock = mockApi({ 'POST /api/v1/auth/login': reply(200, makeUser()) })
    const { wrapper } = await mountWithApp(LoginForm, { path: '/login' })
    await fillAndSubmit(wrapper)
    expect(callsTo(fetchMock, 'POST /api/v1/auth/login')[0]?.body).toEqual({
      email: 'maria@example.org',
      password: 'correct horse battery',
    })
  })

  it('does not submit when fields are empty', async () => {
    const fetchMock = mockApi()
    const { wrapper } = await mountWithApp(LoginForm, { path: '/login' })
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(callsTo(fetchMock, 'POST /api/v1/auth/login')).toHaveLength(0)
    expect(wrapper.text()).toContain(t('errors.fields.required'))
  })

  it('shows an inline error on 401 and stays on the page', async () => {
    mockApi({ 'POST /api/v1/auth/login': replyError(401, 'auth.invalid_credentials') })
    const { wrapper, router } = await mountWithApp(LoginForm, { path: '/login' })
    await fillAndSubmit(wrapper)
    const alert = wrapper.find('[role="alert"]')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toContain(t('errors.api.auth.invalid_credentials'))
    expect(router.currentRoute.value.name).toBe('login')
  })

  it('pushes `next` on success', async () => {
    mockApi({ 'POST /api/v1/auth/login': reply(200, makeUser()) })
    const { wrapper, router } = await mountWithApp(LoginForm, { path: '/login?next=%2Faccount' })
    await fillAndSubmit(wrapper)
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/account'))
  })

  it('pushes home when next is unsafe', async () => {
    mockApi({ 'POST /api/v1/auth/login': reply(200, makeUser()) })
    const { wrapper, router } = await mountWithApp(LoginForm, {
      path: '/login?next=%2F%2Fevil.com',
    })
    await fillAndSubmit(wrapper)
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/'))
  })
})

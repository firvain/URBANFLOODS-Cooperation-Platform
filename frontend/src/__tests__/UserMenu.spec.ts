import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import UserMenu from '@/components/layout/UserMenu.vue'
import i18n from '@/i18n'
import { callsTo, makeUser, mockApi, reply } from './helpers/api'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t

afterEach(unmountAll)

async function openMenu() {
  const trigger = document.querySelector<HTMLElement>('[aria-haspopup="menu"]')
  expect(trigger).not.toBeNull()
  trigger!.focus()
  trigger!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await flushPromises()
}

describe('UserMenu', () => {
  it('anonymous: shows log in and register links', async () => {
    mockApi()
    const { wrapper } = await mountWithApp(UserMenu)
    const login = wrapper.find('a[href="/login"]')
    const register = wrapper.find('a[href="/register"]')
    expect(login.text()).toBe(t('nav.login'))
    expect(register.text()).toBe(t('nav.register'))
    expect(wrapper.text()).not.toContain(t('auth.logout'))
  })

  it('authenticated: shows the display name and a menu with Account and Log out', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/auth/me': reply(200, makeUser({ display_name: 'Maria P.' })),
      'POST /api/v1/auth/logout': reply(204),
    })
    const { wrapper, auth } = await mountWithApp(UserMenu)
    expect(auth.isAuthenticated).toBe(true)
    expect(wrapper.text()).toContain('Maria P.')
    expect(wrapper.find('a[href="/login"]').exists()).toBe(false)

    await openMenu()
    const items = Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"]'))
    expect(items.map((i) => i.textContent?.trim())).toEqual(
      expect.arrayContaining([t('nav.account'), t('auth.logout')]),
    )

    items.find((i) => i.textContent?.includes(t('auth.logout')))!.click()
    await flushPromises()
    expect(callsTo(fetchMock, 'POST /api/v1/auth/logout')).toHaveLength(1)
    expect(auth.isAuthenticated).toBe(false)
  })

  it.each(['/blog', '/account'])('logging out on %s goes to the home page', async (path) => {
    mockApi({
      'GET /api/v1/auth/me': reply(200, makeUser({ display_name: 'Maria P.' })),
      'POST /api/v1/auth/logout': reply(204),
    })
    const { router } = await mountWithApp(UserMenu, { path })
    await openMenu()
    const items = Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"]'))
    items.find((i) => i.textContent?.includes(t('auth.logout')))!.click()
    await flushPromises()
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/'))
  })

  it('mobile variant lists the same actions as plain buttons', async () => {
    mockApi({ 'GET /api/v1/auth/me': reply(200, makeUser({ display_name: 'Maria P.' })) })
    const { wrapper } = await mountWithApp(UserMenu, { props: { mobile: true } })
    expect(wrapper.text()).toContain('Maria P.')
    expect(wrapper.find('a[href="/account"]').exists()).toBe(true)
    expect(wrapper.findAll('button').some((b) => b.text() === t('auth.logout'))).toBe(true)
  })
})

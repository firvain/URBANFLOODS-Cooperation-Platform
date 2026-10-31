import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'

import UserMenu from '@/components/layout/UserMenu.vue'
import i18n from '@/i18n'
import { createAppRouter } from '@/router'
import { makeUser, mockApi, reply } from './helpers/api'
import { ADMIN_ME, makeStats, mountAdmin } from './helpers/admin'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t

afterEach(unmountAll)

const ADMIN_PATHS = [
  '/admin',
  '/admin/queue',
  '/admin/reports',
  '/admin/deleted',
  '/admin/users',
  '/admin/categories',
  '/admin/tags',
  '/admin/organisations',
  '/admin/expertise',
  '/admin/log',
]

async function routerAs(user: ReturnType<typeof makeUser> | null) {
  setActivePinia(createPinia())
  mockApi(user ? { 'GET /api/v1/auth/me': reply(200, user) } : {})
  return createAppRouter(createMemoryHistory())
}

describe('admin routes', () => {
  it.each(ADMIN_PATHS)('a member gets NotFound at %s (URL kept)', async (path) => {
    const router = await routerAs(makeUser({ role: 'member' }))
    await router.push(path)
    expect(router.currentRoute.value.name).toBe('not-found')
    expect(router.currentRoute.value.path).toBe(path)
  })

  it('an anonymous visitor is sent to log in and back', async () => {
    const router = await routerAs(null)
    await router.push('/admin/reports')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.next).toBe('/admin/reports')
  })

  it.each(['admin', 'superadmin'] as const)('a %s opens every admin page', async (role) => {
    const router = await routerAs(makeUser({ role }))
    for (const path of ADMIN_PATHS) {
      await router.push(path)
      expect(router.currentRoute.value.path).toBe(path)
      expect(String(router.currentRoute.value.name)).toMatch(/^admin-/)
    }
  })

  it('the layout lists every section in a labelled navigation', async () => {
    await mountAdmin('/admin', { 'GET /api/v1/admin/stats': reply(200, makeStats()) })
    const nav = document.querySelector(`nav[aria-label="${t('admin.nav.label')}"]`)
    expect(nav).not.toBeNull()
    const hrefs = Array.from(nav!.querySelectorAll('a')).map((a) => a.getAttribute('href'))
    expect(hrefs).toEqual(ADMIN_PATHS)
    expect(document.querySelector('main h1')?.textContent).toContain(t('admin.dashboard.title'))
  })
})

describe('UserMenu admin entry', () => {
  async function menuItems() {
    const trigger = document.querySelector<HTMLElement>('[aria-haspopup="menu"]')!
    trigger.focus()
    trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flushPromises()
    return Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"]'))
  }

  it('shows Admin to administrators', async () => {
    mockApi({ 'GET /api/v1/auth/me': reply(200, ADMIN_ME) })
    await mountWithApp(UserMenu)
    const admin = (await menuItems()).find((i) => i.textContent?.trim() === t('admin.menu'))
    expect(admin).toBeDefined()
    expect(admin!.closest('a')?.getAttribute('href') ?? admin!.getAttribute('href')).toBe('/admin')
  })

  it('does not show Admin to members', async () => {
    mockApi({ 'GET /api/v1/auth/me': reply(200, makeUser()) })
    await mountWithApp(UserMenu)
    const texts = (await menuItems()).map((i) => i.textContent?.trim())
    expect(texts).toContain(t('nav.account'))
    expect(texts).not.toContain(t('admin.menu'))
  })

  it('lists Admin in the mobile menu for administrators only', async () => {
    mockApi({ 'GET /api/v1/auth/me': reply(200, ADMIN_ME) })
    const { wrapper } = await mountWithApp(UserMenu, { props: { mobile: true } })
    expect(wrapper.find('a[href="/admin"]').exists()).toBe(true)
    unmountAll()
    mockApi({ 'GET /api/v1/auth/me': reply(200, makeUser()) })
    const member = await mountWithApp(UserMenu, { props: { mobile: true } })
    expect(member.wrapper.find('a[href="/admin"]').exists()).toBe(false)
  })
})

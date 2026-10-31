import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

import { createAppRouter } from '@/router'
import { safeRedirect } from '@/router/redirect'
import { useAuthStore } from '@/stores/auth'
import { callsTo, deferred, makeUser, mockApi, reply, type Handler } from './helpers/api'

const Blank = defineComponent({ render: () => h('div') })

function makeRouter() {
  const router = createAppRouter(createMemoryHistory())
  router.addRoute({
    path: '/test/admin',
    name: 't-admin',
    component: Blank,
    meta: { title: 'app.title', auth: 'admin' },
  })
  router.addRoute({
    path: '/test/verified',
    name: 't-verified',
    component: Blank,
    meta: { title: 'app.title', auth: 'verified' },
  })
  return router
}

function loggedIn(overrides: Parameters<typeof makeUser>[0] = {}): Record<string, Handler> {
  return { 'GET /api/v1/auth/me': reply(200, makeUser(overrides)) }
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('meta.auth guard', () => {
  it('anonymous → /account redirects to /login?next=%2Faccount', async () => {
    mockApi()
    const router = makeRouter()
    await router.push('/account')
    // vue-router leaves `/` unescaped in query values: `/login?next=/account` ≡ `next=%2Faccount`.
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query).toEqual({ next: '/account' })
    expect(router.resolve({ name: 'login', query: { next: '/account' } }).fullPath).toBe(
      router.currentRoute.value.fullPath,
    )
  })

  it('authenticated → /account is allowed', async () => {
    mockApi(loggedIn())
    const router = makeRouter()
    await router.push('/account')
    expect(router.currentRoute.value.name).toBe('account')
  })

  it('anonymous → a member profile redirects to /login?next=/u/5', async () => {
    mockApi()
    const router = makeRouter()
    await router.push('/u/5')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query).toEqual({ next: '/u/5' })
  })

  it('verified → a member profile is allowed', async () => {
    mockApi(loggedIn())
    const router = makeRouter()
    await router.push('/u/5')
    expect(router.currentRoute.value.name).toBe('profile')
  })

  it('anonymous → public pages are allowed', async () => {
    mockApi()
    const router = makeRouter()
    await router.push('/about')
    expect(router.currentRoute.value.name).toBe('about')
  })

  it('member → admin route shows NotFound and keeps the URL', async () => {
    mockApi(loggedIn({ role: 'member' }))
    const router = makeRouter()
    await router.push('/test/admin')
    expect(router.currentRoute.value.name).toBe('not-found')
    expect(router.currentRoute.value.path).toBe('/test/admin')
  })

  it('admin → admin route is allowed', async () => {
    mockApi(loggedIn({ role: 'admin' }))
    const router = makeRouter()
    await router.push('/test/admin')
    expect(router.currentRoute.value.name).toBe('t-admin')
  })

  it('anonymous → admin route redirects to login', async () => {
    mockApi()
    const router = makeRouter()
    await router.push('/test/admin')
    expect(router.currentRoute.value.name).toBe('login')
  })

  it('unverified user → verified route is allowed (the view shows the banner)', async () => {
    mockApi(loggedIn({ is_verified: false }))
    const router = makeRouter()
    await router.push('/test/verified')
    expect(router.currentRoute.value.name).toBe('t-verified')
  })
})

describe('guest-only pages', () => {
  it('authenticated → /login redirects home', async () => {
    mockApi(loggedIn())
    const router = makeRouter()
    await router.push('/login')
    expect(router.currentRoute.value.fullPath).toBe('/')
  })

  it('authenticated → /register redirects home', async () => {
    mockApi(loggedIn())
    const router = makeRouter()
    await router.push('/register')
    expect(router.currentRoute.value.fullPath).toBe('/')
  })

  it('authenticated → /login?next=/account goes to /account', async () => {
    mockApi(loggedIn())
    const router = makeRouter()
    await router.push('/login?next=%2Faccount')
    expect(router.currentRoute.value.fullPath).toBe('/account')
  })

  it.each(['//evil.com', '/\\evil.com', 'https://evil.com', 'evil.com'])(
    'ignores an unsafe next=%s',
    async (next) => {
      mockApi(loggedIn())
      const router = makeRouter()
      await router.push({ path: '/login', query: { next } })
      expect(router.currentRoute.value.fullPath).toBe('/')
    },
  )

  it('anonymous → /login is allowed', async () => {
    mockApi()
    const router = makeRouter()
    await router.push('/login')
    expect(router.currentRoute.value.name).toBe('login')
  })
})

describe('session bootstrap', () => {
  it('awaits fetchMe once before the first guard decision', async () => {
    const gate = deferred<Response>()
    const fetchMock = mockApi({ 'GET /api/v1/auth/me': () => gate.promise })
    const router = makeRouter()

    const navigation = router.push('/account')
    await Promise.resolve()
    expect(useAuthStore().status).toBe('unknown')
    expect(router.currentRoute.value.name).not.toBe('login')

    gate.resolve(
      new Response(JSON.stringify(makeUser()), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    await navigation
    expect(router.currentRoute.value.name).toBe('account')

    await router.push('/about')
    await router.push('/account')
    expect(callsTo(fetchMock, 'GET /api/v1/auth/me')).toHaveLength(1)
  })
})

describe('safeRedirect', () => {
  it.each([
    ['/account', '/account'],
    ['/blog/x?y=1#z', '/blog/x?y=1#z'],
    ['//evil.com', null],
    ['/\\evil.com', null],
    ['https://evil.com', null],
    ['', null],
    [undefined, null],
    [['/a', '/b'], null],
  ])('%j → %j', (input, expected) => {
    expect(safeRedirect(input)).toBe(expected)
  })
})

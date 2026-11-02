import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { api, ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import { callsTo, deferred, makeUser, mockApi, reply, replyError, sequence } from './helpers/api'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('initial state', () => {
  it('starts unknown with no user', () => {
    const auth = useAuthStore()
    expect(auth.status).toBe('unknown')
    expect(auth.user).toBeNull()
    expect(auth.isAuthenticated).toBe(false)
  })
})

describe('fetchMe', () => {
  it('200 → authenticated with the user', async () => {
    mockApi({ 'GET /api/v1/auth/me': reply(200, makeUser()) })
    const auth = useAuthStore()
    await auth.fetchMe()
    expect(auth.status).toBe('authenticated')
    expect(auth.isAuthenticated).toBe(true)
    expect(auth.user?.email).toBe('maria@example.org')
  })

  it('401 → anonymous, resolves without throwing', async () => {
    mockApi({ 'GET /api/v1/auth/me': replyError(401, 'auth.not_authenticated') })
    const auth = useAuthStore()
    await expect(auth.fetchMe()).resolves.toBeUndefined()
    expect(auth.status).toBe('anonymous')
    expect(auth.user).toBeNull()
  })

  // 7l: only a 401 means signed out. Anything else (a 502 during a deploy, a network error, a
  // 429) says nothing about the session, so the status stays as it was.
  it.each([
    ['a network failure', () => Promise.reject(new TypeError('Failed to fetch'))],
    ['502', replyError(502, 'bad_gateway')],
    ['429', replyError(429, 'rate_limited')],
  ] as const)('%s → stays unknown, resolves without throwing', async (_label, handler) => {
    mockApi({ 'GET /api/v1/auth/me': handler })
    const auth = useAuthStore()
    await expect(auth.fetchMe()).resolves.toBeUndefined()
    expect(auth.status).toBe('unknown')
    expect(auth.user).toBeNull()
    expect(auth.loading).toBe(false)
  })

  it('a non-401 failure keeps an authenticated user', async () => {
    mockApi({
      'GET /api/v1/auth/me': sequence(reply(200, makeUser()), replyError(502, 'bad_gateway')),
    })
    const auth = useAuthStore()
    await auth.fetchMe()
    const before = auth.user

    await auth.fetchMe()

    expect(auth.status).toBe('authenticated')
    expect(auth.user).toBe(before)
  })

  it('a 401 signs an authenticated user out', async () => {
    mockApi({
      'GET /api/v1/auth/me': sequence(
        reply(200, makeUser()),
        replyError(401, 'auth.not_authenticated'),
      ),
    })
    const auth = useAuthStore()
    await auth.fetchMe()

    await auth.fetchMe()

    expect(auth.status).toBe('anonymous')
    expect(auth.user).toBeNull()
  })

  it('a non-401 failure keeps an anonymous status', async () => {
    mockApi({
      'GET /api/v1/auth/me': sequence(
        replyError(401, 'auth.not_authenticated'),
        replyError(503, 'unavailable'),
      ),
    })
    const auth = useAuthStore()
    await auth.fetchMe()

    await auth.fetchMe()

    expect(auth.status).toBe('anonymous')
  })

  it('shares one request between concurrent callers', async () => {
    const gate = deferred<Response>()
    const fetchMock = mockApi({ 'GET /api/v1/auth/me': () => gate.promise })
    const auth = useAuthStore()
    const both = Promise.all([auth.fetchMe(), auth.fetchMe()])
    gate.resolve(
      new Response(JSON.stringify(makeUser()), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    await both
    expect(callsTo(fetchMock, 'GET /api/v1/auth/me')).toHaveLength(1)
  })
})

describe('login', () => {
  it('posts the credentials and sets the user', async () => {
    const fetchMock = mockApi({ 'POST /api/v1/auth/login': reply(200, makeUser()) })
    const auth = useAuthStore()
    await auth.login('maria@example.org', 'correct horse battery')
    expect(callsTo(fetchMock, 'POST /api/v1/auth/login')[0]!.body).toEqual({
      email: 'maria@example.org',
      password: 'correct horse battery',
    })
    expect(auth.status).toBe('authenticated')
    expect(auth.user?.display_name).toBe('Maria')
  })

  it('401 throws ApiError auth.invalid_credentials and leaves the store anonymous', async () => {
    mockApi({ 'POST /api/v1/auth/login': replyError(401, 'auth.invalid_credentials') })
    const auth = useAuthStore()
    await auth.fetchMe()
    const error = await auth.login('maria@example.org', 'wrong').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 401, code: 'auth.invalid_credentials' })
    expect(auth.status).toBe('anonymous')
    expect(auth.user).toBeNull()
  })
})

describe('logout', () => {
  it('posts /auth/logout and clears the user', async () => {
    const fetchMock = mockApi({
      'POST /api/v1/auth/login': reply(200, makeUser()),
      'POST /api/v1/auth/logout': reply(204),
    })
    const auth = useAuthStore()
    await auth.login('maria@example.org', 'correct horse battery')
    await auth.logout()
    expect(callsTo(fetchMock, 'POST /api/v1/auth/logout')).toHaveLength(1)
    expect(auth.user).toBeNull()
    expect(auth.status).toBe('anonymous')
  })

  it('clears locally even when the request fails', async () => {
    mockApi({
      'GET /api/v1/auth/me': reply(200, makeUser()),
      'POST /api/v1/auth/logout': replyError(500, 'internal'),
    })
    const auth = useAuthStore()
    await auth.fetchMe()
    await auth.logout()
    expect(auth.status).toBe('anonymous')
  })
})

describe('getters', () => {
  async function as(overrides: Parameters<typeof makeUser>[0]) {
    mockApi({ 'GET /api/v1/auth/me': reply(200, makeUser(overrides)) })
    const auth = useAuthStore()
    await auth.fetchMe()
    return auth
  }

  it('member: not admin, not superadmin', async () => {
    const auth = await as({ role: 'member' })
    expect(auth.isAdmin).toBe(false)
    expect(auth.isSuperadmin).toBe(false)
  })

  it('admin: isAdmin but not isSuperadmin', async () => {
    const auth = await as({ role: 'admin' })
    expect(auth.isAdmin).toBe(true)
    expect(auth.isSuperadmin).toBe(false)
  })

  it('superadmin: isAdmin and isSuperadmin', async () => {
    const auth = await as({ role: 'superadmin' })
    expect(auth.isAdmin).toBe(true)
    expect(auth.isSuperadmin).toBe(true)
  })

  it('isTrusted and isVerified follow the user flags', async () => {
    const trusted = await as({ is_trusted: true, is_verified: true })
    expect(trusted.isTrusted).toBe(true)
    expect(trusted.isVerified).toBe(true)

    setActivePinia(createPinia())
    const fresh = await as({ is_trusted: false, is_verified: false })
    expect(fresh.isTrusted).toBe(false)
    expect(fresh.isVerified).toBe(false)
  })

  it('all getters are false when anonymous', () => {
    const auth = useAuthStore()
    expect([auth.isAuthenticated, auth.isVerified, auth.isTrusted, auth.isAdmin]).toEqual([
      false,
      false,
      false,
      false,
    ])
  })
})

describe('other actions', () => {
  it('register posts the payload and does not log in', async () => {
    const fetchMock = mockApi({
      'POST /api/v1/auth/register': reply(201, {
        id: 7,
        email: 'new@example.org',
        display_name: 'New',
        is_verified: false,
      }),
    })
    const auth = useAuthStore()
    await auth.fetchMe()
    const payload = {
      email: 'new@example.org',
      password: 'a long enough password',
      display_name: 'New',
      organisation_id: null,
      organisation_other: null,
      country: 'GR',
      locale: 'el',
      accept_terms: true as const,
      turnstile_token: null,
    }
    const created = await auth.register(payload)
    expect(created.email).toBe('new@example.org')
    expect(callsTo(fetchMock, 'POST /api/v1/auth/register')[0]!.body).toEqual(payload)
    expect(auth.status).toBe('anonymous')
  })

  it('verifyEmail posts the token and sets the user', async () => {
    const fetchMock = mockApi({ 'POST /api/v1/auth/verify-email': reply(200, makeUser()) })
    const auth = useAuthStore()
    await auth.verifyEmail('tok123')
    expect(callsTo(fetchMock, 'POST /api/v1/auth/verify-email')[0]!.body).toEqual({
      token: 'tok123',
    })
    expect(auth.isAuthenticated).toBe(true)
  })

  it('resetPassword posts token + password and sets the user', async () => {
    const fetchMock = mockApi({ 'POST /api/v1/auth/password/reset': reply(200, makeUser()) })
    const auth = useAuthStore()
    await auth.resetPassword('tok', 'a brand new password')
    expect(callsTo(fetchMock, 'POST /api/v1/auth/password/reset')[0]!.body).toEqual({
      token: 'tok',
      password: 'a brand new password',
    })
    expect(auth.isAuthenticated).toBe(true)
  })

  it('resendVerification and forgotPassword post the email', async () => {
    const accepted = reply(202, { code: 'auth.email_sent', message: 'If…' })
    const fetchMock = mockApi({
      'POST /api/v1/auth/resend-verification': accepted,
      'POST /api/v1/auth/password/forgot': accepted,
    })
    const auth = useAuthStore()
    await auth.resendVerification('a@example.org')
    await auth.forgotPassword('b@example.org')
    expect(callsTo(fetchMock, 'POST /api/v1/auth/resend-verification')[0]!.body).toMatchObject({
      email: 'a@example.org',
    })
    expect(callsTo(fetchMock, 'POST /api/v1/auth/password/forgot')[0]!.body).toMatchObject({
      email: 'b@example.org',
    })
  })
})

describe('email change', () => {
  it('requestEmailChange posts the new address and the password', async () => {
    const fetchMock = mockApi({
      'POST /api/v1/auth/me/email': reply(202, { code: 'auth.email_change_sent', message: 'ok' }),
    })
    const auth = useAuthStore()
    const result = await auth.requestEmailChange('new@example.org', 'pw 1234567890')
    expect(result.code).toBe('auth.email_change_sent')
    expect(callsTo(fetchMock, 'POST /api/v1/auth/me/email')[0]!.body).toEqual({
      new_email: 'new@example.org',
      current_password: 'pw 1234567890',
    })
  })

  it('confirmEmailChange replaces the signed-in user when it is the same account', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/auth/me': reply(200, makeUser({ id: 1 })),
      'POST /api/v1/auth/email/confirm': reply(200, makeUser({ id: 1, email: 'new@example.org' })),
    })
    const auth = useAuthStore()
    await auth.fetchMe()
    const result = await auth.confirmEmailChange('tok')
    expect(callsTo(fetchMock, 'POST /api/v1/auth/email/confirm')[0]!.body).toEqual({ token: 'tok' })
    expect(result.email).toBe('new@example.org')
    expect(auth.user?.email).toBe('new@example.org')
  })

  it('confirmEmailChange does not sign anyone in', async () => {
    mockApi({
      'POST /api/v1/auth/email/confirm': reply(200, makeUser({ email: 'new@example.org' })),
    })
    const auth = useAuthStore()
    await auth.fetchMe()
    const result = await auth.confirmEmailChange('tok')
    expect(result.email).toBe('new@example.org')
    expect(auth.user).toBeNull()
    expect(auth.isAuthenticated).toBe(false)
  })

  it('confirmEmailChange leaves a different signed-in user alone', async () => {
    mockApi({
      'GET /api/v1/auth/me': reply(200, makeUser({ id: 2, email: 'other@example.org' })),
      'POST /api/v1/auth/email/confirm': reply(200, makeUser({ id: 1, email: 'new@example.org' })),
    })
    const auth = useAuthStore()
    await auth.fetchMe()
    await auth.confirmEmailChange('tok')
    expect(auth.user?.id).toBe(2)
    expect(auth.user?.email).toBe('other@example.org')
  })
})

describe('session expiry hook', () => {
  it('a 401 from another endpoint clears the store', async () => {
    mockApi({
      'GET /api/v1/auth/me': reply(200, makeUser()),
      'GET /api/v1/posts/': replyError(401, 'auth.not_authenticated'),
    })
    const auth = useAuthStore()
    await auth.fetchMe()
    expect(auth.isAuthenticated).toBe(true)

    await expect(api('/api/v1/posts/')).rejects.toBeInstanceOf(ApiError)
    expect(auth.status).toBe('anonymous')
    expect(auth.user).toBeNull()
  })

  it('a 401 from /auth/login does not clear an existing session', async () => {
    mockApi({
      'GET /api/v1/auth/me': reply(200, makeUser()),
      'POST /api/v1/auth/login': replyError(401, 'auth.invalid_credentials'),
    })
    const auth = useAuthStore()
    await auth.fetchMe()
    await api('/api/v1/auth/login', { method: 'POST', body: {} }).catch(() => undefined)
    expect(auth.isAuthenticated).toBe(true)
  })
})

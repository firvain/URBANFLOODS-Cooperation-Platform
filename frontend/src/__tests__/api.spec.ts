import { beforeEach, describe, expect, it, vi } from 'vitest'

async function loadApi() {
  vi.resetModules()
  return import('@/services/api')
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('api base URL', () => {
  it('is empty (same-origin) when VITE_API_BASE_URL is set to ""', async () => {
    vi.stubEnv('VITE_API_BASE_URL', '')
    const { API_BASE_URL, api } = await loadApi()
    expect(API_BASE_URL).toBe('')

    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: 'ok' }))
    vi.stubGlobal('fetch', fetchMock)
    await api('/api/v1/health')
    expect(String(fetchMock.mock.calls[0]![0])).toBe('/api/v1/health')
  })

  it('defaults to http://localhost:8000 when VITE_API_BASE_URL is unset', async () => {
    vi.stubEnv('VITE_API_BASE_URL', undefined)
    const { API_BASE_URL, api } = await loadApi()
    expect(API_BASE_URL).toBe('http://localhost:8000')

    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: 'ok' }))
    vi.stubGlobal('fetch', fetchMock)
    await api('/api/v1/health')
    expect(String(fetchMock.mock.calls[0]![0])).toBe('http://localhost:8000/api/v1/health')
  })
})

describe('api requests', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', '')
  })

  it('sends credentials and the X-Requested-With CSRF header', async () => {
    const { api } = await loadApi()
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await api('/api/v1/health', { method: 'POST', body: { a: 1 } })

    const init = fetchMock.mock.calls[0]![1] as RequestInit
    expect(init.credentials).toBe('include')
    expect(new Headers(init.headers).get('X-Requested-With')).toBe('XMLHttpRequest')
  })

  it('throws ApiError with status and detail.code on a 4xx JSON error', async () => {
    const { api, ApiError } = await loadApi()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(jsonResponse({ detail: { code: 'auth.invalid_credentials' } }, 401)),
    )

    const error = await api('/api/v1/auth/login', { method: 'POST' }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 401, code: 'auth.invalid_credentials' })
  })

  it('throws ApiError without a code when detail is not a code object', async () => {
    const { api, ApiError } = await loadApi()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: [{ msg: 'field required' }] }, 422)),
    )

    const error = await api('/api/v1/things', { method: 'POST' }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 422, code: undefined })
  })
})

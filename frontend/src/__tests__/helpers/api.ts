/**
 * Test helpers: a tiny route table for the global `fetch` that `services/api.ts` (ofetch) uses,
 * plus fixtures for the auth contract. Responses are built fresh for every call.
 */
import { vi, type Mock } from 'vitest'

import type { UserMe } from '@/services/auth'

export type MockRequest = { url: string; path: string; method: string; body: unknown }
export type Handler = (request: MockRequest) => Response | Promise<Response>
export type FetchMock = Mock<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** Handler that answers with `body` (JSON) and `status`; 204 has no body. */
export function reply(status: number, body?: unknown): Handler {
  return () => (status === 204 ? new Response(null, { status }) : jsonResponse(body ?? {}, status))
}

/** Handler for a backend error envelope `{"detail": {code, message, fields?}}`. */
export function replyError(
  status: number,
  code: string,
  fields?: Record<string, string>,
  message = code,
): Handler {
  return reply(status, { detail: { code, message, ...(fields ? { fields } : {}) } })
}

/** Handler that answers each call in turn from `handlers` (the last one repeats). */
export function sequence(...handlers: Handler[]): Handler {
  let call = 0
  return (request) => handlers[Math.min(call++, handlers.length - 1)]!(request)
}

function parseBody(body: BodyInit | null | undefined): unknown {
  if (typeof body !== 'string') return body ?? undefined
  try {
    return JSON.parse(body)
  } catch {
    return body
  }
}

/**
 * Replace `fetch` with a route table keyed by `"METHOD /path"` (path without host or query).
 * Unknown routes answer 404 `test.unmocked`; `GET /api/v1/auth/me` defaults to 401.
 */
export function mockApi(routes: Record<string, Handler> = {}): FetchMock {
  const table: Record<string, Handler> = {
    'GET /api/v1/auth/me': replyError(401, 'auth.not_authenticated'),
    ...routes,
  }
  const fetchMock: FetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const method = (init.method ?? 'GET').toUpperCase()
    const path = new URL(url, 'http://test.invalid').pathname
    const handler = table[`${method} ${path}`] ?? replyError(404, 'test.unmocked')
    return handler({ url, path, method, body: parseBody(init.body) })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** Requests made to `"METHOD /path"`, with parsed JSON bodies. */
export function callsTo(fetchMock: FetchMock, route: string): MockRequest[] {
  return fetchMock.mock.calls
    .map(([input, init = {}]) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      const method = (init.method ?? 'GET').toUpperCase()
      const path = new URL(url, 'http://test.invalid').pathname
      return { url, path, method, body: parseBody(init.body) }
    })
    .filter((r) => `${r.method} ${r.path}` === route)
}

export function makeUser(overrides: Partial<UserMe> = {}): UserMe {
  return {
    id: 1,
    email: 'maria@example.org',
    display_name: 'Maria',
    organisation: null,
    organisation_other: null,
    country: 'GR',
    locale: 'en',
    bio: null,
    expertise: [],
    show_email: false,
    show_in_directory: true,
    role: 'member',
    is_verified: true,
    is_trusted: false,
    trusted_at: null,
    created_at: '2026-10-01T10:00:00Z',
    ...overrides,
  }
}

export const ORGANISATIONS = {
  total: 2,
  items: [
    {
      id: 1,
      short_name: 'UOWM',
      name: 'University of Western Macedonia',
      country: 'GR',
      type: 'PP',
    },
    { id: 4, short_name: 'MC', name: 'Macerata Municipality', country: 'IT', type: 'PP' },
  ],
}

/** A promise you resolve from the outside (to hold a request open). */
export function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}

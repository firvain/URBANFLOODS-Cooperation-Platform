/**
 * Shared HTTP client. Every service module (`services/<resource>.ts`) goes through `api`.
 *
 * - Same-origin in production (`VITE_API_BASE_URL=""`), backend on :8000 in local dev.
 * - Sends the session cookie (`credentials: 'include'`).
 * - Sends `X-Requested-With: XMLHttpRequest`, which the backend CSRF middleware requires on
 *   unsafe methods.
 * - Turns error responses into `ApiError` carrying the backend error envelope
 *   (`detail.code`, `detail.message`, `detail.fields`); views translate the codes via vue-i18n.
 * - Reports 401 (lost session) and 429 (rate limited) through `setApiHooks`, which the auth store
 *   registers, so this module never imports a store.
 */
import { ofetch, type FetchResponse } from 'ofetch'

const DEV_API_BASE_URL = 'http://localhost:8000'

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? DEV_API_BASE_URL

export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  /** Per-field error codes from `detail.fields` (422 validation errors), e.g. `{password: "auth.password_too_common"}`. */
  readonly fields?: Record<string, string>

  constructor(status: number, code?: string, message?: string, fields?: Record<string, string>) {
    super(message ?? code ?? `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.fields = fields
  }
}

type ErrorDetail = { code?: string; message?: string; fields?: Record<string, string> }

/** The backend error envelope is `{"detail": {code, message, fields?}}`; anything else yields `{}`. */
function errorDetail(response: FetchResponse<unknown>): ErrorDetail {
  const data = response._data as { detail?: unknown } | undefined
  const detail = data?.detail
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return {}
  const { code, message, fields } = detail as Record<string, unknown>
  const result: ErrorDetail = {}
  if (typeof code === 'string') result.code = code
  if (typeof message === 'string') result.message = message
  if (fields && typeof fields === 'object' && !Array.isArray(fields)) {
    result.fields = Object.fromEntries(
      Object.entries(fields as Record<string, unknown>).filter(
        (entry): entry is [string, string] => typeof entry[1] === 'string',
      ),
    )
  }
  return result
}

/**
 * Callbacks the rest of the app registers (the auth store does, in its setup), so this module
 * never imports a store: no import cycle, and tests can install their own.
 */
export interface ApiHooks {
  /** A request other than `/auth/me` or `/auth/login` got 401: the session expired or was revoked. */
  onUnauthorized?: () => void
  /** The backend rate limiter answered 429. */
  onRateLimited?: () => void
}

const hooks: ApiHooks = {}

export function setApiHooks(next: ApiHooks): void {
  Object.assign(hooks, next)
}

/** 401 from these is an answer ("not logged in" / "wrong password"), not a lost session. */
const UNAUTHORIZED_EXEMPT = ['/auth/me', '/auth/login']

function requestPath(request: RequestInfo | URL): string {
  const url =
    typeof request === 'string' ? request : request instanceof URL ? request.href : request.url
  return new URL(url, 'http://placeholder.invalid').pathname.replace(/\/+$/, '')
}

export const api = ofetch.create({
  baseURL: API_BASE_URL,
  credentials: 'include',
  headers: { 'X-Requested-With': 'XMLHttpRequest' },

  onResponseError({ request, response }) {
    if (response.status === 401) {
      const path = requestPath(request)
      if (!UNAUTHORIZED_EXEMPT.some((suffix) => path.endsWith(suffix))) hooks.onUnauthorized?.()
    } else if (response.status === 429) {
      hooks.onRateLimited?.()
    }
    const { code, message, fields } = errorDetail(response)
    throw new ApiError(response.status, code, message ?? (response.statusText || undefined), fields)
  },
})

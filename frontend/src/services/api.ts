/**
 * Shared HTTP client. Every service module (`services/<resource>.ts`) goes through `api`.
 *
 * - Same-origin in production (`VITE_API_BASE_URL=""`), backend on :8000 in local dev.
 * - Sends the session cookie (`credentials: 'include'`).
 * - Sends `X-Requested-With: XMLHttpRequest`, which the backend CSRF middleware requires on
 *   unsafe methods.
 * - Turns error responses into `ApiError` carrying the backend error code (`detail.code`),
 *   which views translate through vue-i18n.
 */
import { ofetch, type FetchResponse } from 'ofetch'

const DEV_API_BASE_URL = 'http://localhost:8000'

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? DEV_API_BASE_URL

export class ApiError extends Error {
  readonly status: number
  readonly code?: string

  constructor(status: number, code?: string, message?: string) {
    super(message ?? code ?? `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

function errorCode(response: FetchResponse<unknown>): string | undefined {
  const data = response._data as { detail?: unknown } | undefined
  const detail = data?.detail
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const code = (detail as { code: unknown }).code
    if (typeof code === 'string') return code
  }
  return undefined
}

export const api = ofetch.create({
  baseURL: API_BASE_URL,
  credentials: 'include',
  headers: { 'X-Requested-With': 'XMLHttpRequest' },

  onResponseError({ response }) {
    // TODO(M1): on 401 clear the auth store (session expired or revoked).
    // TODO(M1): on 429 show a "too many requests" toast via useToast().
    throw new ApiError(response.status, errorCode(response), response.statusText || undefined)
  },
})

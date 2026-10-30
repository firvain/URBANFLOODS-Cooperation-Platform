/** Auth endpoints (`/api/v1/auth/*`). The session itself is the HttpOnly `uf_session` cookie. */
import { api } from './api'
import type { OrganisationSummary } from './organisations'

// TODO(gen:types): replace with components['schemas'][...] once generated (`npm run gen:types`).
// Hand-written only because the backend contract is being built concurrently (increment 1j).
export type UserRole = 'member' | 'admin' | 'superadmin'

export interface UserMe {
  id: number
  email: string
  display_name: string
  organisation: OrganisationSummary | null
  organisation_other: string | null
  country: string | null
  locale: string
  bio: string | null
  role: UserRole
  is_verified: boolean
  is_trusted: boolean
  trusted_at: string | null
  created_at: string
}

export interface RegisterPayload {
  email: string
  password: string
  display_name: string
  organisation_id?: number | null
  organisation_other?: string | null
  country?: string | null
  locale: string
  accept_terms: true
  turnstile_token?: string | null
}

export interface RegisterResponse {
  id: number
  email: string
  display_name: string
  is_verified: boolean
}

/** `PATCH /auth/me`: only the fields present are changed; `null` clears a nullable field. */
export interface UpdateMePayload {
  display_name?: string
  organisation_id?: number | null
  organisation_other?: string | null
  country?: string | null
  locale?: string
  bio?: string | null
}

/** One of the user's active sessions (`GET /auth/me/sessions`). */
export interface SessionInfo {
  id: string
  created_at: string
  last_seen_at: string
  expires_at: string
  user_agent: string | null
  is_current: boolean
}

export interface SessionList {
  total: number
  items: SessionInfo[]
}

/** 202 body of the "always accepted" endpoints (resend verification, forgot password). */
export interface AcceptedResponse {
  code: string
  message: string
}

const BASE = '/api/v1/auth'

export const authService = {
  me: () => api<UserMe>(`${BASE}/me`),

  login: (email: string, password: string) =>
    api<UserMe>(`${BASE}/login`, { method: 'POST', body: { email, password } }),

  logout: () => api<void>(`${BASE}/logout`, { method: 'POST' }),

  register: (payload: RegisterPayload) =>
    api<RegisterResponse>(`${BASE}/register`, { method: 'POST', body: payload }),

  verifyEmail: (token: string) =>
    api<UserMe>(`${BASE}/verify-email`, { method: 'POST', body: { token } }),

  resendVerification: (email: string, turnstileToken?: string | null) =>
    api<AcceptedResponse>(`${BASE}/resend-verification`, {
      method: 'POST',
      body: { email, turnstile_token: turnstileToken ?? null },
    }),

  forgotPassword: (email: string, turnstileToken?: string | null) =>
    api<AcceptedResponse>(`${BASE}/password/forgot`, {
      method: 'POST',
      body: { email, turnstile_token: turnstileToken ?? null },
    }),

  resetPassword: (token: string, password: string) =>
    api<UserMe>(`${BASE}/password/reset`, { method: 'POST', body: { token, password } }),

  updateMe: (changes: UpdateMePayload) =>
    api<UserMe>(`${BASE}/me`, { method: 'PATCH', body: changes }),

  /** 204; other sessions are signed out, this one stays. */
  changePassword: (currentPassword: string, newPassword: string) =>
    api<void>(`${BASE}/me/password`, {
      method: 'POST',
      body: { current_password: currentPassword, new_password: newPassword },
    }),

  listSessions: () => api<SessionList>(`${BASE}/me/sessions`),

  revokeSession: (id: string) =>
    api<void>(`${BASE}/me/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}

/** Auth endpoints (`/api/v1/auth/*`). The session itself is the HttpOnly `uf_session` cookie. */
import type { components } from '@/types/api-schema'
import { api } from './api'
import type { ExpertiseTag } from './expertise'
import type { OrganisationSummary } from './organisations'

// TODO(gen:types): replace with components['schemas'][...] once generated (`npm run gen:types`).
// Hand-written only because the backend contract is being built concurrently (increments 1j, 1n).
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
  /** Expertise areas (Collaboration Network matchmaking). */
  expertise: ExpertiseTag[]
  /** Opt-in: other members see the email address in the directory and on the profile. */
  show_email: boolean
  /** Whether the member appears in the Collaboration Network directory. */
  show_in_directory: boolean
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
  /** Optional expertise areas (at most 8). */
  expertise_ids?: number[]
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
  /** Replaces the whole set (at most 8). */
  expertise_ids?: number[]
  show_email?: boolean
  show_in_directory?: boolean
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

/** Email notification preferences (`GET`/`PUT /auth/me/notifications`; PUT replaces all). */
export type NotificationPreferences = components['schemas']['NotificationPreferences']
export type DigestFrequency = components['schemas']['DigestFrequency']

/** The account data download (`GET /auth/me/export`). */
export interface AccountExportFile {
  blob: Blob
  filename: string
}

const EXPORT_FALLBACK_FILENAME = 'urbanfloods-account.json'

/** The filename of a `Content-Disposition` header (`filename*=UTF-8''…` or `filename="…"`). */
export function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null
  const encoded = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(header)
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1]!.trim().replace(/^"|"$/g, ''))
    } catch {
      // Fall through to the plain parameter.
    }
  }
  const plain = /filename\s*=\s*(?:"([^"]*)"|([^;]+))/.exec(header)
  const name = (plain?.[1] ?? plain?.[2])?.trim()
  return name || null
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

  /**
   * 202; a confirmation link goes to the new address (the same 202 when it belongs to someone
   * else). 400 `auth.invalid_credentials` for a wrong password, 422 `new_email: auth.email_same`.
   */
  requestEmailChange: (newEmail: string, currentPassword: string) =>
    api<AcceptedResponse>(`${BASE}/me/email`, {
      method: 'POST',
      body: { new_email: newEmail, current_password: currentPassword },
    }),

  /** The emailed link: switches the account to the new address. No session needed or created. */
  confirmEmailChange: (token: string) =>
    api<UserMe>(`${BASE}/email/confirm`, { method: 'POST', body: { token } }),

  listSessions: () => api<SessionList>(`${BASE}/me/sessions`),

  revokeSession: (id: string) =>
    api<void>(`${BASE}/me/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  getNotifications: () => api<NotificationPreferences>(`${BASE}/me/notifications`),

  /** Full replace: every field is sent. */
  updateNotifications: (preferences: NotificationPreferences) =>
    api<NotificationPreferences>(`${BASE}/me/notifications`, { method: 'PUT', body: preferences }),

  /** The account data as a file (with the session cookie, like every request here). */
  async exportData(): Promise<AccountExportFile> {
    const response = await api.raw(`${BASE}/me/export`, { responseType: 'blob' })
    return {
      blob: response._data as Blob,
      filename:
        filenameFromDisposition(response.headers.get('content-disposition')) ??
        EXPORT_FALLBACK_FILENAME,
    }
  },

  /**
   * 204; the account is erased and every session ends. 400 `auth.invalid_credentials` for a
   * wrong password, 409 `admin.last_superadmin` for the only superadmin.
   */
  deleteMe: (currentPassword: string) =>
    api<void>(`${BASE}/me`, { method: 'DELETE', body: { current_password: currentPassword } }),
}

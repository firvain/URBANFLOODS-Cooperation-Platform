/**
 * Admin endpoints (`/api/v1/admin/*`): dashboard stats, the reporting CSV, the KNOWBASE cache,
 * the admin digest and user management. Admins only; role rules are enforced by the backend (`admin.*` codes).
 */
import type { components, operations } from '@/types/api-schema'
import { api } from './api'
import { filenameFromDisposition } from './auth'

export type AdminStats = components['schemas']['AdminStats']
export type AdminUser = components['schemas']['AdminUserOut']
export type AdminUserList = components['schemas']['AdminUserList']
export type AdminUserListParams = NonNullable<
  operations['list_users_api_v1_admin_users__get']['parameters']['query']
>
export type UserRole = components['schemas']['UserRole']
export type CacheClearResult = components['schemas']['CacheClearResult']
export type DigestSendResult = components['schemas']['DigestSendResult']
export type MessageResponse = components['schemas']['MessageResponse']

/** The one-click user actions (`POST /admin/users/{id}/<action>`). */
export type UserAction = 'promote' | 'demote' | 'ban' | 'unban' | 'trust' | 'untrust'
/** `promote?to=`: admins may raise to `admin`, superadmins also to `superadmin`. */
export type PromoteTarget = 'admin' | 'superadmin'

export interface StatsExportRange {
  /** `YYYY-MM-DD`, inclusive. */
  from: string
  to: string
}

export interface StatsExportFile {
  blob: Blob
  filename: string
}

const BASE = '/api/v1/admin'

const userPath = (id: number, action?: string) => `${BASE}/users/${id}${action ? `/${action}` : ''}`

export const adminService = {
  stats: () => api<AdminStats>(`${BASE}/stats`),

  clearKnowbaseCache: () =>
    api<CacheClearResult>(`${BASE}/knowbase/cache/clear`, { method: 'POST' }),

  /** Send the admin moderation digest now (forced), to every admin who has it switched on. */
  sendDigest: () => api<DigestSendResult>(`${BASE}/digest/send`, { method: 'POST' }),

  /** The reporting CSV for `from`..`to` (with the session cookie, like every request here). */
  async exportStats({ from, to }: StatsExportRange): Promise<StatsExportFile> {
    const response = await api.raw(`${BASE}/stats/export.csv`, {
      query: { from, to },
      responseType: 'blob',
    })
    return {
      blob: response._data as Blob,
      filename:
        filenameFromDisposition(response.headers.get('content-disposition')) ??
        `urbanfloods-report-${from}-${to}.csv`,
    }
  },

  listUsers: (params: AdminUserListParams = {}) =>
    api<AdminUserList>(`${BASE}/users/`, { query: { ...params } }),

  userAction: (id: number, action: UserAction, to?: PromoteTarget) =>
    api<AdminUser>(userPath(id, action), {
      method: 'POST',
      query: action === 'promote' && to ? { to } : undefined,
    }),

  resendVerification: (id: number) =>
    api<MessageResponse>(userPath(id, 'resend-verification'), { method: 'POST' }),
}

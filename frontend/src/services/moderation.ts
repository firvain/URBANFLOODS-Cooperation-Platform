/**
 * Moderation endpoints for admins: the approval queue, the deleted posts and threads, content actions
 * (`/api/v1/moderation/{type}/{id}/<action>`, `.../purge` for a permanent delete), the audit log, and the admin side of reports
 * (list, resolve, dismiss). Members file reports through `services/reports.ts`; an author resubmits
 * their rejected post or thread through `resubmit`.
 */
import type { components, operations } from '@/types/api-schema'
import { api } from './api'

export type ContentType = components['schemas']['ContentType']
export type ContentStatus = components['schemas']['ContentStatus']
export type QueueItem = components['schemas']['QueueItem']
export type ModerationQueue = components['schemas']['ModerationQueue']
export type DeletedItem = components['schemas']['DeletedItem']
export type DeletedPage = components['schemas']['DeletedPage']
export type ModerationResult = components['schemas']['ModerationResult']
export type PurgeResult = components['schemas']['PurgeResultOut']
export type AuditLogEntry = components['schemas']['AuditLogEntry']
export type AuditLogPage = components['schemas']['AuditLogPage']
export type ReportDetail = components['schemas']['ReportDetail']
export type PaginatedReports = components['schemas']['PaginatedReports']
export type ReportStatus = components['schemas']['ReportStatus']
export type ReportReason = components['schemas']['ReportReason']

export type QueueParams = NonNullable<
  operations['moderation_queue_api_v1_moderation_queue__get']['parameters']['query']
>
export type DeletedParams = NonNullable<
  operations['deleted_content_api_v1_moderation_deleted__get']['parameters']['query']
>
export type LogParams = NonNullable<
  operations['moderation_log_api_v1_moderation_log__get']['parameters']['query']
>
export type ReportListParams = NonNullable<
  operations['list_reports_api_v1_reports__get']['parameters']['query']
>

export type ModerationAction = 'approve' | 'reject' | 'hide' | 'unhide' | 'delete' | 'restore'
/** The actions whose (optional) reason goes into the audit row. */
const WITH_REASON: readonly ModerationAction[] = ['reject', 'hide']

const BASE = '/api/v1/moderation'
const REPORTS = '/api/v1/reports'

export const moderationService = {
  queue: (params: QueueParams = {}) =>
    api<ModerationQueue>(`${BASE}/queue/`, { query: { ...params } }),

  /** Deleted posts and threads, newest deletion first (restore or purge them with `act`/`purge`). */
  listDeleted: (params: DeletedParams = {}) =>
    api<DeletedPage>(`${BASE}/deleted/`, { query: { ...params } }),

  log: (params: LogParams = {}) => api<AuditLogPage>(`${BASE}/log/`, { query: { ...params } }),

  /** `reason` is sent (as `null` when blank) for reject and hide only. */
  act: (type: ContentType, id: number, action: ModerationAction, reason?: string | null) =>
    api<ModerationResult>(`${BASE}/${type}/${id}/${action}`, {
      method: 'POST',
      body: WITH_REASON.includes(action) ? { reason: reason?.trim() || null } : undefined,
    }),

  /** Permanent delete from any status (comments/replies and images used only there go too). */
  purge: (type: ContentType, id: number) =>
    api<PurgeResult>(`${BASE}/${type}/${id}/purge`, { method: 'POST' }),

  /** The author sends their rejected post or thread for approval again (back to pending). */
  resubmit: (type: 'post' | 'thread', id: number) =>
    api<ModerationResult>(`${BASE}/${type}/${id}/resubmit`, { method: 'POST' }),

  listReports: (params: ReportListParams = {}) =>
    api<PaginatedReports>(`${REPORTS}/`, { query: { ...params } }),

  resolveReport: (id: number) => api<ReportDetail>(`${REPORTS}/${id}/resolve`, { method: 'POST' }),

  dismissReport: (id: number) => api<ReportDetail>(`${REPORTS}/${id}/dismiss`, { method: 'POST' }),
}

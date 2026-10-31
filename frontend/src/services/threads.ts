/**
 * Forum threads (`/api/v1/threads/*`). Reading is public (the backend applies the visibility
 * rule: the public sees published threads, authors also their own pending/hidden ones, admins
 * all); writing needs a verified account; pin/lock are for admins. Errors arrive as `ApiError`:
 * 404 `threads.not_found`, 403 `threads.forbidden | threads.category_admin_only`, 423
 * `threads.locked`, 422 `validation.failed` with `fields`, 503 `knowbase.unavailable`.
 */
import type { components, operations } from '@/types/api-schema'
import { api } from './api'

export type ThreadSummary = components['schemas']['ThreadSummary']
export type ThreadDetail = components['schemas']['ThreadDetail']
export type PaginatedThreads = components['schemas']['PaginatedThreads']
export type ThreadCreate = components['schemas']['ThreadCreate']
export type ThreadUpdate = components['schemas']['ThreadUpdate']
export type ThreadLocale = ThreadCreate['locale']
export type ThreadListParams = NonNullable<
  operations['list_threads_api_v1_threads__get']['parameters']['query']
>
export type ThreadSort = NonNullable<ThreadListParams['sort']>

/** Admin moderation actions (`POST /threads/{id}/<action>`), each answering the new detail. */
export type ThreadAdminAction = 'pin' | 'unpin' | 'lock' | 'unlock'

const BASE = '/api/v1/threads'

export const threadsService = {
  list: (params: ThreadListParams = {}) =>
    api<PaginatedThreads>(`${BASE}/`, { query: { ...params } }),

  get: (slug: string) => api<ThreadDetail>(`${BASE}/${encodeURIComponent(slug)}`),

  /** 201; `status` is `pending` for authors who are not trusted yet. */
  create: (body: ThreadCreate) => api<ThreadDetail>(`${BASE}/`, { method: 'POST', body }),

  /** Only the fields present are changed. */
  update: (id: number, body: ThreadUpdate) =>
    api<ThreadDetail>(`${BASE}/${id}`, { method: 'PATCH', body }),

  /** 204. */
  remove: (id: number) => api<void>(`${BASE}/${id}`, { method: 'DELETE' }),

  /** Admins: pin, unpin, lock or unlock a thread. */
  moderate: (id: number, action: ThreadAdminAction) =>
    api<ThreadDetail>(`${BASE}/${id}/${action}`, { method: 'POST' }),
}

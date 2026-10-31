/**
 * Replies to forum threads (`/api/v1/threads/{id}/replies/`, `/api/v1/replies/{id}`). Listing
 * follows the thread's visibility; posting needs a verified account and an unlocked, published
 * thread. One level of nesting: a reply to a reply carries `parent_reply_id` of a top-level reply.
 * A deleted reply that still has children is listed as a placeholder (`status "deleted"`,
 * `body_html ""`, `author null`). Errors arrive as `ApiError`: 423 `threads.locked`, 403
 * `replies.forbidden`, 404 `replies.not_found`, 422 `validation.failed` with `fields`
 * (`body_html: "empty" | "too_long"`, `parent_reply_id: "invalid"`).
 */
import type { components } from '@/types/api-schema'
import { api } from './api'

// TODO(gen:types): the replies routes (increment 3c) are not in the OpenAPI schema yet; replace
// these hand-typed interfaces with `components['schemas']['ReplyOut']` etc. after `npm run gen:types`.
export interface ReplyOut {
  id: number
  thread_id: number
  parent_reply_id: number | null
  author: components['schemas']['AuthorSummary'] | null
  body_html: string
  status: components['schemas']['ContentStatus']
  created_at: string
  updated_at: string
  is_edited: boolean
  children: ReplyOut[]
}

export interface PaginatedReplies {
  /** Top-level replies only. */
  total: number
  items: ReplyOut[]
}

export interface ReplyCreate {
  body_html: string
  parent_reply_id?: number | null
}

export interface ReplyUpdate {
  body_html: string
}

export interface ReplyListParams {
  skip?: number
  /** At most 50 (default 20). */
  limit?: number
}

const repliesOf = (threadId: number) => `/api/v1/threads/${threadId}/replies/`
const BASE = '/api/v1/replies'

export const repliesService = {
  list: (threadId: number, params: ReplyListParams = {}) =>
    api<PaginatedReplies>(repliesOf(threadId), { query: { ...params } }),

  /** 201. */
  create: (threadId: number, body: ReplyCreate) =>
    api<ReplyOut>(repliesOf(threadId), { method: 'POST', body }),

  update: (id: number, body: ReplyUpdate) =>
    api<ReplyOut>(`${BASE}/${id}`, { method: 'PATCH', body }),

  /** 204. */
  remove: (id: number) => api<void>(`${BASE}/${id}`, { method: 'DELETE' }),
}

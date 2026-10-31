/**
 * Comments on blog posts (`/api/v1/posts/{id}/comments/`, `/api/v1/comments/{id}`). Flat, oldest
 * first; deleted comments are left out of the list. Listing follows the post's visibility;
 * posting needs a verified account and a published post. Authors edit for 24 hours, admins
 * always. Errors arrive as `ApiError`: 404 `comments.not_found`, 403 `comments.forbidden`,
 * 422 `comments.post_not_published`, 422 `validation.failed` with `fields`
 * (`body_html: "empty" | "too_long"`).
 */
import type { components, operations } from '@/types/api-schema'
import { api } from './api'

export type CommentOut = components['schemas']['CommentOut']
export type PaginatedComments = components['schemas']['PaginatedComments']
export type CommentCreate = components['schemas']['CommentCreate']
export type CommentUpdate = components['schemas']['CommentUpdate']
export type CommentListParams = NonNullable<
  operations['list_comments_api_v1_posts__post_id__comments__get']['parameters']['query']
>

const commentsOf = (postId: number) => `/api/v1/posts/${postId}/comments/`
const BASE = '/api/v1/comments'

export const commentsService = {
  list: (postId: number, params: CommentListParams = {}) =>
    api<PaginatedComments>(commentsOf(postId), { query: { ...params } }),

  /** 201. */
  create: (postId: number, body: CommentCreate) =>
    api<CommentOut>(commentsOf(postId), { method: 'POST', body }),

  update: (id: number, body: CommentUpdate) =>
    api<CommentOut>(`${BASE}/${id}`, { method: 'PATCH', body }),

  /** 204. */
  remove: (id: number) => api<void>(`${BASE}/${id}`, { method: 'DELETE' }),
}

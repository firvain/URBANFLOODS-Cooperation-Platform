/**
 * Blog posts (`/api/v1/posts/*`). Reading is public (the backend applies the visibility rule:
 * the public sees published posts, authors also their own pending/hidden ones, admins all);
 * writing needs a verified account. Errors arrive as `ApiError`: 404 `posts.not_found`,
 * 403 `posts.forbidden | posts.category_admin_only`, 422 `validation.failed` with `fields`
 * (`body_html: "empty"`, `category_id`, `cover_attachment_id: "invalid"`, `event_url`,
 * `knowbase_links: "not_found"`), 503 `knowbase.unavailable` (links cannot be checked).
 */
import type { components, operations } from '@/types/api-schema'
import { api } from './api'

export type PostSummary = components['schemas']['PostSummary']
export type PostDetail = components['schemas']['PostDetail']
export type PaginatedPosts = components['schemas']['PaginatedPosts']
export type PostCreate = components['schemas']['PostCreate']
export type PostUpdate = components['schemas']['PostUpdate']
export type PostStatus = components['schemas']['ContentStatus']
export type PostLocale = PostCreate['locale']
export type PostListParams = NonNullable<
  operations['list_posts_api_v1_posts__get']['parameters']['query']
>

const BASE = '/api/v1/posts'

export const postsService = {
  list: (params: PostListParams = {}) => api<PaginatedPosts>(`${BASE}/`, { query: { ...params } }),

  get: (slug: string) => api<PostDetail>(`${BASE}/${encodeURIComponent(slug)}`),

  /** 201; `status` is `pending` for authors who are not trusted yet. */
  create: (body: PostCreate) => api<PostDetail>(`${BASE}/`, { method: 'POST', body }),

  /** Only the fields present are changed; `null` clears the nullable ones. */
  update: (id: number, body: PostUpdate) =>
    api<PostDetail>(`${BASE}/${id}`, { method: 'PATCH', body }),

  /** 204. */
  remove: (id: number) => api<void>(`${BASE}/${id}`, { method: 'DELETE' }),
}

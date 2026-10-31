/** Fixtures for the comments contract (`/posts/{id}/comments/`, `/comments/{id}`). */
import type { CommentOut } from '@/services/comments'
import { OTHER } from './forum'

export const commentsOf = (postId: number) => `/api/v1/posts/${postId}/comments/`
export const commentUrl = (commentId: number) => `/api/v1/comments/${commentId}`

export function makeComment(id: number, overrides: Partial<CommentOut> = {}): CommentOut {
  return {
    id,
    post_id: 42,
    author: OTHER,
    body_html: `<p>Comment ${id}</p>`,
    status: 'published',
    created_at: '2026-10-30T08:00:00Z',
    updated_at: '2026-10-30T08:00:00Z',
    is_edited: false,
    ...overrides,
  }
}

/** One page of `GET /posts/42/comments/` out of `total`. */
export function commentPage(total: number, skip = 0, limit = 50) {
  const count = Math.max(0, Math.min(limit, total - skip))
  return { total, items: Array.from({ length: count }, (_, i) => makeComment(skip + i + 1)) }
}

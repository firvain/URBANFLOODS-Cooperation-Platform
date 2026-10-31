/**
 * The public page of a piece of content: posts and threads by slug; replies and comments by
 * their thread's / post's slug with the `#reply-<id>` / `#comment-<id>` anchor of their item.
 */
import type { components } from '@/types/api-schema'

export type ContentType = components['schemas']['ContentType']

export function contentLink(type: ContentType, id: number, slug: string | null | undefined) {
  if (!slug) return null
  const path = encodeURIComponent(slug)
  switch (type) {
    case 'post':
      return `/blog/${path}`
    case 'thread':
      return `/forum/t/${path}`
    case 'reply':
      return `/forum/t/${path}#reply-${id}`
    case 'comment':
      return `/blog/${path}#comment-${id}`
  }
}

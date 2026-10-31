/** Fixtures for the blog contract (`/posts/`, `/categories/`, `/tags/`). */
import type { Handler } from './api'
import { jsonResponse } from './api'
import type { CategoryOut } from '@/services/categories'
import type { PostDetail, PostSummary } from '@/services/posts'
import type { TagOut } from '@/services/tags'

export const POSTS = 'GET /api/v1/posts/'
export const CREATE_POST = 'POST /api/v1/posts/'
export const BLOG_CATEGORIES = 'GET /api/v1/categories/'
export const TAGS = 'GET /api/v1/tags/'

/** Search params of a mocked request. */
export const paramsOf = (url: string) => new URL(url, 'http://x.invalid').searchParams

function category(
  id: number,
  slug: string,
  name: string,
  overrides: Partial<CategoryOut> = {},
): CategoryOut {
  return {
    id,
    kind: 'blog',
    slug,
    name,
    name_i18n: {},
    description: null,
    sort_order: id,
    is_archived: false,
    admin_only: false,
    post_count: 1,
    ...overrides,
  }
}

export const CATEGORIES: CategoryOut[] = [
  category(1, 'news', 'News'),
  category(2, 'best-practices', 'Best practices'),
  category(3, 'events', 'Events'),
  category(5, 'project-updates', 'Project updates', { admin_only: true }),
]

export const CATEGORY_LIST = { total: CATEGORIES.length, items: CATEGORIES }

export const TAG_NBS: TagOut = { id: 17, slug: 'nbs', name: 'NBS', usage_count: 3 }
export const TAG_DRAINAGE: TagOut = {
  id: 18,
  slug: 'urban-drainage',
  name: 'urban drainage',
  usage_count: 2,
}
export const TAG_LIST = { total: 2, items: [TAG_NBS, TAG_DRAINAGE] }

export const AUTHOR = {
  id: 11,
  display_name: 'Eleni Papadopoulou',
  organisation: {
    id: 1,
    short_name: 'UOWM',
    name: 'University of Western Macedonia',
    country: 'GR',
    type: 'PP' as const,
  },
  avatar_url: null,
  has_profile: true,
}

export const COVER = {
  id: 7,
  url: '/static/uploads/2026/10/cover.webp',
  thumb_url: '/static/uploads/2026/10/cover_thumb.webp',
  width: 1600,
  height: 900,
  alt_text: 'Rain garden in a school yard',
}

export function makePost(id: number, overrides: Partial<PostSummary> = {}): PostSummary {
  return {
    id,
    slug: `post-${id}`,
    title: `Post ${id}`,
    excerpt: `Excerpt of post ${id}.`,
    locale: 'en',
    status: 'published',
    category: { id: 2, kind: 'blog', slug: 'best-practices', name: 'Best practices' },
    author: AUTHOR,
    cover: null,
    tags: [TAG_NBS],
    event_at: null,
    event_url: null,
    comment_count: 0,
    published_at: '2026-10-20T09:00:00Z',
    created_at: '2026-10-20T09:00:00Z',
    updated_at: '2026-10-20T09:00:00Z',
    ...overrides,
  }
}

export function makePostDetail(overrides: Partial<PostDetail> = {}): PostDetail {
  return {
    ...makePost(42, {
      slug: 'rain-gardens-in-kozani',
      title: 'Rain gardens in Kozani',
      excerpt: 'How Kozani reduces surface runoff with rain gardens.',
      cover: COVER,
      tags: [TAG_NBS, TAG_DRAINAGE],
      comment_count: 3,
    }),
    body_html: '<p>Kozani tests <strong>nature-based solutions</strong>.</p>',
    knowbase_links: [
      {
        kb_type: 'measure',
        kb_id: 2,
        title_en: 'Rain gardens',
        title_local: null,
        url: '/knowbase/measures/2',
      },
      {
        kb_type: 'document',
        kb_id: 1,
        title_en: 'Water Framework Directive',
        title_local: null,
        url: '/knowbase/documents/1',
      },
    ],
    approved_at: null,
    hidden_reason: null,
    deleted_at: null,
    ...overrides,
  }
}

/** One page of `GET /posts/` out of `total`. */
export function postPage(total: number, skip = 0, limit = 12) {
  const count = Math.max(0, Math.min(limit, total - skip))
  return { total, items: Array.from({ length: count }, (_, i) => makePost(skip + i + 1)) }
}

/** Handler serving `GET /posts/` pages out of `total`, honouring skip/limit. */
export function postPages(total: number): Handler {
  return (request) => {
    const query = paramsOf(request.url)
    return jsonResponse(
      postPage(total, Number(query.get('skip') ?? 0), Number(query.get('limit') ?? 12)),
    )
  }
}

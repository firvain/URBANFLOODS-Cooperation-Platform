/** Fixtures for the forum contract (`/threads/`, `/threads/{id}/replies/`, `/replies/{id}`). */
import type { Handler } from './api'
import { jsonResponse } from './api'
import { AUTHOR, TAG_NBS, paramsOf } from './blog'
import type { CategoryOut } from '@/services/categories'
import type { ReplyOut } from '@/services/replies'
import type { ThreadDetail, ThreadSummary } from '@/services/threads'

export const THREADS = 'GET /api/v1/threads/'
export const CREATE_THREAD = 'POST /api/v1/threads/'
export const FORUM_CATEGORIES = 'GET /api/v1/categories/'

export const repliesOf = (threadId: number) => `/api/v1/threads/${threadId}/replies/`
export const replyUrl = (replyId: number) => `/api/v1/replies/${replyId}`

function forumCategory(
  id: number,
  slug: string,
  name: string,
  overrides: Partial<CategoryOut> = {},
): CategoryOut {
  return {
    id,
    kind: 'forum',
    slug,
    name,
    name_i18n: {},
    description: null,
    sort_order: id,
    is_archived: false,
    admin_only: false,
    post_count: 0,
    ...overrides,
  }
}

export const FORUM_CATEGORY_ITEMS: CategoryOut[] = [
  forumCategory(21, 'general', 'General discussion'),
  forumCategory(22, 'early-warning', 'Early warning'),
  forumCategory(23, 'nbs', 'Nature-based solutions'),
  forumCategory(24, 'announcements', 'Announcements', { admin_only: true }),
]

export const FORUM_CATEGORY_LIST = {
  total: FORUM_CATEGORY_ITEMS.length,
  items: FORUM_CATEGORY_ITEMS,
}

/** Another member (not the thread author). */
export const OTHER = {
  id: 12,
  display_name: 'Marko Petrović',
  organisation: null,
  avatar_url: null,
  has_profile: true,
}

export function makeThread(id: number, overrides: Partial<ThreadSummary> = {}): ThreadSummary {
  return {
    id,
    slug: `thread-${id}`,
    title: `Thread ${id}`,
    excerpt: `Excerpt of thread ${id}.`,
    locale: 'en',
    status: 'published',
    category: { id: 22, kind: 'forum', slug: 'early-warning', name: 'Early warning' },
    author: AUTHOR,
    tags: [TAG_NBS],
    is_pinned: false,
    is_locked: false,
    reply_count: 2,
    last_activity_at: '2026-10-30T09:00:00Z',
    published_at: '2026-10-20T09:00:00Z',
    created_at: '2026-10-20T09:00:00Z',
    updated_at: '2026-10-20T09:00:00Z',
    ...overrides,
  }
}

export function makeThreadDetail(overrides: Partial<ThreadDetail> = {}): ThreadDetail {
  return {
    ...makeThread(42, {
      slug: 'sirens-or-sms',
      title: 'Sirens or SMS for flood warnings?',
      excerpt: 'Which channel reaches residents faster?',
      reply_count: 3,
    }),
    body_html: '<p>Which channel reaches residents <strong>faster</strong>?</p>',
    knowbase_links: [
      {
        kb_type: 'measure',
        kb_id: 2,
        title_en: 'early warning systems',
        title_local: null,
        url: '/knowbase/measures/2',
      },
    ],
    approved_at: null,
    hidden_reason: null,
    moderation_note: null,
    deleted_at: null,
    ...overrides,
  }
}

export function makeReply(id: number, overrides: Partial<ReplyOut> = {}): ReplyOut {
  return {
    id,
    thread_id: 42,
    parent_reply_id: null,
    author: OTHER,
    body_html: `<p>Reply ${id}</p>`,
    status: 'published',
    created_at: '2026-10-30T08:00:00Z',
    updated_at: '2026-10-30T08:00:00Z',
    is_edited: false,
    children: [],
    ...overrides,
  }
}

/** One page of `GET /threads/` out of `total`. */
export function threadPage(total: number, skip = 0, limit = 20) {
  const count = Math.max(0, Math.min(limit, total - skip))
  return { total, items: Array.from({ length: count }, (_, i) => makeThread(skip + i + 1)) }
}

/** Handler serving `GET /threads/` pages out of `total`, honouring skip/limit. */
export function threadPages(total: number): Handler {
  return (request) => {
    const query = paramsOf(request.url)
    return jsonResponse(
      threadPage(total, Number(query.get('skip') ?? 0), Number(query.get('limit') ?? 20)),
    )
  }
}

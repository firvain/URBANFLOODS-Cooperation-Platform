/** Fixtures for the search contract (`GET /api/v1/search/`). */
import type { Handler } from './api'
import { jsonResponse } from './api'
import type { SearchHit } from '@/services/search'

export const SEARCH = 'GET /api/v1/search/'

export function makeHit(id: number, overrides: Partial<SearchHit> = {}): SearchHit {
  const type = overrides.type ?? (id % 2 ? 'post' : 'thread')
  return {
    type,
    id,
    slug: `${type}-${id}`,
    title: `${type === 'post' ? 'Post' : 'Thread'} ${id} about floods`,
    snippet: `Text about <mark>floods</mark> number ${id}`,
    locale: 'en',
    author: { id: 11, display_name: 'Eleni Papadopoulou' },
    category: { id: 2, slug: 'best-practices', name: 'Best practices' },
    published_at: '2026-10-20T09:00:00Z',
    rank: 1 / id,
    ...overrides,
  }
}

/** One page of hits out of `total`. */
export function hitPage(total: number, skip = 0, limit = 20) {
  const count = Math.max(0, Math.min(limit, total - skip))
  return { total, items: Array.from({ length: count }, (_, i) => makeHit(skip + i + 1)) }
}

/** Handler serving search pages out of `total`, honouring skip/limit. */
export function hitPages(total: number): Handler {
  return (request) => {
    const query = new URL(request.url, 'http://x.invalid').searchParams
    return jsonResponse(
      hitPage(total, Number(query.get('skip') ?? 0), Number(query.get('limit') ?? 20)),
    )
  }
}

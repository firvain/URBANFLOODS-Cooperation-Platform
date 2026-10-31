/**
 * Site search (`GET /api/v1/search/`): one ranked list of blog posts and forum threads, with the
 * same visibility rules as the lists. `snippet` is escaped text whose only markup is `<mark>`;
 * render it through `SafeHtml` with `allowedTags: ['mark']`. Errors arrive as `ApiError`: 422
 * `validation.failed` (query shorter than 2 characters), 429 (rate limited, toast in `api.ts`).
 */
import type { components, operations } from '@/types/api-schema'
import { api } from './api'

export type SearchHit = components['schemas']['SearchHit']
export type PaginatedSearch = components['schemas']['PaginatedSearch']
export type SearchParams = operations['search_api_v1_search__get']['parameters']['query']
export type SearchType = NonNullable<SearchParams['type']>

export const SEARCH_TYPES: readonly SearchType[] = ['all', 'posts', 'threads']

const BASE = '/api/v1/search'

export const searchService = {
  search: (params: SearchParams, signal?: AbortSignal) =>
    api<PaginatedSearch>(`${BASE}/`, { query: { ...params }, signal }),
}

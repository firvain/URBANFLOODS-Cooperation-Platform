/**
 * Filters of the forum list, kept in the URL like `useBlogFilters`. `/forum/c/:slug` carries the
 * category in the path: a change that keeps it stays on that route; changing or clearing it moves
 * to `/forum` with the value in the query. Filter changes replace the history entry and reset the
 * page; page changes push one.
 */
import { computed } from 'vue'
import { useRoute, useRouter, type LocationQuery, type LocationQueryRaw } from 'vue-router'

import type { ThreadSort } from '@/services/threads'

export interface ForumFilters {
  q: string
  category: string
  tag: string
  locale: string
  sort: ThreadSort
}

/** Names of the routes that render the forum list. */
export const FORUM_LIST_ROUTES = ['forum', 'forum-category'] as const

const SORTS: readonly ThreadSort[] = ['activity', 'newest']
const DEFAULT_SORT: ThreadSort = 'activity'

function first(query: LocationQuery, key: string): string {
  const raw = query[key]
  const value = Array.isArray(raw) ? raw[0] : raw
  return typeof value === 'string' ? value.trim() : ''
}

export function useForumFilters() {
  const route = useRoute()
  const router = useRouter()

  const presetCategory = computed(() =>
    route.name === 'forum-category' ? String(route.params.slug ?? '') : '',
  )

  const filters = computed<ForumFilters>(() => {
    const sort = first(route.query, 'sort') as ThreadSort
    return {
      q: first(route.query, 'q'),
      category: presetCategory.value || first(route.query, 'category'),
      tag: first(route.query, 'tag'),
      locale: first(route.query, 'locale'),
      sort: SORTS.includes(sort) ? sort : DEFAULT_SORT,
    }
  })

  const page = computed(() => {
    const n = Number(first(route.query, 'page'))
    return Number.isInteger(n) && n > 0 ? n : 1
  })

  const hasFilters = computed(() => {
    const { q, category, tag, locale, sort } = filters.value
    return Boolean(q || category || tag || locale || sort !== DEFAULT_SORT)
  })

  function location(next: ForumFilters, nextPage: number) {
    const query: LocationQueryRaw = {}
    const keepPreset = !!presetCategory.value && next.category === presetCategory.value
    if (next.q) query.q = next.q
    if (next.category && !keepPreset) query.category = next.category
    if (next.tag) query.tag = next.tag
    if (next.locale) query.locale = next.locale
    if (next.sort !== DEFAULT_SORT) query.sort = next.sort
    if (nextPage > 1) query.page = String(nextPage)
    return keepPreset
      ? { name: 'forum-category', params: { slug: next.category }, query }
      : { name: 'forum', query }
  }

  /** Change some filters (back to page 1). */
  function setFilters(changes: Partial<ForumFilters>) {
    return router.replace(location({ ...filters.value, ...changes }, 1))
  }

  function setPage(next: number) {
    return router.push(location(filters.value, next))
  }

  function clearFilters() {
    return router.replace({ name: 'forum' })
  }

  return { filters, page, hasFilters, setFilters, setPage, clearFilters }
}

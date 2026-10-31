/**
 * Filters of the blog list, kept in the URL like `useQueryFilters`, plus the two preset routes:
 * `/blog/category/:slug` and `/blog/tag/:slug` carry the category or tag in the path. A change
 * that keeps the preset stays on that route; changing or clearing it moves to `/blog` with the
 * value in the query (`/blog?category=news`). Filter changes replace the history entry and reset
 * the page; page changes push one.
 */
import { computed } from 'vue'
import { useRoute, useRouter, type LocationQuery, type LocationQueryRaw } from 'vue-router'

export type BlogSort = 'newest' | 'oldest' | 'events'

export interface BlogFilters {
  q: string
  category: string
  tag: string
  locale: string
  sort: BlogSort
}

/** Names of the routes that render the blog list. */
export const BLOG_LIST_ROUTES = ['blog', 'blog-category', 'blog-tag'] as const

const SORTS: readonly BlogSort[] = ['newest', 'oldest', 'events']

function first(query: LocationQuery, key: string): string {
  const raw = query[key]
  const value = Array.isArray(raw) ? raw[0] : raw
  return typeof value === 'string' ? value.trim() : ''
}

export function useBlogFilters() {
  const route = useRoute()
  const router = useRouter()

  const presetCategory = computed(() =>
    route.name === 'blog-category' ? String(route.params.slug ?? '') : '',
  )
  const presetTag = computed(() =>
    route.name === 'blog-tag' ? String(route.params.slug ?? '') : '',
  )

  const filters = computed<BlogFilters>(() => {
    const sort = first(route.query, 'sort') as BlogSort
    return {
      q: first(route.query, 'q'),
      category: presetCategory.value || first(route.query, 'category'),
      tag: presetTag.value || first(route.query, 'tag'),
      locale: first(route.query, 'locale'),
      sort: SORTS.includes(sort) ? sort : 'newest',
    }
  })

  const page = computed(() => {
    const n = Number(first(route.query, 'page'))
    return Number.isInteger(n) && n > 0 ? n : 1
  })

  const hasFilters = computed(() => {
    const { q, category, tag, locale, sort } = filters.value
    return Boolean(q || category || tag || locale || sort !== 'newest')
  })

  function location(next: BlogFilters, nextPage: number) {
    const query: LocationQueryRaw = {}
    let name: string = 'blog'
    let params: Record<string, string> = {}
    if (presetCategory.value && next.category === presetCategory.value) {
      name = 'blog-category'
      params = { slug: next.category }
    } else if (presetTag.value && next.tag === presetTag.value) {
      name = 'blog-tag'
      params = { slug: next.tag }
    }
    if (next.q) query.q = next.q
    if (next.category && name !== 'blog-category') query.category = next.category
    if (next.tag && name !== 'blog-tag') query.tag = next.tag
    if (next.locale) query.locale = next.locale
    if (next.sort !== 'newest') query.sort = next.sort
    if (nextPage > 1) query.page = String(nextPage)
    return { name, params, query }
  }

  /** Change some filters (back to page 1). */
  function setFilters(changes: Partial<BlogFilters>) {
    return router.replace(location({ ...filters.value, ...changes }, 1))
  }

  function setPage(next: number) {
    return router.push(location(filters.value, next))
  }

  function clearFilters() {
    return router.replace({ name: 'blog' })
  }

  return { filters, page, hasFilters, setFilters, setPage, clearFilters }
}

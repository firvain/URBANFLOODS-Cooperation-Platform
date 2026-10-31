/**
 * Site search state: the query, type, language filter and page of the search page, and the hits
 * for them. A newer search aborts the request still in flight, and a response that arrives after a
 * newer search started is ignored (request counter), so fast typing never shows stale hits.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { SEARCH_MIN_LENGTH, SEARCH_PAGE_SIZE } from '@/constants/search'
import { ApiError } from '@/services/api'
import { searchService, type SearchHit, type SearchType } from '@/services/search'

export interface SearchInput {
  query?: string
  type?: SearchType
  locale?: string
  page?: number
}

export const useSearchStore = defineStore('search', () => {
  const query = ref('')
  const type = ref<SearchType>('all')
  const locale = ref('')
  const page = ref(1)

  const results = ref<SearchHit[]>([])
  const total = ref(0)
  const loading = ref(false)
  /** Error code of the last failed search (`ApiError.code`), `null` when it succeeded. */
  const error = ref<string | null>(null)

  let latest = 0
  let controller: AbortController | null = null

  const trimmed = computed(() => query.value.trim())
  /** A query was typed but is too short to send. */
  const tooShort = computed(() => trimmed.value !== '' && trimmed.value.length < SEARCH_MIN_LENGTH)

  function clear() {
    results.value = []
    total.value = 0
  }

  /** Update the given fields, then search for the current state (too-short queries are not sent). */
  async function search(input: SearchInput = {}): Promise<void> {
    if (input.query !== undefined) query.value = input.query
    if (input.type !== undefined) type.value = input.type
    if (input.locale !== undefined) locale.value = input.locale
    if (input.page !== undefined) page.value = input.page

    const request = ++latest
    controller?.abort()
    controller = null
    error.value = null

    if (trimmed.value.length < SEARCH_MIN_LENGTH) {
      loading.value = false
      clear()
      return
    }

    controller = new AbortController()
    loading.value = true
    try {
      const response = await searchService.search(
        {
          q: trimmed.value,
          type: type.value,
          locale: locale.value || undefined,
          skip: (page.value - 1) * SEARCH_PAGE_SIZE,
          limit: SEARCH_PAGE_SIZE,
        },
        controller.signal,
      )
      if (request !== latest) return
      results.value = response.items
      total.value = response.total
    } catch (err) {
      if (request !== latest) return
      error.value = (err instanceof ApiError && err.code) || 'unknown'
      clear()
    } finally {
      if (request === latest) {
        loading.value = false
        controller = null
      }
    }
  }

  return { query, type, locale, page, results, total, loading, error, tooShort, search }
})

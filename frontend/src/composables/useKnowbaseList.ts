/**
 * Shared plumbing of the KNOWBASE list views: a debounced search box synced with `?q=`, and a
 * paged list request that reloads when its parameters change (only while `routeName` is open)
 * and ignores responses that arrive out of order.
 */
import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { useRoute } from 'vue-router'

import { KB_MIN_SEARCH_LENGTH, KB_SEARCH_DEBOUNCE_MS } from '@/constants/knowbase'
import type { Page } from '@/services/members'

/** `v-model` for the search input: writes `q` after a pause, follows URL changes otherwise. */
export function useDebouncedSearch(
  current: () => string,
  commit: (q: string) => unknown,
  delay: number = KB_SEARCH_DEBOUNCE_MS,
) {
  const search = ref(current())
  let timer: ReturnType<typeof setTimeout> | undefined

  watch(search, (value) => {
    clearTimeout(timer)
    timer = setTimeout(() => {
      timer = undefined
      const q = value.trim()
      if (q !== current()) void commit(q)
    }, delay)
  })

  // The URL changed some other way (back button, "Clear filters"), unless the user is typing.
  watch(current, (q) => {
    if (timer === undefined && q !== search.value.trim()) search.value = q
  })

  onBeforeUnmount(() => clearTimeout(timer))
  return search
}

/** The search text the proxy accepts (at least 2 characters), else `undefined`. */
export function searchParam(q: string): string | undefined {
  return q.length >= KB_MIN_SEARCH_LENGTH ? q : undefined
}

export function useKnowbaseList<T, P>(
  routeName: string,
  params: Ref<P>,
  fetchPage: (params: P) => Promise<Page<T>>,
) {
  const route = useRoute()
  const items = ref<T[]>([]) as Ref<T[]>
  const total = ref(0)
  const loading = ref(true)
  const failed = ref(false)
  let latest = 0

  async function load() {
    const request = ++latest
    loading.value = true
    failed.value = false
    try {
      const page = await fetchPage(params.value)
      if (request !== latest) return
      items.value = page.items
      total.value = page.total
    } catch {
      if (request !== latest) return
      failed.value = true
      items.value = []
      total.value = 0
    } finally {
      if (request === latest) loading.value = false
    }
  }

  watch(
    () => JSON.stringify(params.value),
    () => {
      // Leaving the page also changes the query; only this route's query matters.
      if (route.name === routeName) void load()
    },
    { immediate: true },
  )

  const initialLoading = computed(() => loading.value && !items.value.length && !failed.value)

  return { items, total, loading, failed, initialLoading, load }
}

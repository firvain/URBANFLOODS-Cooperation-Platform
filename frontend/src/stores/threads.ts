/**
 * Forum list state: the current page of threads for the filters in the URL. Responses that
 * arrive out of order (fast filter changes) are ignored.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { threadsService, type ThreadListParams, type ThreadSummary } from '@/services/threads'

/** Pinned threads first, otherwise the server order (a stable sort). */
const pinnedFirst = (items: ThreadSummary[]) =>
  [...items].sort((a, b) => Number(b.is_pinned) - Number(a.is_pinned))

export const useThreadsStore = defineStore('threads', () => {
  const items = ref<ThreadSummary[]>([])
  const total = ref(0)
  const loading = ref(false)
  const failed = ref(false)
  let latest = 0
  let lastParams: ThreadListParams = {}

  async function fetchList(params: ThreadListParams): Promise<void> {
    const request = ++latest
    lastParams = params
    loading.value = true
    failed.value = false
    try {
      const page = await threadsService.list(params)
      if (request !== latest) return
      items.value = pinnedFirst(page.items)
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

  /** Load the last requested page again (the "Retry" button). */
  const reload = () => fetchList(lastParams)

  /** Skeletons only for the very first load, not while paging through results. */
  const initialLoading = computed(() => loading.value && !items.value.length && !failed.value)

  return { items, total, loading, failed, initialLoading, fetchList, reload }
})

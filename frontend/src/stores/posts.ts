/**
 * Blog list state: the current page of posts for the filters in the URL. Responses that arrive
 * out of order (fast filter changes) are ignored.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { postsService, type PostListParams, type PostSummary } from '@/services/posts'

export const usePostsStore = defineStore('posts', () => {
  const items = ref<PostSummary[]>([])
  const total = ref(0)
  const loading = ref(false)
  const failed = ref(false)
  let latest = 0
  let lastParams: PostListParams = {}

  async function fetchList(params: PostListParams): Promise<void> {
    const request = ++latest
    lastParams = params
    loading.value = true
    failed.value = false
    try {
      const page = await postsService.list(params)
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

  /** Load the last requested page again (the "Retry" button). */
  const reload = () => fetchList(lastParams)

  /** Skeletons only for the very first load, not while paging through results. */
  const initialLoading = computed(() => loading.value && !items.value.length && !failed.value)

  return { items, total, loading, failed, initialLoading, fetchList, reload }
})

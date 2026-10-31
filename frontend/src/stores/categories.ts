/** Blog categories, fetched once per session (they change only through the admin). */
import { ref } from 'vue'
import { defineStore } from 'pinia'

import { categoriesService, type CategoryOut } from '@/services/categories'

export const useCategoriesStore = defineStore('categories', () => {
  /** Live (not archived) blog categories in their admin-defined order. */
  const blog = ref<CategoryOut[]>([])
  let pending: Promise<CategoryOut[]> | null = null

  /** The blog categories; one request shared by every caller, retried after a failure. */
  function loadBlog(): Promise<CategoryOut[]> {
    pending ??= categoriesService
      .list({ kind: 'blog' })
      .then(({ items }) => {
        blog.value = items
          .filter((category) => !category.is_archived)
          .sort((a, b) => a.sort_order - b.sort_order)
        return blog.value
      })
      .catch((error: unknown) => {
        pending = null
        throw error
      })
    return pending
  }

  return { blog, loadBlog }
})

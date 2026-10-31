/** Blog and forum categories, fetched once per session (they change only through the admin). */
import { ref, type Ref } from 'vue'
import { defineStore } from 'pinia'

import { categoriesService, type CategoryKind, type CategoryOut } from '@/services/categories'

export const useCategoriesStore = defineStore('categories', () => {
  /** Live (not archived) blog categories in their admin-defined order. */
  const blog = ref<CategoryOut[]>([])
  /** Live (not archived) forum categories in their admin-defined order. */
  const forum = ref<CategoryOut[]>([])
  const pending: Partial<Record<CategoryKind, Promise<CategoryOut[]>>> = {}

  /** The categories of `kind`; one request shared by every caller, retried after a failure. */
  function load(kind: CategoryKind, target: Ref<CategoryOut[]>): Promise<CategoryOut[]> {
    pending[kind] ??= categoriesService
      .list({ kind })
      .then(({ items }) => {
        target.value = items
          .filter((category) => !category.is_archived)
          .sort((a, b) => a.sort_order - b.sort_order)
        return target.value
      })
      .catch((error: unknown) => {
        delete pending[kind]
        throw error
      })
    return pending[kind]
  }

  const loadBlog = () => load('blog', blog)
  const loadForum = () => load('forum', forum)

  return { blog, forum, loadBlog, loadForum }
})

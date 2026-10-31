/** The most used tags, fetched once per session for the blog filters. */
import { ref } from 'vue'
import { defineStore } from 'pinia'

import { POPULAR_TAGS_LIMIT } from '@/constants/blog'
import { tagsService, type TagOut } from '@/services/tags'

export const useTagsStore = defineStore('tags', () => {
  const popular = ref<TagOut[]>([])
  let pending: Promise<TagOut[]> | null = null

  function loadPopular(): Promise<TagOut[]> {
    pending ??= tagsService
      .list({ sort: 'popular', limit: POPULAR_TAGS_LIMIT })
      .then(({ items }) => (popular.value = items.filter((tag) => tag.usage_count > 0)))
      .catch((error: unknown) => {
        pending = null
        throw error
      })
    return pending
  }

  return { popular, loadPopular }
})

/** Expertise areas (network filter, profile form): fetched once per page load and shared. */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { listExpertise, type ExpertiseTag } from '@/services/expertise'

export const useExpertiseStore = defineStore('expertise', () => {
  const tags = ref<ExpertiseTag[]>([])
  const loaded = ref(false)
  let pending: Promise<ExpertiseTag[]> | null = null

  const sorted = computed(() =>
    [...tags.value].sort((a, b) => a.sort_order - b.sort_order || a.label.localeCompare(b.label)),
  )

  function fetch({ force = false }: { force?: boolean } = {}): Promise<ExpertiseTag[]> {
    if (loaded.value && !force) return Promise.resolve(tags.value)
    pending ??= listExpertise()
      .then(({ items }) => {
        tags.value = items
        loaded.value = true
        return items
      })
      .finally(() => {
        pending = null
      })
    return pending
  }

  return { tags: sorted, loaded, fetch }
})

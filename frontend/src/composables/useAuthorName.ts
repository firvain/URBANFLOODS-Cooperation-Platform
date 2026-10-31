/**
 * The display name behind an `author_id` list filter, for the "by <name>" chip of the blog and
 * forum lists. Taken from the loaded items when one of them is by that author; otherwise (an
 * empty result) asked from the members directory once per id, once `canFetch` holds (the list
 * has loaded and the viewer may read the directory). `null` while unknown.
 */
import { computed, ref, watch } from 'vue'

import { membersService } from '@/services/members'

interface Authored {
  author: { id: number; display_name: string } | null
}

export function useAuthorName(
  authorId: () => number | undefined,
  items: () => readonly Authored[],
  canFetch: () => boolean,
) {
  /** The last id asked from the members directory and its name (`null`: not listed). */
  const fetched = ref<{ id: number; name: string | null } | null>(null)

  const fromItems = computed(() => {
    const id = authorId()
    if (!id) return null
    return items().find((item) => item.author?.id === id)?.author?.display_name ?? null
  })

  watch(
    () => [authorId(), fromItems.value, canFetch()] as const,
    async ([id, name, ready]) => {
      if (!id || name || !ready || fetched.value?.id === id) return
      fetched.value = { id, name: null }
      try {
        const member = await membersService.get(id)
        if (fetched.value?.id === id) fetched.value = { id, name: member.display_name }
      } catch {
        // An unlisted member: the chip falls back to a generic label.
      }
    },
    { immediate: true },
  )

  return computed(() => {
    const id = authorId()
    if (!id) return null
    return fromItems.value ?? (fetched.value?.id === id ? fetched.value.name : null)
  })
}

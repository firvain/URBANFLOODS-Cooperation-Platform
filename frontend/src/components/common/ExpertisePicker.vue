<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'

import { EXPERTISE_MAX } from '@/constants/auth'
import type { ExpertiseTag } from '@/services/expertise'
import { useExpertiseStore } from '@/stores/expertise'

/**
 * Expertise areas multi-select (registration, profile). Loads the vocabulary from the shared
 * store; at the limit only the chosen areas stay selectable (to remove them).
 */
const props = withDefaults(
  defineProps<{
    label: string
    help?: string
    error?: string
    placeholder?: string
    /** Tags to show even before (or without) the vocabulary, e.g. the user's current ones. */
    known?: ExpertiseTag[]
    max?: number
  }>(),
  {
    help: undefined,
    error: undefined,
    placeholder: undefined,
    known: () => [],
    max: EXPERTISE_MAX,
  },
)

const ids = defineModel<number[]>({ required: true })

const expertiseStore = useExpertiseStore()
const { tags } = storeToRefs(expertiseStore)

const items = computed(() => {
  const all = new Map(tags.value.map((tag) => [tag.id, tag]))
  for (const tag of props.known) if (!all.has(tag.id)) all.set(tag.id, tag)
  const full = ids.value.length >= props.max
  return [...all.values()].map((tag) => ({
    label: tag.label,
    value: tag.id,
    disabled: full && !ids.value.includes(tag.id),
  }))
})

onMounted(() => {
  // Without the vocabulary the select still shows (and can remove) the known areas.
  expertiseStore.fetch().catch(() => {})
})
</script>

<template>
  <UFormField :label="label" name="expertise_ids" :help="help" :error="error">
    <USelectMenu
      v-model="ids"
      multiple
      :items="items"
      value-key="value"
      :placeholder="placeholder"
      class="w-full"
    />
  </UFormField>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'

import { EXPERTISE_MAX, EXPERTISE_OTHER_MAX_LENGTH } from '@/constants/auth'
import type { ExpertiseTag } from '@/services/expertise'
import { useExpertiseStore } from '@/stores/expertise'

/**
 * Expertise areas multi-select (registration, profile) plus an optional free-text "other" area
 * for a field not in the list (`v-model:other`, the raw text: the parent trims it and sends
 * `null` when blank). Loads the vocabulary from the shared store; at the limit only the chosen
 * areas stay selectable (to remove them). Renders two `UFormField`s named `expertise_ids` and
 * `expertise_other`; server errors come in through `error` and `otherError`.
 */
const props = withDefaults(
  defineProps<{
    label: string
    help?: string
    error?: string
    otherError?: string
    placeholder?: string
    /** Tags to show even before (or without) the vocabulary, e.g. the user's current ones. */
    known?: ExpertiseTag[]
    max?: number
  }>(),
  {
    help: undefined,
    error: undefined,
    otherError: undefined,
    placeholder: undefined,
    known: () => [],
    max: EXPERTISE_MAX,
  },
)

const ids = defineModel<number[]>({ required: true })
const other = defineModel<string>('other', { default: '' })

const { t } = useI18n()

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
  <div class="space-y-5">
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

    <UFormField
      :label="t('auth.expertiseOtherLabel')"
      name="expertise_other"
      :help="t('auth.expertiseOtherHint')"
      :error="otherError"
    >
      <template #hint>
        <span class="text-xs tabular-nums">
          {{
            t('auth.expertiseOtherCount', {
              count: other.length,
              max: EXPERTISE_OTHER_MAX_LENGTH,
            })
          }}
        </span>
      </template>
      <UInput
        v-model="other"
        name="expertise_other"
        autocomplete="off"
        :maxlength="EXPERTISE_OTHER_MAX_LENGTH"
        class="w-full"
      />
    </UFormField>
  </div>
</template>

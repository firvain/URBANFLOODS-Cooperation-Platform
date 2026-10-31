<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Measure } from '@/services/knowbase'

/** One flood management measure in the KNOWBASE list (as the KNOWBASE's own card, lighter). */
const props = defineProps<{ measure: Measure }>()

const { t } = useI18n()

/** At most this many keyword badges on a card. */
const MAX_KEYWORDS = 3

const title = computed(() => props.measure.title_en || t('knowbase.measures.untitled'))
const keywords = computed(() => props.measure.all_keywords.slice(0, MAX_KEYWORDS))
</script>

<template>
  <li
    data-testid="measure-card"
    class="flex h-full flex-col overflow-hidden rounded border border-default bg-white shadow-xs"
  >
    <img
      v-if="measure.photo_url"
      :src="measure.photo_url"
      :alt="title"
      loading="lazy"
      class="h-44 w-full object-cover"
    />
    <div class="flex flex-1 flex-col gap-3 p-4">
      <UBadge
        v-if="measure.category"
        data-testid="measure-category"
        color="secondary"
        variant="subtle"
        size="sm"
        class="self-start"
      >
        {{ measure.category.label_en }}
      </UBadge>
      <h2 class="text-base leading-snug font-semibold">
        <ULink
          :to="`/knowbase/measures/${measure.id}`"
          raw
          class="text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
        >
          {{ title }}
        </ULink>
      </h2>
      <p v-if="measure.description_en" class="line-clamp-3 text-sm text-gray-700">
        {{ measure.description_en }}
      </p>
      <ul
        v-if="keywords.length"
        class="mt-auto flex flex-wrap gap-1.5"
        :aria-label="t('knowbase.fields.keywords')"
      >
        <li v-for="keyword in keywords" :key="keyword">
          <UBadge data-testid="measure-keyword" color="neutral" variant="outline" size="sm">
            {{ keyword }}
          </UBadge>
        </li>
      </ul>
    </div>
  </li>
</template>

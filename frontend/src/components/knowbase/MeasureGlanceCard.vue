<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Measure } from '@/services/knowbase'
import { measureTitle } from '@/utils/knowbase'

/**
 * One measure on "Flood Management Measures": photo, linked title and the phase and scale badges.
 * The view passes the badge labels already translated by code.
 */
const props = defineProps<{ measure: Measure; phases: string[]; scales: string[] }>()

const { t } = useI18n()

const title = computed(
  () => measureTitle(props.measure.title_en ?? '') || t('knowbase.measures.untitled'),
)
</script>

<template>
  <li
    data-testid="measure-card"
    class="flex h-full flex-col overflow-hidden rounded border border-default bg-white shadow-xs"
  >
    <!-- Decorative: the title right below names the measure. -->
    <img
      v-if="measure.photo_url"
      :src="measure.photo_url"
      alt=""
      loading="lazy"
      class="aspect-[4/3] w-full object-cover"
    />
    <div
      v-else
      data-testid="measure-photo-placeholder"
      aria-hidden="true"
      class="flex aspect-[4/3] w-full items-center justify-center bg-gray-100 text-muted"
    >
      <UIcon name="i-lucide-image" class="size-10" />
    </div>
    <div class="flex flex-1 flex-col gap-3 p-4">
      <h3 class="text-base leading-snug font-semibold">
        <RouterLink
          :to="`/knowbase/measures/${measure.id}`"
          class="text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
        >
          {{ title }}
        </RouterLink>
      </h3>
      <div v-if="phases.length || scales.length" class="mt-auto flex flex-wrap gap-1.5">
        <UBadge
          v-for="phase in phases"
          :key="`phase-${phase}`"
          color="primary"
          variant="subtle"
          size="sm"
        >
          <span class="sr-only">{{ `${t('knowbase.glance.phase')}: ` }}</span>
          {{ phase }}
        </UBadge>
        <UBadge
          v-for="scale in scales"
          :key="`scale-${scale}`"
          color="neutral"
          variant="subtle"
          size="sm"
        >
          <span class="sr-only">{{ `${t('knowbase.glance.scale')}: ` }}</span>
          {{ scale }}
        </UBadge>
      </div>
    </div>
  </li>
</template>

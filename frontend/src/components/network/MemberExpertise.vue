<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ExpertiseTag } from '@/services/expertise'

/**
 * Expertise badges, capped at `max` with a "+N" badge (the rest named for screen readers). The
 * member's free-text "other" area, if any, is one more badge after the areas.
 */
const props = withDefaults(
  defineProps<{ expertise: ExpertiseTag[]; other?: string | null; max?: number }>(),
  { other: null, max: 4 },
)

const { t } = useI18n()

const labels = computed(() => {
  const all = props.expertise.map((tag) => tag.label)
  if (props.other) all.push(props.other)
  return all
})
const shown = computed(() => labels.value.slice(0, props.max))
const rest = computed(() => labels.value.slice(props.max))
</script>

<template>
  <ul v-if="labels.length" :aria-label="t('network.card.expertise')" class="flex flex-wrap gap-1">
    <!-- Index keys: the free text may repeat an area's label. -->
    <li v-for="(label, index) in shown" :key="index">
      <UBadge data-testid="expertise-badge" color="secondary" variant="subtle" size="sm">
        {{ label }}
      </UBadge>
    </li>
    <li v-if="rest.length">
      <UBadge
        data-testid="expertise-more"
        color="neutral"
        variant="outline"
        size="sm"
        :title="rest.join(', ')"
      >
        <span aria-hidden="true">{{
          t('network.card.moreExpertise', { count: rest.length })
        }}</span>
        <span class="sr-only">
          {{
            t('network.card.moreExpertiseLabel', {
              count: rest.length,
              labels: rest.join(', '),
            })
          }}
        </span>
      </UBadge>
    </li>
  </ul>
</template>

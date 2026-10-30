<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ExpertiseTag } from '@/services/expertise'

/** Expertise badges, capped at `max` with a "+N" badge (the rest named for screen readers). */
const props = withDefaults(defineProps<{ expertise: ExpertiseTag[]; max?: number }>(), { max: 4 })

const { t } = useI18n()

const shown = computed(() => props.expertise.slice(0, props.max))
const rest = computed(() => props.expertise.slice(props.max))
</script>

<template>
  <ul
    v-if="expertise.length"
    :aria-label="t('network.card.expertise')"
    class="flex flex-wrap gap-1"
  >
    <li v-for="tag in shown" :key="tag.id">
      <UBadge data-testid="expertise-badge" color="secondary" variant="subtle" size="sm">
        {{ tag.label }}
      </UBadge>
    </li>
    <li v-if="rest.length">
      <UBadge
        data-testid="expertise-more"
        color="neutral"
        variant="outline"
        size="sm"
        :title="rest.map((tag) => tag.label).join(', ')"
      >
        <span aria-hidden="true">{{
          t('network.card.moreExpertise', { count: rest.length })
        }}</span>
        <span class="sr-only">
          {{
            t('network.card.moreExpertiseLabel', {
              count: rest.length,
              labels: rest.map((tag) => tag.label).join(', '),
            })
          }}
        </span>
      </UBadge>
    </li>
  </ul>
</template>

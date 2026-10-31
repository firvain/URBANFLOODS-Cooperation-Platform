<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ContentStatus } from '@/services/moderation'

/** The moderation status of a post, thread, reply or comment (published included). */
const props = defineProps<{ status: ContentStatus }>()

const { t } = useI18n()

const STYLE = {
  pending: { color: 'warning', icon: 'i-lucide-hourglass' },
  published: { color: 'success', icon: 'i-lucide-circle-check' },
  hidden: { color: 'error', icon: 'i-lucide-eye-off' },
  deleted: { color: 'neutral', icon: 'i-lucide-trash-2' },
} as const

const style = computed(() => STYLE[props.status])
</script>

<template>
  <UBadge :color="style.color" :icon="style.icon" variant="subtle" size="sm">
    {{ t(`admin.contentStatus.${status}`) }}
  </UBadge>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ContentStatus, HiddenReason } from '@/services/reports'

/**
 * Status of content that is not published (pending approval, hidden, deleted), with an
 * explanation in its `title`; for hidden content the reason is added. Only the author and admins
 * ever receive such content, so only they see the badge. Nothing for published content.
 */
const props = defineProps<{ status: ContentStatus; hiddenReason?: HiddenReason | null }>()

const { t } = useI18n()

const STYLE = {
  pending: { color: 'warning', icon: 'i-lucide-hourglass' },
  hidden: { color: 'error', icon: 'i-lucide-eye-off' },
  deleted: { color: 'neutral', icon: 'i-lucide-trash-2' },
} as const

const style = computed(() => (props.status === 'published' ? null : STYLE[props.status]))
const title = computed(() => {
  if (props.status === 'published') return undefined
  const base = t(`status.title.${props.status}`)
  return props.status === 'hidden' && props.hiddenReason
    ? `${base} ${t(`status.reason.${props.hiddenReason}`)}`
    : base
})
</script>

<template>
  <UBadge
    v-if="style"
    data-testid="post-status"
    :color="style.color"
    variant="subtle"
    size="sm"
    :icon="style.icon"
    :title="title"
    class="self-start"
  >
    {{ t(`post.status.${status}`) }}
  </UBadge>
</template>

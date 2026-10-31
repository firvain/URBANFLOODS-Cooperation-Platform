<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { PostStatus } from '@/services/posts'

/**
 * Status of a post that is not published (pending approval, hidden, deleted). Only the author
 * and admins ever receive such posts, so the badge is shown to them alone. Nothing for published.
 */
const props = defineProps<{ status: PostStatus }>()

const { t } = useI18n()

const color = computed(() =>
  props.status === 'pending' ? 'warning' : props.status === 'hidden' ? 'error' : 'neutral',
)
const icon = computed(() =>
  props.status === 'pending'
    ? 'i-lucide-hourglass'
    : props.status === 'hidden'
      ? 'i-lucide-eye-off'
      : 'i-lucide-trash-2',
)
</script>

<template>
  <UBadge
    v-if="status !== 'published'"
    data-testid="post-status"
    :color="color"
    variant="subtle"
    size="sm"
    :icon="icon"
    class="self-start"
  >
    {{ t(`post.status.${status}`) }}
  </UBadge>
</template>

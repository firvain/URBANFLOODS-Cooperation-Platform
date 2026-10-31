<script setup lang="ts">
import { useI18n } from 'vue-i18n'

/** "Pinned" (pin icon and label) and "Locked" (lock icon and label) marks of a thread. */
withDefaults(defineProps<{ pinned: boolean; locked: boolean; size?: 'sm' | 'md' }>(), {
  size: 'sm',
})

const { t } = useI18n()
</script>

<template>
  <UBadge v-if="pinned" data-testid="thread-pinned" color="secondary" variant="subtle" :size="size">
    <template #leading>
      <UIcon name="i-lucide-pin" data-icon="i-lucide-pin" class="size-3.5" aria-hidden="true" />
    </template>
    {{ t('thread.pinned') }}
  </UBadge>
  <UBadge v-if="locked" data-testid="thread-locked" color="neutral" variant="subtle" :size="size">
    <template #leading>
      <UIcon name="i-lucide-lock" data-icon="i-lucide-lock" class="size-3.5" aria-hidden="true" />
    </template>
    {{ t('thread.locked') }}
  </UBadge>
</template>

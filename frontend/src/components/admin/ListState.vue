<script setup lang="ts">
import { useI18n } from 'vue-i18n'

/**
 * Loading skeleton or load error (with "Try again") of an admin list; renders the default slot
 * once the list has loaded.
 */
defineProps<{ initial: boolean; loading: boolean; failed: boolean; errorTitle?: string }>()
const emit = defineEmits<{ retry: [] }>()

const { t } = useI18n()
</script>

<template>
  <div v-if="initial && loading" aria-busy="true" class="space-y-3">
    <span class="sr-only">{{ t('admin.common.loading') }}</span>
    <USkeleton v-for="n in 4" :key="n" class="h-12 w-full" />
  </div>
  <div v-else-if="failed" role="alert">
    <UAlert
      color="error"
      variant="subtle"
      icon="i-lucide-circle-alert"
      :title="errorTitle ?? t('admin.common.loadError')"
      :actions="[
        {
          label: t('admin.common.retry'),
          color: 'error',
          variant: 'outline',
          icon: 'i-lucide-rotate-cw',
          onClick: () => emit('retry'),
        },
      ]"
    />
  </div>
  <slot v-else />
</template>

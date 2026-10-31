<script setup lang="ts">
import { useI18n } from 'vue-i18n'

/**
 * A modal asking to confirm an action (never the browser's `confirm()`). The parent closes it,
 * so it can keep it open to show an `error` from a failed request.
 */
withDefaults(
  defineProps<{
    title: string
    description?: string
    confirmLabel: string
    cancelLabel?: string
    color?: 'primary' | 'error' | 'warning'
    loading?: boolean
    error?: string
  }>(),
  { description: undefined, cancelLabel: undefined, color: 'primary', loading: false, error: '' },
)
const open = defineModel<boolean>('open', { required: true })
const emit = defineEmits<{ confirm: []; cancel: [] }>()

const { t } = useI18n()

function cancel() {
  open.value = false
  emit('cancel')
}
</script>

<template>
  <UModal v-model:open="open" :title="title" :description="description" :dismissible="!loading">
    <template v-if="error" #body>
      <div role="alert">
        <UAlert color="error" variant="subtle" icon="i-lucide-circle-alert" :title="error" />
      </div>
    </template>
    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <UButton color="neutral" variant="outline" :disabled="loading" @click="cancel">
          {{ cancelLabel ?? t('common.cancel') }}
        </UButton>
        <UButton :color="color" :loading="loading" @click="emit('confirm')">
          {{ confirmLabel }}
        </UButton>
      </div>
    </template>
  </UModal>
</template>

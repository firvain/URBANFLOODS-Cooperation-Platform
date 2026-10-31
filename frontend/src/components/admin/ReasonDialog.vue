<script setup lang="ts">
import { ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

/**
 * Confirm a moderation action that takes an optional reason (reject, hide). The reason goes into
 * the audit row only. The parent closes the dialog, so it can stay open to show an `error`.
 */
withDefaults(
  defineProps<{
    title: string
    description?: string
    confirmLabel: string
    color?: 'primary' | 'error' | 'warning'
    loading?: boolean
    error?: string
  }>(),
  { description: undefined, color: 'error', loading: false, error: '' },
)
const open = defineModel<boolean>('open', { required: true })
const emit = defineEmits<{ confirm: [reason: string] }>()

const { t } = useI18n()
const reason = ref('')
const formId = useId()

// A fresh, empty reason every time the dialog opens.
watch(open, (isOpen) => {
  if (isOpen) reason.value = ''
})
</script>

<template>
  <UModal v-model:open="open" :title="title" :description="description" :dismissible="!loading">
    <template #body>
      <form :id="formId" novalidate class="space-y-4" @submit.prevent="emit('confirm', reason)">
        <div role="alert">
          <UAlert
            v-if="error"
            color="error"
            variant="subtle"
            icon="i-lucide-circle-alert"
            :title="error"
          />
        </div>
        <UFormField
          :label="t('admin.queue.reason')"
          :help="t('admin.queue.reasonHelp')"
          name="reason"
        >
          <UTextarea v-model="reason" :rows="3" :maxlength="500" class="w-full" />
        </UFormField>
      </form>
    </template>
    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <UButton color="neutral" variant="outline" :disabled="loading" @click="open = false">
          {{ t('common.cancel') }}
        </UButton>
        <UButton type="submit" :form="formId" :color="color" :loading="loading">
          {{ confirmLabel }}
        </UButton>
      </div>
    </template>
  </UModal>
</template>

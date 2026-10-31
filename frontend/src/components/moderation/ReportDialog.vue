<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from '@nuxt/ui/composables'

import { REPORT_DETAILS_MAX_LENGTH, REPORT_REASONS } from '@/constants/moderation'
import { ApiError } from '@/services/api'
import {
  reportsService,
  type ContentType,
  type ReportCreate,
  type ReportReason,
} from '@/services/reports'

/**
 * Asks why an item is reported (one of the five reasons, optional details) and sends the report.
 * Outcomes end in a toast; `reported` fires when the item now counts as reported by this member
 * (sent, or reported earlier). Unexpected failures stay in the dialog so the member can retry.
 */
const props = defineProps<{ contentType: ContentType; contentId: number }>()
const open = defineModel<boolean>('open', { required: true })
const emit = defineEmits<{ reported: [] }>()

const { t } = useI18n()
const toast = useToast()
const formId = useId()

const reason = ref<ReportReason | undefined>(undefined)
const details = ref('')
const reasonError = ref('')
const error = ref('')
const sending = ref(false)

const reasons = computed(() =>
  REPORT_REASONS.map((value) => ({ value, label: t(`report.reasons.${value}`) })),
)

watch(open, (isOpen) => {
  if (!isOpen) return
  reason.value = undefined
  details.value = ''
  reasonError.value = ''
  error.value = ''
})

/** Error codes that end the attempt with a toast (nothing to retry). */
const CLOSING_ERRORS: Record<string, string> = {
  'report.own_content': 'report.errors.ownContent',
  'report.content_not_found': 'report.errors.contentNotFound',
}

function close(message: string, color: 'success' | 'info' | 'warning' | 'error', icon: string) {
  open.value = false
  toast.add({ title: message, color, icon })
}

async function send() {
  if (sending.value) return
  if (!reason.value) {
    reasonError.value = t('report.reasonRequired')
    return
  }
  error.value = ''
  sending.value = true
  const body: ReportCreate = {
    content_type: props.contentType,
    content_id: props.contentId,
    reason: reason.value,
  }
  const trimmed = details.value.trim()
  if (trimmed) body.details = trimmed
  try {
    const result = await reportsService.create(body)
    emit('reported')
    if (result.auto_hidden) close(t('report.autoHidden'), 'success', 'i-lucide-eye-off')
    else close(t('report.sent'), 'success', 'i-lucide-check')
  } catch (err) {
    if (err instanceof ApiError && err.code === 'report.already_reported') {
      emit('reported')
      close(t('report.alreadyReported'), 'info', 'i-lucide-info')
    } else if (err instanceof ApiError && err.status === 429) {
      close(t('report.errors.rateLimited'), 'warning', 'i-lucide-timer')
    } else if (err instanceof ApiError && err.code && CLOSING_ERRORS[err.code]) {
      close(t(CLOSING_ERRORS[err.code]!), 'error', 'i-lucide-circle-alert')
    } else {
      error.value = t('errors.generic')
    }
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <UModal
    v-model:open="open"
    :title="t(`report.title.${contentType}`)"
    :description="t('report.description')"
  >
    <template #body>
      <form :id="formId" novalidate class="space-y-5" @submit.prevent="send">
        <UFormField name="reason" :error="reasonError || undefined" required>
          <URadioGroup
            v-model="reason"
            name="reason"
            :legend="t('report.reason')"
            :items="reasons"
            required
            @update:model-value="reasonError = ''"
          />
        </UFormField>

        <UFormField
          name="details"
          :label="t('report.details')"
          :help="t('report.detailsHint')"
          :hint="`${details.length}/${REPORT_DETAILS_MAX_LENGTH}`"
        >
          <UTextarea
            v-model="details"
            :maxlength="REPORT_DETAILS_MAX_LENGTH"
            :rows="3"
            autoresize
            class="w-full"
          />
        </UFormField>

        <p v-if="error" role="alert" class="text-sm text-error">{{ error }}</p>
      </form>
    </template>
    <template #footer>
      <div class="flex w-full flex-wrap justify-end gap-2">
        <UButton color="neutral" variant="outline" @click="open = false">
          {{ t('report.cancel') }}
        </UButton>
        <UButton
          type="submit"
          :form="formId"
          color="error"
          icon="i-lucide-flag"
          :loading="sending"
          @click.prevent="send"
        >
          {{ t('report.submit') }}
        </UButton>
      </div>
    </template>
  </UModal>
</template>

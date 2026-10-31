<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useCanReport, useReportedContent } from '@/composables/useReportedContent'
import type { ContentStatus, ContentType } from '@/services/reports'
import ReportDialog from './ReportDialog.vue'

/**
 * "Report" for a post, thread, reply or comment: shown to verified members on published content
 * that is not their own; opens the report dialog. Once reported (here, or earlier in this
 * session) it turns into a disabled "Reported".
 */
const props = withDefaults(
  defineProps<{
    contentType: ContentType
    contentId: number
    /** `null` for content by a former member. */
    authorId: number | null
    status?: ContentStatus
    size?: 'xs' | 'sm' | 'md'
  }>(),
  { status: 'published', size: 'xs' },
)

const { t } = useI18n()
const { isReported, markReported } = useReportedContent()

const visible = useCanReport(() => ({
  authorId: props.authorId,
  status: props.status,
  contentId: props.contentId,
}))
const open = ref(false)
/** Kept here too, for when `sessionStorage` is unavailable. */
const reportedHere = ref(false)
const reported = computed(
  () => reportedHere.value || isReported(props.contentType, props.contentId),
)

function onReported() {
  reportedHere.value = true
  markReported(props.contentType, props.contentId)
}
</script>

<template>
  <template v-if="visible">
    <UButton
      data-testid="report-button"
      :size="size"
      color="neutral"
      variant="ghost"
      :icon="reported ? 'i-lucide-flag-off' : 'i-lucide-flag'"
      :disabled="reported"
      :aria-label="reported ? undefined : t(`report.title.${contentType}`)"
      @click="open = true"
    >
      {{ reported ? t('report.reported') : t('report.button') }}
    </UButton>
    <ReportDialog
      v-model:open="open"
      :content-type="contentType"
      :content-id="contentId"
      @reported="onReported"
    />
  </template>
</template>

<script setup lang="ts">
import { onMounted, ref, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import RichTextEditor from '@/components/editor/RichTextEditor.vue'
import { REPLY_BODY_MAX_LENGTH } from '@/constants/forum'
import { useApiErrors } from '@/composables/useApiErrors'
import { ApiError } from '@/services/api'
import type { ReplyOut } from '@/services/replies'
import { useRepliesStore } from '@/stores/replies'

/**
 * Write a reply (to the thread, or to a top-level reply with `parentReplyId`) or edit one
 * (`reply`). A compact editor with the comment subset; the new reply appears in the list at once
 * (the store inserts it optimistically) and the form empties for the next one.
 */
const props = withDefaults(
  defineProps<{
    threadId: number
    parentReplyId?: number | null
    /** The reply being edited. */
    reply?: ReplyOut | null
    /** Visible label (defaults to "Your reply" / "Edit your reply"). */
    label?: string
    cancellable?: boolean
    /** Move focus into the editor when the form appears (it was opened by a button). */
    focusOnOpen?: boolean
  }>(),
  {
    parentReplyId: null,
    reply: null,
    label: undefined,
    cancellable: false,
    focusOnOpen: false,
  },
)
const emit = defineEmits<{ done: [reply: ReplyOut]; cancel: [] }>()

const { t } = useI18n()
const { errorMessage } = useApiErrors()
const replies = useRepliesStore()

const labelId = useId()
const errorId = useId()
const editorRef = useTemplateRef<InstanceType<typeof RichTextEditor>>('editor')

const body = ref(props.reply?.body_html ?? '')
const error = ref('')
const pending = ref(false)

onMounted(() => {
  if (props.focusOnOpen) editorRef.value?.focus()
})

/** Field codes of the replies API that deserve their own sentence. */
const FIELD_ERRORS: Record<string, string> = {
  'body_html:empty': 'reply.errors.empty',
  'body_html:too_long': 'reply.errors.tooLong',
  'parent_reply_id:invalid': 'reply.errors.parentInvalid',
}

function messageFor(failure: unknown): string {
  if (failure instanceof ApiError && failure.fields) {
    for (const [field, code] of Object.entries(failure.fields)) {
      const key = FIELD_ERRORS[`${field}:${code}`]
      if (key) return t(key)
    }
  }
  return errorMessage(failure)
}

async function submit() {
  if (pending.value) return
  error.value = ''
  if (!body.value) {
    error.value = t('reply.errors.empty')
    return
  }
  if (editorRef.value?.isOverLimit) {
    error.value = t('reply.errors.tooLong')
    return
  }
  pending.value = true
  try {
    const saved = props.reply
      ? await replies.update(props.threadId, props.reply.id, body.value)
      : await replies.create(props.threadId, body.value, props.parentReplyId)
    if (!props.reply) body.value = ''
    emit('done', saved)
  } catch (failure) {
    error.value = messageFor(failure)
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div data-testid="reply-form">
    <form novalidate class="space-y-2" @submit.prevent="submit">
      <span :id="labelId" class="block text-sm font-medium text-default">
        {{ label ?? (reply ? t('reply.labelEdit') : t('reply.label')) }}
      </span>
      <RichTextEditor
        ref="editor"
        v-model="body"
        compact
        :label-id="labelId"
        :placeholder="t('reply.placeholder')"
        :max-length="REPLY_BODY_MAX_LENGTH"
        :disabled="pending"
      />
      <p v-if="error" :id="errorId" role="alert" class="text-sm text-error">{{ error }}</p>
      <div class="flex flex-wrap justify-end gap-2">
        <UButton
          v-if="cancellable"
          color="neutral"
          variant="outline"
          :disabled="pending"
          @click="emit('cancel')"
        >
          {{ t('reply.cancel') }}
        </UButton>
        <UButton
          type="submit"
          :icon="reply ? 'i-lucide-check' : 'i-lucide-send'"
          :loading="pending"
        >
          {{ reply ? t('reply.save') : t('reply.submit') }}
        </UButton>
      </div>
    </form>
  </div>
</template>

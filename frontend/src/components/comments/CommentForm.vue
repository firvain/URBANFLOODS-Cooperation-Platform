<script setup lang="ts">
import { onMounted, ref, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import RichTextEditor from '@/components/editor/RichTextEditor.vue'
import { COMMENT_BODY_MAX_LENGTH } from '@/constants/blog'
import { useApiErrors } from '@/composables/useApiErrors'
import { ApiError } from '@/services/api'
import type { CommentOut } from '@/services/comments'
import { useCommentsStore } from '@/stores/comments'

/**
 * Write a comment on a post, or edit one (`comment`). A compact editor with the comment subset;
 * the new comment appears in the list at once (the store inserts it optimistically) and the form
 * empties for the next one.
 */
const props = withDefaults(
  defineProps<{
    postId: number
    /** The comment being edited. */
    comment?: CommentOut | null
    cancellable?: boolean
    /** Move focus into the editor when the form appears (it was opened by a button). */
    focusOnOpen?: boolean
  }>(),
  { comment: null, cancellable: false, focusOnOpen: false },
)
const emit = defineEmits<{ done: [comment: CommentOut]; cancel: [] }>()

const { t } = useI18n()
const { errorMessage } = useApiErrors()
const comments = useCommentsStore()

const labelId = useId()
const errorId = useId()
const editorRef = useTemplateRef<InstanceType<typeof RichTextEditor>>('editor')

const body = ref(props.comment?.body_html ?? '')
const error = ref('')
const pending = ref(false)

onMounted(() => {
  if (props.focusOnOpen) editorRef.value?.focus()
})

/** Field codes of the comments API that deserve their own sentence. */
const FIELD_ERRORS: Record<string, string> = {
  'body_html:empty': 'comments.errors.empty',
  'body_html:too_long': 'comments.errors.tooLong',
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
    error.value = t('comments.errors.empty')
    return
  }
  if (editorRef.value?.isOverLimit) {
    error.value = t('comments.errors.tooLong')
    return
  }
  pending.value = true
  // A new comment is listed at once; the form empties now and gets the text back on failure.
  const text = body.value
  if (!props.comment) body.value = ''
  try {
    const saved = props.comment
      ? await comments.update(props.postId, props.comment.id, text)
      : await comments.create(props.postId, text)
    emit('done', saved)
  } catch (failure) {
    if (!props.comment) body.value = text
    error.value = messageFor(failure)
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div data-testid="comment-form">
    <form novalidate class="space-y-2" @submit.prevent="submit">
      <span :id="labelId" class="block text-sm font-medium text-default">
        {{ comment ? t('comments.labelEdit') : t('comments.label') }}
      </span>
      <RichTextEditor
        ref="editor"
        v-model="body"
        compact
        :label-id="labelId"
        :placeholder="t('comments.placeholder')"
        :max-length="COMMENT_BODY_MAX_LENGTH"
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
          {{ t('comments.cancel') }}
        </UButton>
        <UButton
          type="submit"
          :icon="comment ? 'i-lucide-check' : 'i-lucide-send'"
          :loading="pending"
        >
          {{ comment ? t('comments.save') : t('comments.submit') }}
        </UButton>
      </div>
    </form>
  </div>
</template>

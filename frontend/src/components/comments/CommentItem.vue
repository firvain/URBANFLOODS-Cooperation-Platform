<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import RelativeTime from '@/components/common/RelativeTime.vue'
import SafeHtml from '@/components/common/SafeHtml.vue'
import ReportButton from '@/components/moderation/ReportButton.vue'
import { useCanReport } from '@/composables/useReportedContent'
import { COMMENT_EDIT_WINDOW_MS } from '@/constants/blog'
import type { CommentOut } from '@/services/comments'
import { useAuthStore } from '@/stores/auth'
import { useCommentsStore } from '@/stores/comments'
import CommentForm from './CommentForm.vue'

/**
 * One comment: author, relative time, "edited", the sanitised body and its actions. Authors may
 * edit for 24 hours and delete any time; admins always. Editing happens inline.
 */
const props = defineProps<{ comment: CommentOut; postId: number }>()
const emit = defineEmits<{ delete: [comment: CommentOut] }>()

const { t } = useI18n()
const auth = useAuthStore()
const comments = useCommentsStore()

const editing = ref(false)

/** An optimistic comment (negative id) exists only here until the server answers. */
const saved = computed(() => props.comment.id > 0)
const sending = computed(() => comments.sending.has(props.comment.id))
const authorName = computed(() => props.comment.author?.display_name ?? t('comments.formerMember'))
const isAuthor = computed(
  () =>
    auth.user !== null && props.comment.author !== null && auth.user.id === props.comment.author.id,
)

const canEdit = computed(() => {
  if (!saved.value) return false
  if (auth.isAdmin) return true
  const age = Date.now() - new Date(props.comment.created_at).getTime()
  return isAuthor.value && age < COMMENT_EDIT_WINDOW_MS
})
const canDelete = computed(() => saved.value && (auth.isAdmin || isAuthor.value))
const canReport = useCanReport(() => ({
  authorId: props.comment.author?.id ?? null,
  status: props.comment.status,
  contentId: props.comment.id,
}))
</script>

<template>
  <li data-testid="comment" :id="`comment-${comment.id}`">
    <article class="rounded border border-default bg-white p-3" :aria-busy="sending">
      <header class="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        <UAvatar
          :src="comment.author?.avatar_url ?? undefined"
          :alt="authorName"
          size="xs"
          aria-hidden="true"
        />
        <span data-testid="comment-author">
          <ULink
            v-if="comment.author?.has_profile"
            :to="`/u/${comment.author.id}`"
            raw
            class="font-medium text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
          >
            {{ comment.author.display_name }}
          </ULink>
          <span v-else class="font-medium">{{ authorName }}</span>
          <span v-if="comment.author?.organisation" class="text-gray-700">
            · {{ comment.author.organisation.name }}
          </span>
        </span>
        <span aria-hidden="true" class="text-muted">·</span>
        <RelativeTime :datetime="comment.created_at" class="text-gray-700" />
        <span v-if="comment.is_edited" data-testid="comment-edited" class="text-muted italic">
          {{ t('comments.edited') }}
        </span>
        <span v-if="sending" data-testid="comment-sending" class="text-muted" role="status">
          {{ t('comments.sending') }}
        </span>
      </header>

      <CommentForm
        v-if="editing"
        :post-id="postId"
        :comment="comment"
        cancellable
        focus-on-open
        @done="editing = false"
        @cancel="editing = false"
      />
      <SafeHtml v-else data-testid="comment-body" :html="comment.body_html" class="content-prose" />

      <div
        v-if="(canEdit || canDelete || canReport) && !editing"
        data-testid="comment-actions"
        class="mt-2 flex flex-wrap gap-1"
      >
        <UButton
          v-if="canEdit"
          size="xs"
          color="neutral"
          variant="ghost"
          icon="i-lucide-pencil"
          @click="editing = true"
        >
          {{ t('comments.edit') }}
        </UButton>
        <UButton
          v-if="canDelete"
          size="xs"
          color="error"
          variant="ghost"
          icon="i-lucide-trash-2"
          @click="emit('delete', comment)"
        >
          {{ t('comments.delete') }}
        </UButton>
        <ReportButton
          content-type="comment"
          :content-id="comment.id"
          :author-id="comment.author?.id ?? null"
          :status="comment.status"
        />
      </div>
    </article>
  </li>
</template>

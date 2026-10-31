<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useToast } from '@nuxt/ui/composables'

import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import type { CommentOut } from '@/services/comments'
import type { PostStatus } from '@/services/posts'
import { useAuthStore } from '@/stores/auth'
import { useCommentsStore } from '@/stores/comments'
import CommentForm from './CommentForm.vue'
import CommentItem from './CommentItem.vue'

/**
 * The comments under a blog post: "N comments", the list oldest first with "Load more
 * comments", and the form. Visitors are invited to log in, unverified members to verify; a post
 * that is not published takes no comments (a pending one has none to list). Deleting asks in a
 * modal.
 */
const props = defineProps<{
  postId: number
  /** The post's `comment_count`, shown until the list has loaded. */
  count: number
  status: PostStatus
}>()

const { t } = useI18n()
const route = useRoute()
const toast = useToast()
const auth = useAuthStore()
const { errorMessage } = useApiErrors()
const comments = useCommentsStore()

const headingId = useId()
const pending = computed(() => props.status === 'pending')
const open = computed(() => props.status === 'published')

watch(
  () => [props.postId, pending.value] as const,
  ([id, isPending]) => {
    if (!isPending) void comments.load(id)
  },
  { immediate: true },
)

const state = computed(() => comments.posts[props.postId] ?? comments.of(props.postId))
const items = computed(() => comments.list(props.postId))
const hasMore = computed(() => comments.hasMore(props.postId))
const total = computed(() => (state.value.loaded ? comments.count(props.postId) : props.count))
const loginTo = computed(() => ({ name: 'login', query: { next: route.fullPath } }))

// --- Delete -----------------------------------------------------------------------------------

const target = ref<CommentOut | null>(null)
const deleteOpen = ref(false)
const deleting = ref(false)
const deleteError = ref('')

function askDelete(comment: CommentOut) {
  target.value = comment
  deleteError.value = ''
  deleteOpen.value = true
}

async function confirmDelete() {
  if (!target.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    await comments.remove(props.postId, target.value.id)
    deleteOpen.value = false
    target.value = null
    toast.add({ title: t('comments.removed'), color: 'success', icon: 'i-lucide-check' })
  } catch (error) {
    deleteError.value = errorMessage(error)
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <section data-testid="post-comments" :aria-labelledby="headingId" class="space-y-6">
    <h2 :id="headingId" class="text-2xl font-semibold text-primary-600">
      {{ t('comments.title', total) }}
    </h2>

    <template v-if="!pending">
      <div v-if="state.loading && !state.loaded" aria-busy="true" class="space-y-3">
        <span class="sr-only">{{ t('comments.loading') }}</span>
        <USkeleton v-for="n in 3" :key="n" class="h-20 w-full" />
      </div>

      <div v-else-if="state.failed && !items.length" role="alert">
        <UAlert
          color="error"
          variant="subtle"
          icon="i-lucide-circle-alert"
          :title="t('comments.loadError')"
          :actions="[
            {
              label: t('comments.retry'),
              color: 'error',
              variant: 'outline',
              icon: 'i-lucide-rotate-cw',
              onClick: () => comments.load(postId),
            },
          ]"
        />
      </div>

      <p v-else-if="!items.length" class="text-sm text-gray-700">{{ t('comments.empty') }}</p>

      <ol v-else data-testid="comment-list" class="space-y-4">
        <CommentItem
          v-for="comment in items"
          :key="comment.id"
          :comment="comment"
          :post-id="postId"
          @delete="askDelete"
        />
      </ol>

      <div v-if="hasMore && state.loaded" class="flex justify-center">
        <UButton
          color="neutral"
          variant="outline"
          icon="i-lucide-chevrons-down"
          :loading="state.loading"
          @click="comments.loadMore(postId)"
        >
          {{ t('comments.loadMore') }}
        </UButton>
      </div>
    </template>

    <p
      v-if="!open"
      data-testid="comments-closed"
      class="rounded border border-default p-4 text-sm text-gray-700"
    >
      {{ pending ? t('comments.notPublished') : t('comments.closed') }}
    </p>
    <p
      v-else-if="!auth.isAuthenticated"
      data-testid="login-to-comment"
      class="rounded border border-default p-4 text-center"
    >
      <ULink
        :to="loginTo"
        raw
        class="inline-flex items-center gap-1 font-medium text-primary-700 underline underline-offset-2 hover:text-primary-800"
      >
        <UIcon name="i-lucide-log-in" class="size-4" aria-hidden="true" />
        {{ t('comments.loginToComment') }}
      </ULink>
    </p>
    <UAlert
      v-else-if="!auth.isVerified"
      data-testid="comment-unverified"
      color="warning"
      variant="subtle"
      icon="i-lucide-mail-warning"
      :title="t('comments.unverified')"
    />
    <CommentForm v-else :post-id="postId" />

    <ConfirmDialog
      v-model:open="deleteOpen"
      :title="t('comments.deleteConfirm.title')"
      :description="t('comments.deleteConfirm.description')"
      :confirm-label="t('comments.deleteConfirm.confirm')"
      :cancel-label="t('comments.deleteConfirm.cancel')"
      color="error"
      :loading="deleting"
      :error="deleteError"
      @confirm="confirmDelete"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import RelativeTime from '@/components/common/RelativeTime.vue'
import SafeHtml from '@/components/common/SafeHtml.vue'
import { REPLY_EDIT_WINDOW_MS } from '@/constants/forum'
import type { ReplyOut } from '@/services/replies'
import { useAuthStore } from '@/stores/auth'
import { useRepliesStore } from '@/stores/replies'
import ReplyForm from './ReplyForm.vue'

/**
 * One reply: author, relative time, "edited", the sanitised body and its actions. A top-level
 * reply also lists its children (one level only, never deeper) and opens an inline form to answer
 * it. Authors may edit for 24 hours (not on a locked thread) and delete any time; admins always.
 * A deleted reply that still has children shows as a muted "[deleted]" placeholder.
 */
const props = withDefaults(
  defineProps<{ reply: ReplyOut; threadId: number; locked?: boolean; nested?: boolean }>(),
  { locked: false, nested: false },
)
const emit = defineEmits<{ delete: [reply: ReplyOut] }>()

const { t } = useI18n()
const auth = useAuthStore()
const replies = useRepliesStore()

const editing = ref(false)
const replying = ref(false)

const deleted = computed(() => props.reply.status === 'deleted')
/** An optimistic reply (negative id) exists only here until the server answers. */
const saved = computed(() => props.reply.id > 0)
const sending = computed(() => replies.sending.has(props.reply.id))
const authorName = computed(() => props.reply.author?.display_name ?? t('reply.formerMember'))
const isAuthor = computed(
  () => auth.user !== null && props.reply.author !== null && auth.user.id === props.reply.author.id,
)

const canReply = computed(
  () => !props.nested && !deleted.value && saved.value && auth.isVerified && !props.locked,
)
const canEdit = computed(() => {
  if (deleted.value || !saved.value) return false
  if (auth.isAdmin) return true
  const age = Date.now() - new Date(props.reply.created_at).getTime()
  return isAuthor.value && !props.locked && age < REPLY_EDIT_WINDOW_MS
})
const canDelete = computed(() => !deleted.value && saved.value && (auth.isAdmin || isAuthor.value))
const hasActions = computed(() => canReply.value || canEdit.value || canDelete.value)
</script>

<template>
  <li data-testid="reply" :id="`reply-${reply.id}`" class="space-y-3">
    <article
      class="rounded border p-3"
      :class="deleted ? 'border-dashed border-default bg-elevated/40' : 'border-default bg-white'"
      :aria-busy="sending"
    >
      <p v-if="deleted" data-testid="reply-deleted" class="text-sm text-muted italic">
        {{ t('reply.deleted') }}
      </p>

      <template v-else>
        <header class="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <UAvatar
            :src="reply.author?.avatar_url ?? undefined"
            :alt="authorName"
            size="xs"
            aria-hidden="true"
          />
          <span data-testid="reply-author">
            <ULink
              v-if="reply.author"
              :to="`/u/${reply.author.id}`"
              raw
              class="font-medium text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
            >
              {{ reply.author.display_name }}
            </ULink>
            <span v-else class="font-medium">{{ authorName }}</span>
            <span v-if="reply.author?.organisation" class="text-gray-700">
              · {{ reply.author.organisation.name }}
            </span>
          </span>
          <span aria-hidden="true" class="text-muted">·</span>
          <RelativeTime :datetime="reply.created_at" class="text-gray-700" />
          <span v-if="reply.is_edited" data-testid="reply-edited" class="text-muted italic">
            {{ t('reply.edited') }}
          </span>
          <span v-if="sending" class="text-muted" role="status">{{ t('reply.sending') }}</span>
        </header>

        <ReplyForm
          v-if="editing"
          :thread-id="threadId"
          :reply="reply"
          cancellable
          focus-on-open
          @done="editing = false"
          @cancel="editing = false"
        />
        <SafeHtml v-else data-testid="reply-body" :html="reply.body_html" class="content-prose" />

        <div
          v-if="hasActions && !editing"
          data-testid="reply-actions"
          class="mt-2 flex flex-wrap gap-1"
        >
          <UButton
            v-if="canReply"
            size="xs"
            color="neutral"
            variant="ghost"
            icon="i-lucide-reply"
            :aria-label="t('reply.replyTo', { name: authorName })"
            :aria-expanded="replying ? 'true' : 'false'"
            @click="replying = !replying"
          >
            {{ t('reply.reply') }}
          </UButton>
          <UButton
            v-if="canEdit"
            size="xs"
            color="neutral"
            variant="ghost"
            icon="i-lucide-pencil"
            @click="editing = true"
          >
            {{ t('reply.edit') }}
          </UButton>
          <UButton
            v-if="canDelete"
            size="xs"
            color="error"
            variant="ghost"
            icon="i-lucide-trash-2"
            @click="emit('delete', reply)"
          >
            {{ t('reply.delete') }}
          </UButton>
        </div>
      </template>
    </article>

    <ol
      v-if="!nested && reply.children.length"
      data-testid="reply-children"
      class="ms-4 space-y-3 border-s-2 border-secondary-200 ps-4 sm:ms-8"
    >
      <ReplyItem
        v-for="child in reply.children"
        :key="child.id"
        :reply="child"
        :thread-id="threadId"
        :locked="locked"
        nested
        @delete="(target: ReplyOut) => emit('delete', target)"
      />
    </ol>

    <div v-if="replying && canReply" class="ms-4 border-s-2 border-secondary-200 ps-4 sm:ms-8">
      <ReplyForm
        :thread-id="threadId"
        :parent-reply-id="reply.id"
        :label="t('reply.replyTo', { name: authorName })"
        cancellable
        focus-on-open
        @done="replying = false"
        @cancel="replying = false"
      />
    </div>
  </li>
</template>

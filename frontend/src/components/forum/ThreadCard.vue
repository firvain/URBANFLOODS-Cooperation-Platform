<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import RelativeTime from '@/components/common/RelativeTime.vue'
import StatusBadge from '@/components/moderation/StatusBadge.vue'
import type { ThreadSummary } from '@/services/threads'
import ThreadFlags from './ThreadFlags.vue'

/**
 * One thread in the forum list: pinned/locked marks, category, title, excerpt, author, reply
 * count and the last activity. The status badge appears only on threads that are not published
 * (which only their author and admins receive).
 */
const props = defineProps<{ thread: ThreadSummary }>()

const { t } = useI18n()

const organisation = computed(() => props.thread.author?.organisation?.name ?? null)
</script>

<template>
  <li
    data-testid="thread-card"
    class="flex flex-col gap-3 rounded border bg-white p-4 shadow-xs sm:flex-row sm:items-start sm:justify-between"
    :class="thread.is_pinned ? 'border-secondary-300' : 'border-default'"
  >
    <div class="min-w-0 flex-1 space-y-2">
      <div class="flex flex-wrap items-center gap-2">
        <ThreadFlags :pinned="thread.is_pinned" :locked="thread.is_locked" />
        <ULink
          data-testid="thread-category"
          :to="`/forum/c/${thread.category.slug}`"
          raw
          class="rounded-md bg-secondary-100 px-2 py-0.5 text-xs font-medium text-secondary-900 underline-offset-2 hover:underline focus-visible:underline"
        >
          {{ thread.category.name }}
        </ULink>
        <StatusBadge :status="thread.status" />
      </div>

      <h2 class="text-base leading-snug font-semibold" :lang="thread.locale">
        <ULink
          :to="`/forum/t/${thread.slug}`"
          raw
          class="text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
        >
          {{ thread.title }}
        </ULink>
      </h2>
      <p v-if="thread.excerpt" class="line-clamp-2 text-sm text-gray-700" :lang="thread.locale">
        {{ thread.excerpt }}
      </p>

      <p data-testid="thread-author" class="text-xs text-gray-700">
        <span class="font-medium text-default">
          {{ thread.author?.display_name ?? t('post.formerMember') }}
        </span>
        <template v-if="organisation">
          <span aria-hidden="true"> · </span>
          <span>{{ organisation }}</span>
        </template>
      </p>
    </div>

    <div
      class="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-700 sm:flex-col sm:items-end"
    >
      <p data-testid="thread-replies" class="inline-flex items-center gap-1 font-medium">
        <UIcon name="i-lucide-message-circle" class="size-3.5" aria-hidden="true" />
        {{ t('thread.replies', thread.reply_count) }}
      </p>
      <p data-testid="thread-activity">
        {{ t('thread.lastActivity') }}
        <RelativeTime :datetime="thread.last_activity_at" />
      </p>
    </div>
  </li>
</template>

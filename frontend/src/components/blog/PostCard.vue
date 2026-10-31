<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import StatusBadge from '@/components/moderation/StatusBadge.vue'
import type { PostSummary } from '@/services/posts'
import { formatDate, formatDateTime } from '@/utils/datetime'

/** One post in the blog list (the KNOWBASE card style): cover, category, title, meta, tags. */
const props = defineProps<{ post: PostSummary }>()

const { t, locale } = useI18n()

const coverSrc = computed(() => props.post.cover?.thumb_url || props.post.cover?.url || null)
/** Publication date; a post that is not published yet shows when it was written. */
const date = computed(() => props.post.published_at ?? props.post.created_at)
const organisation = computed(() => props.post.author?.organisation?.name ?? null)
</script>

<template>
  <li
    data-testid="post-card"
    class="flex h-full flex-col overflow-hidden rounded border border-default bg-white shadow-xs"
  >
    <img
      v-if="post.cover && coverSrc"
      :src="coverSrc"
      :alt="post.cover.alt_text"
      :width="post.cover.width"
      :height="post.cover.height"
      loading="lazy"
      class="h-44 w-full object-cover"
    />
    <div class="flex flex-1 flex-col gap-3 p-4">
      <div class="flex flex-wrap items-center gap-2">
        <ULink
          data-testid="post-category"
          :to="`/blog/category/${post.category.slug}`"
          raw
          class="rounded-md bg-secondary-100 px-2 py-0.5 text-xs font-medium text-secondary-900 underline-offset-2 hover:underline focus-visible:underline"
        >
          {{ post.category.name }}
        </ULink>
        <UBadge
          v-if="post.event_at"
          data-testid="post-event"
          color="primary"
          variant="subtle"
          size="sm"
          icon="i-lucide-calendar"
        >
          <span class="sr-only">{{ `${t('post.event.label')}: ` }}</span>
          {{ formatDateTime(post.event_at, locale) }}
        </UBadge>
        <StatusBadge :status="post.status" />
      </div>

      <h2 class="text-base leading-snug font-semibold" :lang="post.locale">
        <ULink
          :to="`/blog/${post.slug}`"
          raw
          class="text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
        >
          {{ post.title }}
        </ULink>
      </h2>
      <p v-if="post.excerpt" class="line-clamp-3 text-sm text-gray-700" :lang="post.locale">
        {{ post.excerpt }}
      </p>

      <ul v-if="post.tags.length" class="flex flex-wrap gap-1.5" :aria-label="t('post.tags')">
        <li v-for="tag in post.tags" :key="tag.id">
          <ULink
            data-testid="post-tag"
            :to="`/blog/tag/${tag.slug}`"
            raw
            class="inline-flex rounded-md border border-accented px-1.5 py-0.5 text-xs text-gray-700 underline-offset-2 hover:underline focus-visible:underline"
          >
            #{{ tag.name }}
          </ULink>
        </li>
      </ul>

      <div
        class="mt-auto flex flex-wrap items-end justify-between gap-x-3 gap-y-1 border-t border-default pt-3 text-xs text-gray-700"
      >
        <p data-testid="post-author" class="min-w-0">
          <span class="font-medium text-default">
            {{ post.author?.display_name ?? t('post.formerMember') }}
          </span>
          <span v-if="organisation" class="block">{{ organisation }}</span>
        </p>
        <p class="flex items-center gap-3">
          <time :datetime="date">{{ formatDate(date, locale) }}</time>
          <span data-testid="post-comments" class="inline-flex items-center gap-1">
            <UIcon name="i-lucide-message-circle" class="size-3.5" aria-hidden="true" />
            {{ t('post.comments', post.comment_count) }}
          </span>
        </p>
      </div>
    </div>
  </li>
</template>

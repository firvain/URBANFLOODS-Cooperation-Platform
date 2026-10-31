<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'

import ThreadCard from '@/components/forum/ThreadCard.vue'
import { FORUM_PAGE_SIZE, FORUM_SEARCH_DEBOUNCE_MS } from '@/constants/forum'
import { FORUM_LIST_ROUTES, useForumFilters } from '@/composables/useForumFilters'
import { useDebouncedSearch } from '@/composables/useKnowbaseList'
import { SUPPORTED_LOCALES } from '@/i18n'
import { categoryName } from '@/services/categories'
import type { ThreadListParams, ThreadSort } from '@/services/threads'
import { useAuthStore } from '@/stores/auth'
import { useCategoriesStore } from '@/stores/categories'
import { useThreadsStore } from '@/stores/threads'

/**
 * The forum: threads (pinned first) filterable by category (chips), text, language and order,
 * 20 per page. Filters live in the URL (`useForumFilters`); `/forum/c/:slug` opens the list with
 * that category set.
 */
const { t, locale } = useI18n()
const route = useRoute()
const { isVerified } = storeToRefs(useAuthStore())
const threads = useThreadsStore()
const { items, total, loading, failed, initialLoading } = storeToRefs(threads)
const categories = useCategoriesStore()

const { filters, page, hasFilters, setFilters, setPage, clearFilters } = useForumFilters()

/** Select value for "no filter" (reka-ui selects cannot hold an empty string). */
const ALL = 'all'

const search = useDebouncedSearch(
  () => filters.value.q,
  (q) => setFilters({ q }),
  FORUM_SEARCH_DEBOUNCE_MS,
)

onMounted(() => {
  // Optional data for the chips: without it only "All" is shown.
  categories.loadForum().catch(() => {})
})

// --- Filters ----------------------------------------------------------------------------------

const categoryChips = computed(() => [
  { slug: '', label: t('forum.filters.allCategories') },
  ...categories.forum.map((category) => ({
    slug: category.slug,
    label: categoryName(category, locale.value),
  })),
])

const localeItems = computed(() => [
  { label: t('forum.filters.allLocales'), value: ALL },
  ...SUPPORTED_LOCALES.map((l) => ({ label: l.nativeName, value: l.code })),
])
const localeFilter = computed<string>({
  get: () => filters.value.locale || ALL,
  set: (value) => void setFilters({ locale: value === ALL ? '' : value }),
})

const sortOptions = computed<{ value: ThreadSort; label: string; icon: string }[]>(() => [
  { value: 'activity', label: t('forum.filters.sortActivity'), icon: 'i-lucide-activity' },
  { value: 'newest', label: t('forum.filters.sortNewest'), icon: 'i-lucide-sparkles' },
])

// --- Threads ----------------------------------------------------------------------------------

const params = computed<ThreadListParams>(() => {
  const { q, category, tag, locale: threadLocale, sort } = filters.value
  return {
    q: q || undefined,
    category: category || undefined,
    tag: tag || undefined,
    locale: threadLocale || undefined,
    sort,
    skip: (page.value - 1) * FORUM_PAGE_SIZE,
    limit: FORUM_PAGE_SIZE,
  }
})

watch(
  () => JSON.stringify(params.value),
  () => {
    // Leaving the page also changes the route; only the forum list's own changes matter.
    if ((FORUM_LIST_ROUTES as readonly unknown[]).includes(route.name)) {
      void threads.fetchList(params.value)
    }
  },
  { immediate: true },
)
</script>

<template>
  <UContainer class="pt-8 pb-16 lg:pb-24">
    <div class="mb-8 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <h1 tabindex="-1" class="mb-4 text-4xl font-bold text-primary-600 focus:outline-none">
          {{ t('forum.title') }}
        </h1>
        <div class="h-1 w-20 rounded bg-secondary-500" />
        <p class="mt-4 max-w-3xl text-muted">{{ t('forum.intro') }}</p>
      </div>
      <UButton
        v-if="isVerified"
        to="/forum/new"
        icon="i-lucide-message-square-plus"
        class="shrink-0 self-start"
      >
        {{ t('forum.start') }}
      </UButton>
    </div>

    <section aria-labelledby="forum-filters-heading" class="mb-6 space-y-4">
      <h2 id="forum-filters-heading" class="sr-only">{{ t('forum.filters.title') }}</h2>

      <div role="group" :aria-label="t('forum.filters.category')" class="flex flex-wrap gap-2">
        <UButton
          v-for="chip in categoryChips"
          :key="chip.slug || 'all'"
          data-testid="category-chip"
          size="sm"
          :color="filters.category === chip.slug ? 'primary' : 'neutral'"
          :variant="filters.category === chip.slug ? 'solid' : 'outline'"
          :aria-pressed="filters.category === chip.slug ? 'true' : 'false'"
          class="rounded-full"
          @click="setFilters({ category: chip.slug })"
        >
          {{ chip.label }}
        </UButton>
      </div>

      <div class="grid gap-4 md:grid-cols-[1fr_14rem_auto] md:items-end">
        <UFormField :label="t('forum.filters.search')" name="q">
          <UInput
            v-model="search"
            type="search"
            icon="i-lucide-search"
            :placeholder="t('forum.filters.searchPlaceholder')"
            class="w-full"
          />
        </UFormField>
        <UFormField :label="t('forum.filters.locale')" name="locale">
          <USelect v-model="localeFilter" :items="localeItems" class="w-full" />
        </UFormField>
        <div class="space-y-1.5">
          <span id="forum-sort-label" class="block text-sm font-medium text-default">
            {{ t('forum.filters.sort') }}
          </span>
          <div role="group" aria-labelledby="forum-sort-label" class="flex gap-1">
            <UButton
              v-for="option in sortOptions"
              :key="option.value"
              data-testid="sort-option"
              :icon="option.icon"
              :color="filters.sort === option.value ? 'primary' : 'neutral'"
              :variant="filters.sort === option.value ? 'soft' : 'ghost'"
              :aria-pressed="filters.sort === option.value ? 'true' : 'false'"
              @click="setFilters({ sort: option.value })"
            >
              {{ option.label }}
            </UButton>
          </div>
        </div>
      </div>

      <div
        v-if="filters.tag || hasFilters"
        class="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm"
      >
        <p
          v-if="filters.tag"
          data-testid="active-tag"
          class="inline-flex items-center gap-1 rounded-full border border-primary-300 bg-primary-50 py-0.5 ps-3 pe-1 text-primary-800"
        >
          <span class="sr-only">{{ `${t('forum.filters.tag')}: ` }}</span>
          <span>#{{ filters.tag }}</span>
          <UButton
            icon="i-lucide-x"
            color="neutral"
            variant="ghost"
            size="xs"
            :aria-label="t('forum.filters.removeTag', { tag: filters.tag })"
            @click="setFilters({ tag: '' })"
          />
        </p>
        <UButton
          v-if="hasFilters"
          color="neutral"
          variant="link"
          icon="i-lucide-x"
          class="px-0"
          @click="clearFilters()"
        >
          {{ t('forum.clearFilters') }}
        </UButton>
      </div>
    </section>

    <div class="min-w-0 space-y-4">
      <div v-if="initialLoading" data-testid="forum-loading" aria-busy="true" class="space-y-3">
        <span class="sr-only">{{ t('forum.loading') }}</span>
        <USkeleton v-for="n in 5" :key="n" class="h-28 w-full" />
      </div>

      <div v-else-if="failed" role="alert">
        <UAlert
          color="error"
          variant="subtle"
          icon="i-lucide-circle-alert"
          :title="t('forum.loadError')"
          :actions="[
            {
              label: t('forum.retry'),
              color: 'error',
              variant: 'outline',
              icon: 'i-lucide-rotate-cw',
              onClick: () => threads.reload(),
            },
          ]"
        />
      </div>

      <template v-else>
        <p data-testid="forum-count" role="status" class="text-sm font-medium text-gray-700">
          {{ t('forum.count', { count: total }, total) }}
        </p>

        <div v-if="!items.length" class="rounded border border-default p-6 text-center">
          <p class="text-gray-700">{{ hasFilters ? t('forum.empty') : t('forum.emptyAll') }}</p>
          <UButton
            v-if="hasFilters"
            color="neutral"
            variant="outline"
            icon="i-lucide-x"
            class="mt-4"
            @click="clearFilters()"
          >
            {{ t('forum.clearFilters') }}
          </UButton>
        </div>

        <ul v-else :aria-busy="loading" class="space-y-3">
          <ThreadCard v-for="thread in items" :key="thread.id" :thread="thread" />
        </ul>

        <div v-if="total > FORUM_PAGE_SIZE" class="flex justify-center pt-4">
          <UPagination
            :page="page"
            :total="total"
            :items-per-page="FORUM_PAGE_SIZE"
            :aria-label="t('forum.pagination')"
            @update:page="(next: number) => setPage(next)"
          />
        </div>
      </template>
    </div>
  </UContainer>
</template>

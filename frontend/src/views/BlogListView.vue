<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'

import PostCard from '@/components/blog/PostCard.vue'
import { BLOG_PAGE_SIZE, BLOG_SEARCH_DEBOUNCE_MS } from '@/constants/blog'
import { BLOG_LIST_ROUTES, useBlogFilters, type BlogSort } from '@/composables/useBlogFilters'
import { useDebouncedSearch } from '@/composables/useKnowbaseList'
import { SUPPORTED_LOCALES } from '@/i18n'
import { categoryName } from '@/services/categories'
import type { PostListParams } from '@/services/posts'
import { useAuthStore } from '@/stores/auth'
import { useCategoriesStore } from '@/stores/categories'
import { usePostsStore } from '@/stores/posts'
import { useTagsStore } from '@/stores/tags'

/**
 * The blog: posts filterable by category (chips), tag, text, language and order, 12 per page.
 * Filters live in the URL (`useBlogFilters`); `/blog/category/:slug` and `/blog/tag/:slug` open
 * the list with that filter set.
 */
const { t, locale } = useI18n()
const route = useRoute()
const { isVerified } = storeToRefs(useAuthStore())
const posts = usePostsStore()
const { items, total, loading, failed, initialLoading } = storeToRefs(posts)
const categories = useCategoriesStore()
const tags = useTagsStore()

const { filters, page, hasFilters, setFilters, setPage, clearFilters } = useBlogFilters()

/** Select value for "no filter" (reka-ui selects cannot hold an empty string). */
const ALL = 'all'

const search = useDebouncedSearch(
  () => filters.value.q,
  (q) => setFilters({ q }),
  BLOG_SEARCH_DEBOUNCE_MS,
)

onMounted(() => {
  // Optional data for the filters: without it only "All" and the URL's tag are shown.
  categories.loadBlog().catch(() => {})
  tags.loadPopular().catch(() => {})
})

// --- Filters ----------------------------------------------------------------------------------

const categoryChips = computed(() => [
  { slug: '', label: t('blog.filters.allCategories') },
  ...categories.blog.map((category) => ({
    slug: category.slug,
    label: categoryName(category, locale.value),
  })),
])

const localeItems = computed(() => [
  { label: t('blog.filters.allLocales'), value: ALL },
  ...SUPPORTED_LOCALES.map((l) => ({ label: l.nativeName, value: l.code })),
])
const localeFilter = computed<string>({
  get: () => filters.value.locale || ALL,
  set: (value) => void setFilters({ locale: value === ALL ? '' : value }),
})

const sortItems = computed(() => [
  { label: t('blog.filters.sortNewest'), value: 'newest' },
  { label: t('blog.filters.sortOldest'), value: 'oldest' },
  { label: t('blog.filters.sortEvents'), value: 'events' },
])
const sort = computed<BlogSort>({
  get: () => filters.value.sort,
  set: (value) => void setFilters({ sort: value }),
})

// --- Posts ------------------------------------------------------------------------------------

const params = computed<PostListParams>(() => {
  const { q, category, tag, locale: postLocale, sort: order } = filters.value
  return {
    q: q || undefined,
    category: category || undefined,
    tag: tag || undefined,
    locale: postLocale || undefined,
    sort: order,
    upcoming_only: order === 'events' ? true : undefined,
    skip: (page.value - 1) * BLOG_PAGE_SIZE,
    limit: BLOG_PAGE_SIZE,
  }
})

watch(
  () => JSON.stringify(params.value),
  () => {
    // Leaving the page also changes the route; only the blog list's own changes matter.
    if ((BLOG_LIST_ROUTES as readonly unknown[]).includes(route.name)) {
      void posts.fetchList(params.value)
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
          {{ t('blog.title') }}
        </h1>
        <div class="h-1 w-20 rounded bg-secondary-500" />
        <p class="mt-4 max-w-3xl text-muted">{{ t('blog.intro') }}</p>
      </div>
      <UButton
        v-if="isVerified"
        to="/blog/new"
        icon="i-lucide-pen-line"
        class="shrink-0 self-start"
      >
        {{ t('blog.write') }}
      </UButton>
    </div>

    <section aria-labelledby="blog-filters-heading" class="mb-6 space-y-4">
      <h2 id="blog-filters-heading" class="sr-only">{{ t('blog.filters.title') }}</h2>

      <div role="group" :aria-label="t('blog.filters.category')" class="flex flex-wrap gap-2">
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

      <div class="grid gap-4 md:grid-cols-[1fr_14rem_14rem]">
        <UFormField :label="t('blog.filters.search')" name="q">
          <UInput
            v-model="search"
            type="search"
            icon="i-lucide-search"
            :placeholder="t('blog.filters.searchPlaceholder')"
            class="w-full"
          />
        </UFormField>
        <UFormField :label="t('blog.filters.locale')" name="locale">
          <USelect v-model="localeFilter" :items="localeItems" class="w-full" />
        </UFormField>
        <UFormField :label="t('blog.filters.sort')" name="sort">
          <USelect v-model="sort" :items="sortItems" class="w-full" />
        </UFormField>
      </div>

      <div class="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <p
          v-if="filters.tag"
          data-testid="active-tag"
          class="inline-flex items-center gap-1 rounded-full border border-primary-300 bg-primary-50 py-0.5 ps-3 pe-1 text-primary-800"
        >
          <span class="sr-only">{{ `${t('blog.filters.tag')}: ` }}</span>
          <span>#{{ filters.tag }}</span>
          <UButton
            icon="i-lucide-x"
            color="neutral"
            variant="ghost"
            size="xs"
            :aria-label="t('blog.filters.removeTag', { tag: filters.tag })"
            @click="setFilters({ tag: '' })"
          />
        </p>
        <div v-if="tags.popular.length" class="flex flex-wrap items-center gap-1.5">
          <span id="popular-tags-label" class="text-gray-700">{{
            t('blog.filters.popularTags')
          }}</span>
          <ul aria-labelledby="popular-tags-label" class="flex flex-wrap gap-1.5">
            <li v-for="tag in tags.popular" :key="tag.id">
              <UButton
                size="xs"
                :color="filters.tag === tag.slug ? 'primary' : 'neutral'"
                :variant="filters.tag === tag.slug ? 'soft' : 'ghost'"
                :aria-pressed="filters.tag === tag.slug ? 'true' : 'false'"
                @click="setFilters({ tag: filters.tag === tag.slug ? '' : tag.slug })"
              >
                #{{ tag.name }}
              </UButton>
            </li>
          </ul>
        </div>
        <UButton
          v-if="hasFilters"
          color="neutral"
          variant="link"
          icon="i-lucide-x"
          class="px-0"
          @click="clearFilters()"
        >
          {{ t('blog.clearFilters') }}
        </UButton>
      </div>
    </section>

    <div class="min-w-0 space-y-4">
      <div v-if="initialLoading" data-testid="blog-loading" aria-busy="true">
        <span class="sr-only">{{ t('blog.loading') }}</span>
        <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <USkeleton v-for="n in 6" :key="n" class="h-72 w-full" />
        </div>
      </div>

      <div v-else-if="failed" role="alert">
        <UAlert
          color="error"
          variant="subtle"
          icon="i-lucide-circle-alert"
          :title="t('blog.loadError')"
          :actions="[
            {
              label: t('blog.retry'),
              color: 'error',
              variant: 'outline',
              icon: 'i-lucide-rotate-cw',
              onClick: () => posts.reload(),
            },
          ]"
        />
      </div>

      <template v-else>
        <p data-testid="blog-count" role="status" class="text-sm font-medium text-gray-700">
          {{ t('blog.count', { count: total }, total) }}
        </p>

        <div v-if="!items.length" class="rounded border border-default p-6 text-center">
          <p class="text-gray-700">{{ hasFilters ? t('blog.empty') : t('blog.emptyAll') }}</p>
          <UButton
            v-if="hasFilters"
            color="neutral"
            variant="outline"
            icon="i-lucide-x"
            class="mt-4"
            @click="clearFilters()"
          >
            {{ t('blog.clearFilters') }}
          </UButton>
        </div>

        <ul
          v-else
          :aria-busy="loading"
          class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3"
        >
          <PostCard v-for="post in items" :key="post.id" :post="post" />
        </ul>

        <div v-if="total > BLOG_PAGE_SIZE" class="flex justify-center pt-4">
          <UPagination
            :page="page"
            :total="total"
            :items-per-page="BLOG_PAGE_SIZE"
            :aria-label="t('blog.pagination')"
            @update:page="(next: number) => setPage(next)"
          />
        </div>
      </template>
    </div>
  </UContainer>
</template>

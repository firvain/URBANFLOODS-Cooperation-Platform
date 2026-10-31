<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'

import SafeHtml from '@/components/common/SafeHtml.vue'
import { SEARCH_MAX_LENGTH, SEARCH_MIN_LENGTH, SEARCH_PAGE_SIZE } from '@/constants/search'
import { usePageHead } from '@/composables/usePageHead'
import { useQueryFilters } from '@/composables/useQueryFilters'
import { SUPPORTED_LOCALES } from '@/i18n'
import { SEARCH_TYPES, type SearchHit, type SearchType } from '@/services/search'
import { useSearchStore } from '@/stores/search'
import { formatDate } from '@/utils/datetime'

/**
 * Site search: one ranked list of blog posts and forum threads. The query, type, language and
 * page live in the URL (`?q=&type=&locale=&page=`), so a search can be linked to and survives
 * Back. Queries shorter than 2 characters are not sent; the page says why instead.
 */
const { t, locale: uiLocale } = useI18n()
const route = useRoute()
const store = useSearchStore()
const { results, total, loading, error } = storeToRefs(store)

const { filters, page, setFilters, setPage } = useQueryFilters({
  q: 'string',
  type: 'string',
  locale: 'string',
})

/** Select value for "no filter" (reka-ui selects cannot hold an empty string). */
const ALL = 'all'
/** Snippets are escaped text whose only markup is the highlight. */
const SNIPPET_TAGS = ['mark'] as const

const query = computed(() => filters.value.q)
const searchType = computed<SearchType>(() => {
  const value = filters.value.type as SearchType
  return SEARCH_TYPES.includes(value) ? value : 'all'
})
const tooShort = computed(() => query.value !== '' && query.value.length < SEARCH_MIN_LENGTH)
const searchable = computed(() => query.value.length >= SEARCH_MIN_LENGTH)

// --- Form -------------------------------------------------------------------------------------

const draft = ref(query.value)
watch(query, (q) => (draft.value = q))

function submit() {
  const q = draft.value.trim()
  // The same search again (e.g. after an error) has no URL change to react to.
  if (q === query.value && page.value === 1) void store.search()
  else void setFilters({ q })
}

const typeItems = computed(() =>
  SEARCH_TYPES.map((value) => ({ label: t(`search.types.${value}`), value })),
)
const typeModel = computed<SearchType>({
  get: () => searchType.value,
  set: (value) => void setFilters({ type: value === 'all' ? '' : value }),
})

const localeItems = computed(() => [
  { label: t('search.allLocales'), value: ALL },
  ...SUPPORTED_LOCALES.map((l) => ({ label: l.nativeName, value: l.code })),
])
const localeModel = computed<string>({
  get: () => filters.value.locale || ALL,
  set: (value) => void setFilters({ locale: value === ALL ? '' : value }),
})

// --- Results ----------------------------------------------------------------------------------

const params = computed(() => ({
  query: query.value,
  type: searchType.value,
  locale: filters.value.locale,
  page: page.value,
}))

watch(
  () => JSON.stringify(params.value),
  () => {
    // Leaving the page also changes the route; only the search page's own changes matter.
    if (route.name === 'search') void store.search(params.value)
  },
  { immediate: true },
)

const initialLoading = computed(() => loading.value && !results.value.length)

/** Text of the polite live region: the result count once a search has answered. */
const countText = computed(() => {
  if (!searchable.value || error.value) return ''
  if (loading.value) return t('search.loading')
  return t('search.count', { count: total.value, query: query.value }, total.value)
})

function hitLink(hit: SearchHit): string {
  const slug = encodeURIComponent(hit.slug)
  return hit.type === 'post' ? `/blog/${slug}` : `/forum/t/${slug}`
}

usePageHead(() => ({
  title: searchable.value ? t('search.titleWithQuery', { query: query.value }) : t('search.title'),
  description: t('head.searchDescription'),
  canonical: '/search',
  type: 'website',
}))
</script>

<template>
  <UContainer class="pt-8 pb-16 lg:pb-24">
    <h1 tabindex="-1" class="mb-4 text-4xl font-bold text-primary-600 focus:outline-none">
      {{ t('search.title') }}
    </h1>
    <div class="h-1 w-20 rounded bg-secondary-500" />
    <p class="mt-4 max-w-3xl text-muted">{{ t('search.intro') }}</p>

    <div class="mt-8 mb-6 space-y-4">
      <form
        role="search"
        :aria-label="t('search.formLabel')"
        class="flex max-w-3xl gap-2"
        @submit.prevent="submit"
      >
        <UInput
          v-model="draft"
          type="search"
          name="q"
          size="lg"
          icon="i-lucide-search"
          :aria-label="t('search.inputLabel')"
          :placeholder="t('search.placeholder')"
          :maxlength="SEARCH_MAX_LENGTH"
          class="flex-1"
        />
        <UButton type="submit" size="lg" icon="i-lucide-search">{{ t('search.submit') }}</UButton>
      </form>

      <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <URadioGroup
          v-model="typeModel"
          name="type"
          :legend="t('search.typeLabel')"
          :items="typeItems"
          orientation="horizontal"
          variant="table"
          indicator="hidden"
        />
        <UFormField :label="t('search.locale')" name="locale" class="md:w-56">
          <USelect v-model="localeModel" :items="localeItems" class="w-full" />
        </UFormField>
      </div>
    </div>

    <p
      data-testid="search-count"
      role="status"
      aria-live="polite"
      class="mb-4 text-sm font-medium text-gray-700"
    >
      {{ countText }}
    </p>

    <div aria-live="polite">
      <p
        v-if="tooShort"
        data-testid="search-too-short"
        class="flex items-center gap-2 rounded border border-default p-4 text-gray-700"
      >
        <UIcon name="i-lucide-info" class="size-5 shrink-0 text-primary" aria-hidden="true" />
        {{ t('search.tooShort', { min: SEARCH_MIN_LENGTH }) }}
      </p>
    </div>

    <p
      v-if="!query"
      data-testid="search-prompt"
      class="rounded border border-default p-6 text-center text-gray-700"
    >
      {{ t('search.prompt') }}
    </p>

    <template v-else-if="searchable">
      <div v-if="error" role="alert">
        <UAlert
          color="error"
          variant="subtle"
          icon="i-lucide-circle-alert"
          :title="t('search.error')"
          :actions="[
            {
              label: t('search.retry'),
              color: 'error',
              variant: 'outline',
              icon: 'i-lucide-rotate-cw',
              onClick: () => store.search(),
            },
          ]"
        />
      </div>

      <div v-else-if="initialLoading" data-testid="search-loading" aria-busy="true">
        <USkeleton v-for="n in 4" :key="n" class="mb-4 h-28 w-full" />
      </div>

      <div
        v-else-if="!results.length"
        data-testid="search-empty"
        class="rounded border border-default p-6 text-center text-gray-700"
      >
        <p class="font-medium">{{ t('search.empty', { query }) }}</p>
        <p class="mt-2 text-sm">{{ t('search.emptyHint') }}</p>
      </div>

      <template v-else>
        <ul :aria-busy="loading" class="space-y-4">
          <li
            v-for="hit in results"
            :key="`${hit.type}-${hit.id}`"
            data-testid="search-result"
            class="rounded border border-default p-4"
          >
            <UBadge
              data-testid="search-result-type"
              :color="hit.type === 'post' ? 'primary' : 'neutral'"
              variant="subtle"
              size="sm"
              :icon="hit.type === 'post' ? 'i-lucide-newspaper' : 'i-lucide-messages-square'"
            >
              {{ t(`search.badge.${hit.type}`) }}
            </UBadge>
            <h2 class="mt-2 text-lg font-semibold" :lang="hit.locale">
              <ULink
                :to="hitLink(hit)"
                raw
                class="text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
              >
                {{ hit.title }}
              </ULink>
            </h2>
            <SafeHtml
              data-testid="search-snippet"
              tag="p"
              :html="hit.snippet"
              :allowed-tags="SNIPPET_TAGS"
              :lang="hit.locale"
              class="mt-2 text-gray-700 [&_mark]:rounded-sm [&_mark]:bg-secondary-200 [&_mark]:px-0.5 [&_mark]:text-primary-900"
            />
            <p class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
              <span>
                <span class="sr-only">{{ `${t('search.author')}: ` }}</span>
                {{ hit.author?.display_name ?? t('search.formerMember') }}
              </span>
              <span>
                <span class="sr-only">{{ `${t('search.category')}: ` }}</span>
                {{ hit.category.name }}
              </span>
              <span v-if="hit.published_at">
                <span class="sr-only">{{ `${t('search.published')}: ` }}</span>
                <time :datetime="hit.published_at">{{
                  formatDate(hit.published_at, uiLocale)
                }}</time>
              </span>
            </p>
          </li>
        </ul>

        <div v-if="total > SEARCH_PAGE_SIZE" class="flex justify-center pt-6">
          <UPagination
            :page="page"
            :total="total"
            :items-per-page="SEARCH_PAGE_SIZE"
            :aria-label="t('search.pagination')"
            @update:page="(next: number) => setPage(next)"
          />
        </div>
      </template>
    </template>
  </UContainer>
</template>

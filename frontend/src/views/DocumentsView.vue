<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import DocumentCard from '@/components/knowbase/DocumentCard.vue'
import KnowbaseResults from '@/components/knowbase/KnowbaseResults.vue'
import KnowbaseStatusBanner from '@/components/knowbase/KnowbaseStatusBanner.vue'
import { KB_PAGE_SIZE } from '@/constants/knowbase'
import { useCountries } from '@/composables/useCountries'
import { searchParam, useDebouncedSearch, useKnowbaseList } from '@/composables/useKnowbaseList'
import { useQueryFilters } from '@/composables/useQueryFilters'
import type {
  CountryLookupItem,
  DocumentListParams,
  DocumentLookup,
  DocumentLookupItem,
} from '@/services/knowbase'
import { useKnowbaseStore } from '@/stores/knowbase'

/**
 * KNOWBASE legislation and policies, filterable by text, country, governance level, subject and
 * keyword. Filters and page live in the URL (`useQueryFilters`).
 */
const { t, locale } = useI18n()
const { countryName } = useCountries()
const store = useKnowbaseStore()

const { filters, page, hasFilters, setFilter, setPage, clearFilters } = useQueryFilters({
  q: 'string',
  country: 'string',
  level_id: 'number',
  subject_id: 'number',
  keyword_ids: 'numbers',
})

/** Select value for "no filter" (reka-ui selects cannot hold an empty string). */
const ALL = 'all'

const search = useDebouncedSearch(
  () => filters.value.q,
  (q) => setFilter('q', q),
)

// --- Filter options ---------------------------------------------------------------------------

const countries = ref<CountryLookupItem[]>([])
const lookups = ref<Record<DocumentLookup, DocumentLookupItem[]>>({
  levels: [],
  subjects: [],
  keywords: [],
})

onMounted(() => {
  // Optional data for the filters: without it the selects are just empty.
  store
    .countries()
    .then((items) => (countries.value = items))
    .catch(() => {})
  for (const name of Object.keys(lookups.value) as DocumentLookup[]) {
    store
      .documentLookup(name)
      .then((items) => (lookups.value[name] = items))
      .catch(() => {})
  }
})

const options = (name: DocumentLookup) =>
  lookups.value[name].map((item) => ({ label: item.label, value: item.id }))

const countryItems = computed(() => {
  const items = countries.value.map((c) => ({ label: countryName(c.code), value: c.code }))
  items.sort((a, b) => a.label.localeCompare(b.label, locale.value))
  return [{ label: t('knowbase.documents.filters.allCountries'), value: ALL }, ...items]
})
const country = computed<string>({
  get: () => filters.value.country.toUpperCase() || ALL,
  set: (value) => void setFilter('country', value === ALL ? '' : value),
})

function single(key: 'level_id' | 'subject_id') {
  return computed<number | typeof ALL>({
    get: () => filters.value[key] ?? ALL,
    set: (value) => void setFilter(key, value === ALL ? undefined : value),
  })
}
const levelId = single('level_id')
const subjectId = single('subject_id')
const levelItems = computed(() => [
  { label: t('knowbase.documents.filters.allLevels'), value: ALL },
  ...options('levels'),
])
const subjectItems = computed(() => [
  { label: t('knowbase.documents.filters.allSubjects'), value: ALL },
  ...options('subjects'),
])

const keywordIds = computed<number[]>({
  get: () => filters.value.keyword_ids,
  set: (ids) =>
    void setFilter(
      'keyword_ids',
      [...ids].sort((a, b) => a - b),
    ),
})

// --- Documents --------------------------------------------------------------------------------

const params = computed<DocumentListParams>(() => {
  const { q, country, level_id, subject_id, keyword_ids } = filters.value
  return {
    q: searchParam(q),
    country: country.toUpperCase() || undefined,
    level_id,
    subject_id,
    keyword_ids: keyword_ids.length ? keyword_ids : undefined,
    skip: (page.value - 1) * KB_PAGE_SIZE,
    limit: KB_PAGE_SIZE,
  }
})

const { items, total, loading, failed, initialLoading, load } = useKnowbaseList(
  'knowbase-documents',
  params,
  store.listDocuments,
)
</script>

<template>
  <UContainer class="pt-8 pb-16 lg:pb-24">
    <ULink
      to="/knowbase"
      raw
      class="mb-4 inline-flex items-center gap-1 text-sm text-primary-700 underline-offset-2 hover:underline"
    >
      <UIcon name="i-lucide-arrow-left" class="size-4" aria-hidden="true" />
      {{ t('knowbase.backToLibrary') }}
    </ULink>
    <div class="mb-8">
      <h1 tabindex="-1" class="mb-4 text-4xl font-bold text-primary-600 focus:outline-none">
        {{ t('knowbase.documents.title') }}
      </h1>
      <div class="h-1 w-20 rounded bg-secondary-500" />
      <p class="mt-4 max-w-3xl text-muted">{{ t('knowbase.documents.intro') }}</p>
    </div>

    <KnowbaseStatusBanner :families="['documents']" class="mb-6" />

    <div class="grid gap-8 lg:grid-cols-[18rem_1fr]">
      <section aria-labelledby="kb-filters-heading" class="space-y-4">
        <h2 id="kb-filters-heading" class="text-lg font-semibold text-secondary-600">
          {{ t('knowbase.filters.title') }}
        </h2>
        <UFormField :label="t('knowbase.filters.search')" name="q">
          <UInput
            v-model="search"
            type="search"
            icon="i-lucide-search"
            :placeholder="t('knowbase.documents.filters.searchPlaceholder')"
            class="w-full"
          />
        </UFormField>
        <UFormField :label="t('knowbase.documents.filters.country')" name="country">
          <USelect v-model="country" :items="countryItems" class="w-full" />
        </UFormField>
        <UFormField :label="t('knowbase.documents.filters.level')" name="level_id">
          <USelect v-model="levelId" :items="levelItems" class="w-full" />
        </UFormField>
        <UFormField :label="t('knowbase.documents.filters.subject')" name="subject_id">
          <USelect v-model="subjectId" :items="subjectItems" class="w-full" />
        </UFormField>
        <UFormField :label="t('knowbase.filters.keywords')" name="keyword_ids">
          <USelectMenu
            v-model="keywordIds"
            multiple
            :items="options('keywords')"
            value-key="value"
            :placeholder="t('knowbase.filters.any')"
            class="w-full"
          />
        </UFormField>
        <UButton
          v-if="hasFilters"
          color="neutral"
          variant="link"
          icon="i-lucide-x"
          class="px-0"
          @click="clearFilters()"
        >
          {{ t('knowbase.clearFilters') }}
        </UButton>
      </section>

      <KnowbaseResults
        :total="total"
        :page="page"
        :count="t('knowbase.documents.count', { count: total }, total)"
        :empty="hasFilters ? t('knowbase.documents.empty') : t('knowbase.documents.emptyAll')"
        :load-error="t('knowbase.documents.loadError')"
        :pagination-label="t('knowbase.documents.pagination')"
        :has-items="items.length > 0"
        :has-filters="hasFilters"
        :loading="loading"
        :initial-loading="initialLoading"
        :failed="failed"
        @retry="load()"
        @clear="clearFilters()"
        @page="setPage"
      >
        <ul class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <DocumentCard v-for="doc in items" :key="doc.id" :document="doc" />
        </ul>
      </KnowbaseResults>
    </div>
  </UContainer>
</template>

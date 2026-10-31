<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import KnowbaseResults from '@/components/knowbase/KnowbaseResults.vue'
import KnowbaseStatusBanner from '@/components/knowbase/KnowbaseStatusBanner.vue'
import MeasureCard from '@/components/knowbase/MeasureCard.vue'
import { KB_PAGE_SIZE } from '@/constants/knowbase'
import { searchParam, useDebouncedSearch, useKnowbaseList } from '@/composables/useKnowbaseList'
import { useQueryFilters } from '@/composables/useQueryFilters'
import type { MeasureListParams, MeasureLookup, MeasureLookupItem } from '@/services/knowbase'
import { useKnowbaseStore } from '@/stores/knowbase'

/**
 * KNOWBASE flood management measures, filterable by text, category, level of application, scale
 * and keyword. Filters and page live in the URL (`useQueryFilters`).
 */
const { t } = useI18n()
const store = useKnowbaseStore()

const { filters, page, hasFilters, setFilter, setPage, clearFilters } = useQueryFilters({
  q: 'string',
  category_id: 'number',
  level_of_application_ids: 'numbers',
  scale_ids: 'numbers',
  keyword_ids: 'numbers',
})

/** Select value for "no filter" (reka-ui selects cannot hold an empty string). */
const ALL = 'all'

const search = useDebouncedSearch(
  () => filters.value.q,
  (q) => setFilter('q', q),
)

// --- Filter options ---------------------------------------------------------------------------

const lookups = ref<Record<MeasureLookup, MeasureLookupItem[]>>({
  categories: [],
  'levels-of-application': [],
  scales: [],
  keywords: [],
})

onMounted(() => {
  // Optional data for the filters: without it the selects are just empty.
  for (const name of Object.keys(lookups.value) as MeasureLookup[]) {
    store
      .measureLookup(name)
      .then((items) => (lookups.value[name] = items))
      .catch(() => {})
  }
})

const options = (name: MeasureLookup) =>
  lookups.value[name].map((item) => ({ label: item.label_en, value: item.id }))

const categoryItems = computed(() => [
  { label: t('knowbase.measures.filters.allCategories'), value: ALL },
  ...options('categories'),
])
const category = computed<number | typeof ALL>({
  get: () => filters.value.category_id ?? ALL,
  set: (value) => void setFilter('category_id', value === ALL ? undefined : value),
})

type MultiKey = 'level_of_application_ids' | 'scale_ids' | 'keyword_ids'

function multi(key: MultiKey) {
  return computed<number[]>({
    get: () => filters.value[key],
    set: (ids) =>
      void setFilter(
        key,
        [...ids].sort((a, b) => a - b),
      ),
  })
}
const levelIds = multi('level_of_application_ids')
const scaleIds = multi('scale_ids')
const keywordIds = multi('keyword_ids')

// --- Measures ---------------------------------------------------------------------------------

const params = computed<MeasureListParams>(() => {
  const { q, category_id, level_of_application_ids, scale_ids, keyword_ids } = filters.value
  return {
    q: searchParam(q),
    category_id,
    level_of_application_ids: level_of_application_ids.length
      ? level_of_application_ids
      : undefined,
    scale_ids: scale_ids.length ? scale_ids : undefined,
    keyword_ids: keyword_ids.length ? keyword_ids : undefined,
    skip: (page.value - 1) * KB_PAGE_SIZE,
    limit: KB_PAGE_SIZE,
  }
})

const { items, total, loading, failed, initialLoading, load } = useKnowbaseList(
  'knowbase-measures',
  params,
  store.listMeasures,
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
        {{ t('knowbase.measures.title') }}
      </h1>
      <div class="h-1 w-20 rounded bg-secondary-500" />
      <p class="mt-4 max-w-3xl text-muted">{{ t('knowbase.measures.intro') }}</p>
    </div>

    <KnowbaseStatusBanner :families="['measures']" class="mb-6" />

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
            :placeholder="t('knowbase.measures.filters.searchPlaceholder')"
            class="w-full"
          />
        </UFormField>
        <UFormField :label="t('knowbase.measures.filters.category')" name="category_id">
          <USelect v-model="category" :items="categoryItems" class="w-full" />
        </UFormField>
        <UFormField :label="t('knowbase.measures.filters.levels')" name="level_of_application_ids">
          <USelectMenu
            v-model="levelIds"
            multiple
            :items="options('levels-of-application')"
            value-key="value"
            :placeholder="t('knowbase.filters.any')"
            class="w-full"
          />
        </UFormField>
        <UFormField :label="t('knowbase.measures.filters.scales')" name="scale_ids">
          <USelectMenu
            v-model="scaleIds"
            multiple
            :items="options('scales')"
            value-key="value"
            :placeholder="t('knowbase.filters.any')"
            class="w-full"
          />
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
        :count="t('knowbase.measures.count', { count: total }, total)"
        :empty="hasFilters ? t('knowbase.measures.empty') : t('knowbase.measures.emptyAll')"
        :load-error="t('knowbase.measures.loadError')"
        :pagination-label="t('knowbase.measures.pagination')"
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
          <MeasureCard v-for="measure in items" :key="measure.id" :measure="measure" />
        </ul>
      </KnowbaseResults>
    </div>
  </UContainer>
</template>

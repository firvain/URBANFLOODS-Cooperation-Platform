<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import ExternalLink from '@/components/common/ExternalLink.vue'
import KnowbaseStatusBanner from '@/components/knowbase/KnowbaseStatusBanner.vue'
import { useCountries } from '@/composables/useCountries'
import { EXTERNAL_LINKS } from '@/constants/links'
import type { CountryLookupItem } from '@/services/knowbase'
import { useKnowbaseStore } from '@/stores/knowbase'

/**
 * KNOWBASE Library landing: the two collections with their sizes, and the Policy Toolkit (the
 * legislation of one country, plus the measures). The timeline facet (short/mid/long term) is
 * not in the KNOWBASE yet.
 */
const { t, locale } = useI18n()
const { countryName } = useCountries()
const store = useKnowbaseStore()

/** `undefined` while loading, `null` when the count could not be loaded. */
const counts = ref<Record<'measures' | 'documents', number | null | undefined>>({
  measures: undefined,
  documents: undefined,
})
const countries = ref<CountryLookupItem[]>([])

onMounted(() => {
  // `limit=1`: only the totals are needed.
  store
    .listMeasures({ limit: 1 })
    .then((page) => (counts.value.measures = page.total))
    .catch(() => (counts.value.measures = null))
  store
    .listDocuments({ limit: 1 })
    .then((page) => (counts.value.documents = page.total))
    .catch(() => (counts.value.documents = null))
  store
    .countries()
    .then((items) => (countries.value = items))
    .catch(() => {})
})

const collections = computed(() => [
  {
    key: 'measures' as const,
    to: '/knowbase/measures',
    icon: 'i-lucide-shield-check',
    count: counts.value.measures,
  },
  {
    key: 'documents' as const,
    to: '/knowbase/documents',
    icon: 'i-lucide-scale',
    count: counts.value.documents,
  },
])

// --- Policy Toolkit ---------------------------------------------------------------------------

/** Select value for "no country" (reka-ui selects cannot hold an empty string). */
const ALL = 'all'
const country = ref<string>(ALL)

const countryItems = computed(() => {
  const items = countries.value.map((c) => ({ label: countryName(c.code), value: c.code }))
  items.sort((a, b) => a.label.localeCompare(b.label, locale.value))
  return [{ label: t('knowbase.toolkit.allCountries'), value: ALL }, ...items]
})

const documentsLink = computed(() =>
  country.value === ALL
    ? { to: '/knowbase/documents', label: t('knowbase.toolkit.documents') }
    : {
        to: `/knowbase/documents?country=${encodeURIComponent(country.value)}`,
        label: t('knowbase.toolkit.documentsFor', { country: countryName(country.value) }),
      },
)
</script>

<template>
  <UContainer class="pt-8 pb-16 lg:pb-24">
    <div class="mb-8">
      <h1 tabindex="-1" class="mb-4 text-4xl font-bold text-primary-600 focus:outline-none">
        {{ t('knowbase.title') }}
      </h1>
      <div class="h-1 w-20 rounded bg-secondary-500" />
      <p class="mt-4 max-w-3xl text-muted">{{ t('knowbase.intro') }}</p>
      <p class="mt-3">
        <ExternalLink :href="EXTERNAL_LINKS.knowbase" trailing-icon="i-lucide-arrow-up-right">
          {{ t('knowbase.openKnowbase') }}
        </ExternalLink>
      </p>
    </div>

    <KnowbaseStatusBanner class="mb-6" />

    <ul class="grid gap-6 md:grid-cols-2">
      <li v-for="item in collections" :key="item.key" :data-testid="`kb-card-${item.key}`">
        <UCard class="h-full">
          <h2 class="flex items-center gap-2 text-xl font-semibold">
            <UIcon :name="item.icon" class="size-6 text-primary" aria-hidden="true" />
            <ULink
              :to="item.to"
              raw
              class="text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
            >
              {{ t(`knowbase.${item.key}.title`) }}
            </ULink>
          </h2>
          <p class="mt-3 text-muted">{{ t(`knowbase.${item.key}.description`) }}</p>
          <div class="mt-4 text-sm font-medium text-gray-700">
            <USkeleton v-if="item.count === undefined" class="h-5 w-28" />
            <template v-else-if="item.count !== null">
              {{ t(`knowbase.${item.key}.count`, { count: item.count }, item.count) }}
            </template>
          </div>
        </UCard>
      </li>
    </ul>

    <section
      data-testid="policy-toolkit"
      aria-labelledby="policy-toolkit-heading"
      class="mt-10 rounded border border-secondary-200 bg-secondary-50 p-6"
    >
      <h2 id="policy-toolkit-heading" class="text-xl font-semibold text-primary-700">
        {{ t('knowbase.toolkit.title') }}
      </h2>
      <p class="mt-2 max-w-3xl text-gray-700">{{ t('knowbase.toolkit.intro') }}</p>
      <div class="mt-4 flex flex-col gap-4 md:flex-row md:items-end">
        <UFormField :label="t('knowbase.toolkit.country')" name="toolkit-country" class="md:w-72">
          <USelect v-model="country" :items="countryItems" class="w-full" />
        </UFormField>
        <div class="flex flex-wrap gap-3">
          <UButton :to="documentsLink.to" icon="i-lucide-scale">{{ documentsLink.label }}</UButton>
          <UButton
            to="/knowbase/measures"
            color="neutral"
            variant="outline"
            icon="i-lucide-shield-check"
          >
            {{ t('knowbase.toolkit.measures') }}
          </UButton>
        </div>
      </div>
      <p class="mt-4 text-sm text-gray-700">
        <UIcon
          name="i-lucide-info"
          class="me-1 inline-block size-4 align-[-3px]"
          aria-hidden="true"
        />
        {{ t('knowbase.toolkit.timelineNote') }}
      </p>
    </section>
  </UContainer>
</template>

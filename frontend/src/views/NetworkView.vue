<script lang="ts">
/** How long the search box waits after the last keystroke before it filters. */
export const SEARCH_DEBOUNCE_MS = 300
/** Members per page. */
export const PAGE_SIZE = 24
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'

import CompleteProfileBanner from '@/components/account/CompleteProfileBanner.vue'
import MemberCard from '@/components/network/MemberCard.vue'
import MembersRestricted from '@/components/network/MembersRestricted.vue'
import { useCountries } from '@/composables/useCountries'
import { useQueryFilters } from '@/composables/useQueryFilters'
import { PROJECT_COUNTRIES } from '@/constants/auth'
import { ApiError } from '@/services/api'
import { membersService, type Member, type MemberListParams } from '@/services/members'
import { useAuthStore } from '@/stores/auth'
import { useExpertiseStore } from '@/stores/expertise'
import { useOrganisationsStore } from '@/stores/organisations'

/**
 * Collaboration Network: the members directory, filterable by text, expertise, country and
 * organisation. Filters and page live in the URL (`useQueryFilters`). The directory is for
 * verified users (as `GET /members/`): anyone else sees a sign-in or verify notice in its place,
 * and no members request is made; a 401/403 from the API falls back to the same notice.
 */
const { t, locale } = useI18n()
const route = useRoute()
const { countryName } = useCountries()
const expertiseStore = useExpertiseStore()
const organisationsStore = useOrganisationsStore()
const { tags } = storeToRefs(expertiseStore)
const { all: organisations } = storeToRefs(organisationsStore)
const { isVerified } = storeToRefs(useAuthStore())

const { filters, page, hasFilters, setFilter, setPage, clearFilters } = useQueryFilters({
  q: 'string',
  expertise_ids: 'numbers',
  country: 'string',
  organisation_id: 'number',
})

/** Select value for "no filter" (reka-ui selects cannot hold an empty string). */
const ALL = 'all'

// --- Filter controls --------------------------------------------------------------------------

const search = ref(filters.value.q)
let searchTimer: ReturnType<typeof setTimeout> | undefined

watch(search, (value) => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    searchTimer = undefined
    const q = value.trim()
    if (q !== filters.value.q) void setFilter('q', q)
  }, SEARCH_DEBOUNCE_MS)
})

// The URL changed some other way (back button, "Clear filters"): show it, unless the user is
// still typing.
watch(
  () => filters.value.q,
  (q) => {
    if (searchTimer === undefined && q !== search.value.trim()) search.value = q
  },
)

onBeforeUnmount(() => clearTimeout(searchTimer))

const expertiseItems = computed(() =>
  tags.value.map((tag) => ({ label: tag.label, value: tag.id })),
)
const expertiseIds = computed<number[]>({
  get: () => filters.value.expertise_ids,
  set: (ids) =>
    void setFilter(
      'expertise_ids',
      [...ids].sort((a, b) => a - b),
    ),
})

const countryItems = computed(() => {
  const countries = PROJECT_COUNTRIES.map((code) => ({ label: countryName(code), value: code }))
  countries.sort((a, b) => a.label.localeCompare(b.label, locale.value))
  return [{ label: t('network.filters.allCountries'), value: ALL }, ...countries]
})
const country = computed<string>({
  get: () => filters.value.country.toUpperCase() || ALL,
  set: (value) => void setFilter('country', value === ALL ? '' : value),
})

const organisationItems = computed(() => [
  { label: t('network.filters.allOrganisations'), value: ALL },
  ...organisations.value.map((o) => ({ label: o.name, value: o.id })),
])
const organisation = computed<number | typeof ALL>({
  get: () => filters.value.organisation_id ?? ALL,
  set: (value) => void setFilter('organisation_id', value === ALL ? undefined : value),
})

onMounted(() => {
  // Optional data for the filters: without it the selects are just shorter.
  expertiseStore.fetch().catch(() => {})
  organisationsStore.fetchAll().catch(() => {})
})

// --- Members ----------------------------------------------------------------------------------

const members = ref<Member[]>([])
const total = ref(0)
const loading = ref(true)
const failed = ref(false)
/** The API refused the directory (401/403) although the session looked verified. */
const refused = ref(false)

const showDirectory = computed(() => isVerified.value && !refused.value)

const params = computed<MemberListParams>(() => {
  const { q, expertise_ids, country, organisation_id } = filters.value
  return {
    q: q || undefined,
    expertise_ids: expertise_ids.length ? expertise_ids : undefined,
    country: country.toUpperCase() || undefined,
    organisation_id,
    skip: (page.value - 1) * PAGE_SIZE,
    limit: PAGE_SIZE,
  }
})

let latest = 0

async function load() {
  const request = ++latest
  failed.value = false
  if (!isVerified.value) {
    loading.value = false
    return
  }
  loading.value = true
  refused.value = false
  try {
    const result = await membersService.list(params.value)
    if (request !== latest) return
    members.value = result.items
    total.value = result.total
  } catch (e) {
    if (request !== latest) return
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) refused.value = true
    else failed.value = true
    members.value = []
    total.value = 0
  } finally {
    if (request === latest) loading.value = false
  }
}

watch(
  () => [JSON.stringify(params.value), isVerified.value],
  () => {
    // Leaving the page also changes the query; only this route's query matters.
    if (route.name === 'network') void load()
  },
  { immediate: true },
)

const initialLoading = computed(() => loading.value && !members.value.length && !failed.value)
</script>

<template>
  <UContainer class="pt-8 pb-16 lg:pb-24">
    <div class="mb-8">
      <h1 tabindex="-1" class="mb-4 text-4xl font-bold text-primary-600 focus:outline-none">
        {{ t('network.title') }}
      </h1>
      <div class="h-1 w-20 rounded bg-secondary-500" />
      <p class="mt-4 max-w-3xl text-muted">{{ t('network.intro') }}</p>
    </div>

    <CompleteProfileBanner class="mb-8" />

    <MembersRestricted
      v-if="!showDirectory"
      data-testid="members-restricted"
      partners
      class="max-w-3xl"
    />

    <div v-else class="grid gap-8 lg:grid-cols-[18rem_1fr]">
      <section aria-labelledby="network-filters-heading" class="space-y-4">
        <h2 id="network-filters-heading" class="text-lg font-semibold text-secondary">
          {{ t('network.filters.title') }}
        </h2>
        <UFormField :label="t('network.filters.search')" name="q">
          <UInput
            v-model="search"
            type="search"
            icon="i-lucide-search"
            :placeholder="t('network.filters.searchPlaceholder')"
            class="w-full"
          />
        </UFormField>
        <UFormField :label="t('network.filters.expertise')" name="expertise_ids">
          <USelectMenu
            v-model="expertiseIds"
            multiple
            :items="expertiseItems"
            value-key="value"
            :placeholder="t('network.filters.expertisePlaceholder')"
            class="w-full"
          />
        </UFormField>
        <UFormField :label="t('network.filters.country')" name="country">
          <USelect v-model="country" :items="countryItems" class="w-full" />
        </UFormField>
        <UFormField :label="t('network.filters.organisation')" name="organisation_id">
          <USelectMenu
            v-model="organisation"
            :items="organisationItems"
            value-key="value"
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
          {{ t('network.clearFilters') }}
        </UButton>
      </section>

      <div class="min-w-0 space-y-4">
        <div v-if="initialLoading" data-testid="network-loading" aria-busy="true">
          <span class="sr-only">{{ t('network.loading') }}</span>
          <div class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            <USkeleton v-for="n in 6" :key="n" class="h-36 w-full" />
          </div>
        </div>

        <div v-else-if="failed" role="alert">
          <UAlert
            color="error"
            variant="subtle"
            icon="i-lucide-circle-alert"
            :title="t('network.loadError')"
            :actions="[
              {
                label: t('network.retry'),
                color: 'error',
                variant: 'outline',
                icon: 'i-lucide-rotate-cw',
                onClick: () => load(),
              },
            ]"
          />
        </div>

        <template v-else>
          <p data-testid="member-count" role="status" class="text-sm font-medium text-gray-700">
            {{ t('network.count', { count: total }, total) }}
          </p>

          <div v-if="!members.length" class="rounded border border-default p-6 text-center">
            <p class="text-gray-700">
              {{ hasFilters ? t('network.empty') : t('network.emptyAll') }}
            </p>
            <UButton
              v-if="hasFilters"
              color="neutral"
              variant="outline"
              icon="i-lucide-x"
              class="mt-4"
              @click="clearFilters()"
            >
              {{ t('network.clearFilters') }}
            </UButton>
          </div>

          <ul
            v-else
            :aria-busy="loading"
            class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3"
          >
            <MemberCard v-for="member in members" :key="member.id" :member="member" />
          </ul>

          <div v-if="total > PAGE_SIZE" class="flex justify-center pt-4">
            <UPagination
              :page="page"
              :total="total"
              :items-per-page="PAGE_SIZE"
              :aria-label="t('network.pagination')"
              @update:page="setPage"
            />
          </div>
        </template>
      </div>
    </div>
  </UContainer>
</template>

/**
 * Organisations store: the partner list (`/partners`) and the full list (organisation picker),
 * each fetched once per page load and shared by every component that needs it.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { listOrganisations, type Organisation } from '@/services/organisations'

/** The lead partner's short name (type PP, sort_order 1 in the seed data). */
export const LEAD_PARTNER_SHORT_NAME = 'UOWM'

/** The backend's page size cap is 100; the partnership has 22 organisations. */
const PAGE_LIMIT = 100

const bySortOrder = (a: Organisation, b: Organisation) =>
  a.sort_order - b.sort_order || a.name.localeCompare(b.name)

/** A list fetched at most once (unless forced), with concurrent callers sharing the request. */
function cachedList(load: () => Promise<Organisation[]>) {
  const items = ref<Organisation[]>([])
  const loaded = ref(false)
  let pending: Promise<Organisation[]> | null = null

  function fetch({ force = false }: { force?: boolean } = {}): Promise<Organisation[]> {
    if (loaded.value && !force) return Promise.resolve(items.value)
    pending ??= load()
      .then((result) => {
        items.value = result
        loaded.value = true
        return result
      })
      .finally(() => {
        pending = null
      })
    return pending
  }

  return { items, loaded, fetch }
}

export const useOrganisationsStore = defineStore('organisations', () => {
  const partnerList = cachedList(
    async () => (await listOrganisations({ partners_only: true, limit: PAGE_LIMIT })).items,
  )
  const allList = cachedList(async () => (await listOrganisations({ limit: PAGE_LIMIT })).items)

  const partners = computed(() => [...partnerList.items.value].sort(bySortOrder))

  const leadPartner = computed(
    () => partners.value.find((o) => o.short_name === LEAD_PARTNER_SHORT_NAME) ?? null,
  )
  const projectPartners = computed(() =>
    partners.value.filter((o) => o.type === 'PP' && o.id !== leadPartner.value?.id),
  )
  const associatedPartners = computed(() => partners.value.filter((o) => o.type === 'AP'))
  /** Distinct countries of the lead, project and associated partners. */
  const partnerCountryCount = computed(
    () =>
      new Set(
        partners.value.filter((o) => o.type === 'PP' || o.type === 'AP').map((o) => o.country),
      ).size,
  )

  return {
    partners,
    partnersLoaded: partnerList.loaded,
    leadPartner,
    projectPartners,
    associatedPartners,
    partnerCountryCount,
    fetchPartners: partnerList.fetch,
    all: allList.items,
    allLoaded: allList.loaded,
    fetchAll: allList.fetch,
  }
})

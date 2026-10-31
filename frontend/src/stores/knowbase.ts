/**
 * KNOWBASE Library state shared by its views:
 *
 * - lookups (filter options) cached per family for the page load, one request per lookup;
 * - whether the KNOWBASE is reachable, from the last list response of each family: the proxy's
 *   `X-Knowbase-Cache: stale` means cached data is shown, a 503 means no data at all.
 *   `KnowbaseStatusBanner` reads it.
 */
import { computed, reactive } from 'vue'
import { defineStore } from 'pinia'

import { ApiError } from '@/services/api'
import {
  knowbaseService,
  type CountryLookupItem,
  type DocumentListParams,
  type DocumentLookup,
  type DocumentLookupItem,
  type KbResult,
  type MeasureListParams,
  type MeasureLookup,
  type MeasureLookupItem,
} from '@/services/knowbase'

export type KbFamily = 'measures' | 'documents'
export type KbAvailability = 'ok' | 'stale' | 'unavailable'

export const useKnowbaseStore = defineStore('knowbase', () => {
  const availability = reactive<Record<KbFamily, KbAvailability>>({
    measures: 'ok',
    documents: 'ok',
  })

  /** Worst state over the given families (all by default): unavailable > stale > ok. */
  function statusOf(families: KbFamily[] = ['measures', 'documents']): KbAvailability {
    const states = families.map((family) => availability[family])
    if (states.includes('unavailable')) return 'unavailable'
    if (states.includes('stale')) return 'stale'
    return 'ok'
  }

  const status = computed(() => statusOf())

  /** Run a list request and record what it says about the KNOWBASE. */
  async function track<T>(family: KbFamily, request: Promise<KbResult<T>>): Promise<T> {
    try {
      const { data, cache } = await request
      availability[family] = cache === 'stale' ? 'stale' : 'ok'
      return data
    } catch (error) {
      const unavailable = error instanceof ApiError && error.status === 503
      availability[family] = unavailable ? 'unavailable' : 'ok'
      throw error
    }
  }

  const listMeasures = (params: MeasureListParams) =>
    track('measures', knowbaseService.listMeasures(params))

  const listDocuments = (params: DocumentListParams) =>
    track('documents', knowbaseService.listDocuments(params))

  // --- lookups ------------------------------------------------------------------------------

  const lookupCache = new Map<string, Promise<unknown>>()

  /** One shared request per lookup; a failure is not cached, so the next view retries. */
  function cached<T>(key: string, load: () => Promise<KbResult<T>>): Promise<T> {
    let pending = lookupCache.get(key) as Promise<T> | undefined
    if (!pending) {
      pending = load().then((result) => result.data)
      pending.catch(() => lookupCache.delete(key))
      lookupCache.set(key, pending)
    }
    return pending
  }

  const measureLookup = (name: MeasureLookup) =>
    cached<MeasureLookupItem[]>(`measures/${name}`, () => knowbaseService.measureLookup(name))

  const documentLookup = (name: DocumentLookup) =>
    cached<DocumentLookupItem[]>(`documents/${name}`, () => knowbaseService.documentLookup(name))

  const countries = () =>
    cached<CountryLookupItem[]>('documents/countries', () => knowbaseService.countries())

  return {
    availability,
    status,
    statusOf,
    listMeasures,
    listDocuments,
    measureLookup,
    documentLookup,
    countries,
  }
})

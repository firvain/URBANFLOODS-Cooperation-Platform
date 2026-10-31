/**
 * KNOWBASE Library through the platform's read-only proxy (`/api/v1/knowbase/*`, public).
 *
 * Every function resolves to `{ data, cache }`: `cache` is the proxy's `X-Knowbase-Cache` header
 * (`hit | miss | stale`), so the store can tell when the KNOWBASE is down and cached data is shown.
 * Errors arrive as `ApiError` (503 `knowbase.unavailable`, 502 `knowbase.upstream_error`,
 * 404 `knowbase.not_found`). Array filters are sent as repeated parameters
 * (`level_of_application_ids=1&level_of_application_ids=2`), as in `members.ts`.
 */
import { api } from './api'
import type { Page } from './members'

// TODO(gen:types): replace with components['schemas'][...] once generated (`npm run gen:types`).
// Hand-written because the proxy passes upstream objects through loosely (`extra="allow"`).

/** `X-Knowbase-Cache` response header. */
export type KbCacheState = 'hit' | 'miss' | 'stale'

export interface KbResult<T> {
  data: T
  /** `null` when the header is missing (or not exposed by CORS in local development). */
  cache: KbCacheState | null
}

/** Reference value of a measure (category, level of application, scale, keyword). */
export interface MeasureRef {
  id: number
  code: string
  label_en: string
  label_local: string | null
}

/** Option of a measures lookup. */
export interface MeasureLookupItem extends MeasureRef {
  count?: number
  sort_order?: number
}

export interface Measure {
  id: number
  measure_code: string | null
  title_en: string | null
  title_local: string | null
  photo_filename: string | null
  /** Absolute photo URL added by the proxy. */
  photo_url: string | null
  category: MeasureRef | null
  levels_of_application: MeasureRef[]
  scales: MeasureRef[]
  keywords: MeasureRef[]
  description_en: string | null
  description_local: string | null
  resources_required_en: string | null
  resources_required_local: string | null
  benefits_en: string | null
  benefits_local: string | null
  constraints_en: string | null
  constraints_local: string | null
  other_keywords: string | null
  photo_source: string | null
  all_keywords: string[]
}

/** Reference value of a document (level, subject). */
export interface DocumentRef {
  id: number
  code: string
  label: string
}

/** Option of a documents lookup (levels, subjects, keywords). */
export interface DocumentLookupItem extends DocumentRef {
  count?: number
}

export interface CountryLookupItem {
  /** ISO 3166-1 alpha-2. */
  code: string
  name: string
  count?: number
}

/** A legislation or policy document (`Document` would shadow the DOM type). */
export interface KbDocument {
  id: number
  name_of_document_en: string | null
  name_of_document_local: string | null
  /** ISO 3166-1 alpha-2. */
  country: string | null
  level: DocumentRef | null
  subject: DocumentRef | null
  no: string | null
  official_gazzette_ref: string | null
  extended_description_en: string | null
  extended_description_local: string | null
  /** Free text: URLs separated by whitespace, commas or new lines. */
  web_links: string | null
  keywords: string | null
  comments: string | null
  keyword_labels: string[]
  all_keywords: string[]
}

/** A post linking a KNOWBASE item (the subset of the posts summary this page shows). */
export interface MentionPost {
  id: number
  slug: string
  title: string
  excerpt?: string | null
  published_at?: string | null
}

export interface KnowbaseStatus {
  reachable: boolean
  last_error: string | null
  cache: Record<string, unknown>
}

export interface MeasureListParams {
  q?: string
  category_id?: number
  level_of_application_ids?: number[]
  scale_ids?: number[]
  keyword_ids?: number[]
  keyword_search?: string
  skip?: number
  /** At most 200. */
  limit?: number
}

export interface DocumentListParams {
  q?: string
  country?: string
  level_id?: number
  subject_id?: number
  keyword_ids?: number[]
  keyword_search?: string
  skip?: number
  limit?: number
}

export type MeasureLookup = 'categories' | 'levels-of-application' | 'scales' | 'keywords'
export type DocumentLookup = 'levels' | 'subjects' | 'keywords'
export type KbType = 'measure' | 'document'

const BASE = '/api/v1/knowbase'

function cacheState(value: string | null): KbCacheState | null {
  return value === 'hit' || value === 'miss' || value === 'stale' ? value : null
}

/** GET through the shared client, keeping the cache header. */
async function get<T>(path: string, query?: object): Promise<KbResult<T>> {
  const response = await api.raw<T>(`${BASE}${path}`, query ? { query: { ...query } } : {})
  return {
    data: response._data as T,
    cache: cacheState(response.headers.get('X-Knowbase-Cache')),
  }
}

export const knowbaseService = {
  listMeasures: (params: MeasureListParams = {}) => get<Page<Measure>>('/measures/', params),

  getMeasure: (id: number) => get<Measure>(`/measures/${id}`),

  measureLookup: (name: MeasureLookup) => get<MeasureLookupItem[]>(`/measures/lookups/${name}`),

  listDocuments: (params: DocumentListParams = {}) => get<Page<KbDocument>>('/documents/', params),

  getDocument: (id: number) => get<KbDocument>(`/documents/${id}`),

  countries: () => get<CountryLookupItem[]>('/lookups/countries'),

  documentLookup: (name: DocumentLookup) => get<DocumentLookupItem[]>(`/lookups/${name}`),

  status: () => get<KnowbaseStatus>('/status'),

  /** Posts linking the item (visible to the current user). */
  mentions: (kbType: KbType, id: number) => get<Page<MentionPost>>(`/${kbType}/${id}/mentions/`),
}

/**
 * The http(s) URLs in a document's free-text `web_links`, split on whitespace and commas.
 * Anything else (`javascript:`, `ftp:`, bare host names) is dropped, never rendered as a link.
 */
export function parseWebLinks(text: string | null | undefined): string[] {
  if (!text) return []
  const links = new Set<string>()
  for (const part of text.split(/[\s,]+/)) {
    const candidate = part.trim().replace(/[.;)]+$/, '')
    if (!/^https?:\/\//i.test(candidate)) continue
    try {
      const url = new URL(candidate)
      if (url.protocol === 'http:' || url.protocol === 'https:') links.add(candidate)
    } catch {
      // Not a URL: skip.
    }
  }
  return [...links]
}

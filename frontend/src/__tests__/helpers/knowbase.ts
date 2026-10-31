/** Fixtures for the KNOWBASE proxy contract (`/api/v1/knowbase/*`). */
import type { Handler } from './api'
import type { KbDocument, Measure, MentionPost } from '@/services/knowbase'

export const KB = '/api/v1/knowbase'
export const MEASURES = `GET ${KB}/measures/`

export type CacheHeader = 'hit' | 'miss' | 'stale'

/** JSON response with the proxy's `X-Knowbase-Cache` header. */
export function kbReply(body: unknown, cache: CacheHeader = 'miss', status = 200): Handler {
  return () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json', 'X-Knowbase-Cache': cache },
    })
}

export const CATEGORIES = [
  { id: 1, code: 'structural', label_en: 'Structural', label_local: null },
  { id: 2, code: 'nbs', label_en: 'Nature-Based Solutions', label_local: null },
  { id: 3, code: 'hybrid', label_en: 'Hybrid', label_local: null },
  { id: 4, code: 'non-structural', label_en: 'Non-Structural', label_local: null },
]
export const LEVELS_OF_APPLICATION = [
  { id: 1, code: 'protection', label_en: 'Protection', label_local: null },
  { id: 2, code: 'preparedness', label_en: 'Preparedness', label_local: null },
  { id: 3, code: 'recovery', label_en: 'Recovery', label_local: null },
]
export const SCALES = [
  { id: 1, code: 'property', label_en: 'Property', label_local: null },
  { id: 2, code: 'local', label_en: 'Local', label_local: null },
]
export const MEASURE_KEYWORDS = [
  { id: 5, code: 'green-roof', label_en: 'Green roof', label_local: null },
  { id: 6, code: 'retention', label_en: 'Retention', label_local: null },
]

export function makeMeasure(id: number, overrides: Partial<Measure> = {}): Measure {
  return {
    id,
    measure_code: `M${id}`,
    title_en: `Measure ${id}`,
    title_local: `Μέτρο ${id}`,
    photo_filename: `m${id}.jpg`,
    photo_url: `https://knowbase.test/static/measures/photos/m${id}.jpg`,
    category: CATEGORIES[1]!,
    levels_of_application: [LEVELS_OF_APPLICATION[0]!],
    scales: [SCALES[1]!],
    keywords: [MEASURE_KEYWORDS[0]!],
    description_en: `Description of measure ${id}.`,
    description_local: null,
    resources_required_en: `Resources for measure ${id}.`,
    resources_required_local: null,
    benefits_en: `Benefits of measure ${id}.`,
    benefits_local: null,
    constraints_en: `Constraints of measure ${id}.`,
    constraints_local: null,
    other_keywords: null,
    photo_source: 'Municipality of Kozani',
    all_keywords: ['Green roof', 'Retention', 'Runoff', 'Stormwater', 'Urban'],
    ...overrides,
  }
}

/** One page of `GET /measures/` out of `total`. */
export function measurePage(total: number, skip = 0, limit = 24) {
  const count = Math.max(0, Math.min(limit, total - skip))
  return { total, items: Array.from({ length: count }, (_, i) => makeMeasure(skip + i + 1)) }
}

export function makeDocument(id: number, overrides: Partial<KbDocument> = {}): KbDocument {
  return {
    id,
    name_of_document_en: `Law ${id} on flood risk management`,
    name_of_document_local: `Νόμος ${id} για τους κινδύνους πλημμύρας`,
    country: 'GR',
    level: { id: 1, code: 'NAT', label: 'National' },
    subject: { id: 1, code: 'FLM', label: 'Floods management' },
    no: `${4000 + id}/2010`,
    official_gazzette_ref: `ΦΕΚ Α ${id}/2010`,
    extended_description_en: `Transposes the Floods Directive (document ${id}).`,
    extended_description_local: `Ενσωμάτωση της Οδηγίας (έγγραφο ${id}).`,
    web_links: null,
    keywords: null,
    comments: null,
    keyword_labels: ['Flood risk'],
    all_keywords: ['Flood risk', 'Floods Directive'],
    ...overrides,
  }
}

export function makeMention(id: number): MentionPost {
  return {
    id,
    slug: `post-${id}`,
    title: `Post ${id} about green roofs`,
    excerpt: `Excerpt of post ${id}.`,
    published_at: '2026-10-20T10:00:00Z',
  }
}

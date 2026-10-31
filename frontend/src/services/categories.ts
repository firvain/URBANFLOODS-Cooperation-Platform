/** Blog and forum categories (`/api/v1/categories/`: public list; admin create/update/archive). */
import type { components, operations } from '@/types/api-schema'
import { api } from './api'

export type CategoryOut = components['schemas']['CategoryOut']
export type CategoryList = components['schemas']['CategoryList']
export type CategoryKind = components['schemas']['CategoryKind']
export type CategoryCreate = components['schemas']['CategoryCreate']
export type CategoryUpdate = components['schemas']['CategoryUpdate']
export type CategoryListParams = NonNullable<
  operations['list_categories_api_v1_categories__get']['parameters']['query']
>

const BASE = '/api/v1/categories'

export const categoriesService = {
  list: (params: CategoryListParams = {}) =>
    api<CategoryList>(`${BASE}/`, { query: { ...params } }),

  /** Admin. 409 `categories.slug_taken`. */
  create: (payload: CategoryCreate) =>
    api<CategoryOut>(`${BASE}/`, { method: 'POST', body: payload }),

  /** Admin; omitted fields are kept. 409 `categories.slug_taken` / `categories.slug_locked`. */
  update: (id: number, changes: CategoryUpdate) =>
    api<CategoryOut>(`${BASE}/${id}`, { method: 'PATCH', body: changes }),

  /** Admin; 204. Never a hard delete. 409 `categories.last_active`. */
  archive: (id: number) => api<void>(`${BASE}/${id}`, { method: 'DELETE' }),
}

/** The category name in `locale` (`name_i18n`), else the default name. */
export function categoryName(category: CategoryOut, locale: string): string {
  return category.name_i18n[locale] || category.name
}

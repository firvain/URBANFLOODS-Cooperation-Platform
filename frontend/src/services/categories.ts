/** Blog and forum categories (`/api/v1/categories/`, public). */
import type { components, operations } from '@/types/api-schema'
import { api } from './api'

export type CategoryOut = components['schemas']['CategoryOut']
export type CategoryList = components['schemas']['CategoryList']
export type CategoryKind = components['schemas']['CategoryKind']
export type CategoryListParams = NonNullable<
  operations['list_categories_api_v1_categories__get']['parameters']['query']
>

const BASE = '/api/v1/categories'

export const categoriesService = {
  list: (params: CategoryListParams = {}) =>
    api<CategoryList>(`${BASE}/`, { query: { ...params } }),
}

/** The category name in `locale` (`name_i18n`), else the default name. */
export function categoryName(category: CategoryOut, locale: string): string {
  return category.name_i18n[locale] || category.name
}

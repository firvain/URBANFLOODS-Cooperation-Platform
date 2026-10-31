/** Tags of posts and threads (`/api/v1/tags/`, public). */
import type { components, operations } from '@/types/api-schema'
import { api } from './api'

export type TagOut = components['schemas']['TagOut']
export type TagList = components['schemas']['TagList']
export type TagListParams = NonNullable<
  operations['list_tags_api_v1_tags__get']['parameters']['query']
>

const BASE = '/api/v1/tags'

export const tagsService = {
  list: (params: TagListParams = {}) => api<TagList>(`${BASE}/`, { query: { ...params } }),
}

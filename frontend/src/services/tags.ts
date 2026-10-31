/** Tags of posts and threads (`/api/v1/tags/`: public list; admin merge/delete). */
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

  /** Admin: the tag's posts move to `targetId` and it is deleted; returns the target. */
  merge: (id: number, targetId: number) =>
    api<TagOut>(`${BASE}/${id}/merge`, { method: 'POST', body: { target_id: targetId } }),

  /** Admin; 204. The tag is removed from every post. */
  remove: (id: number) => api<void>(`${BASE}/${id}`, { method: 'DELETE' }),
}

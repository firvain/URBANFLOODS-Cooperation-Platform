/** Expertise areas: the controlled vocabulary members tag their profiles with. */
import type { components, operations } from '@/types/api-schema'
import { api } from './api'

export type ExpertiseTag = components['schemas']['ExpertiseTagOut']
export type ExpertiseList = components['schemas']['ExpertiseTagList']
export type ExpertiseTagCreate = components['schemas']['ExpertiseTagCreate']
export type ExpertiseTagUpdate = components['schemas']['ExpertiseTagUpdate']
export type ExpertiseListParams = NonNullable<
  operations['list_expertise_api_v1_expertise__get']['parameters']['query']
>

const BASE = '/api/v1/expertise'

/** The active tags (`include_inactive` is honoured for admins only). */
export function listExpertise(params: ExpertiseListParams = {}): Promise<ExpertiseList> {
  return api<ExpertiseList>(`${BASE}/`, { query: { ...params } })
}

export const expertiseService = {
  list: listExpertise,

  /** Admin; the slug is derived from the label when omitted. 409 `expertise.slug_taken`. */
  create: (payload: ExpertiseTagCreate) =>
    api<ExpertiseTag>(`${BASE}/`, { method: 'POST', body: payload }),

  /** Admin; omitted fields are kept. `is_active: false` deactivates. 409 `expertise.slug_taken`. */
  update: (id: number, changes: ExpertiseTagUpdate) =>
    api<ExpertiseTag>(`${BASE}/${id}`, { method: 'PATCH', body: changes }),
}

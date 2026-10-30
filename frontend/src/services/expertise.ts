/** Expertise areas: the controlled vocabulary members tag their profiles with. */
import { api } from './api'

// TODO(gen:types): replace with components['schemas'][...] once generated (`npm run gen:types`).
// Hand-written only because the backend contract is being built concurrently (increment 1n).
export interface ExpertiseTag {
  id: number
  slug: string
  label: string
  sort_order: number
}

export interface ExpertiseList {
  total: number
  items: ExpertiseTag[]
}

export function listExpertise(): Promise<ExpertiseList> {
  return api<ExpertiseList>('/api/v1/expertise/')
}

/** Organisations (project partners and associated partners). */
import { api } from './api'

// TODO(gen:types): replace with components['schemas'][...] once generated (`npm run gen:types`).
// Hand-written only because the backend contract is being built concurrently (increment 1j).
export type OrganisationType = 'PP' | 'AP' | 'other'

/** `OrganisationSummary` (embedded in `UserMe`). */
export interface OrganisationSummary {
  id: number
  short_name: string
  name: string
  /** ISO 3166-1 alpha-2. */
  country: string
  type: OrganisationType
}

/** `OrganisationOut` (the public list). */
export interface Organisation extends OrganisationSummary {
  website: string | null
  is_partner: boolean
  sort_order: number
  member_count: number
}

export interface OrganisationList {
  total: number
  items: Organisation[]
}

export interface OrganisationListParams {
  partners_only?: boolean
  q?: string
  skip?: number
  limit?: number
}

/**
 * A user's organisation as the register and profile forms send it: a listed organisation
 * (`organisation_id`) or free text (`organisation_other`), never both. `organisation_other`
 * being a string (possibly empty) means "Other…" is selected.
 */
export interface OrganisationChoice {
  organisation_id: number | null
  organisation_other: string | null
}

export function listOrganisations(params: OrganisationListParams = {}): Promise<OrganisationList> {
  return api<OrganisationList>('/api/v1/organisations/', { query: params })
}

/** Organisations (project partners and associated partners): public list, admin create/update. */
import type { components, operations } from '@/types/api-schema'
import { api } from './api'

export type OrganisationType = components['schemas']['OrganisationType']
/** `OrganisationSummary` (embedded in `UserMe`). */
export type OrganisationSummary = components['schemas']['OrganisationSummary']
/** `OrganisationOut` (the public list). */
export type Organisation = components['schemas']['OrganisationOut']
export type OrganisationList = components['schemas']['OrganisationList']
export type OrganisationCreate = components['schemas']['OrganisationCreate']
export type OrganisationUpdate = components['schemas']['OrganisationUpdate']
export type OrganisationListParams = NonNullable<
  operations['list_organisations_api_v1_organisations__get']['parameters']['query']
>

/**
 * A user's organisation as the register and profile forms send it: a listed organisation
 * (`organisation_id`) or free text (`organisation_other`), never both. `organisation_other`
 * being a string (possibly empty) means "Other…" is selected.
 */
export interface OrganisationChoice {
  organisation_id: number | null
  organisation_other: string | null
}

const BASE = '/api/v1/organisations'

export function listOrganisations(params: OrganisationListParams = {}): Promise<OrganisationList> {
  return api<OrganisationList>(`${BASE}/`, { query: { ...params } })
}

export const organisationsService = {
  list: listOrganisations,

  /** Admin. 409 `organisations.name_taken`. */
  create: (payload: OrganisationCreate) =>
    api<Organisation>(`${BASE}/`, { method: 'POST', body: payload }),

  /** Admin; omitted fields are kept, `website: null` clears. 409 `organisations.name_taken`. */
  update: (id: number, changes: OrganisationUpdate) =>
    api<Organisation>(`${BASE}/${id}`, { method: 'PATCH', body: changes }),
}

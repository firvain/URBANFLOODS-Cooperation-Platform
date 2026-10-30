/** Organisations (project partners and associated partners). */
import { api } from './api'

// TODO(gen:types): replace with components['schemas'][...] once generated (`npm run gen:types`).
// Hand-written only because the backend contract is being built concurrently (increment 1j).
export type OrganisationType = 'PP' | 'AP' | 'other'

export interface Organisation {
  id: number
  short_name: string
  name: string
  /** ISO 3166-1 alpha-2. */
  country: string
  type: OrganisationType
}

export interface OrganisationList {
  total: number
  items: Organisation[]
}

export function listOrganisations(): Promise<OrganisationList> {
  return api<OrganisationList>('/api/v1/organisations/')
}

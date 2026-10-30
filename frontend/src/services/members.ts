/** Members directory of the Collaboration Network (`/api/v1/members/*`). */
import { api } from './api'
import type { ExpertiseTag } from './expertise'
import type { OrganisationSummary } from './organisations'

// TODO(gen:types): replace with components['schemas'][...] once generated (`npm run gen:types`).
// Hand-written only because the backend contract is being built concurrently (increment 1n).

/** A member as the directory lists them. `email` is null unless they chose to show it. */
export interface Member {
  id: number
  display_name: string
  organisation: OrganisationSummary | null
  organisation_other: string | null
  /** ISO 3166-1 alpha-2. */
  country: string | null
  bio_excerpt: string | null
  expertise: ExpertiseTag[]
  email: string | null
  created_at: string
}

/** `GET /members/{id}`: the full bio as plain text. */
export interface MemberDetail extends Member {
  bio: string | null
}

/** `GET /members/suggested`: members ranked by expertise they share with the current user. */
export interface SuggestedMember extends Member {
  shared_expertise: number
}

export interface Page<T> {
  total: number
  items: T[]
}

export interface MemberListParams {
  q?: string
  /** Sent as repeated `expertise_ids=` parameters. */
  expertise_ids?: number[]
  country?: string
  organisation_id?: number
  skip?: number
  limit?: number
}

const BASE = '/api/v1/members'

export const membersService = {
  list: (params: MemberListParams = {}) => api<Page<Member>>(`${BASE}/`, { query: params }),

  get: (id: number) => api<MemberDetail>(`${BASE}/${id}`),

  /** Verified users only (401/403 otherwise). */
  suggested: () => api<Page<SuggestedMember>>(`${BASE}/suggested`),
}

/** The organisation a member names: the listed one, else their free text. */
export function memberOrganisation(member: Member): string | null {
  return member.organisation?.name ?? member.organisation_other ?? null
}

/** Members directory of the Collaboration Network (`/api/v1/members/*`). */
import { api } from './api'
import type { components } from '@/types/api-schema'

/** A member as the directory lists them. `email` is null unless they chose to show it;
 * `is_admin` (admin or superadmin) is the only role signal the API exposes. */
export type Member = components['schemas']['MemberOut']

/** `GET /members/{id}`: the full bio as plain text. */
export type MemberDetail = components['schemas']['MemberDetail']

/** `GET /members/suggested`: members ranked by expertise they share with the current user. */
export type SuggestedMember = components['schemas']['SuggestedMember']

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

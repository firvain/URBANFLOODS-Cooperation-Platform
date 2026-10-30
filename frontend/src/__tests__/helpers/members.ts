/** Fixtures for the Collaboration Network contract (`/expertise/`, `/members/`). */
import type { ExpertiseTag } from '@/services/expertise'
import type { Member, MemberDetail, SuggestedMember } from '@/services/members'

const LABELS = [
  'Hydrology',
  'Civil protection',
  'Urban planning',
  'Nature-based solutions',
  'GIS and remote sensing',
  'Policy and governance',
  'Water utilities',
  'Early warning systems',
  'Climate adaptation',
  'Hydraulic modelling',
]

export const EXPERTISE: ExpertiseTag[] = LABELS.map((label, i) => ({
  id: i + 1,
  slug: label.toLowerCase().replace(/[^a-z]+/g, '-'),
  label,
  sort_order: i + 1,
}))

export const EXPERTISE_RESPONSE = { total: EXPERTISE.length, items: EXPERTISE }

export const UOWM = {
  id: 1,
  short_name: 'UOWM',
  name: 'University of Western Macedonia',
  country: 'GR',
  type: 'PP' as const,
}

/** Member `id`: odd ids show their email, every third has free-text organisation. */
export function makeMember(id: number, overrides: Partial<Member> = {}): Member {
  const freeText = id % 3 === 0
  return {
    id,
    display_name: `Member ${id}`,
    organisation: freeText ? null : UOWM,
    organisation_other: freeText ? `Civil Protection Unit ${id}` : null,
    country: 'GR',
    bio_excerpt: `Works on flood management, member ${id}.`,
    expertise: EXPERTISE.slice(0, 2),
    email: id % 2 ? `member${id}@example.org` : null,
    created_at: '2026-10-01T10:00:00Z',
    ...overrides,
  }
}

/** One page of `GET /members/`: `limit` members starting after `skip`, out of `total`. */
export function memberPage(total: number, skip = 0, limit = 24) {
  const count = Math.max(0, Math.min(limit, total - skip))
  return {
    total,
    items: Array.from({ length: count }, (_, i) => makeMember(skip + i + 1)),
  }
}

export function makeMemberDetail(id: number, overrides: Partial<MemberDetail> = {}): MemberDetail {
  return { ...makeMember(id), bio: `Line one about member ${id}.\nLine two.`, ...overrides }
}

export function makeSuggested(id: number, shared: number): SuggestedMember {
  return { ...makeMember(id), shared_expertise: shared }
}

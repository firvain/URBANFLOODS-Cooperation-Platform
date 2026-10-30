import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useOrganisationsStore } from '@/stores/organisations'
import { callsTo, mockApi, ORGANISATIONS, reply } from './helpers/api'
import { PARTNERS, PARTNERS_RESPONSE } from './helpers/organisations'

beforeEach(() => setActivePinia(createPinia()))

describe('organisations store', () => {
  it('caches the partner list and shares an in-flight request', async () => {
    const fetchMock = mockApi({ 'GET /api/v1/organisations/': reply(200, PARTNERS_RESPONSE) })
    const store = useOrganisationsStore()
    await Promise.all([store.fetchPartners(), store.fetchPartners()])
    await store.fetchPartners()
    expect(callsTo(fetchMock, 'GET /api/v1/organisations/')).toHaveLength(1)

    await store.fetchPartners({ force: true })
    expect(callsTo(fetchMock, 'GET /api/v1/organisations/')).toHaveLength(2)
  })

  it('splits the partners into lead, project and associated partners by sort_order', async () => {
    mockApi({ 'GET /api/v1/organisations/': reply(200, PARTNERS_RESPONSE) })
    const store = useOrganisationsStore()
    await store.fetchPartners()
    expect(store.leadPartner?.short_name).toBe('UOWM')
    expect(store.projectPartners.map((o) => o.sort_order)).toEqual(
      PARTNERS.slice(1, 11).map((o) => o.sort_order),
    )
    expect(store.associatedPartners).toHaveLength(11)
    expect(store.partnerCountryCount).toBe(8)
  })

  it('caches the full list for the organisation picker separately', async () => {
    const fetchMock = mockApi({ 'GET /api/v1/organisations/': reply(200, ORGANISATIONS) })
    const store = useOrganisationsStore()
    await store.fetchAll()
    await store.fetchAll()
    const calls = callsTo(fetchMock, 'GET /api/v1/organisations/')
    expect(calls).toHaveLength(1)
    expect(new URL(calls[0]!.url, 'http://x.invalid').searchParams.get('partners_only')).toBeNull()
    expect(store.all).toHaveLength(2)
  })
})

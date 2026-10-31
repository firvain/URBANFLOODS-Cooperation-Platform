import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useAdminStore } from '@/stores/admin'
import { callsTo, mockApi, reply, replyError } from './helpers/api'
import {
  makeAdminUser,
  makeCategory,
  makeExpertise,
  makeOrganisation,
  makeStats,
  makeTag,
  page,
  queryOf,
} from './helpers/admin'
import { useExpertiseStore } from '@/stores/expertise'

beforeEach(() => setActivePinia(createPinia()))

const USERS = 'GET /api/v1/admin/users/'

describe('admin store: dashboard', () => {
  it('fetchStats loads the dashboard counts', async () => {
    const fetchMock = mockApi({ 'GET /api/v1/admin/stats': reply(200, makeStats()) })
    const store = useAdminStore()
    await store.fetchStats()
    expect(callsTo(fetchMock, 'GET /api/v1/admin/stats')).toHaveLength(1)
    expect(store.stats?.users.total).toBe(128)
    expect(store.statsFailed).toBe(false)
  })

  it('fetchStats flags a failure', async () => {
    mockApi({ 'GET /api/v1/admin/stats': replyError(500, 'server.error') })
    const store = useAdminStore()
    await store.fetchStats()
    expect(store.stats).toBeNull()
    expect(store.statsFailed).toBe(true)
  })

  it('clearKnowbaseCache posts, returns the count and reloads the stats', async () => {
    const fetchMock = mockApi({
      'POST /api/v1/admin/knowbase/cache/clear': reply(200, { cleared: 23 }),
      'GET /api/v1/admin/stats': reply(200, makeStats()),
    })
    const store = useAdminStore()
    expect(await store.clearKnowbaseCache()).toBe(23)
    expect(callsTo(fetchMock, 'POST /api/v1/admin/knowbase/cache/clear')).toHaveLength(1)
    expect(callsTo(fetchMock, 'GET /api/v1/admin/stats')).toHaveLength(1)
  })
})

describe('admin store: users', () => {
  it('fetchUsers sends the filters and keeps total and items', async () => {
    const fetchMock = mockApi({ [USERS]: reply(200, page([makeAdminUser()], 41)) })
    const store = useAdminStore()
    await store.fetchUsers({ q: 'nik', role: 'admin', verified: false, skip: 20, limit: 20 })
    const query = queryOf(callsTo(fetchMock, USERS)[0]!.url)
    expect(query.get('q')).toBe('nik')
    expect(query.get('role')).toBe('admin')
    expect(query.get('verified')).toBe('false')
    expect(query.get('skip')).toBe('20')
    expect(store.users.total).toBe(41)
    expect(store.users.items[0]!.display_name).toBe('Nikos')
  })

  it.each([
    ['promote', 'admin', 'POST /api/v1/admin/users/7/promote', { role: 'admin' }],
    ['demote', undefined, 'POST /api/v1/admin/users/7/demote', { role: 'member' }],
    ['ban', undefined, 'POST /api/v1/admin/users/7/ban', { is_active: false }],
    ['unban', undefined, 'POST /api/v1/admin/users/7/unban', { is_active: true }],
    ['trust', undefined, 'POST /api/v1/admin/users/7/trust', { is_trusted: true }],
    ['untrust', undefined, 'POST /api/v1/admin/users/7/untrust', { is_trusted: false }],
  ] as const)('%s calls its endpoint and replaces the row', async (action, to, route, changes) => {
    const updated = makeAdminUser(changes as Partial<ReturnType<typeof makeAdminUser>>)
    const fetchMock = mockApi({
      [USERS]: reply(200, page([makeAdminUser(), makeAdminUser({ id: 8, display_name: 'Ana' })])),
      [route]: reply(200, updated),
    })
    const store = useAdminStore()
    await store.fetchUsers({})
    await store.userAction(7, action, to)
    const calls = callsTo(fetchMock, route)
    expect(calls).toHaveLength(1)
    if (to) expect(queryOf(calls[0]!.url).get('to')).toBe(to)
    expect(store.users.items[0]).toEqual(updated)
    expect(store.users.items[1]!.display_name).toBe('Ana')
  })

  it('promote to superadmin passes to=superadmin', async () => {
    const route = 'POST /api/v1/admin/users/7/promote'
    const fetchMock = mockApi({ [route]: reply(200, makeAdminUser({ role: 'superadmin' })) })
    await useAdminStore().userAction(7, 'promote', 'superadmin')
    expect(queryOf(callsTo(fetchMock, route)[0]!.url).get('to')).toBe('superadmin')
  })

  it('resendVerification posts and leaves the rows alone', async () => {
    const route = 'POST /api/v1/admin/users/7/resend-verification'
    const fetchMock = mockApi({
      [USERS]: reply(200, page([makeAdminUser({ is_verified: false })])),
      [route]: reply(202, { code: 'admin.verification_sent', message: 'Sent' }),
    })
    const store = useAdminStore()
    await store.fetchUsers({})
    await store.resendVerification(7)
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(store.users.items[0]!.is_verified).toBe(false)
  })

  it('an action error propagates and keeps the row', async () => {
    mockApi({
      [USERS]: reply(200, page([makeAdminUser({ role: 'superadmin' })])),
      'POST /api/v1/admin/users/7/demote': replyError(409, 'admin.last_superadmin'),
    })
    const store = useAdminStore()
    await store.fetchUsers({})
    await expect(store.userAction(7, 'demote')).rejects.toMatchObject({
      code: 'admin.last_superadmin',
    })
    expect(store.users.items[0]!.role).toBe('superadmin')
  })
})

describe('admin store: categories', () => {
  const LIST = 'GET /api/v1/categories/'

  it('fetchCategories asks for archived ones too and orders by kind and sort_order', async () => {
    const fetchMock = mockApi({
      [LIST]: reply(
        200,
        page([
          makeCategory({ id: 1, kind: 'forum', sort_order: 1 }),
          makeCategory({ id: 2, kind: 'blog', sort_order: 20 }),
          makeCategory({ id: 3, kind: 'blog', sort_order: 5, is_archived: true }),
        ]),
      ),
    })
    const store = useAdminStore()
    await store.fetchCategories()
    expect(queryOf(callsTo(fetchMock, LIST)[0]!.url).get('include_archived')).toBe('true')
    expect(store.categories.map((c) => c.id)).toEqual([3, 2, 1])
  })

  it('createCategory posts the payload and adds the category', async () => {
    const created = makeCategory({ id: 9, name: 'Early warning', slug: 'early-warning' })
    const fetchMock = mockApi({ 'POST /api/v1/categories/': reply(201, created) })
    const store = useAdminStore()
    const payload = {
      kind: 'blog' as const,
      name: 'Early warning',
      slug: null,
      description: null,
      sort_order: 3,
      admin_only: false,
    }
    await store.createCategory(payload)
    expect(callsTo(fetchMock, 'POST /api/v1/categories/')[0]!.body).toEqual(payload)
    expect(store.categories).toContainEqual(created)
  })

  it('updateCategory patches and replaces the category', async () => {
    const fetchMock = mockApi({
      [LIST]: reply(200, page([makeCategory()])),
      'PATCH /api/v1/categories/2': reply(200, makeCategory({ name: 'NBS' })),
    })
    const store = useAdminStore()
    await store.fetchCategories()
    await store.updateCategory(2, { name: 'NBS' })
    expect(callsTo(fetchMock, 'PATCH /api/v1/categories/2')[0]!.body).toEqual({ name: 'NBS' })
    expect(store.categories[0]!.name).toBe('NBS')
  })

  it('archiveCategory deletes and marks the category archived', async () => {
    const fetchMock = mockApi({
      [LIST]: reply(200, page([makeCategory()])),
      'DELETE /api/v1/categories/2': reply(204),
    })
    const store = useAdminStore()
    await store.fetchCategories()
    await store.archiveCategory(2)
    expect(callsTo(fetchMock, 'DELETE /api/v1/categories/2')).toHaveLength(1)
    expect(store.categories[0]!.is_archived).toBe(true)
  })
})

describe('admin store: organisations', () => {
  const LIST = 'GET /api/v1/organisations/'

  it('fetchOrganisations loads up to 200, partners first by type and sort_order', async () => {
    const fetchMock = mockApi({
      [LIST]: reply(
        200,
        page([
          makeOrganisation({ id: 1, name: 'Zeta', type: 'other', is_partner: false }),
          makeOrganisation({ id: 2, type: 'AP', sort_order: 1 }),
          makeOrganisation({ id: 3, type: 'PP', sort_order: 9 }),
        ]),
      ),
    })
    const store = useAdminStore()
    await store.fetchOrganisations()
    expect(queryOf(callsTo(fetchMock, LIST)[0]!.url).get('limit')).toBe('200')
    expect(store.organisations.map((o) => o.id)).toEqual([3, 2, 1])
  })

  it('fetchOrganisations flags a failure', async () => {
    mockApi({ [LIST]: replyError(500, 'server.error') })
    const store = useAdminStore()
    await store.fetchOrganisations()
    expect(store.organisationsFailed).toBe(true)
  })

  it('createOrganisation posts and adds; updateOrganisation patches and replaces', async () => {
    const created = makeOrganisation({ id: 9, name: 'New org', short_name: 'NO' })
    const fetchMock = mockApi({
      'POST /api/v1/organisations/': reply(201, created),
      'PATCH /api/v1/organisations/9': reply(200, { ...created, short_name: 'NEW' }),
    })
    const store = useAdminStore()
    const payload = {
      name: 'New org',
      short_name: 'NO',
      country: 'GR',
      type: 'PP' as const,
      website: null,
      is_partner: true,
      sort_order: 1,
    }
    await store.createOrganisation(payload)
    expect(callsTo(fetchMock, 'POST /api/v1/organisations/')[0]!.body).toEqual(payload)
    expect(store.organisations).toContainEqual(created)
    await store.updateOrganisation(9, { short_name: 'NEW' })
    expect(store.organisations.map((o) => o.short_name)).toEqual(['NEW'])
  })
})

describe('admin store: expertise areas', () => {
  const LIST = 'GET /api/v1/expertise/'

  it('fetchExpertise asks for deactivated areas too, in sort_order', async () => {
    const fetchMock = mockApi({
      [LIST]: reply(
        200,
        page([
          makeExpertise({ id: 2, sort_order: 5, is_active: false }),
          makeExpertise({ id: 1, sort_order: 1 }),
        ]),
      ),
    })
    const store = useAdminStore()
    await store.fetchExpertise()
    expect(queryOf(callsTo(fetchMock, LIST)[0]!.url).get('include_inactive')).toBe('true')
    expect(store.expertise.map((e) => e.id)).toEqual([1, 2])
  })

  it('updateExpertise patches, replaces the area and refreshes a loaded vocabulary', async () => {
    const fetchMock = mockApi({
      [LIST]: reply(200, page([makeExpertise()])),
      'PATCH /api/v1/expertise/1': reply(200, makeExpertise({ is_active: false })),
    })
    const vocabulary = useExpertiseStore()
    await vocabulary.fetch()
    const store = useAdminStore()
    await store.fetchExpertise()
    const before = callsTo(fetchMock, LIST).length
    await store.updateExpertise(1, { is_active: false })
    expect(callsTo(fetchMock, 'PATCH /api/v1/expertise/1')[0]!.body).toEqual({ is_active: false })
    expect(store.expertise[0]!.is_active).toBe(false)
    expect(callsTo(fetchMock, LIST).length).toBe(before + 1)
  })

  it('createExpertise posts the payload and adds the area', async () => {
    const created = makeExpertise({ id: 9, slug: 'drones', label: 'Drones' })
    const fetchMock = mockApi({ 'POST /api/v1/expertise/': reply(201, created) })
    const store = useAdminStore()
    await store.createExpertise({ label: 'Drones', slug: null, sort_order: 0 })
    expect(callsTo(fetchMock, 'POST /api/v1/expertise/')[0]!.body).toEqual({
      label: 'Drones',
      slug: null,
      sort_order: 0,
    })
    expect(store.expertise).toContainEqual(created)
  })
})

describe('admin store: tags', () => {
  const LIST = 'GET /api/v1/tags/'

  it('fetchTags sends the search and page', async () => {
    const fetchMock = mockApi({ [LIST]: reply(200, page([makeTag()], 60)) })
    const store = useAdminStore()
    await store.fetchTags({ q: 'flo', skip: 50, limit: 50 })
    const query = queryOf(callsTo(fetchMock, LIST)[0]!.url)
    expect(query.get('q')).toBe('flo')
    expect(query.get('skip')).toBe('50')
    expect(query.get('sort')).toBe('name')
    expect(store.tags.total).toBe(60)
  })

  it('mergeTag posts the target, drops the source and updates the target', async () => {
    const fetchMock = mockApi({
      [LIST]: reply(
        200,
        page([makeTag(), makeTag({ id: 4, name: 'floods', slug: 'floods', usage_count: 2 })]),
      ),
      'POST /api/v1/tags/4/merge': reply(200, makeTag({ usage_count: 14 })),
    })
    const store = useAdminStore()
    await store.fetchTags({})
    await store.mergeTag(4, 3)
    expect(callsTo(fetchMock, 'POST /api/v1/tags/4/merge')[0]!.body).toEqual({ target_id: 3 })
    expect(store.tags.items.map((t) => t.id)).toEqual([3])
    expect(store.tags.items[0]!.usage_count).toBe(14)
    expect(store.tags.total).toBe(1)
  })

  it('deleteTag deletes and drops the tag', async () => {
    const fetchMock = mockApi({
      [LIST]: reply(200, page([makeTag({ usage_count: 0 })])),
      'DELETE /api/v1/tags/3': reply(204),
    })
    const store = useAdminStore()
    await store.fetchTags({})
    await store.deleteTag(3)
    expect(callsTo(fetchMock, 'DELETE /api/v1/tags/3')).toHaveLength(1)
    expect(store.tags.items).toHaveLength(0)
  })
})

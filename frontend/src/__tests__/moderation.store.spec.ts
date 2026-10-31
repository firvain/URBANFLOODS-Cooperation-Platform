import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useModerationStore } from '@/stores/moderation'
import { callsTo, deferred, jsonResponse, mockApi, reply, replyError } from './helpers/api'
import { makeLogEntry, makeQueueItem, makeReport, page, queryOf } from './helpers/admin'

beforeEach(() => setActivePinia(createPinia()))

const QUEUE = 'GET /api/v1/moderation/queue/'
const REPORTS = 'GET /api/v1/reports/'
const LOG = 'GET /api/v1/moderation/log/'

const result = (status: string, id = 12, type = 'thread') => ({
  content_type: type,
  id,
  status,
  hidden_reason: status === 'hidden' ? 'admin' : null,
  published_at: null,
  deleted_at: null,
  author_trusted: true,
})

describe('moderation store: queue', () => {
  it('fetchQueue sends the page and keeps total and items', async () => {
    const fetchMock = mockApi({ [QUEUE]: reply(200, page([makeQueueItem()], 30)) })
    const store = useModerationStore()
    await store.fetchQueue({ skip: 20, limit: 20 })
    expect(queryOf(callsTo(fetchMock, QUEUE)[0]!.url).get('skip')).toBe('20')
    expect(store.queue.total).toBe(30)
    expect(store.queue.items).toHaveLength(1)
  })

  it('approve removes the item before the server answers', async () => {
    const held = deferred<Response>()
    const fetchMock = mockApi({
      [QUEUE]: reply(
        200,
        page([makeQueueItem(), makeQueueItem({ id: 12, content_type: 'thread' })]),
      ),
      'POST /api/v1/moderation/post/11/approve': () => held.promise,
    })
    const store = useModerationStore()
    await store.fetchQueue({})
    const pending = store.approve(store.queue.items[0]!)
    expect(store.queue.items.map((i) => i.id)).toEqual([12])
    expect(store.queue.total).toBe(1)
    held.resolve(jsonResponse(result('published', 11, 'post')))
    await pending
    expect(callsTo(fetchMock, 'POST /api/v1/moderation/post/11/approve')).toHaveLength(1)
    expect(store.queue.items.map((i) => i.id)).toEqual([12])
  })

  it('approve puts the item back when the server refuses', async () => {
    mockApi({
      [QUEUE]: reply(200, page([makeQueueItem()])),
      'POST /api/v1/moderation/post/11/approve': replyError(409, 'moderation.invalid_transition'),
    })
    const store = useModerationStore()
    await store.fetchQueue({})
    await expect(store.approve(store.queue.items[0]!)).rejects.toMatchObject({
      code: 'moderation.invalid_transition',
    })
    expect(store.queue.items.map((i) => i.id)).toEqual([11])
    expect(store.queue.total).toBe(1)
  })

  it('reject sends the reason and removes the item', async () => {
    const route = 'POST /api/v1/moderation/thread/12/reject'
    const fetchMock = mockApi({
      [QUEUE]: reply(200, page([makeQueueItem({ id: 12, content_type: 'thread' })])),
      [route]: reply(200, result('hidden')),
    })
    const store = useModerationStore()
    await store.fetchQueue({})
    await store.reject(store.queue.items[0]!, 'Off-topic advert')
    expect(callsTo(fetchMock, route)[0]!.body).toEqual({ reason: 'Off-topic advert' })
    expect(store.queue.items).toHaveLength(0)
  })

  it('reject without a reason sends reason null', async () => {
    const route = 'POST /api/v1/moderation/post/11/reject'
    const fetchMock = mockApi({ [route]: reply(200, result('hidden', 11, 'post')) })
    await useModerationStore().reject(makeQueueItem(), '   ')
    expect(callsTo(fetchMock, route)[0]!.body).toEqual({ reason: null })
  })
})

describe('moderation store: reports', () => {
  it('fetchReports sends status and content_type', async () => {
    const fetchMock = mockApi({ [REPORTS]: reply(200, page([makeReport()], 3)) })
    const store = useModerationStore()
    await store.fetchReports({ status: 'open', content_type: 'thread', skip: 0, limit: 20 })
    const query = queryOf(callsTo(fetchMock, REPORTS)[0]!.url)
    expect(query.get('status')).toBe('open')
    expect(query.get('content_type')).toBe('thread')
    expect(store.reports.total).toBe(3)
  })

  it.each([
    ['resolveReport', 'resolve', 'resolved'],
    ['dismissReport', 'dismiss', 'dismissed'],
  ] as const)('%s updates the report status', async (method, path, status) => {
    const route = `POST /api/v1/reports/31/${path}`
    const fetchMock = mockApi({
      [REPORTS]: reply(200, page([makeReport()])),
      [route]: reply(200, makeReport({ status, resolver: { id: 1, display_name: 'Ada' } })),
    })
    const store = useModerationStore()
    await store.fetchReports({})
    await store[method](31)
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(store.reports.items[0]!.status).toBe(status)
  })

  it('contentAction hide sends the reason and updates every report of that content', async () => {
    const route = 'POST /api/v1/moderation/thread/12/hide'
    const fetchMock = mockApi({
      [REPORTS]: reply(200, page([makeReport(), makeReport({ id: 32 })])),
      [route]: reply(200, result('hidden')),
    })
    const store = useModerationStore()
    await store.fetchReports({})
    await store.contentAction('thread', 12, 'hide', 'Spam')
    expect(callsTo(fetchMock, route)[0]!.body).toEqual({ reason: 'Spam' })
    expect(store.reports.items.map((r) => r.content?.status)).toEqual(['hidden', 'hidden'])
  })

  it.each(['unhide', 'delete', 'restore'] as const)(
    'contentAction %s posts without a body',
    async (action) => {
      const route = `POST /api/v1/moderation/thread/12/${action}`
      const fetchMock = mockApi({ [route]: reply(200, result('published')) })
      await useModerationStore().contentAction('thread', 12, action)
      expect(callsTo(fetchMock, route)).toHaveLength(1)
      expect(callsTo(fetchMock, route)[0]!.body).toBeUndefined()
    },
  )
})

describe('moderation store: log', () => {
  it('fetchLog sends the filters and keeps the page', async () => {
    const fetchMock = mockApi({ [LOG]: reply(200, page([makeLogEntry()], 75)) })
    const store = useModerationStore()
    await store.fetchLog({ action: 'admin.', actor_id: 4, target_type: 'user', skip: 50 })
    const query = queryOf(callsTo(fetchMock, LOG)[0]!.url)
    expect(query.get('action')).toBe('admin.')
    expect(query.get('actor_id')).toBe('4')
    expect(query.get('target_type')).toBe('user')
    expect(query.get('skip')).toBe('50')
    expect(store.log.total).toBe(75)
  })

  it('a slower earlier response does not overwrite a newer one', async () => {
    const first = deferred<Response>()
    let calls = 0
    mockApi({
      [LOG]: () =>
        ++calls === 1 ? first.promise : jsonResponse(page([makeLogEntry({ id: 2 })], 1)),
    })
    const store = useModerationStore()
    const older = store.fetchLog({ action: 'auth.' })
    await store.fetchLog({ action: 'admin.' })
    first.resolve(jsonResponse(page([makeLogEntry({ id: 1 })], 1)))
    await older
    expect(store.log.items.map((e) => e.id)).toEqual([2])
  })
})

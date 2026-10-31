import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { SEARCH_PAGE_SIZE } from '@/constants/search'
import { useSearchStore } from '@/stores/search'
import { callsTo, deferred, jsonResponse, mockApi, reply, replyError } from './helpers/api'
import { paramsOf } from './helpers/blog'
import { SEARCH, hitPage, hitPages, makeHit } from './helpers/search'

beforeEach(() => {
  setActivePinia(createPinia())
})

const lastParams = (fetchMock: ReturnType<typeof mockApi>) =>
  paramsOf(callsTo(fetchMock, SEARCH).at(-1)!.url)

describe('search store', () => {
  it('starts empty', () => {
    const store = useSearchStore()
    expect(store.query).toBe('')
    expect(store.type).toBe('all')
    expect(store.locale).toBe('')
    expect(store.page).toBe(1)
    expect(store.results).toEqual([])
    expect(store.total).toBe(0)
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })

  it('sends q (trimmed), type, skip and limit, and keeps the page of hits', async () => {
    const fetchMock = mockApi({ [SEARCH]: hitPages(45) })
    const store = useSearchStore()
    await store.search({ query: '  rain gardens ', type: 'posts', page: 3 })
    const params = lastParams(fetchMock)
    expect(params.get('q')).toBe('rain gardens')
    expect(params.get('type')).toBe('posts')
    expect(params.get('skip')).toBe(String(2 * SEARCH_PAGE_SIZE))
    expect(params.get('limit')).toBe(String(SEARCH_PAGE_SIZE))
    expect(params.has('locale')).toBe(false)
    expect(store.total).toBe(45)
    expect(store.results).toHaveLength(5)
    expect(store.query).toBe('  rain gardens ')
    expect(store.page).toBe(3)
    expect(store.loading).toBe(false)
  })

  it('sends the locale filter when set', async () => {
    const fetchMock = mockApi({ [SEARCH]: hitPages(1) })
    const store = useSearchStore()
    await store.search({ query: 'flood', locale: 'el' })
    expect(lastParams(fetchMock).get('locale')).toBe('el')
    expect(lastParams(fetchMock).get('type')).toBe('all')
  })

  it('does not call the API for a query shorter than 2 characters, and clears the results', async () => {
    const fetchMock = mockApi({ [SEARCH]: hitPages(3) })
    const store = useSearchStore()
    await store.search({ query: 'flood' })
    expect(store.total).toBe(3)
    await store.search({ query: ' a ' })
    expect(callsTo(fetchMock, SEARCH)).toHaveLength(1)
    expect(store.results).toEqual([])
    expect(store.total).toBe(0)
    expect(store.tooShort).toBe(true)
  })

  it('ignores a slow earlier response that arrives after a newer one', async () => {
    const slow = deferred<Response>()
    let calls = 0
    mockApi({
      [SEARCH]: () => {
        calls += 1
        return calls === 1 ? slow.promise : jsonResponse({ total: 1, items: [makeHit(7)] })
      },
    })
    const store = useSearchStore()
    const first = store.search({ query: 'flood' })
    await store.search({ query: 'drought' })
    slow.resolve(jsonResponse(hitPage(20)))
    await first
    expect(store.total).toBe(1)
    expect(store.results.map((hit) => hit.id)).toEqual([7])
    expect(store.loading).toBe(false)
  })

  it('a too-short query also discards a response still in flight', async () => {
    const slow = deferred<Response>()
    mockApi({ [SEARCH]: () => slow.promise })
    const store = useSearchStore()
    const first = store.search({ query: 'flood' })
    await store.search({ query: 'f' })
    slow.resolve(jsonResponse(hitPage(20)))
    await first
    expect(store.results).toEqual([])
    expect(store.loading).toBe(false)
  })

  it('records the error code and clears the results on failure', async () => {
    mockApi({ [SEARCH]: hitPages(3) })
    const store = useSearchStore()
    await store.search({ query: 'flood' })
    mockApi({ [SEARCH]: replyError(429, 'rate_limited') })
    await store.search({ query: 'floods' })
    expect(store.error).toBe('rate_limited')
    expect(store.results).toEqual([])
    expect(store.total).toBe(0)
    expect(store.loading).toBe(false)
  })

  it('clears the error on the next successful search', async () => {
    mockApi({ [SEARCH]: replyError(500, 'server.error') })
    const store = useSearchStore()
    await store.search({ query: 'flood' })
    expect(store.error).toBe('server.error')
    mockApi({ [SEARCH]: reply(200, hitPage(2)) })
    await store.search()
    expect(store.error).toBeNull()
    expect(store.total).toBe(2)
  })
})

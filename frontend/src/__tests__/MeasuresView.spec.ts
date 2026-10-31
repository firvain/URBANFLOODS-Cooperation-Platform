import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import MeasuresView from '@/views/MeasuresView.vue'
import { KB_SEARCH_DEBOUNCE_MS as SEARCH_DEBOUNCE_MS } from '@/constants/knowbase'
import i18n from '@/i18n'
import { callsTo, deferred, mockApi, replyError, type Handler } from './helpers/api'
import {
  MEASURES,
  kbReply,
  makeMeasure,
  measureLookupRoutes,
  measurePages,
  paramsOf,
} from './helpers/knowbase'
import { mountWithApp, unmountAll } from './helpers/mount'
import { clickOption, enterOption, openSelect } from './helpers/select'

const t = i18n.global.t

afterEach(() => {
  vi.useRealTimers()
  unmountAll()
})

function routes(measures: Handler = measurePages(60)) {
  return { [MEASURES]: measures, ...measureLookupRoutes() }
}

const mountMeasures = (path = '/knowbase/measures') => mountWithApp(MeasuresView, { path })
const cards = (wrapper: VueWrapper) => wrapper.findAll('[data-testid="measure-card"]')
const lastQuery = (fetchMock: ReturnType<typeof mockApi>) =>
  paramsOf(callsTo(fetchMock, MEASURES).at(-1)!.url)

describe('MeasuresView', () => {
  it('has a focusable h1 and lists 24 measure cards with a count', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountMeasures()
    expect(wrapper.find('h1').text()).toBe(t('knowbase.measures.title'))
    expect(wrapper.find('h1').attributes('tabindex')).toBe('-1')
    expect(cards(wrapper)).toHaveLength(24)
    expect(wrapper.find('[data-testid="kb-count"]').text()).toBe(
      t('knowbase.measures.count', { count: 60 }, 60),
    )
    const query = lastQuery(fetchMock)
    expect(query.get('skip')).toBe('0')
    expect(query.get('limit')).toBe('24')
    expect(query.has('q')).toBe(false)
  })

  it('cards show the photo (alt = title), title linked to the detail, category and 3 keywords', async () => {
    mockApi(routes())
    const { wrapper } = await mountMeasures()
    const first = cards(wrapper)[0]!
    const img = first.find('img')
    expect(img.attributes('alt')).toBe('Measure 1')
    expect(img.attributes('src')).toBe('https://knowbase.test/static/measures/photos/m1.jpg')
    expect(first.find('a[href="/knowbase/measures/1"]').text()).toBe('Measure 1')
    expect(first.find('[data-testid="measure-category"]').text()).toBe('Nature-Based Solutions')
    const keywords = first.findAll('[data-testid="measure-keyword"]')
    expect(keywords.map((k) => k.text())).toEqual(['Green roof', 'Retention', 'Runoff'])
  })

  it('a card without a photo has no image', async () => {
    mockApi(routes(kbReply({ total: 1, items: [makeMeasure(1, { photo_url: null })] })))
    const { wrapper } = await mountMeasures()
    expect(cards(wrapper)[0]!.find('img').exists()).toBe(false)
  })

  it('reads the filters and page from the URL into the request', async () => {
    const fetchMock = mockApi(routes())
    await mountMeasures(
      '/knowbase/measures?q=green&category_id=2&level_of_application_ids=1&level_of_application_ids=3&scale_ids=2&keyword_ids=5&page=2',
    )
    const query = lastQuery(fetchMock)
    expect(query.get('q')).toBe('green')
    expect(query.get('category_id')).toBe('2')
    expect(query.getAll('level_of_application_ids')).toEqual(['1', '3'])
    expect(query.getAll('scale_ids')).toEqual(['2'])
    expect(query.getAll('keyword_ids')).toEqual(['5'])
    expect(query.get('skip')).toBe('24')
  })

  it('debounces the search, then puts q in the URL and refetches', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountMeasures()
    await wrapper.find('input[type="search"]').setValue('roof')
    vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS)
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ q: 'roof' })
    expect(lastQuery(fetchMock).get('q')).toBe('roof')
  })

  it('levels of application multi-select writes repeated ids to the URL and refetches', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountMeasures()
    await openSelect(wrapper, t('knowbase.measures.filters.levels'))
    await clickOption('Protection')
    await clickOption('Preparedness')
    await flushPromises()
    expect(router.currentRoute.value.query.level_of_application_ids).toEqual(['1', '2'])
    expect(router.currentRoute.value.fullPath).toContain(
      'level_of_application_ids=1&level_of_application_ids=2',
    )
    expect(lastQuery(fetchMock).getAll('level_of_application_ids')).toEqual(['1', '2'])
  })

  it('category select filters by category_id', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountMeasures()
    await openSelect(wrapper, t('knowbase.measures.filters.category'))
    await enterOption('Hybrid')
    expect(router.currentRoute.value.query.category_id).toBe('3')
    expect(lastQuery(fetchMock).get('category_id')).toBe('3')
  })

  it('paginates 24 per page: next page sets page=2 and skip=24', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountMeasures()
    await wrapper.find('[data-slot="next"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.page).toBe('2')
    expect(lastQuery(fetchMock).get('skip')).toBe('24')
    expect(cards(wrapper)[0]!.find('h2').text()).toBe('Measure 25')
  })

  it('shows skeletons while loading', async () => {
    const pending = deferred<Response>()
    mockApi(routes(() => pending.promise))
    const { wrapper } = await mountMeasures()
    expect(wrapper.find('[data-testid="kb-loading"]').exists()).toBe(true)
    pending.resolve(kbReply({ total: 0, items: [] })({} as never) as Response)
    await flushPromises()
    expect(wrapper.find('[data-testid="kb-loading"]').exists()).toBe(false)
  })

  it('shows an empty state with a way to clear the filters', async () => {
    mockApi(routes(kbReply({ total: 0, items: [] })))
    const { wrapper, router } = await mountMeasures('/knowbase/measures?category_id=1')
    expect(cards(wrapper)).toHaveLength(0)
    expect(wrapper.text()).toContain(t('knowbase.measures.empty'))
    const clear = wrapper.findAll('button').find((b) => b.text() === t('knowbase.clearFilters'))
    await clear!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({})
  })

  it('shows an error with a retry button that fetches again', async () => {
    let calls = 0
    const fetchMock = mockApi(
      routes((r) =>
        ++calls === 1 ? replyError(502, 'knowbase.upstream_error')(r) : measurePages(60)(r),
      ),
    )
    const { wrapper } = await mountMeasures()
    expect(wrapper.text()).toContain(t('knowbase.measures.loadError'))
    const retry = wrapper.findAll('button').find((b) => b.text() === t('knowbase.retry'))
    await retry!.trigger('click')
    await flushPromises()
    expect(callsTo(fetchMock, MEASURES)).toHaveLength(2)
    expect(cards(wrapper)).toHaveLength(24)
  })
})

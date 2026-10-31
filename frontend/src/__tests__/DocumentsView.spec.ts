import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import DocumentsView from '@/views/DocumentsView.vue'
import i18n from '@/i18n'
import { callsTo, mockApi, type Handler } from './helpers/api'
import {
  COUNTRIES,
  DOCUMENTS,
  documentLookupRoutes,
  documentPages,
  kbReply,
  makeDocument,
  paramsOf,
} from './helpers/knowbase'
import { mountWithApp, unmountAll } from './helpers/mount'
import { clickOption, enterOption, openSelect } from './helpers/select'

const t = i18n.global.t

afterEach(() => unmountAll())

function routes(documents: Handler = documentPages(60)) {
  return { [DOCUMENTS]: documents, ...documentLookupRoutes() }
}

const mountDocuments = (path = '/knowbase/documents') => mountWithApp(DocumentsView, { path })
const cards = (wrapper: VueWrapper) => wrapper.findAll('[data-testid="document-card"]')
const lastQuery = (fetchMock: ReturnType<typeof mockApi>) =>
  paramsOf(callsTo(fetchMock, DOCUMENTS).at(-1)!.url)

describe('DocumentsView', () => {
  it('lists 24 documents with flag, country, level, subject and a link to the detail', async () => {
    const items = [makeDocument(1), makeDocument(2, { country: 'IT' })]
    mockApi(routes(kbReply({ total: 2, items })))
    const { wrapper } = await mountDocuments()
    expect(wrapper.find('h1').text()).toBe(t('knowbase.documents.title'))
    const [first, second] = cards(wrapper)
    expect(first!.find('a[href="/knowbase/documents/1"]').text()).toBe(
      'Law 1 on flood risk management',
    )
    expect(first!.find('span.fi.fi-gr').exists()).toBe(true)
    expect(first!.text()).toContain('Greece')
    expect(first!.text()).toContain('National')
    expect(first!.text()).toContain('Floods management')
    expect(second!.find('span.fi.fi-it').exists()).toBe(true)
    expect(second!.text()).toContain('Italy')
  })

  it('paginates 24 per page', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountDocuments()
    expect(cards(wrapper)).toHaveLength(24)
    expect(lastQuery(fetchMock).get('limit')).toBe('24')
    await wrapper.find('[data-slot="next"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.page).toBe('2')
    expect(lastQuery(fetchMock).get('skip')).toBe('24')
  })

  it('reads the filters from the URL into the request', async () => {
    const fetchMock = mockApi(routes())
    await mountDocuments(
      '/knowbase/documents?q=flood&country=GR&level_id=1&subject_id=2&keyword_ids=7&keyword_ids=8',
    )
    const query = lastQuery(fetchMock)
    expect(query.get('q')).toBe('flood')
    expect(query.get('country')).toBe('GR')
    expect(query.get('level_id')).toBe('1')
    expect(query.get('subject_id')).toBe('2')
    expect(query.getAll('keyword_ids')).toEqual(['7', '8'])
  })

  it('country select lists the KNOWBASE countries and filters by country', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountDocuments()
    await openSelect(wrapper, t('knowbase.documents.filters.country'))
    expect(document.querySelectorAll('[role="option"]')).toHaveLength(COUNTRIES.length + 1)
    await enterOption('Italy')
    expect(router.currentRoute.value.query.country).toBe('IT')
    expect(lastQuery(fetchMock).get('country')).toBe('IT')
  })

  it('keywords multi-select writes repeated keyword_ids', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountDocuments()
    await openSelect(wrapper, t('knowbase.filters.keywords'))
    await clickOption('Flood risk')
    await clickOption('Spatial planning')
    await flushPromises()
    expect(router.currentRoute.value.query.keyword_ids).toEqual(['7', '8'])
    expect(lastQuery(fetchMock).getAll('keyword_ids')).toEqual(['7', '8'])
  })

  it('shows an empty state', async () => {
    mockApi(routes(kbReply({ total: 0, items: [] })))
    const { wrapper } = await mountDocuments('/knowbase/documents?country=AL')
    expect(wrapper.text()).toContain(t('knowbase.documents.empty'))
  })
})

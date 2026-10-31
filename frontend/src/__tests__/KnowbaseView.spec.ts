import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import KnowbaseView from '@/views/KnowbaseView.vue'
import i18n from '@/i18n'
import { EXTERNAL_LINKS } from '@/constants/links'
import { callsTo, mockApi, replyError } from './helpers/api'
import {
  COUNTRIES,
  DOCUMENTS,
  KB,
  MEASURES,
  kbReply,
  paramsOf,
  type CacheHeader,
} from './helpers/knowbase'
import { mountWithApp, unmountAll } from './helpers/mount'
import { enterOption, openSelect } from './helpers/select'

const t = i18n.global.t

afterEach(() => unmountAll())

function routes(measures: CacheHeader = 'miss', documents: CacheHeader = 'hit') {
  return {
    [MEASURES]: kbReply({ total: 120, items: [] }, measures),
    [DOCUMENTS]: kbReply({ total: 345, items: [] }, documents),
    [`GET ${KB}/lookups/countries`]: kbReply(COUNTRIES),
  }
}

const banner = () => document.querySelector('[data-testid="knowbase-status"]')

describe('KnowbaseView', () => {
  it('has a focusable h1, an intro and two cards with counts from the list totals', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountWithApp(KnowbaseView, { path: '/knowbase' })
    expect(wrapper.find('h1').text()).toBe(t('knowbase.title'))
    expect(wrapper.find('h1').attributes('tabindex')).toBe('-1')
    expect(wrapper.text()).toContain(t('knowbase.intro'))

    const measures = wrapper.find('[data-testid="kb-card-measures"]')
    expect(measures.find('a[href="/knowbase/measures"]').exists()).toBe(true)
    expect(measures.text()).toContain(t('knowbase.measures.title'))
    expect(measures.text()).toContain(t('knowbase.measures.count', { count: 120 }, 120))
    expect(t('knowbase.measures.count', { count: 120 }, 120)).toBe('120 measures')

    const documents = wrapper.find('[data-testid="kb-card-documents"]')
    expect(documents.find('a[href="/knowbase/documents"]').exists()).toBe(true)
    expect(documents.text()).toContain(t('knowbase.documents.title'))
    expect(t('knowbase.documents.title')).toBe('Legislation and policies')
    expect(documents.text()).toContain(t('knowbase.documents.count', { count: 345 }, 345))

    for (const route of [MEASURES, DOCUMENTS]) {
      const calls = callsTo(fetchMock, route)
      expect(calls).toHaveLength(1)
      expect(paramsOf(calls[0]!.url).get('limit')).toBe('1')
    }
    expect(banner()).toBeNull()
  })

  it('Policy Toolkit: a country select links to the filtered legislation and to the measures', async () => {
    mockApi(routes())
    const { wrapper } = await mountWithApp(KnowbaseView, { path: '/knowbase' })
    const toolkit = wrapper.find('[data-testid="policy-toolkit"]')
    expect(toolkit.find('h2').text()).toBe(t('knowbase.toolkit.title'))
    expect(toolkit.text()).toContain(t('knowbase.toolkit.timelineNote'))
    expect(t('knowbase.toolkit.timelineNote')).toBe(
      'Short/mid/long-term filtering will follow once WP3 adds it to the KNOWBASE.',
    )
    expect(toolkit.find('a[href="/knowbase/measures"]').exists()).toBe(true)

    await openSelect(wrapper, t('knowbase.toolkit.country'))
    const options = Array.from(document.querySelectorAll('[role="option"]'))
    expect(options).toHaveLength(COUNTRIES.length + 1)
    await enterOption('Greece')
    await flushPromises()
    const link = toolkit.find('a[href="/knowbase/documents?country=GR"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain(t('knowbase.toolkit.documentsFor', { country: 'Greece' }))
  })

  it('shows a warning banner when a list answers 503 (no data available)', async () => {
    mockApi({
      ...routes(),
      [MEASURES]: replyError(503, 'knowbase.unavailable'),
      [DOCUMENTS]: replyError(503, 'knowbase.unavailable'),
    })
    await mountWithApp(KnowbaseView, { path: '/knowbase' })
    expect(banner()).not.toBeNull()
    expect(banner()!.textContent).toContain(t('knowbase.status.unavailable'))
    expect(t('knowbase.status.unavailable')).toBe(
      'The KNOWBASE is temporarily unreachable; no data available.',
    )
  })

  it('shows a warning banner when a list answers from a stale cache', async () => {
    mockApi(routes('stale', 'hit'))
    const { wrapper } = await mountWithApp(KnowbaseView, { path: '/knowbase' })
    expect(banner()).not.toBeNull()
    expect(banner()!.textContent).toContain(t('knowbase.status.stale'))
    expect(t('knowbase.status.stale')).toBe(
      'The KNOWBASE is temporarily unreachable; showing cached data.',
    )
    // Cached counts are still shown.
    expect(wrapper.text()).toContain(t('knowbase.measures.count', { count: 120 }, 120))
  })

  it('links out to the KNOWBASE in a new tab, announced', async () => {
    mockApi(routes())
    const { wrapper } = await mountWithApp(KnowbaseView, { path: '/knowbase' })
    const link = wrapper.find(`a[href="${EXTERNAL_LINKS.knowbase}"]`)
    expect(link.exists()).toBe(true)
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toContain('noopener')
    expect(link.find('.sr-only').text()).toBe(t('a11y.opensInNewTab'))
  })
})

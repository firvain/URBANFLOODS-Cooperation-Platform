import { afterEach, describe, expect, it } from 'vitest'

import MeasureDetailView from '@/views/MeasureDetailView.vue'
import i18n from '@/i18n'
import { callsTo, mockApi, replyError, type Handler } from './helpers/api'
import { KB, kbReply, makeMeasure, makeMention } from './helpers/knowbase'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const MEASURE = `GET ${KB}/measures/7`
const MENTIONS = `GET ${KB}/measure/7/mentions/`

afterEach(() => unmountAll())

function routes(
  mentions: Handler = kbReply({ total: 2, items: [makeMention(1), makeMention(2)] }),
) {
  return {
    [MEASURE]: kbReply(
      makeMeasure(7, {
        levels_of_application: [
          { id: 1, code: 'protection', label_en: 'Protection', label_local: null },
          { id: 2, code: 'preparedness', label_en: 'Preparedness', label_local: null },
        ],
      }),
    ),
    [MENTIONS]: mentions,
  }
}

const mountDetail = () => mountWithApp(MeasureDetailView, { path: '/knowbase/measures/7' })
const mentions = () => document.querySelector('[data-testid="kb-mentions"]')

describe('MeasureDetailView', () => {
  it('renders the measure fields', async () => {
    mockApi(routes())
    const { wrapper } = await mountDetail()
    const h1 = wrapper.find('h1')
    expect(h1.text()).toBe('Measure 7')
    expect(h1.attributes('tabindex')).toBe('-1')
    const local = wrapper.find('[data-testid="title-local"]')
    expect(local.text()).toBe('Μέτρο 7')
    expect(local.attributes('lang')).toBe('')
    const text = wrapper.text()
    for (const value of [
      'Nature-Based Solutions',
      'Protection',
      'Preparedness',
      'Local',
      'Description of measure 7.',
      'Resources for measure 7.',
      'Benefits of measure 7.',
      'Constraints of measure 7.',
      t('knowbase.measures.fields.resources'),
      t('knowbase.measures.fields.benefits'),
      t('knowbase.measures.fields.constraints'),
    ]) {
      expect(text).toContain(value)
    }
    const keywords = wrapper.findAll('[data-testid="kb-keyword"]').map((k) => k.text())
    expect(keywords).toEqual(['Green roof', 'Retention', 'Runoff', 'Stormwater', 'Urban'])
  })

  it('shows the photo with alt = title and the photo credit', async () => {
    mockApi(routes())
    const { wrapper } = await mountDetail()
    const img = wrapper.find('figure img')
    expect(img.attributes('alt')).toBe('Measure 7')
    expect(img.attributes('src')).toBe('https://knowbase.test/static/measures/photos/m7.jpg')
    expect(wrapper.find('figcaption').text()).toBe(
      t('knowbase.measures.photoCredit', { source: 'Municipality of Kozani' }),
    )
  })

  it('links back to the list and out to the KNOWBASE', async () => {
    mockApi(routes())
    const { wrapper } = await mountDetail()
    expect(wrapper.find('a[href="/knowbase/measures"]').text()).toContain(
      t('knowbase.measures.back'),
    )
    const out = wrapper.find('a[href="https://knowbase.urbanfloods.app/measures"]')
    expect(out.text()).toContain(t('knowbase.openInKnowbase'))
    expect(out.attributes('target')).toBe('_blank')
    expect(out.find('.sr-only').text()).toBe(t('a11y.opensInNewTab'))
  })

  it('lists the posts that mention the measure', async () => {
    const fetchMock = mockApi(routes())
    await mountDetail()
    expect(callsTo(fetchMock, MENTIONS)).toHaveLength(1)
    const section = mentions()
    expect(section).not.toBeNull()
    expect(section!.querySelector('h2')!.textContent).toContain(t('knowbase.mentions.title'))
    const links = Array.from(section!.querySelectorAll('a'))
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['/blog/post-1', '/blog/post-2'])
    expect(links[0]!.textContent).toContain('Post 1 about green roofs')
  })

  it('hides "Mentioned in" when the mentions request fails or is empty', async () => {
    mockApi(routes(replyError(404, 'test.unmocked')))
    await mountDetail()
    expect(mentions()).toBeNull()
    unmountAll()

    mockApi(routes(kbReply({ total: 0, items: [] })))
    await mountDetail()
    expect(mentions()).toBeNull()
  })

  it('shows a not-found message for an unknown measure', async () => {
    mockApi({ [MEASURE]: replyError(404, 'knowbase.not_found') })
    const { wrapper } = await mountDetail()
    expect(wrapper.text()).toContain(t('knowbase.measures.notFound'))
    expect(wrapper.find('a[href="/knowbase/measures"]').exists()).toBe(true)
  })
})

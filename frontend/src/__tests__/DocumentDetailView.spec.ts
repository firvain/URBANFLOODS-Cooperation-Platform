import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import DocumentDetailView from '@/views/DocumentDetailView.vue'
import i18n from '@/i18n'
import { callsTo, mockApi, replyError } from './helpers/api'
import { KB, kbReply, makeDocument, makeMention } from './helpers/knowbase'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const DOCUMENT = `GET ${KB}/documents/3`
const MENTIONS = `GET ${KB}/document/3/mentions/`

afterEach(() => unmountAll())

const LINKS =
  'https://www.ypeka.gr/law-3, http://example.it/doc javascript:alert(1)\nftp://files.example.org/x www.no-scheme.gr'

function routes() {
  return {
    [DOCUMENT]: kbReply(makeDocument(3, { web_links: LINKS, comments: 'Amended in 2014.' })),
    [MENTIONS]: kbReply({ total: 1, items: [makeMention(9)] }),
  }
}

const mountDetail = () => mountWithApp(DocumentDetailView, { path: '/knowbase/documents/3' })

describe('DocumentDetailView', () => {
  it('renders the English and local names, country, gazette, descriptions and keywords', async () => {
    mockApi(routes())
    const { wrapper } = await mountDetail()
    expect(wrapper.find('h1').text()).toBe('Law 3 on flood risk management')
    const local = wrapper.find('[data-testid="title-local"]')
    expect(local.text()).toBe('Νόμος 3 για τους κινδύνους πλημμύρας')
    expect(local.attributes('lang')).toBe('')
    expect(wrapper.find('span.fi.fi-gr').exists()).toBe(true)
    const text = wrapper.text()
    for (const value of [
      'Greece',
      'National',
      'Floods management',
      'ΦΕΚ Α 3/2010',
      t('knowbase.documents.fields.gazette'),
      'Transposes the Floods Directive (document 3).',
      'Ενσωμάτωση της Οδηγίας (έγγραφο 3).',
      'Amended in 2014.',
    ]) {
      expect(text).toContain(value)
    }
    expect(wrapper.findAll('[data-testid="kb-keyword"]').map((k) => k.text())).toEqual([
      'Flood risk',
      'Floods Directive',
    ])
  })

  it('renders only http(s) web links, as external links', async () => {
    mockApi(routes())
    const { wrapper } = await mountDetail()
    const links = wrapper.findAll('[data-testid="web-links"] a')
    expect(links.map((a) => a.attributes('href'))).toEqual([
      'https://www.ypeka.gr/law-3',
      'http://example.it/doc',
    ])
    for (const link of links) {
      expect(link.attributes('target')).toBe('_blank')
      expect(link.attributes('rel')).toContain('noopener')
    }
    expect(wrapper.find('a[href^="javascript:"]').exists()).toBe(false)
    expect(wrapper.html()).not.toContain('javascript:')
  })

  it('lists the posts that mention the document and links back', async () => {
    mockApi(routes())
    const { wrapper } = await mountDetail()
    const section = wrapper.find('[data-testid="kb-mentions"]')
    expect(section.find('a[href="/blog/post-9"]').exists()).toBe(true)
    // The list lives on the KNOWBASE site only (user decision 2026-10-31).
    expect(wrapper.find('a[href="/knowbase/documents"]').exists()).toBe(false)
    // Only the "all documents" link goes to the KNOWBASE list; no "Open in the KNOWBASE", because
    // the KNOWBASE has no address for one document (owner's decision).
    const links = wrapper.findAll('a[href="https://knowbase.urbanfloods.app/legislation"]')
    expect(links).toHaveLength(1)
    expect(links[0]!.text()).toContain(t('knowbase.documents.back'))
    expect(links[0]!.attributes('target')).toBe('_blank')
    expect(links[0]!.find('.sr-only').text()).toBe(t('a11y.opensInNewTab'))
  })

  it('shows a not-found message for an unknown document', async () => {
    mockApi({ [DOCUMENT]: replyError(404, 'knowbase.not_found') })
    const { wrapper } = await mountDetail()
    expect(wrapper.text()).toContain(t('knowbase.documents.notFound'))
    const back = wrapper.find('a[href="https://knowbase.urbanfloods.app/legislation"]')
    expect(back.text()).toContain(t('knowbase.documents.back'))
    expect(back.attributes('target')).toBe('_blank')
  })

  it('keeps one focusable h1 with the page title when the KNOWBASE is unavailable', async () => {
    const fetchMock = mockApi({ [DOCUMENT]: replyError(503, 'knowbase.unavailable') })
    const { wrapper } = await mountDetail()
    const headings = wrapper.findAll('h1')
    expect(headings).toHaveLength(1)
    expect(headings[0]!.attributes('tabindex')).toBe('-1')
    expect(headings[0]!.text()).toBe(t('knowbase.documents.detailTitle'))
    const alert = wrapper.find('[role="alert"]')
    expect(alert.text()).toContain(t('knowbase.documents.detailError'))
    const retry = alert.findAll('button').find((b) => b.text().includes(t('knowbase.retry')))
    expect(retry).toBeDefined()
    await retry!.trigger('click')
    await flushPromises()
    expect(callsTo(fetchMock, DOCUMENT)).toHaveLength(2)
  })
})

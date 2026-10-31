import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import AboutView from '@/views/AboutView.vue'
import i18n from '@/i18n'
import en from '@/i18n/locales/en.json'
import { PARTNER_LOGO_FILES, partnerLogoUrl, partnerSlug } from '@/constants/partnerLogos'
import { callsTo, deferred, jsonResponse, mockApi, reply, replyError } from './helpers/api'
import { PARTNERS, PARTNERS_RESPONSE } from './helpers/organisations'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const LIST = 'GET /api/v1/organisations/'

afterEach(unmountAll)

/** Mount the About page; the organisations API answers with the 22 partners unless `mocked`. */
async function mountAbout({ mocked = false } = {}) {
  if (!mocked) mockApi({ [LIST]: reply(200, PARTNERS_RESPONSE) })
  const { wrapper } = await mountWithApp(AboutView, { path: '/about' })
  return wrapper
}

const shortNames = (els: Element[]) => els.map((el) => el.getAttribute('data-short-name'))
const tilesIn = (testId: string) =>
  Array.from(document.querySelectorAll(`[data-testid="${testId}"] [data-testid="partner-tile"]`))

describe('AboutView', () => {
  it('uses the KNOWBASE header pattern: h1 and accent bar', async () => {
    const wrapper = await mountAbout()
    const h1 = wrapper.find('h1')
    expect(h1.classes()).toEqual(expect.arrayContaining(['text-4xl', 'text-primary-600']))
    expect(wrapper.find('.h-1.w-20.bg-secondary-500').exists()).toBe(true)
  })

  it('shows the acronym and the full title in the highlight box', async () => {
    const wrapper = await mountAbout()
    expect(wrapper.text()).toContain('URBANFLOODS')
    const box = wrapper.find('[data-testid="full-title"]')
    expect(box.classes()).toEqual(
      expect.arrayContaining(['bg-primary-50', 'border-l-4', 'border-primary-500']),
    )
    expect(box.text()).toContain(
      'Promoting Urban Resilience Through an Integrated Advanced Decision Support System for Flood Control',
    )
  })

  it('lists the project facts', async () => {
    const wrapper = await mountAbout()
    const text = wrapper.text()
    for (const fact of [
      'Interreg IPA ADRION 2021–2027',
      'IPA ADRION 1st Call for Proposals',
      '2. Supporting a greener and climate resilient Adriatic-Ionian region',
      'SO2.1. Promoting climate change adaptation and disaster risk prevention, resilience taking into account eco-system based approaches',
      '01/09/2024 – 31/08/2027',
      'EUR 1.747.583,17',
      'EUR 1.485.445,68',
    ]) {
      expect(text, fact).toContain(fact)
    }
    for (const key of [
      'acronym',
      'fullTitle',
      'programme',
      'priority',
      'call',
      'specificObjective',
      'dates',
      'totalBudget',
      'interregFunds',
    ]) {
      expect(text, key).toContain(t(`about.facts.${key}`))
    }
  })

  it('shows the Priority 2 icon with alt text beside the priority', async () => {
    const wrapper = await mountAbout()
    const icon = wrapper.find('img[src*="priority-2-greener"]')
    expect(icon.exists()).toBe(true)
    expect(icon.attributes('alt')).toBe(t('about.priorityIconAlt'))
    expect(icon.classes()).toEqual(expect.arrayContaining(['h-12', 'w-12']))
    expect(existsSync(resolve(__dirname, '../assets/logos/priority-2-greener.png'))).toBe(true)
  })

  it('shows the lead partner card with address and a mailto for the scientific coordinator', async () => {
    const wrapper = await mountAbout()
    const lead = wrapper.find('[data-testid="lead-partner"]')
    expect(lead.text()).toContain('LEAD')
    expect(lead.text()).toContain('University of Western Macedonia')
    expect(lead.text()).toContain('Active Urban Planning Zone (ZEP) I, 50100 Kozani, Greece')
    expect(lead.text()).toContain('Prof. Malamati Louta')
    expect(lead.text()).toContain(t('about.leadPartner.coordinatorRole'))
    const mail = lead.find('a[href^="mailto:"]')
    expect(mail.attributes('href')).toBe('mailto:louta@uowm.gr')
    // WCAG 2.5.3 label in name: the accessible name is the visible address (no aria-label that
    // would replace it); the coordinator's name is the text right above the link.
    expect(mail.attributes('aria-label')).toBeUndefined()
    expect(mail.attributes('aria-labelledby')).toBeUndefined()
    expect(mail.text()).toBe('louta@uowm.gr')
  })

  it('keeps the address out of the translation files and the template source', async () => {
    expect(JSON.stringify(en)).not.toContain('louta@uowm.gr')
    const source = await import('@/views/AboutView.vue?raw')
    expect(source.default).not.toContain('louta@uowm.gr')
  })

  it('renders every summary paragraph and output from en.json', async () => {
    const wrapper = await mountAbout()
    const text = wrapper.text()
    for (const paragraph of en.about.summary.paragraphs) expect(text).toContain(paragraph)
    for (const output of en.about.summary.outputs) {
      expect(text).toContain(output.title)
      expect(text).toContain(output.text)
    }
    expect(text).toContain(en.about.summary.closing)
  })

  it('no longer shows the budget placeholder', async () => {
    const wrapper = await mountAbout()
    expect(wrapper.text()).not.toMatch(/to be provided/i)
  })

  it('has one h1 and headings in order (no level skipped)', async () => {
    const wrapper = await mountAbout()
    const levels = wrapper
      .findAll('h1, h2, h3, h4, h5, h6')
      .map((h) => Number(h.element.tagName[1]))
    expect(levels.filter((l) => l === 1)).toHaveLength(1)
    expect(levels[0]).toBe(1)
    for (let i = 1; i < levels.length; i++) {
      expect(levels[i]! - levels[i - 1]!, `heading ${i}`).toBeLessThanOrEqual(1)
    }
  })

  it('no longer links to a separate partners page', async () => {
    const wrapper = await mountAbout()
    expect(wrapper.find('a[href="/partners"]').exists()).toBe(false)
  })
})

describe('partner logos', () => {
  it('derives the slug from the short name', () => {
    expect(partnerSlug('UOWM')).toBe('uowm')
    expect(partnerSlug('RDA Backa')).toBe('rda-backa')
    expect(partnerSlug('AVP_Jadransko more')).toBe('avp-jadransko-more')
    expect(partnerSlug('FCSE-UKIM')).toBe('fcse-ukim')
  })

  it('knows the 11 supplied logo files and each one exists in public/partners', () => {
    expect(Object.keys(PARTNER_LOGO_FILES)).toHaveLength(11)
    for (const file of Object.values(PARTNER_LOGO_FILES)) {
      expect(existsSync(resolve(__dirname, '../../public/partners', file)), file).toBe(true)
    }
    expect(partnerLogoUrl('MC')).toMatch(/\/partners\/mc\.svg$/)
    expect(partnerLogoUrl('HydrowaterAL')).toMatch(/\/partners\/hydrowateral\.png$/)
    expect(partnerLogoUrl('Scicli')).toBeNull()
  })
})

describe('AboutView partnership section (merged from /partners, user decision 2026-10-31)', () => {
  const section = () => document.querySelector('section#partnership')

  it('requests the partners only, up to 100', async () => {
    const fetchMock = mockApi({ [LIST]: reply(200, PARTNERS_RESPONSE) })
    await mountAbout({ mocked: true })
    const calls = callsTo(fetchMock, LIST)
    expect(calls).toHaveLength(1)
    const query = new URL(calls[0]!.url, 'http://x.invalid').searchParams
    expect(query.get('partners_only')).toBe('true')
    expect(query.get('limit')).toBe('100')
  })

  it('is a section with id "partnership" headed "Partnership", after the facts', async () => {
    await mountAbout()
    const el = section()
    expect(el).not.toBeNull()
    const heading = el!.querySelector('h2')
    expect(heading?.textContent?.trim()).toBe(t('partners.partnershipTitle'))
    expect(t('partners.partnershipTitle')).toBe('Partnership')
    expect(el!.getAttribute('aria-labelledby')).toBe(heading!.id)
    const information = document.querySelector('section[aria-labelledby="information-heading"]')!
    expect(information.compareDocumentPosition(el!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('holds the lead partner card with the LEAD badge, website, logo and coordinator', async () => {
    await mountAbout()
    const lead = section()!.querySelector('[data-testid="lead-partner"]')!
    expect(lead).not.toBeNull()
    expect(lead.textContent).toContain('LEAD')
    expect(lead.textContent).toContain('University of Western Macedonia')
    const link = lead.querySelector('a[href="https://www.uowm.gr/en/"]')
    expect(link).not.toBeNull()
    expect(link!.getAttribute('target')).toBe('_blank')
    const logo = lead.querySelector('img')!
    expect(logo.getAttribute('src')).toMatch(/\/partners\/uowm\.png$/)
    expect(logo.getAttribute('alt')).toBe('University of Western Macedonia logo')
    expect(lead.querySelector('a[href="mailto:louta@uowm.gr"]')).not.toBeNull()
    expect(document.querySelectorAll('[data-testid="lead-partner"]')).toHaveLength(1)
    // The lead partner is not repeated in the project partner grid.
    expect(shortNames(tilesIn('project-partners'))).not.toContain('UOWM')
  })

  it('lists 10 project partners and then 11 associated partners in sort_order, as lists', async () => {
    await mountAbout()
    const pp = tilesIn('project-partners')
    const ap = tilesIn('associated-partners')
    expect(pp).toHaveLength(10)
    expect(ap).toHaveLength(11)
    expect(shortNames(pp)).toEqual(PARTNERS.slice(1, 11).map((p) => p.short_name))
    expect(shortNames(ap)).toEqual(PARTNERS.slice(11).map((p) => p.short_name))
    for (const id of ['project-partners', 'associated-partners']) {
      const list = section()!.querySelector(`[data-testid="${id}"]`)!
      expect(list.tagName).toBe('UL')
      for (const tile of list.querySelectorAll('[data-testid="partner-tile"]'))
        expect(tile.tagName).toBe('LI')
    }
    const text = section()!.textContent!
    expect(text).toContain(t('partners.projectPartners'))
    expect(text).toContain(t('partners.associatedPartners'))
    expect(text.indexOf(t('partners.projectPartners'))).toBeLessThan(
      text.indexOf(t('partners.associatedPartners')),
    )
  })

  it('tiles show name, flag and country name, but no short-name badge', async () => {
    await mountAbout()
    const heis = tilesIn('project-partners').find(
      (el) => el.getAttribute('data-short-name') === 'HEIS',
    )!
    expect(heis.textContent).toContain('Hydro-Engineering Institute Sarajevo')
    expect(heis.textContent).toContain('Bosnia & Herzegovina')
    const flag = heis.querySelector('span.fi')
    expect(flag?.className).toContain('fi-ba')
    expect(flag?.getAttribute('aria-hidden')).toBe('true')
    expect(heis.textContent).not.toMatch(/\bHEIS\b/)

    const kozani = tilesIn('associated-partners').find(
      (el) => el.getAttribute('data-short-name') === 'Kozani',
    )!
    expect(kozani.querySelector('span.fi')?.classList.contains('fi-gr')).toBe(true)
    expect(kozani.textContent).toContain('Greece')
  })

  it('website links are external with the hidden "opens in a new tab" suffix', async () => {
    await mountAbout()
    const pp = tilesIn('project-partners')
    for (const tile of pp) {
      const link = tile.querySelector('a')
      expect(link, tile.getAttribute('data-short-name')!).not.toBeNull()
      expect(link!.getAttribute('target')).toBe('_blank')
      expect(link!.getAttribute('rel')).toContain('noopener')
      expect(link!.querySelector('.sr-only')?.textContent?.trim()).toBe(t('a11y.opensInNewTab'))
    }
    const heis = pp.find((el) => el.getAttribute('data-short-name') === 'HEIS')!
    expect(heis.querySelector('a')!.getAttribute('href')).toBe('http://heis.ba/')
    for (const tile of tilesIn('associated-partners')) expect(tile.querySelector('a')).toBeNull()
  })

  it('shows a logo box only for partners with a known logo file, with the same alt texts', async () => {
    await mountAbout()
    for (const tile of tilesIn('project-partners')) {
      const shortName = tile.getAttribute('data-short-name')!
      const img = tile.querySelector('img')
      expect(img, shortName).not.toBeNull()
      expect(img!.getAttribute('src')).toBe(partnerLogoUrl(shortName))
      const name = PARTNERS.find((p) => p.short_name === shortName)!.name
      expect(img!.getAttribute('alt')).toBe(`${name} logo`)
      expect(img!.classList.contains('object-contain')).toBe(true)
      const box = img!.parentElement!
      expect(box.className).toContain('h-10')
      expect(box.className).toContain('lg:h-12')
      expect(box.className).toContain('bg-white')
    }
    for (const tile of tilesIn('associated-partners')) expect(tile.querySelector('img')).toBeNull()
  })

  it('shows a loading skeleton inside the section, then the tiles', async () => {
    const pending = deferred<Response>()
    mockApi({ [LIST]: () => pending.promise })
    const wrapper = await mountAbout({ mocked: true })
    const loading = section()!.querySelector('[data-testid="partners-loading"]')
    expect(loading).not.toBeNull()
    expect(loading!.getAttribute('aria-busy')).toBe('true')
    expect(tilesIn('project-partners')).toHaveLength(0)
    // The facts and the lead partner do not wait for the API.
    expect(wrapper.find('[data-testid="full-title"]').exists()).toBe(true)
    expect(section()!.querySelector('[data-testid="lead-partner"]')).not.toBeNull()

    pending.resolve(jsonResponse(PARTNERS_RESPONSE))
    await flushPromises()
    expect(document.querySelector('[data-testid="partners-loading"]')).toBeNull()
    expect(tilesIn('project-partners')).toHaveLength(10)
  })

  it('shows an error with a retry button that fetches again', async () => {
    let calls = 0
    const fetchMock = mockApi({
      [LIST]: (request) =>
        ++calls === 1
          ? replyError(500, 'server.error')(request)
          : reply(200, PARTNERS_RESPONSE)(request),
    })
    const wrapper = await mountAbout({ mocked: true })
    expect(section()!.textContent).toContain(t('partners.loadError'))
    expect(tilesIn('project-partners')).toHaveLength(0)

    const retry = wrapper.findAll('button').find((b) => b.text() === t('partners.retry'))
    expect(retry).toBeDefined()
    await retry!.trigger('click')
    await flushPromises()
    expect(callsTo(fetchMock, LIST)).toHaveLength(2)
    expect(wrapper.text()).not.toContain(t('partners.loadError'))
    expect(tilesIn('project-partners')).toHaveLength(10)
  })
})

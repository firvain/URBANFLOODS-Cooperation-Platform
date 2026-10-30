import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import PartnersView from '@/views/PartnersView.vue'
import i18n from '@/i18n'
import { PARTNER_LOGO_FILES, partnerLogoUrl, partnerSlug } from '@/constants/partnerLogos'
import { callsTo, deferred, jsonResponse, mockApi, reply, replyError } from './helpers/api'
import { PARTNERS, PARTNERS_RESPONSE } from './helpers/organisations'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const LIST = 'GET /api/v1/organisations/'

afterEach(unmountAll)

async function mountPartners() {
  const { wrapper } = await mountWithApp(PartnersView, { path: '/partners' })
  return wrapper
}

const shortNames = (els: Element[]) => els.map((el) => el.getAttribute('data-short-name'))
const tilesIn = (testId: string) =>
  Array.from(document.querySelectorAll(`[data-testid="${testId}"] [data-testid="partner-tile"]`))

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

describe('PartnersView', () => {
  it('requests the partners only, up to 100', async () => {
    const fetchMock = mockApi({ [LIST]: reply(200, PARTNERS_RESPONSE) })
    await mountPartners()
    const calls = callsTo(fetchMock, LIST)
    expect(calls).toHaveLength(1)
    const query = new URL(calls[0]!.url, 'http://x.invalid').searchParams
    expect(query.get('partners_only')).toBe('true')
    expect(query.get('limit')).toBe('100')
  })

  it('has a focusable h1, the accent bar, the counts line and the stacked project logo', async () => {
    mockApi({ [LIST]: reply(200, PARTNERS_RESPONSE) })
    const wrapper = await mountPartners()
    const h1 = wrapper.find('h1')
    expect(h1.text()).toBe(t('partners.title'))
    expect(h1.attributes('tabindex')).toBe('-1')
    expect(wrapper.text()).toContain(
      t('partners.counts', { projectPartners: 11, associatedPartners: 11, countries: 8 }),
    )
    expect(wrapper.text()).toContain(
      '11 project partners and 11 associated partners from 8 countries',
    )
    const logo = wrapper.find('img[src*="interreg-urbanfloods-stacked"]')
    expect(logo.exists()).toBe(true)
    expect(logo.attributes('alt')).toBe(t('app.logoAlt'))
  })

  it('shows UOWM as the lead partner with the LEAD badge, website and logo', async () => {
    mockApi({ [LIST]: reply(200, PARTNERS_RESPONSE) })
    const wrapper = await mountPartners()
    const lead = wrapper.find('[data-testid="lead-partner"]')
    expect(lead.exists()).toBe(true)
    expect(lead.text()).toContain(t('partners.leadBadge'))
    expect(t('partners.leadBadge')).toBe('LEAD')
    expect(lead.text()).toContain('University of Western Macedonia')
    const link = lead.find('a[href="https://www.uowm.gr/en/"]')
    expect(link.exists()).toBe(true)
    expect(link.attributes('target')).toBe('_blank')
    const logo = lead.find('img')
    expect(logo.attributes('src')).toMatch(/\/partners\/uowm\.png$/)
    expect(logo.attributes('alt')).toBe('University of Western Macedonia logo')
    // The lead partner is not repeated in the project partner grid.
    expect(shortNames(tilesIn('project-partners'))).not.toContain('UOWM')
  })

  it('lists 10 project partners and 11 associated partners in sort_order', async () => {
    mockApi({ [LIST]: reply(200, PARTNERS_RESPONSE) })
    const wrapper = await mountPartners()
    const pp = tilesIn('project-partners')
    const ap = tilesIn('associated-partners')
    expect(pp).toHaveLength(10)
    expect(ap).toHaveLength(11)
    expect(shortNames(pp)).toEqual(PARTNERS.slice(1, 11).map((p) => p.short_name))
    expect(shortNames(ap)).toEqual(PARTNERS.slice(11).map((p) => p.short_name))
    expect(wrapper.text()).toContain(t('partners.projectPartners'))
    expect(wrapper.text()).toContain(t('partners.associatedPartners'))
  })

  it('tiles show name, flag and country name, but no short-name badge', async () => {
    mockApi({ [LIST]: reply(200, PARTNERS_RESPONSE) })
    await mountPartners()
    const heis = tilesIn('project-partners').find(
      (el) => el.getAttribute('data-short-name') === 'HEIS',
    )!
    expect(heis.textContent).toContain('Hydro-Engineering Institute Sarajevo')
    expect(heis.textContent).toContain('Bosnia & Herzegovina')
    const flag = heis.querySelector('span.fi')
    expect(flag?.className).toContain('fi-ba')
    expect(flag?.getAttribute('aria-hidden')).toBe('true')
    expect(heis.querySelector('[data-testid="short-name"]')).toBeNull()
    expect(heis.textContent).not.toMatch(/\bHEIS\b/)

    const kozani = tilesIn('associated-partners').find(
      (el) => el.getAttribute('data-short-name') === 'Kozani',
    )!
    expect(kozani.querySelector('span.fi')?.classList.contains('fi-gr')).toBe(true)
    expect(kozani.textContent).toContain('Greece')
  })

  it('website links are external with the hidden "opens in a new tab" suffix', async () => {
    mockApi({ [LIST]: reply(200, PARTNERS_RESPONSE) })
    await mountPartners()
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
    // Associated partners have no website in the data: no link.
    for (const tile of tilesIn('associated-partners')) expect(tile.querySelector('a')).toBeNull()
  })

  it('shows a logo box only for partners with a known logo file', async () => {
    mockApi({ [LIST]: reply(200, PARTNERS_RESPONSE) })
    await mountPartners()
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

  it('shows a loading skeleton, then the content', async () => {
    const pending = deferred<Response>()
    mockApi({ [LIST]: () => pending.promise })
    const wrapper = await mountPartners()
    const loading = wrapper.find('[data-testid="partners-loading"]')
    expect(loading.exists()).toBe(true)
    expect(loading.attributes('aria-busy')).toBe('true')
    expect(tilesIn('project-partners')).toHaveLength(0)

    pending.resolve(jsonResponse(PARTNERS_RESPONSE))
    await flushPromises()
    expect(wrapper.find('[data-testid="partners-loading"]').exists()).toBe(false)
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
    const wrapper = await mountPartners()
    expect(wrapper.text()).toContain(t('partners.loadError'))
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

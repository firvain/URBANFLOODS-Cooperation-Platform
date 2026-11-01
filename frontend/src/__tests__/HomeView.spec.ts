import { afterEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/i18n'

import HomeView from '@/views/HomeView.vue'
import { makeUser, mockApi, reply } from './helpers/api'
import { EXPERTISE } from './helpers/members'
import { mountWithApp, unmountAll } from './helpers/mount'

const ME = 'GET /api/v1/auth/me'
const SUGGESTED = 'GET /api/v1/members/suggested'

afterEach(() => {
  unmountAll()
  sessionStorage.clear()
})

const banner = () => document.querySelector('[data-testid="complete-profile-banner"]')

describe('HomeView profile nudge', () => {
  it('is hidden for anonymous visitors', async () => {
    mockApi()
    await mountWithApp(HomeView)
    expect(banner()).toBeNull()
  })

  it('is hidden for unverified users', async () => {
    mockApi({ [ME]: reply(200, makeUser({ is_verified: false })) })
    await mountWithApp(HomeView)
    expect(banner()).toBeNull()
  })

  it('is hidden for users with expertise', async () => {
    mockApi({
      [ME]: reply(200, makeUser({ expertise: [EXPERTISE[0]!] })),
      [SUGGESTED]: reply(200, { total: 0, items: [] }),
    })
    await mountWithApp(HomeView)
    expect(banner()).toBeNull()
  })

  it('shows under the intro, above the cards, for a verified user without expertise', async () => {
    mockApi({ [ME]: reply(200, makeUser()) })
    const { wrapper } = await mountWithApp(HomeView)
    const el = banner()
    expect(el).not.toBeNull()
    const intro = wrapper.find('h1 + p').element
    const cards = wrapper.find('ul').element
    expect(intro.compareDocumentPosition(el!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(el!.compareDocumentPosition(cards) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})

describe('HomeView section cards', () => {
  const t = i18n.global.t

  it('the KNOWBASE card has a plain title, the description and Open', async () => {
    mockApi()
    const { wrapper } = await mountWithApp(HomeView)
    const card = wrapper.find('[data-testid="home-card-knowbase"]')
    expect(card.exists()).toBe(true)
    const heading = card.find('h2')
    expect(heading.text()).toContain(t('home.cards.knowbase.title'))
    expect(heading.find('a').exists()).toBe(false)
    expect(card.text()).toContain(t('home.cards.knowbase.description'))
    expect(t('home.cards.knowbase.description')).toBe(
      'Browse legislation, policies and flood-protection measures.',
    )
    // Browsing happens on the KNOWBASE site (user decision 2026-10-31); the platform's measures
    // page is reached from the header menu ("Measures"), not from this card (owner, 7c).
    expect(card.findAll('a').map((a) => a.attributes('href'))).toEqual([
      'https://knowbase.urbanfloods.app',
    ])
    expect(card.text()).not.toContain(t('home.comingSoon'))
  })

  it('the KNOWBASE card has an Open button to the live KNOWBASE, styled like the DSS one', async () => {
    mockApi()
    const { wrapper } = await mountWithApp(HomeView)
    const card = wrapper.find('[data-testid="home-card-knowbase"]')
    const open = card.find('a[href="https://knowbase.urbanfloods.app"]')
    expect(open.exists()).toBe(true)
    expect(open.attributes('target')).toBe('_blank')
    expect(open.attributes('rel')).toContain('noopener')
    expect(open.text()).toContain(t('home.cards.knowbase.open'))
    expect(t('home.cards.knowbase.open')).toBe('Open the KNOWBASE')
    expect(open.text()).toContain(t('a11y.opensInNewTab'))
    expect(wrapper.find('[data-testid="home-card-blog"]').find('a[target="_blank"]').exists()).toBe(
      false,
    )
  })

  it('the Forum card links to /forum without a "coming soon" badge', async () => {
    mockApi()
    const { wrapper } = await mountWithApp(HomeView)
    const card = wrapper.find('[data-testid="home-card-forum"]')
    const link = card.find('a[href="/forum"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain(t('home.cards.forum.title'))
    expect(card.text()).not.toContain(t('home.comingSoon'))
  })

  it('the Blog card links to /blog without a "coming soon" badge', async () => {
    mockApi()
    const { wrapper } = await mountWithApp(HomeView)
    const card = wrapper.find('[data-testid="home-card-blog"]')
    const link = card.find('a[href="/blog"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain(t('home.cards.blog.title'))
    expect(card.text()).not.toContain(t('home.comingSoon'))
  })
})

describe('HomeView head', () => {
  it('emits WebSite JSON-LD with a SearchAction targeting /search?q=', async () => {
    mockApi()
    await mountWithApp(HomeView)
    const script = () => document.head.querySelector('script[type="application/ld+json"]')
    await vi.waitFor(() => expect(script()).not.toBeNull())
    const data = JSON.parse(script()!.textContent!)
    expect(data['@type']).toBe('WebSite')
    expect(data.name).toBe(i18n.global.t('app.title'))
    expect(data.url).toBe(`${window.location.origin}/`)
    expect(data.potentialAction['@type']).toBe('SearchAction')
    expect(data.potentialAction.target.urlTemplate).toBe(
      `${window.location.origin}/search?q={search_term_string}`,
    )
    expect(data.potentialAction['query-input']).toBe('required name=search_term_string')
    expect(document.title).toBe(i18n.global.t('app.title'))
  })
})

describe('HomeView "Project at a Glance" card (modelled on the KNOWBASE home page)', () => {
  const t = i18n.global.t
  const glance = () => document.querySelector<HTMLElement>('[data-testid="home-glance"]')

  it('has an h2 in the olive heading colour inside a card with the green top edge', async () => {
    mockApi()
    await mountWithApp(HomeView)
    const card = glance()
    expect(card).not.toBeNull()
    const heading = card!.querySelector('h2')!
    expect(heading.textContent?.trim()).toBe('Project at a Glance')
    expect(heading.classList.contains('text-secondary')).toBe(true)
    expect(card!.getAttribute('aria-labelledby')).toBe(heading.id)
    expect(card!.querySelector('.border-t-secondary-500')).not.toBeNull()
  })

  it('shows the full title and the acronym in the highlight box', async () => {
    mockApi()
    await mountWithApp(HomeView)
    const box = glance()!.querySelector('[data-testid="glance-title"]')!
    expect(box.className).toContain('bg-primary-50')
    expect(box.className).toContain('border-l-4')
    expect(box.className).toContain('border-primary-500')
    expect(box.textContent).toContain(t('about.values.fullTitle'))
    const acronym = box.querySelector('[data-testid="glance-acronym"]')!
    expect(acronym.textContent?.trim()).toBe('URBANFLOODS')
    expect(acronym.className).toMatch(/text-primary-\d00/)
    expect(acronym.className).toContain('font-bold')
  })

  it('lists the facts as label/value pairs, the Interreg funds in the olive accent', async () => {
    mockApi()
    await mountWithApp(HomeView)
    const pairs = Array.from(glance()!.querySelectorAll('dl dt')).map((dt) => [
      dt.textContent?.trim(),
      dt.nextElementSibling?.textContent?.trim(),
    ])
    expect(pairs).toEqual([
      ['Period', '2021 – 2027'],
      ['Duration', t('about.values.dates')],
      [t('about.facts.totalBudget'), t('about.values.totalBudget')],
      [t('about.facts.interregFunds'), t('about.values.interregFunds')],
      [t('partners.partnershipTitle'), '11 partners from 8 countries'],
    ])
    const funds = Array.from(glance()!.querySelectorAll('dd'))[3]!
    expect(funds.classList.contains('text-secondary')).toBe(true)
  })

  it('ends with a full-width "Learn more" link to /about', async () => {
    mockApi()
    await mountWithApp(HomeView)
    const link = glance()!.querySelector('a[href="/about"]')!
    expect(link).not.toBeNull()
    expect(link.textContent?.trim()).toBe('Learn more')
    expect(link.className).toContain('w-full')
  })

  it('comes after the intro and before the section cards; one h1, headings in order', async () => {
    mockApi()
    const { wrapper } = await mountWithApp(HomeView)
    const intro = wrapper.find('h1 + p').element
    const cards = wrapper.find('[data-testid="home-card-blog"]').element
    expect(intro.compareDocumentPosition(glance()!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(glance()!.compareDocumentPosition(cards) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    const levels = wrapper.findAll('h1, h2, h3, h4').map((h) => Number(h.element.tagName[1]))
    expect(levels.filter((l) => l === 1)).toHaveLength(1)
    for (let i = 1; i < levels.length; i++)
      expect(levels[i]! - levels[i - 1]!).toBeLessThanOrEqual(1)
  })

  it('sits in its own column from lg, spanning the hero', async () => {
    mockApi()
    await mountWithApp(HomeView)
    const grid = glance()!.parentElement!
    expect(grid.className).toContain('lg:grid-cols-[minmax(0,1fr)_26rem]')
    expect(glance()!.className).toContain('lg:col-start-2')
    expect(glance()!.className).toContain('lg:row-span-2')
  })
})

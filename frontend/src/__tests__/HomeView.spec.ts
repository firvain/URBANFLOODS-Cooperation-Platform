import { afterEach, describe, expect, it } from 'vitest'

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

  it('the KNOWBASE card links to /knowbase and is no longer "coming soon"', async () => {
    mockApi()
    const { wrapper } = await mountWithApp(HomeView)
    const card = wrapper.find('[data-testid="home-card-knowbase"]')
    expect(card.exists()).toBe(true)
    const link = card.find('a[href="/knowbase"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain(t('home.cards.knowbase.title'))
    expect(card.text()).not.toContain(t('home.comingSoon'))
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

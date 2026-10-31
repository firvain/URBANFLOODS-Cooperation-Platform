import { afterEach, describe, expect, it } from 'vitest'

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

import { afterEach, describe, expect, it } from 'vitest'

import HomeView from '@/views/HomeView.vue'
import i18n from '@/i18n'
import { callsTo, makeUser, mockApi, reply, replyError } from './helpers/api'
import { makeSuggested } from './helpers/members'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'
const SUGGESTED = 'GET /api/v1/members/suggested'

afterEach(unmountAll)

const SUGGESTIONS = {
  total: 8,
  items: [
    makeSuggested(11, 3),
    makeSuggested(12, 1),
    makeSuggested(13, 0),
    makeSuggested(14, 2),
    makeSuggested(15, 2),
    makeSuggested(16, 1),
    makeSuggested(17, 1),
    makeSuggested(18, 1),
  ],
}

const widget = () => document.querySelector('[data-testid="suggested-collaborators"]')
const cards = () => Array.from(document.querySelectorAll('[data-testid="suggested-card"]'))

describe('SuggestedCollaborators on the home page', () => {
  it('is not requested or shown for anonymous visitors', async () => {
    const fetchMock = mockApi({ [SUGGESTED]: reply(200, SUGGESTIONS) })
    await mountWithApp(HomeView)
    expect(callsTo(fetchMock, SUGGESTED)).toHaveLength(0)
    expect(widget()).toBeNull()
  })

  it('is not requested or shown for unverified users', async () => {
    const fetchMock = mockApi({
      [ME]: reply(200, makeUser({ is_verified: false })),
      [SUGGESTED]: reply(200, SUGGESTIONS),
    })
    await mountWithApp(HomeView)
    expect(callsTo(fetchMock, SUGGESTED)).toHaveLength(0)
    expect(widget()).toBeNull()
  })

  it('shows up to 6 suggestions with the shared expertise count for verified users', async () => {
    const fetchMock = mockApi({
      [ME]: reply(200, makeUser()),
      [SUGGESTED]: reply(200, SUGGESTIONS),
    })
    await mountWithApp(HomeView)
    expect(callsTo(fetchMock, SUGGESTED)).toHaveLength(1)
    expect(widget()).not.toBeNull()
    expect(widget()!.querySelector('h2')?.textContent).toContain(t('network.suggested.title'))

    const list = cards()
    expect(list).toHaveLength(6)
    expect(list[0]!.querySelector('a[href="/u/11"]')?.textContent).toContain('Member 11')
    expect(list[0]!.textContent).toContain(t('network.suggested.shared', { count: 3 }, 3))
    expect(t('network.suggested.shared', { count: 3 }, 3)).toBe('shares 3 expertise areas')
    expect(t('network.suggested.shared', { count: 1 }, 1)).toBe('shares 1 expertise area')
    expect(list[1]!.textContent).toContain('shares 1 expertise area')
    // No shared expertise: no "shares 0" line.
    expect(list[2]!.textContent).not.toContain('shares')

    const link = widget()!.querySelector('a[href="/network"]')
    expect(link?.textContent).toContain(t('network.suggested.seeAll'))
  })

  it('explains what to do when there are no suggestions', async () => {
    mockApi({
      [ME]: reply(200, makeUser()),
      [SUGGESTED]: reply(200, { total: 0, items: [] }),
    })
    await mountWithApp(HomeView)
    expect(cards()).toHaveLength(0)
    expect(widget()!.textContent).toContain(t('network.suggested.empty'))
    expect(widget()!.querySelector('a[href="/account"]')).not.toBeNull()
  })

  it('stays quiet (no cards, a short note) when the request fails', async () => {
    mockApi({ [ME]: reply(200, makeUser()), [SUGGESTED]: replyError(403, 'auth.not_verified') })
    await mountWithApp(HomeView)
    expect(cards()).toHaveLength(0)
    expect(widget()!.textContent).toContain(t('network.suggested.loadError'))
  })
})

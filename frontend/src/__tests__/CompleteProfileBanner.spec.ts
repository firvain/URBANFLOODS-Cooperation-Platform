import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import CompleteProfileBanner, {
  NUDGE_DISMISSED_KEY,
} from '@/components/account/CompleteProfileBanner.vue'
import i18n from '@/i18n'
import { makeUser, mockApi, reply } from './helpers/api'
import { EXPERTISE } from './helpers/members'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'

afterEach(() => {
  unmountAll()
  sessionStorage.clear()
})

const banner = () => document.querySelector('[data-testid="complete-profile-banner"]')

describe('CompleteProfileBanner', () => {
  it('is hidden for anonymous visitors', async () => {
    mockApi()
    await mountWithApp(CompleteProfileBanner)
    expect(banner()).toBeNull()
  })

  it('is hidden for unverified users', async () => {
    mockApi({ [ME]: reply(200, makeUser({ is_verified: false })) })
    await mountWithApp(CompleteProfileBanner)
    expect(banner()).toBeNull()
  })

  it('is hidden for users who already have expertise', async () => {
    mockApi({ [ME]: reply(200, makeUser({ expertise: [EXPERTISE[0]!] })) })
    await mountWithApp(CompleteProfileBanner)
    expect(banner()).toBeNull()
  })

  it('is hidden for users whose only expertise is the free-text "other" area', async () => {
    mockApi({ [ME]: reply(200, makeUser({ expertise_other: 'Coastal engineering' })) })
    await mountWithApp(CompleteProfileBanner)
    expect(banner()).toBeNull()
  })

  it('asks a verified user without expertise to add some, linking to the profile tab', async () => {
    mockApi({ [ME]: reply(200, makeUser()) })
    await mountWithApp(CompleteProfileBanner)
    expect(banner()).not.toBeNull()
    expect(t('account.nudge.title')).toBe('Tell members what you work on')
    expect(banner()!.textContent).toContain(t('account.nudge.title'))
    expect(banner()!.textContent).toContain(t('account.nudge.description'))
    const link = banner()!.querySelector('a[href="/account?tab=profile"]')
    expect(link?.textContent).toContain(t('account.nudge.action'))
  })

  it('can be dismissed for the rest of the session', async () => {
    mockApi({ [ME]: reply(200, makeUser()) })
    const { wrapper } = await mountWithApp(CompleteProfileBanner)
    const close = wrapper.find(`button[aria-label="${t('account.nudge.dismiss')}"]`)
    expect(close.exists()).toBe(true)
    await close.trigger('click')
    await flushPromises()
    expect(banner()).toBeNull()
    expect(sessionStorage.getItem(NUDGE_DISMISSED_KEY)).toBe('1')
    expect(NUDGE_DISMISSED_KEY).toBe('profileNudgeDismissed')
  })

  it('stays hidden once dismissed in this session', async () => {
    sessionStorage.setItem('profileNudgeDismissed', '1')
    mockApi({ [ME]: reply(200, makeUser()) })
    await mountWithApp(CompleteProfileBanner)
    expect(banner()).toBeNull()
  })
})

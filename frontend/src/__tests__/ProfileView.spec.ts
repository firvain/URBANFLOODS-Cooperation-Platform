import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import ProfileView from '@/views/ProfileView.vue'
import i18n from '@/i18n'
import { callsTo, mockApi, reply, replyError } from './helpers/api'
import { EXPERTISE, makeMemberDetail } from './helpers/members'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const MEMBER = 'GET /api/v1/members/5'

afterEach(unmountAll)

describe('ProfileView', () => {
  it('shows the member: name, organisation, country, bio, expertise, email, member since', async () => {
    const member = makeMemberDetail(5, {
      display_name: 'Maria Papadopoulou',
      email: 'maria@example.org',
      expertise: EXPERTISE.slice(0, 3),
      bio: 'Hydrologist in Kozani.\nWorks on early warning.',
      created_at: '2026-10-01T10:00:00Z',
    })
    const fetchMock = mockApi({ [MEMBER]: reply(200, member) })
    const { wrapper } = await mountWithApp(ProfileView, { path: '/u/5' })
    expect(callsTo(fetchMock, MEMBER)).toHaveLength(1)

    const h1 = wrapper.find('h1')
    expect(h1.text()).toBe('Maria Papadopoulou')
    expect(h1.attributes('tabindex')).toBe('-1')
    expect(wrapper.text()).toContain('University of Western Macedonia')
    expect(wrapper.text()).toContain('Greece')

    const bio = wrapper.find('[data-testid="profile-bio"]')
    expect(bio.text()).toContain('Hydrologist in Kozani.')
    expect(bio.text()).toContain('Works on early warning.')
    expect(bio.classes()).toContain('whitespace-pre-line')

    const expertise = wrapper.findAll('[data-testid="profile-expertise"] li').map((li) => li.text())
    expect(expertise).toEqual(['Hydrology', 'Civil protection', 'Urban planning'])

    const email = wrapper.find('a[href="mailto:maria@example.org"]')
    expect(email.exists()).toBe(true)
    expect(email.text()).toContain('maria@example.org')

    expect(wrapper.text()).toContain(t('profile.memberSince', { date: 'October 2026' }))
  })

  it('has no email link when the member does not share it, and handles a missing bio', async () => {
    mockApi({ [MEMBER]: reply(200, makeMemberDetail(5, { email: null, bio: null })) })
    const { wrapper } = await mountWithApp(ProfileView, { path: '/u/5' })
    expect(wrapper.find('a[href^="mailto:"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="profile-bio"]').exists()).toBe(false)
  })

  it('shows the not-found content for an unknown member', async () => {
    mockApi({ [MEMBER]: replyError(404, 'members.not_found') })
    const { wrapper } = await mountWithApp(ProfileView, { path: '/u/5' })
    expect(wrapper.find('h1').text()).toBe(t('errors.notFound'))
    expect(wrapper.text()).toContain(t('errors.notFoundDescription'))
    expect(wrapper.find('a[href="/"]').exists()).toBe(true)
  })

  it('shows the not-found content for a non-numeric id without asking the server', async () => {
    const fetchMock = mockApi()
    const { wrapper } = await mountWithApp(ProfileView, { path: '/u/abc' })
    expect(wrapper.find('h1').text()).toBe(t('errors.notFound'))
    expect(fetchMock.mock.calls.filter(([u]) => String(u).includes('/members/'))).toHaveLength(0)
  })

  it('shows an error with retry for other failures', async () => {
    let calls = 0
    const fetchMock = mockApi({
      [MEMBER]: (r) =>
        ++calls === 1 ? replyError(500, 'server.error')(r) : reply(200, makeMemberDetail(5))(r),
    })
    const { wrapper } = await mountWithApp(ProfileView, { path: '/u/5' })
    expect(wrapper.text()).toContain(t('profile.loadError'))
    await wrapper
      .findAll('button')
      .find((b) => b.text() === t('profile.retry'))!
      .trigger('click')
    await flushPromises()
    expect(callsTo(fetchMock, MEMBER)).toHaveLength(2)
    expect(wrapper.find('h1').text()).toBe('Member 5')
  })
})

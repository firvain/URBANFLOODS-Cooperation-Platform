import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import ProfileView from '@/views/ProfileView.vue'
import i18n from '@/i18n'
import {
  callsTo,
  makeUser,
  mockApi as mockAnyApi,
  reply,
  replyError,
  type Handler,
} from './helpers/api'
import { POSTS, makePost, paramsOf } from './helpers/blog'
import { THREADS, makeThread } from './helpers/forum'
import { EXPERTISE, makeMemberDetail } from './helpers/members'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const MEMBER = 'GET /api/v1/members/5'
const ME = 'GET /api/v1/auth/me'

/** Profiles are for verified users (route meta `auth: 'verified'`): sign one in by default. */
const mockApi = (routes: Record<string, Handler> = {}) =>
  mockAnyApi({ [ME]: reply(200, makeUser({ id: 1 })), ...routes })

/** A `{total, items}` page with `shown` items out of `total`. */
function listOf<T>(total: number, shown: number, make: (id: number) => T) {
  return { total, items: Array.from({ length: shown }, (_, i) => make(i + 1)) }
}

function contributions(posts: unknown, threads: unknown): Record<string, Handler> {
  return { [POSTS]: reply(200, posts), [THREADS]: reply(200, threads) }
}

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

  it('shows the free-text "other" area as one more badge after the areas', async () => {
    const member = makeMemberDetail(5, {
      expertise: EXPERTISE.slice(0, 2),
      expertise_other: 'Coastal engineering',
    })
    mockApi({ [MEMBER]: reply(200, member) })
    const { wrapper } = await mountWithApp(ProfileView, { path: '/u/5' })
    const expertise = wrapper.findAll('[data-testid="profile-expertise"] li').map((li) => li.text())
    expect(expertise).toEqual(['Hydrology', 'Civil protection', 'Coastal engineering'])
  })

  it('shows the expertise row for a member with only the free-text area', async () => {
    mockApi({
      [MEMBER]: reply(200, makeMemberDetail(5, { expertise: [], expertise_other: 'Coastal' })),
    })
    const { wrapper } = await mountWithApp(ProfileView, { path: '/u/5' })
    expect(wrapper.text()).toContain(t('profile.expertise'))
    const expertise = wrapper.findAll('[data-testid="profile-expertise"] li').map((li) => li.text())
    expect(expertise).toEqual(['Coastal'])
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

  describe('contributions', () => {
    it('asks for the member’s published posts and discussions, newest first, 10 of each', async () => {
      const fetchMock = mockApi({
        [MEMBER]: reply(200, makeMemberDetail(5)),
        ...contributions(listOf(0, 0, makePost), listOf(0, 0, makeThread)),
      })
      await mountWithApp(ProfileView, { path: '/u/5' })
      for (const route of [POSTS, THREADS]) {
        const calls = callsTo(fetchMock, route)
        expect(calls).toHaveLength(1)
        const query = paramsOf(calls[0]!.url)
        expect(query.get('author_id')).toBe('5')
        expect(query.get('status')).toBe('published')
        expect(query.get('sort')).toBe('newest')
        expect(query.get('limit')).toBe('10')
      }
    })

    it('shows the counts in the heading and lists posts and discussions with links and dates', async () => {
      mockApi({
        [MEMBER]: reply(200, makeMemberDetail(5)),
        ...contributions(
          listOf(12, 10, (id) =>
            makePost(id, { title: `Post ${id}`, published_at: '2026-10-20T09:00:00Z' }),
          ),
          listOf(4, 4, (id) => makeThread(id, { title: `Thread ${id}` })),
        ),
      })
      const { wrapper } = await mountWithApp(ProfileView, { path: '/u/5' })

      const section = wrapper.find('[data-testid="profile-contributions"]')
      expect(section.find('h2').text()).toBe(t('profile.contributions.title'))
      expect(section.find('[data-testid="contributions-counts"]').text()).toBe(
        `${t('blog.count', { count: 12 }, 12)} · ${t('forum.count', { count: 4 }, 4)}`,
      )

      const posts = section.findAll('[data-testid="contributions-posts"] li')
      expect(posts).toHaveLength(10)
      expect(posts[0]!.find('a').attributes('href')).toBe('/blog/post-1')
      expect(posts[0]!.find('a').text()).toBe('Post 1')
      expect(posts[0]!.find('time').attributes('datetime')).toBe('2026-10-20T09:00:00Z')

      const threads = section.findAll('[data-testid="contributions-threads"] li')
      expect(threads).toHaveLength(4)
      expect(threads[0]!.find('a').attributes('href')).toBe('/forum/t/thread-1')
      expect(threads[0]!.find('a').text()).toBe('Thread 1')

      expect(section.find('a[href="/blog?author_id=5"]').text()).toBe(
        t('profile.contributions.seeAllPosts'),
      )
      expect(section.find('a[href="/forum?author_id=5"]').text()).toBe(
        t('profile.contributions.seeAllThreads'),
      )
    })

    it('leaves out a kind the member has not published', async () => {
      mockApi({
        [MEMBER]: reply(200, makeMemberDetail(5)),
        ...contributions(listOf(0, 0, makePost), listOf(1, 1, makeThread)),
      })
      const { wrapper } = await mountWithApp(ProfileView, { path: '/u/5' })
      const section = wrapper.find('[data-testid="profile-contributions"]')
      expect(section.find('[data-testid="contributions-counts"]').text()).toBe(
        `${t('blog.count', { count: 0 }, 0)} · ${t('forum.count', { count: 1 }, 1)}`,
      )
      expect(section.find('[data-testid="contributions-posts"]').exists()).toBe(false)
      expect(section.find('a[href="/blog?author_id=5"]').exists()).toBe(false)
      expect(section.findAll('[data-testid="contributions-threads"] li')).toHaveLength(1)
    })

    it('shows an empty state when the member has published nothing', async () => {
      mockApi({
        [MEMBER]: reply(200, makeMemberDetail(5, { display_name: 'Maria' })),
        ...contributions(listOf(0, 0, makePost), listOf(0, 0, makeThread)),
      })
      const { wrapper } = await mountWithApp(ProfileView, { path: '/u/5' })
      const section = wrapper.find('[data-testid="profile-contributions"]')
      expect(section.text()).toContain(t('profile.contributions.empty', { name: 'Maria' }))
      expect(section.find('[data-testid="contributions-counts"]').exists()).toBe(false)
      expect(section.find('ul').exists()).toBe(false)
    })

    it('keeps the profile and says so when the contributions cannot be loaded', async () => {
      mockApi({
        [MEMBER]: reply(200, makeMemberDetail(5)),
        [POSTS]: replyError(500, 'server.error'),
        [THREADS]: reply(200, listOf(0, 0, makeThread)),
      })
      const { wrapper } = await mountWithApp(ProfileView, { path: '/u/5' })
      expect(wrapper.find('h1').text()).toBe('Member 5')
      expect(wrapper.find('[data-testid="profile-contributions"]').text()).toContain(
        t('profile.contributions.loadError'),
      )
    })
  })

  it('shows an Admin badge next to the name for an admin, outside the h1', async () => {
    mockApi({ [MEMBER]: reply(200, makeMemberDetail(5, { is_admin: true })) })
    const { wrapper } = await mountWithApp(ProfileView, { path: '/u/5' })
    const badge = wrapper.find('[data-testid="profile-admin-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe(t('profile.adminBadge'))
    expect(t('profile.adminBadge')).toBe('Admin')
    expect(wrapper.find('h1').text()).toBe('Member 5')
  })

  it('shows no admin badge for a member who is not an admin', async () => {
    mockApi({ [MEMBER]: reply(200, makeMemberDetail(5, { is_admin: false })) })
    const { wrapper } = await mountWithApp(ProfileView, { path: '/u/5' })
    expect(wrapper.find('h1').text()).toBe('Member 5')
    expect(wrapper.find('[data-testid="profile-admin-badge"]').exists()).toBe(false)
  })

  it('an unverified user sees a verify-your-email notice and the member is not requested', async () => {
    const fetchMock = mockApi({
      [ME]: reply(200, makeUser({ is_verified: false })),
      [MEMBER]: reply(200, makeMemberDetail(5)),
    })
    const { wrapper } = await mountWithApp(ProfileView, { path: '/u/5' })
    expect(callsTo(fetchMock, MEMBER)).toHaveLength(0)
    expect(wrapper.find('h1').text()).toBe(t('profile.title'))
    expect(wrapper.find('[data-testid="profile-restricted"]').text()).toContain(
      t('network.restricted.verify'),
    )
  })

  it('a 403 from the API shows the verify notice, not an error', async () => {
    mockApi({ [MEMBER]: replyError(403, 'auth.email_not_verified') })
    const { wrapper } = await mountWithApp(ProfileView, { path: '/u/5' })
    expect(wrapper.find('[data-testid="profile-restricted"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain(t('profile.loadError'))
  })
})

import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import NetworkView, { SEARCH_DEBOUNCE_MS } from '@/views/NetworkView.vue'
import i18n from '@/i18n'
import { PROJECT_COUNTRIES } from '@/constants/auth'
import {
  callsTo,
  makeUser,
  mockApi,
  ORGANISATIONS,
  reply,
  replyError,
  type Handler,
} from './helpers/api'
import { EXPERTISE, EXPERTISE_RESPONSE, makeMember, memberPage } from './helpers/members'
import { mountWithApp, unmountAll } from './helpers/mount'
import { clickOption, enterOption, openSelect } from './helpers/select'

const t = i18n.global.t
const MEMBERS = 'GET /api/v1/members/'
const AUTH_ME = 'GET /api/v1/auth/me'
/** The directory is for verified users; this one has expertise, so no profile nudge shows. */
const VIEWER = makeUser({ id: 999, expertise: [EXPERTISE[0]!] })

afterEach(() => {
  vi.useRealTimers()
  unmountAll()
  sessionStorage.clear()
})

/** Serve `GET /members/` pages out of `total` members, honouring skip/limit. */
function pages(total: number): Handler {
  return (request) => {
    const query = new URL(request.url, 'http://x.invalid').searchParams
    const skip = Number(query.get('skip') ?? 0)
    return reply(200, memberPage(total, skip, Number(query.get('limit') ?? 24)))(request)
  }
}

function routes(members: Handler = pages(60)) {
  return {
    [AUTH_ME]: reply(200, VIEWER),
    [MEMBERS]: members,
    'GET /api/v1/expertise/': reply(200, EXPERTISE_RESPONSE),
    'GET /api/v1/organisations/': reply(200, ORGANISATIONS),
  }
}

async function mountNetwork(path = '/network') {
  return mountWithApp(NetworkView, { path })
}

const cards = (wrapper: VueWrapper) => wrapper.findAll('[data-testid="member-card"]')
const lastQuery = (fetchMock: ReturnType<typeof mockApi>) =>
  new URL(callsTo(fetchMock, MEMBERS).at(-1)!.url, 'http://x.invalid').searchParams

describe('NetworkView', () => {
  it('has a focusable h1 and lists 24 member cards with a counts line', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountNetwork()
    expect(wrapper.find('h1').text()).toBe(t('network.title'))
    expect(wrapper.find('h1').attributes('tabindex')).toBe('-1')
    expect(cards(wrapper)).toHaveLength(24)
    expect(wrapper.find('[data-testid="member-count"]').text()).toBe(
      t('network.count', { count: 60 }, 60),
    )
    expect(t('network.count', { count: 60 }, 60)).toBe('60 members')
    const query = lastQuery(fetchMock)
    expect(query.get('skip')).toBe('0')
    expect(query.get('limit')).toBe('24')
    expect(query.has('q')).toBe(false)
    expect(query.has('country')).toBe(false)
  })

  it('cards show name (linked to the profile), organisation, country and bio excerpt', async () => {
    mockApi(routes())
    const { wrapper } = await mountNetwork()
    const first = cards(wrapper)[0]!
    expect(first.find('a[href="/u/1"]').text()).toBe('Member 1')
    expect(first.text()).toContain('University of Western Macedonia')
    expect(first.text()).toContain('Greece')
    expect(first.find('span.fi.fi-gr').exists()).toBe(true)
    expect(first.text()).toContain('Works on flood management, member 1.')
    // Free-text organisation.
    expect(cards(wrapper)[2]!.text()).toContain('Civil Protection Unit 3')
  })

  it('shows an Email link only for members who share their address', async () => {
    mockApi(routes())
    const { wrapper } = await mountNetwork()
    const withEmail = cards(wrapper)[0]!.find('a[href="mailto:member1@example.org"]')
    expect(withEmail.exists()).toBe(true)
    expect(withEmail.text()).toContain(t('network.card.email'))
    expect(withEmail.attributes('rel')).toContain('noopener')
    expect(cards(wrapper)[1]!.find('a[href^="mailto:"]').exists()).toBe(false)
  })

  it('caps the expertise badges at 4 with a "+N" badge', async () => {
    const members = {
      total: 2,
      items: [
        makeMember(1, { expertise: EXPERTISE.slice(0, 6) }),
        makeMember(2, { expertise: EXPERTISE.slice(0, 3) }),
      ],
    }
    mockApi(routes(reply(200, members)))
    const { wrapper } = await mountNetwork()
    const [six, three] = cards(wrapper)
    const badges = six!.findAll('[data-testid="expertise-badge"]')
    expect(badges.map((b) => b.text())).toEqual(EXPERTISE.slice(0, 4).map((e) => e.label))
    expect(six!.find('[data-testid="expertise-more"]').text()).toContain('+2')
    expect(three!.findAll('[data-testid="expertise-badge"]')).toHaveLength(3)
    expect(three!.find('[data-testid="expertise-more"]').exists()).toBe(false)
  })

  it('reads the filters and page from the URL into the request', async () => {
    const fetchMock = mockApi(routes())
    await mountNetwork(
      '/network?q=flood&expertise_ids=1&expertise_ids=3&country=GR&organisation_id=4&page=3',
    )
    const query = lastQuery(fetchMock)
    expect(query.get('q')).toBe('flood')
    expect(query.getAll('expertise_ids')).toEqual(['1', '3'])
    expect(query.get('country')).toBe('GR')
    expect(query.get('organisation_id')).toBe('4')
    expect(query.get('skip')).toBe('48')
    expect(query.get('limit')).toBe('24')
  })

  it('debounces the search, then puts q in the URL, resets the page and refetches', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountNetwork('/network?page=2')
    expect(callsTo(fetchMock, MEMBERS)).toHaveLength(1)

    const search = wrapper.find('input[type="search"]')
    await search.setValue('hyd')
    await search.setValue('hydro')
    await flushPromises()
    expect(callsTo(fetchMock, MEMBERS)).toHaveLength(1)
    expect(router.currentRoute.value.query.q).toBeUndefined()

    vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS)
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ q: 'hydro' })
    expect(callsTo(fetchMock, MEMBERS)).toHaveLength(2)
    expect(lastQuery(fetchMock).get('q')).toBe('hydro')
    expect(lastQuery(fetchMock).get('skip')).toBe('0')
  })

  it('expertise multi-select puts repeated expertise_ids in the URL and refetches', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountNetwork()
    await openSelect(wrapper, t('network.filters.expertise'))
    await clickOption('Hydrology')
    await clickOption('Civil protection')
    await flushPromises()
    expect(router.currentRoute.value.query.expertise_ids).toEqual(['1', '2'])
    expect(lastQuery(fetchMock).getAll('expertise_ids')).toEqual(['1', '2'])
    expect(router.currentRoute.value.fullPath).toContain('expertise_ids=1&expertise_ids=2')
  })

  it('country select offers all + the 8 project countries and filters by country', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountNetwork()
    await openSelect(wrapper, t('network.filters.country'))
    const options = Array.from(document.querySelectorAll('[role="option"]'))
    expect(options).toHaveLength(PROJECT_COUNTRIES.length + 1)
    expect(options[0]!.textContent).toContain(t('network.filters.allCountries'))
    await enterOption('Italy')
    expect(router.currentRoute.value.query.country).toBe('IT')
    expect(lastQuery(fetchMock).get('country')).toBe('IT')
  })

  it('organisation select lists the organisations and filters by organisation_id', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountNetwork()
    await openSelect(wrapper, t('network.filters.organisation'))
    const labels = Array.from(document.querySelectorAll('[role="option"]')).map((o) =>
      o.textContent?.trim(),
    )
    expect(labels).toContain('University of Western Macedonia')
    expect(labels.some((l) => /UOWM|\bMC\b/.test(l ?? ''))).toBe(false)
    await clickOption('Macerata Municipality')
    expect(router.currentRoute.value.query.organisation_id).toBe('4')
    expect(lastQuery(fetchMock).get('organisation_id')).toBe('4')
  })

  it('paginates 24 per page: next page sets page=2 and skip=24', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountNetwork()
    const next = wrapper.find('[data-slot="next"]')
    expect(next.exists()).toBe(true)
    await next.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.page).toBe('2')
    expect(lastQuery(fetchMock).get('skip')).toBe('24')
    expect(cards(wrapper)[0]!.find('a').text()).toBe('Member 25')
  })

  it('has no pagination when everything fits on one page', async () => {
    mockApi(routes(pages(10)))
    const { wrapper } = await mountNetwork()
    expect(cards(wrapper)).toHaveLength(10)
    expect(wrapper.find('[data-slot="next"]').exists()).toBe(false)
  })

  it('shows an empty state with a way to clear the filters', async () => {
    mockApi(routes(reply(200, { total: 0, items: [] })))
    const { wrapper, router } = await mountNetwork('/network?country=AL')
    expect(cards(wrapper)).toHaveLength(0)
    expect(wrapper.text()).toContain(t('network.empty'))
    const clear = wrapper.findAll('button').find((b) => b.text() === t('network.clearFilters'))
    expect(clear).toBeDefined()
    await clear!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({})
  })

  it('shows an error with a retry button that fetches again', async () => {
    let calls = 0
    const fetchMock = mockApi(
      routes((r) => (++calls === 1 ? replyError(500, 'server.error')(r) : pages(60)(r))),
    )
    const { wrapper } = await mountNetwork()
    expect(wrapper.text()).toContain(t('network.loadError'))
    expect(cards(wrapper)).toHaveLength(0)
    const retry = wrapper.findAll('button').find((b) => b.text() === t('network.retry'))
    expect(retry).toBeDefined()
    await retry!.trigger('click')
    await flushPromises()
    expect(callsTo(fetchMock, MEMBERS)).toHaveLength(2)
    expect(wrapper.text()).not.toContain(t('network.loadError'))
    expect(cards(wrapper)).toHaveLength(24)
  })

  describe('profile nudge', () => {
    const ME = 'GET /api/v1/auth/me'
    const banner = () => document.querySelector('[data-testid="complete-profile-banner"]')
    const ownLink = (card: ReturnType<typeof cards>[number]) =>
      card.find('[data-testid="add-own-expertise"]')

    it('shows the banner above the member grid for a verified user without expertise', async () => {
      mockApi({ ...routes(), [ME]: reply(200, makeUser()) })
      const { wrapper } = await mountNetwork()
      const el = banner()
      expect(el).not.toBeNull()
      const grid = cards(wrapper)[0]!.element
      expect(el!.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })

    it('shows no banner for anonymous visitors or members with expertise', async () => {
      mockApi({ ...routes(), [ME]: replyError(401, 'auth.not_authenticated') })
      await mountNetwork()
      expect(banner()).toBeNull()
      unmountAll()

      mockApi({ ...routes(), [ME]: reply(200, makeUser({ expertise: [EXPERTISE[0]!] })) })
      await mountNetwork()
      expect(banner()).toBeNull()
    })

    it('own card without expertise links to the profile; others show nothing extra', async () => {
      const members = {
        total: 2,
        items: [makeMember(1, { expertise: [] }), makeMember(2, { expertise: [] })],
      }
      mockApi({ ...routes(reply(200, members)), [ME]: reply(200, makeUser({ id: 1 })) })
      const { wrapper } = await mountNetwork()
      const [own, other] = cards(wrapper)
      const link = ownLink(own!)
      expect(link.exists()).toBe(true)
      expect(link.attributes('href')).toBe('/account?tab=profile')
      expect(link.text()).toContain(t('account.nudge.ownCard'))
      expect(t('account.nudge.ownCard')).toBe('Add your expertise')
      expect(ownLink(other!).exists()).toBe(false)
      expect(other!.find('[data-testid="expertise-badge"]').exists()).toBe(false)
    })

    it('own card with expertise shows the badges, not the link', async () => {
      mockApi({ ...routes(), [ME]: reply(200, makeUser({ id: 1 })) })
      const { wrapper } = await mountNetwork()
      const own = cards(wrapper)[0]!
      expect(ownLink(own).exists()).toBe(false)
      expect(own.findAll('[data-testid="expertise-badge"]')).toHaveLength(2)
    })
  })

  describe('access (members directory for verified users only)', () => {
    const notice = () => document.querySelector('[data-testid="members-restricted"]')

    it('anonymous: a sign-in notice instead of the directory, and no members request', async () => {
      const fetchMock = mockApi({
        ...routes(),
        [AUTH_ME]: replyError(401, 'auth.not_authenticated'),
      })
      const { wrapper } = await mountNetwork()
      expect(wrapper.find('h1').text()).toBe(t('network.title'))
      expect(callsTo(fetchMock, MEMBERS)).toHaveLength(0)
      expect(notice()?.textContent).toContain(t('network.restricted.signIn'))
      expect(notice()?.querySelector('a[href="/login?next=/network"]')).not.toBeNull()
      expect(notice()?.querySelector('a[href="/partners"]')?.textContent).toContain(
        t('network.restricted.partners'),
      )
      expect(wrapper.find('#network-filters-heading').exists()).toBe(false)
      expect(cards(wrapper)).toHaveLength(0)
      expect(wrapper.text()).not.toContain(t('network.loadError'))
    })

    it('unverified: a verify-your-email notice, and no members request', async () => {
      const fetchMock = mockApi({
        ...routes(),
        [AUTH_ME]: reply(200, makeUser({ is_verified: false })),
      })
      const { wrapper } = await mountNetwork()
      expect(callsTo(fetchMock, MEMBERS)).toHaveLength(0)
      expect(notice()?.textContent).toContain(t('network.restricted.verify'))
      expect(notice()?.querySelector('a[href^="/login"]')).toBeNull()
      expect(cards(wrapper)).toHaveLength(0)
    })

    it('verified: the directory loads', async () => {
      const fetchMock = mockApi(routes())
      const { wrapper } = await mountNetwork()
      expect(callsTo(fetchMock, MEMBERS)).toHaveLength(1)
      expect(notice()).toBeNull()
      expect(cards(wrapper)).toHaveLength(24)
    })

    it('a 401 or 403 from the API shows the notice, not an error', async () => {
      for (const [status, code] of [
        [401, 'auth.not_authenticated'],
        [403, 'auth.email_not_verified'],
      ] as const) {
        mockApi(routes(replyError(status, code)))
        const { wrapper } = await mountNetwork()
        expect(notice(), String(status)).not.toBeNull()
        expect(wrapper.text()).not.toContain(t('network.loadError'))
        unmountAll()
      }
    })
  })
})

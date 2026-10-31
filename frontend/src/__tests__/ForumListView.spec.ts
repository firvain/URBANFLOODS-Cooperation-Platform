import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import ForumListView from '@/views/ForumListView.vue'
import { FORUM_SEARCH_DEBOUNCE_MS } from '@/constants/forum'
import i18n from '@/i18n'
import {
  callsTo,
  jsonResponse,
  makeUser,
  mockApi,
  reply,
  replyError,
  type Handler,
} from './helpers/api'
import { paramsOf } from './helpers/blog'
import {
  FORUM_CATEGORIES,
  FORUM_CATEGORY_LIST,
  THREADS,
  makeThread,
  threadPages,
} from './helpers/forum'
import { mountWithApp, unmountAll } from './helpers/mount'
import { enterOption, openSelect } from './helpers/select'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'

afterEach(() => {
  vi.useRealTimers()
  unmountAll()
})

function routes(threads: Handler = threadPages(45), extra: Record<string, Handler> = {}) {
  return {
    [THREADS]: threads,
    [FORUM_CATEGORIES]: reply(200, FORUM_CATEGORY_LIST),
    ...extra,
  }
}

const mountForum = (path = '/forum') => mountWithApp(ForumListView, { path })
const rows = (wrapper: VueWrapper) => wrapper.findAll('[data-testid="thread-card"]')
const chips = (wrapper: VueWrapper) => wrapper.findAll('[data-testid="category-chip"]')
const sortButton = (wrapper: VueWrapper, label: string) =>
  wrapper.findAll('[data-testid="sort-option"]').find((b) => b.text() === label)!
const lastQuery = (fetchMock: ReturnType<typeof mockApi>) =>
  paramsOf(callsTo(fetchMock, THREADS).at(-1)!.url)

describe('ForumListView', () => {
  it('has a focusable h1 and lists 20 threads per page, sorted by activity', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountForum()
    expect(wrapper.find('h1').text()).toBe(t('forum.title'))
    expect(wrapper.find('h1').attributes('tabindex')).toBe('-1')
    expect(rows(wrapper)).toHaveLength(20)
    expect(wrapper.find('[data-testid="forum-count"]').text()).toBe(
      t('forum.count', { count: 45 }, 45),
    )
    const query = lastQuery(fetchMock)
    expect(query.get('skip')).toBe('0')
    expect(query.get('limit')).toBe('20')
    expect(query.get('sort')).toBe('activity')
    expect(query.has('category')).toBe(false)
  })

  it('shows pinned threads first with the "Pinned" label and locked threads with a lock', async () => {
    mockApi(
      routes(() =>
        jsonResponse({
          total: 3,
          items: [
            makeThread(1),
            makeThread(2, { is_pinned: true, title: 'Read me first' }),
            makeThread(3, { is_locked: true }),
          ],
        }),
      ),
    )
    const { wrapper } = await mountForum()
    const [first, second, third] = rows(wrapper)
    expect(first!.find('h2').text()).toBe('Read me first')
    expect(first!.find('[data-testid="thread-pinned"]').text()).toBe(t('thread.pinned'))
    expect(second!.find('[data-testid="thread-pinned"]').exists()).toBe(false)
    expect(third!.find('[data-testid="thread-locked"]').exists()).toBe(true)
  })

  it('loads forum categories as chips; a chip writes the category to the URL', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountForum('/forum?page=2')
    expect(paramsOf(callsTo(fetchMock, FORUM_CATEGORIES)[0]!.url).get('kind')).toBe('forum')
    expect(chips(wrapper).map((c) => c.text())).toEqual([
      t('forum.filters.allCategories'),
      'General discussion',
      'Early warning',
      'Nature-based solutions',
      'Announcements',
    ])
    expect(chips(wrapper)[0]!.attributes('aria-pressed')).toBe('true')
    await chips(wrapper)[2]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ category: 'early-warning' })
    expect(lastQuery(fetchMock).get('category')).toBe('early-warning')
    expect(lastQuery(fetchMock).get('skip')).toBe('0')
    expect(chips(wrapper)[2]!.attributes('aria-pressed')).toBe('true')
  })

  it('/forum/c/:slug presets the category', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountForum('/forum/c/nbs')
    expect(lastQuery(fetchMock).get('category')).toBe('nbs')
    const nbs = chips(wrapper).find((c) => c.text() === 'Nature-based solutions')!
    expect(nbs.attributes('aria-pressed')).toBe('true')
  })

  it('the sort toggle switches between latest activity and newest', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountForum()
    const activity = sortButton(wrapper, t('forum.filters.sortActivity'))
    expect(activity.attributes('aria-pressed')).toBe('true')
    await sortButton(wrapper, t('forum.filters.sortNewest')).trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ sort: 'newest' })
    expect(lastQuery(fetchMock).get('sort')).toBe('newest')
    expect(sortButton(wrapper, t('forum.filters.sortNewest')).attributes('aria-pressed')).toBe(
      'true',
    )
    await sortButton(wrapper, t('forum.filters.sortActivity')).trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({})
    expect(lastQuery(fetchMock).get('sort')).toBe('activity')
  })

  it('?author_id= filters by author and shows a "by <name>" chip that clears it', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountForum('/forum?author_id=11')
    expect(lastQuery(fetchMock).get('author_id')).toBe('11')
    const chip = wrapper.find('[data-testid="active-author"]')
    expect(chip.text()).toContain(t('forum.filters.byAuthor', { name: 'Eleni Papadopoulou' }))
    const remove = chip.find('button')
    expect(remove.attributes('aria-label')).toBe(
      t('forum.filters.removeAuthor', { name: 'Eleni Papadopoulou' }),
    )
    await remove.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({})
    expect(lastQuery(fetchMock).has('author_id')).toBe(false)
    expect(wrapper.find('[data-testid="active-author"]').exists()).toBe(false)
  })

  it('names the author from the members API (verified viewers) when the list is empty', async () => {
    mockApi(
      routes(reply(200, { total: 0, items: [] }), {
        [ME]: reply(200, makeUser()),
        'GET /api/v1/members/11': reply(200, { id: 11, display_name: 'Eleni P.' }),
      }),
    )
    const { wrapper } = await mountForum('/forum?author_id=11&category=news')
    expect(wrapper.find('[data-testid="active-author"]').text()).toContain(
      t('forum.filters.byAuthor', { name: 'Eleni P.' }),
    )
  })

  it('does not ask the members API for anonymous viewers (generic chip label)', async () => {
    const fetchMock = mockApi(routes(reply(200, { total: 0, items: [] })))
    const { wrapper } = await mountForum('/forum?author_id=11')
    expect(callsTo(fetchMock, 'GET /api/v1/members/11')).toHaveLength(0)
    expect(wrapper.find('[data-testid="active-author"]').text()).toContain(
      t('forum.filters.byAuthor', { name: t('forum.filters.unknownAuthor') }),
    )
  })

  it('keeps author_id when another filter changes', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountForum('/forum?author_id=11')
    await chips(wrapper)[1]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.author_id).toBe('11')
    expect(lastQuery(fetchMock).get('author_id')).toBe('11')
  })

  it('debounces the search, then puts q in the URL', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountForum()
    await wrapper.find('input[type="search"]').setValue('sirens')
    vi.advanceTimersByTime(FORUM_SEARCH_DEBOUNCE_MS)
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ q: 'sirens' })
    expect(lastQuery(fetchMock).get('q')).toBe('sirens')
  })

  it('the language select filters by locale', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountForum()
    await openSelect(wrapper, t('forum.filters.locale'))
    await enterOption('Italiano')
    expect(router.currentRoute.value.query.locale).toBe('it')
    expect(lastQuery(fetchMock).get('locale')).toBe('it')
  })

  it('paginates 20 per page: next page sets page=2 and skip=20', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountForum()
    await wrapper.find('[data-slot="next"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.page).toBe('2')
    expect(lastQuery(fetchMock).get('skip')).toBe('20')
    expect(rows(wrapper)[0]!.find('h2').text()).toBe('Thread 21')
  })

  it('offers "Start a discussion" only to verified users', async () => {
    mockApi(routes())
    let { wrapper } = await mountForum()
    expect(wrapper.find('a[href="/forum/new"]').exists()).toBe(false)
    unmountAll()

    mockApi(routes(threadPages(3), { [ME]: reply(200, makeUser({ is_verified: false })) }))
    ;({ wrapper } = await mountForum())
    expect(wrapper.find('a[href="/forum/new"]').exists()).toBe(false)
    unmountAll()

    mockApi(routes(threadPages(3), { [ME]: reply(200, makeUser()) }))
    ;({ wrapper } = await mountForum())
    const start = wrapper.find('a[href="/forum/new"]')
    expect(start.text()).toBe(t('forum.start'))
    expect(t('forum.start')).toBe('Start a discussion')
  })

  it('shows a status badge on the viewer’s own pending thread', async () => {
    mockApi(
      routes(() =>
        jsonResponse({
          total: 2,
          items: [makeThread(1, { status: 'pending', published_at: null }), makeThread(2)],
        }),
      ),
    )
    const { wrapper } = await mountForum()
    const [pending, published] = rows(wrapper)
    expect(pending!.find('[data-testid="post-status"]').text()).toBe(t('post.status.pending'))
    expect(published!.find('[data-testid="post-status"]').exists()).toBe(false)
  })

  it('shows an empty state, with "Clear filters" when filtered', async () => {
    mockApi(routes(reply(200, { total: 0, items: [] })))
    const { wrapper, router } = await mountForum('/forum?q=zzz&sort=newest')
    expect(wrapper.text()).toContain(t('forum.empty'))
    const clear = wrapper.findAll('button').find((b) => b.text() === t('forum.clearFilters'))!
    await clear.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({})
  })

  it('shows "no discussions yet" when nothing is filtered', async () => {
    mockApi(routes(reply(200, { total: 0, items: [] })))
    const { wrapper } = await mountForum()
    expect(wrapper.text()).toContain(t('forum.emptyAll'))
  })

  it('shows an error with a retry button', async () => {
    let calls = 0
    const fetchMock = mockApi(
      routes(() => {
        calls += 1
        return calls === 1
          ? replyError(500, 'server.error')({} as never)
          : jsonResponse({ total: 1, items: [makeThread(1)] })
      }),
    )
    const { wrapper } = await mountForum()
    const alert = wrapper.find('[role="alert"]')
    expect(alert.text()).toContain(t('forum.loadError'))
    await alert.find('button').trigger('click')
    await flushPromises()
    expect(callsTo(fetchMock, THREADS)).toHaveLength(2)
    expect(rows(wrapper)).toHaveLength(1)
  })
})

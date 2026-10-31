import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import BlogListView from '@/views/BlogListView.vue'
import { BLOG_SEARCH_DEBOUNCE_MS } from '@/constants/blog'
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
import {
  BLOG_CATEGORIES,
  CATEGORY_LIST,
  POSTS,
  TAGS,
  TAG_LIST,
  makePost,
  paramsOf,
  postPages,
} from './helpers/blog'
import { mountWithApp, unmountAll } from './helpers/mount'
import { enterOption, openSelect } from './helpers/select'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'

afterEach(() => {
  vi.useRealTimers()
  unmountAll()
})

function routes(posts: Handler = postPages(30), extra: Record<string, Handler> = {}) {
  return {
    [POSTS]: posts,
    [BLOG_CATEGORIES]: reply(200, CATEGORY_LIST),
    [TAGS]: reply(200, TAG_LIST),
    ...extra,
  }
}

const mountBlog = (path = '/blog') => mountWithApp(BlogListView, { path })
const cards = (wrapper: VueWrapper) => wrapper.findAll('[data-testid="post-card"]')
const chips = (wrapper: VueWrapper) => wrapper.findAll('[data-testid="category-chip"]')
const lastQuery = (fetchMock: ReturnType<typeof mockApi>) =>
  paramsOf(callsTo(fetchMock, POSTS).at(-1)!.url)

describe('BlogListView', () => {
  it('has a focusable h1 and lists 12 post cards with a count', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountBlog()
    expect(wrapper.find('h1').text()).toBe(t('blog.title'))
    expect(wrapper.find('h1').attributes('tabindex')).toBe('-1')
    expect(cards(wrapper)).toHaveLength(12)
    expect(wrapper.find('[data-testid="blog-count"]').text()).toBe(
      t('blog.count', { count: 30 }, 30),
    )
    const query = lastQuery(fetchMock)
    expect(query.get('skip')).toBe('0')
    expect(query.get('limit')).toBe('12')
    expect(query.has('q')).toBe(false)
    expect(query.has('category')).toBe(false)
  })

  it('shows category chips from the API, "All" first and pressed, admin-only ones included', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountBlog()
    expect(paramsOf(callsTo(fetchMock, BLOG_CATEGORIES)[0]!.url).get('kind')).toBe('blog')
    expect(chips(wrapper).map((c) => c.text())).toEqual([
      t('blog.filters.allCategories'),
      'News',
      'Best practices',
      'Events',
      'Project updates',
    ])
    expect(chips(wrapper)[0]!.attributes('aria-pressed')).toBe('true')
    expect(chips(wrapper)[1]!.attributes('aria-pressed')).toBe('false')
  })

  it('clicking a category chip writes category to the URL and refetches', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountBlog('/blog?page=2')
    await chips(wrapper)[1]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ category: 'news' })
    expect(lastQuery(fetchMock).get('category')).toBe('news')
    expect(lastQuery(fetchMock).get('skip')).toBe('0')
    expect(chips(wrapper)[1]!.attributes('aria-pressed')).toBe('true')
    await chips(wrapper)[0]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({})
    expect(lastQuery(fetchMock).has('category')).toBe(false)
  })

  it('/blog/category/:slug presets the category', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountBlog('/blog/category/events')
    expect(lastQuery(fetchMock).get('category')).toBe('events')
    const events = chips(wrapper).find((c) => c.text() === 'Events')!
    expect(events.attributes('aria-pressed')).toBe('true')
  })

  it('/blog/tag/:slug presets the tag, shown as a chip that can be removed', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountBlog('/blog/tag/nbs')
    expect(lastQuery(fetchMock).get('tag')).toBe('nbs')
    const chip = wrapper.find('[data-testid="active-tag"]')
    expect(chip.text()).toContain('nbs')
    await chip.find('button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/blog')
    expect(lastQuery(fetchMock).has('tag')).toBe(false)
  })

  it('a ?tag= query filters by tag too', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountBlog('/blog?tag=urban-drainage&category=news')
    expect(lastQuery(fetchMock).get('tag')).toBe('urban-drainage')
    expect(lastQuery(fetchMock).get('category')).toBe('news')
    expect(wrapper.find('[data-testid="active-tag"]').exists()).toBe(true)
  })

  it('debounces the search, then puts q in the URL and refetches', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountBlog()
    const before = callsTo(fetchMock, POSTS).length
    await wrapper.find('input[type="search"]').setValue('rain')
    expect(callsTo(fetchMock, POSTS)).toHaveLength(before)
    vi.advanceTimersByTime(BLOG_SEARCH_DEBOUNCE_MS)
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ q: 'rain' })
    expect(lastQuery(fetchMock).get('q')).toBe('rain')
  })

  it('the language select filters by locale', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountBlog()
    await openSelect(wrapper, t('blog.filters.locale'))
    await enterOption('Ελληνικά')
    expect(router.currentRoute.value.query.locale).toBe('el')
    expect(lastQuery(fetchMock).get('locale')).toBe('el')
  })

  it('sort=events asks for upcoming events', async () => {
    const fetchMock = mockApi(routes())
    await mountBlog('/blog?sort=events')
    expect(lastQuery(fetchMock).get('sort')).toBe('events')
    expect(lastQuery(fetchMock).get('upcoming_only')).toBe('true')
  })

  it('the sort select writes sort to the URL', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountBlog()
    await openSelect(wrapper, t('blog.filters.sort'))
    await enterOption(t('blog.filters.sortOldest'))
    expect(router.currentRoute.value.query.sort).toBe('oldest')
    expect(lastQuery(fetchMock).get('sort')).toBe('oldest')
    expect(lastQuery(fetchMock).has('upcoming_only')).toBe(false)
  })

  it('paginates 12 per page: next page sets page=2 and skip=12', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountBlog()
    await wrapper.find('[data-slot="next"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.page).toBe('2')
    expect(lastQuery(fetchMock).get('skip')).toBe('12')
    expect(cards(wrapper)[0]!.find('h2').text()).toBe('Post 13')
  })

  it('offers "Write a post" only to verified users', async () => {
    mockApi(routes())
    let { wrapper } = await mountBlog()
    expect(wrapper.find('a[href="/blog/new"]').exists()).toBe(false)
    unmountAll()

    mockApi(routes(postPages(30), { [ME]: reply(200, makeUser({ is_verified: false })) }))
    ;({ wrapper } = await mountBlog())
    expect(wrapper.find('a[href="/blog/new"]').exists()).toBe(false)
    unmountAll()

    mockApi(routes(postPages(30), { [ME]: reply(200, makeUser()) }))
    ;({ wrapper } = await mountBlog())
    const write = wrapper.find('a[href="/blog/new"]')
    expect(write.exists()).toBe(true)
    expect(write.text()).toBe(t('blog.write'))
  })

  it('shows a status badge on a pending post the viewer can see', async () => {
    mockApi(
      routes(() =>
        jsonResponse({
          total: 2,
          items: [makePost(1, { status: 'pending', published_at: null }), makePost(2)],
        }),
      ),
    )
    const { wrapper } = await mountBlog()
    const [pending, published] = cards(wrapper)
    expect(pending!.find('[data-testid="post-status"]').text()).toBe(t('post.status.pending'))
    expect(published!.find('[data-testid="post-status"]').exists()).toBe(false)
  })

  it('shows an empty state, with "Clear filters" when filtered', async () => {
    mockApi(routes(reply(200, { total: 0, items: [] })))
    const { wrapper, router } = await mountBlog('/blog?category=news&q=zzz')
    expect(cards(wrapper)).toHaveLength(0)
    expect(wrapper.text()).toContain(t('blog.empty'))
    const clear = wrapper.findAll('button').find((b) => b.text() === t('blog.clearFilters'))!
    await clear.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({})
  })

  it('shows "no posts yet" when nothing is filtered', async () => {
    mockApi(routes(reply(200, { total: 0, items: [] })))
    const { wrapper } = await mountBlog()
    expect(wrapper.text()).toContain(t('blog.emptyAll'))
  })

  it('shows an error with a retry button that fetches again', async () => {
    let calls = 0
    const fetchMock = mockApi(
      routes(() => {
        calls += 1
        return calls === 1
          ? replyError(500, 'server.error')({} as never)
          : jsonResponse({ total: 1, items: [makePost(1)] })
      }),
    )
    const { wrapper } = await mountBlog()
    const alert = wrapper.find('[role="alert"]')
    expect(alert.text()).toContain(t('blog.loadError'))
    await alert.find('button').trigger('click')
    await flushPromises()
    expect(callsTo(fetchMock, POSTS)).toHaveLength(2)
    expect(cards(wrapper)).toHaveLength(1)
  })

  it('still lists posts when the categories cannot be loaded', async () => {
    mockApi(routes(postPages(3), { [BLOG_CATEGORIES]: replyError(500, 'server.error') }))
    const { wrapper } = await mountBlog()
    expect(cards(wrapper)).toHaveLength(3)
    expect(chips(wrapper).map((c) => c.text())).toEqual([t('blog.filters.allCategories')])
  })
})

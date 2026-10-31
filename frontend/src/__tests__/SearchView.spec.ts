import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import SearchView from '@/views/SearchView.vue'
import i18n from '@/i18n'
import { formatDate } from '@/utils/datetime'
import { callsTo, mockApi, reply, replyError, type Handler } from './helpers/api'
import { paramsOf } from './helpers/blog'
import { mountWithApp, unmountAll } from './helpers/mount'
import { SEARCH, hitPages, makeHit } from './helpers/search'

const t = i18n.global.t

afterEach(unmountAll)

const mountSearch = (path = '/search') => mountWithApp(SearchView, { path })
const lastParams = (fetchMock: ReturnType<typeof mockApi>) =>
  paramsOf(callsTo(fetchMock, SEARCH).at(-1)!.url)
const results = (wrapper: VueWrapper) => wrapper.findAll('[data-testid="search-result"]')
const status = (wrapper: VueWrapper) => wrapper.find('[data-testid="search-count"]')
const input = (wrapper: VueWrapper) =>
  wrapper.find<HTMLInputElement>('form[role="search"] input[type="search"]')

/** The type option (a `role="radio"` button, labelled by its text) named `text`. */
function typeOption(text: string): HTMLElement {
  const radio = Array.from(document.querySelectorAll<HTMLElement>('[role="radio"]')).find(
    (r) => r.getAttribute('aria-label') === text,
  )
  expect(radio, `type option ${text}`).toBeDefined()
  return radio!
}

async function submit(wrapper: VueWrapper, text: string) {
  await input(wrapper).setValue(text)
  await wrapper.find('form[role="search"]').trigger('submit')
  await flushPromises()
}

const routes = (handler: Handler = hitPages(12)) => ({ [SEARCH]: handler })

describe('SearchView', () => {
  it('has a focusable h1 and a labelled search form with a submit button', async () => {
    mockApi(routes())
    const { wrapper } = await mountSearch()
    expect(wrapper.find('h1').text()).toBe(t('search.title'))
    expect(wrapper.find('h1').attributes('tabindex')).toBe('-1')
    const form = wrapper.find('form[role="search"]')
    expect(form.exists()).toBe(true)
    expect(form.attributes('aria-label')).toBe(t('search.formLabel'))
    expect(input(wrapper).attributes('aria-label')).toBe(t('search.inputLabel'))
    expect(form.find('button[type="submit"]').text()).toContain(t('search.submit'))
  })

  it('without a query asks for one and makes no request', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountSearch()
    expect(callsTo(fetchMock, SEARCH)).toHaveLength(0)
    expect(wrapper.find('[data-testid="search-prompt"]').text()).toBe(t('search.prompt'))
    expect(status(wrapper).text()).toBe('')
  })

  it('reads q, type, locale and page from the URL into the request and the form', async () => {
    const fetchMock = mockApi(routes(hitPages(60)))
    const { wrapper } = await mountSearch('/search?q=flood&type=threads&locale=el&page=2')
    const params = lastParams(fetchMock)
    expect(params.get('q')).toBe('flood')
    expect(params.get('type')).toBe('threads')
    expect(params.get('locale')).toBe('el')
    expect(params.get('skip')).toBe('20')
    expect(params.get('limit')).toBe('20')
    expect(input(wrapper).element.value).toBe('flood')
    expect(typeOption(t('search.types.threads')).getAttribute('aria-checked')).toBe('true')
  })

  it('treats an unknown type in the URL as "all"', async () => {
    const fetchMock = mockApi(routes())
    await mountSearch('/search?q=flood&type=bogus')
    expect(lastParams(fetchMock).get('type')).toBe('all')
    expect(typeOption(t('search.types.all')).getAttribute('aria-checked')).toBe('true')
  })

  it('submitting the form writes q to the URL and searches', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountSearch('/search?page=3')
    await submit(wrapper, '  rain gardens ')
    expect(router.currentRoute.value.query).toEqual({ q: 'rain gardens' })
    expect(lastParams(fetchMock).get('q')).toBe('rain gardens')
    expect(lastParams(fetchMock).get('skip')).toBe('0')
  })

  it('follows URL changes (back/forward): new query in the input and a new request', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountSearch('/search?q=flood')
    await router.push('/search?q=drought')
    await flushPromises()
    expect(input(wrapper).element.value).toBe('drought')
    expect(lastParams(fetchMock).get('q')).toBe('drought')
  })

  it('a query shorter than 2 characters shows a notice and makes no request', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountSearch('/search?q=a')
    expect(callsTo(fetchMock, SEARCH)).toHaveLength(0)
    expect(wrapper.find('[data-testid="search-too-short"]').text()).toBe(
      t('search.tooShort', { min: 2 }),
    )
    expect(results(wrapper)).toHaveLength(0)
  })

  it('submitting a one-character query shows the notice without calling the API', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountSearch()
    await submit(wrapper, 'x')
    expect(callsTo(fetchMock, SEARCH)).toHaveLength(0)
    expect(wrapper.find('[data-testid="search-too-short"]').exists()).toBe(true)
  })

  it('renders posts and threads with their badge, link, author, category and date', async () => {
    mockApi(routes())
    const { wrapper } = await mountSearch('/search?q=flood')
    expect(results(wrapper)).toHaveLength(12)
    const [post, thread] = results(wrapper)
    expect(post!.find('h2 a').attributes('href')).toBe('/blog/post-1')
    expect(post!.find('h2 a').text()).toBe('Post 1 about floods')
    expect(post!.find('[data-testid="search-result-type"]').text()).toBe(t('search.badge.post'))
    expect(thread!.find('h2 a').attributes('href')).toBe('/forum/t/thread-2')
    expect(thread!.find('[data-testid="search-result-type"]').text()).toBe(t('search.badge.thread'))
    expect(post!.text()).toContain('Eleni Papadopoulou')
    expect(post!.text()).toContain('Best practices')
    expect(post!.find('time').attributes('datetime')).toBe('2026-10-20T09:00:00Z')
    expect(post!.find('time').text()).toBe(formatDate('2026-10-20T09:00:00Z', 'en'))
  })

  it('keeps <mark> in snippets and strips every other tag and scripts', async () => {
    mockApi(
      routes(
        reply(200, {
          total: 1,
          items: [
            makeHit(1, {
              snippet:
                'Rain <mark>gardens</mark> <b>bold</b> <a href="/x">link</a><script>window.hacked = 1</script>',
            }),
          ],
        }),
      ),
    )
    const { wrapper } = await mountSearch('/search?q=gardens')
    const snippet = results(wrapper)[0]!.find('[data-testid="search-snippet"]')
    expect(snippet.find('mark').text()).toBe('gardens')
    expect(snippet.find('b').exists()).toBe(false)
    expect(snippet.find('a').exists()).toBe(false)
    expect(snippet.find('script').exists()).toBe(false)
    expect(snippet.text()).toContain('bold')
    expect(snippet.html()).not.toContain('hacked')
    expect(snippet.attributes('lang')).toBe('en')
  })

  it('announces the result count for the query in a polite live region', async () => {
    mockApi(routes())
    const { wrapper } = await mountSearch('/search?q=flood')
    expect(status(wrapper).attributes('aria-live')).toBe('polite')
    expect(status(wrapper).text()).toBe(t('search.count', { count: 12, query: 'flood' }, 12))
    expect(status(wrapper).text()).toContain('12')
    expect(status(wrapper).text()).toContain('“flood”')
  })

  it('shows an empty state when nothing matches', async () => {
    mockApi(routes(reply(200, { total: 0, items: [] })))
    const { wrapper } = await mountSearch('/search?q=zzzz')
    expect(wrapper.find('[data-testid="search-empty"]').text()).toContain(
      t('search.empty', { query: 'zzzz' }),
    )
    expect(status(wrapper).text()).toBe(t('search.count', { count: 0, query: 'zzzz' }, 0))
  })

  it('switching the type writes it to the URL and resets the page', async () => {
    const fetchMock = mockApi(routes(hitPages(60)))
    const { router } = await mountSearch('/search?q=flood&page=3')
    typeOption(t('search.types.threads')).click()
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ q: 'flood', type: 'threads' })
    expect(lastParams(fetchMock).get('type')).toBe('threads')
    expect(lastParams(fetchMock).get('skip')).toBe('0')
  })

  it('switching back to "All" removes type from the URL', async () => {
    mockApi(routes())
    const { router } = await mountSearch('/search?q=flood&type=posts')
    typeOption(t('search.types.all')).click()
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ q: 'flood' })
  })

  it('paginates 20 per page: next page sets page=2 and skip=20', async () => {
    const fetchMock = mockApi(routes(hitPages(45)))
    const { wrapper, router } = await mountSearch('/search?q=flood')
    expect(results(wrapper)).toHaveLength(20)
    await wrapper.find('[data-slot="next"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ q: 'flood', page: '2' })
    expect(lastParams(fetchMock).get('skip')).toBe('20')
    expect(results(wrapper)[0]!.find('h2 a').text()).toBe('Post 21 about floods')
  })

  it('has no pagination for a single page', async () => {
    mockApi(routes(hitPages(12)))
    const { wrapper } = await mountSearch('/search?q=flood')
    expect(wrapper.find('[data-slot="next"]').exists()).toBe(false)
  })

  it('shows an error with retry when the search fails (429 included)', async () => {
    const fetchMock = mockApi(routes(replyError(429, 'rate_limited')))
    const { wrapper } = await mountSearch('/search?q=flood')
    const alert = wrapper.find('[role="alert"]')
    expect(alert.text()).toContain(t('search.error'))
    mockApi(routes())
    await alert.find('button').trigger('click')
    await flushPromises()
    expect(callsTo(fetchMock, SEARCH)).toHaveLength(1)
    expect(results(wrapper)).toHaveLength(12)
  })

  it('sets the page title with the query', async () => {
    mockApi(routes())
    await mountSearch('/search?q=flood')
    await vi.waitFor(() =>
      expect(document.title).toBe(
        `${t('search.titleWithQuery', { query: 'flood' })} · ${t('app.title')}`,
      ),
    )
  })
})

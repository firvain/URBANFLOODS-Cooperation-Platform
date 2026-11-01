import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, RouterView, type RouteLocationNormalized } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import ui from '@nuxt/ui/vue-plugin'
import { defineComponent, h } from 'vue'

import i18n from '@/i18n'
import { createAppRouter, scrollBehavior } from '@/router'
import { mockApi } from './helpers/api'
import { mountApp, unmountAll } from './helpers/mount'

const t = i18n.global.t

describe('routes', () => {
  const router = createAppRouter(createMemoryHistory())

  it.each([
    ['/', 'home'],
    ['/about', 'about'],
    ['/network', 'network'],
    ['/u/5', 'profile'],
    ['/terms', 'terms'],
    ['/privacy', 'privacy'],
    ['/accessibility', 'accessibility'],
    ['/open-data', 'open-data'],
    ['/knowbase/measures', 'knowbase-measures'],
    ['/knowbase/measures/12', 'knowbase-measure'],
    ['/knowbase/documents/34', 'knowbase-document'],
    ['/blog', 'blog'],
    ['/blog/category/news', 'blog-category'],
    ['/blog/tag/nbs', 'blog-tag'],
    ['/blog/new', 'post-new'],
    ['/blog/rain-gardens', 'post'],
    ['/blog/rain-gardens/edit', 'post-edit'],
    ['/forum', 'forum'],
    ['/forum/c/early-warning', 'forum-category'],
    ['/forum/new', 'thread-new'],
    ['/forum/t/sirens-or-sms', 'thread'],
    ['/forum/t/sirens-or-sms/edit', 'thread-edit'],
    ['/search', 'search'],
    ['/this/does/not/exist', 'not-found'],
  ])('%s resolves to %s with an i18n meta.title', (path, name) => {
    const resolved = router.resolve(path)
    expect(resolved.name).toBe(name)
    const title = resolved.meta.title
    expect(typeof title).toBe('string')
    expect(i18n.global.te(title as string, 'en')).toBe(true)
  })
})

describe('/partners (merged into the About page, user decision 2026-10-31)', () => {
  it('keeps the route name and redirects to the partnership section of /about', async () => {
    setActivePinia(createPinia())
    mockApi()
    const router = createAppRouter(createMemoryHistory())
    expect(router.resolve({ name: 'partners' }).path).toBe('/partners')
    await router.push('/partners')
    expect(router.currentRoute.value.name).toBe('about')
    expect(router.currentRoute.value.path).toBe('/about')
    expect(router.currentRoute.value.hash).toBe('#partnership')
  })

  it('scrolls to the section below the sticky header', () => {
    const router = createAppRouter(createMemoryHistory())
    document.body.innerHTML = '<header></header>'
    Object.defineProperty(document.querySelector('header')!, 'offsetHeight', { value: 64 })
    const to = router.resolve('/about#partnership') as unknown as RouteLocationNormalized
    expect(scrollBehavior(to, to, null)).toEqual({ el: '#partnership', top: 80 })
    document.body.innerHTML = ''
  })
})

it('the network route is titled nav.network; the profile route takes an id and needs a verified account', () => {
  const router = createAppRouter(createMemoryHistory())
  expect(router.resolve('/network').meta.title).toBe('nav.network')
  const profile = router.resolve('/u/42')
  expect(profile.params.id).toBe('42')
  expect(profile.meta.auth).toBe('verified')
  expect(router.resolve('/network').meta.auth).toBeUndefined()
})

it('the KNOWBASE item routes are public and take an id; only the measures glance page lists', () => {
  const router = createAppRouter(createMemoryHistory())
  const measure = router.resolve('/knowbase/measures/12')
  const doc = router.resolve('/knowbase/documents/34')
  expect(measure.meta.title).toBe('knowbase.measures.detailTitle')
  expect(doc.meta.title).toBe('knowbase.documents.detailTitle')
  expect(measure.params.id).toBe('12')
  expect(doc.params.id).toBe('34')
  expect(measure.meta.auth).toBeUndefined()
  expect(doc.meta.auth).toBeUndefined()
  // Browsing happens on the KNOWBASE site itself (user decision 2026-10-31); 7c adds back one
  // read-only page, "Flood Management Measures", not a library.
  const glance = router.resolve('/knowbase/measures')
  expect(glance.name).toBe('knowbase-measures')
  expect(glance.meta.title).toBe('knowbase.glance.title')
  expect(glance.meta.auth).toBeUndefined()
  expect(glance.matched[0]!.components!.default).not.toBe(measure.matched[0]!.components!.default)
  for (const path of ['/knowbase', '/knowbase/documents']) {
    expect(router.resolve(path).name).toBe('not-found')
  }
  for (const name of ['knowbase', 'knowbase-documents']) {
    expect(router.hasRoute(name)).toBe(false)
  }
})

it('the blog list routes are public, titled nav.blog, and share one view', () => {
  const router = createAppRouter(createMemoryHistory())
  const list = router.resolve('/blog')
  expect(list.meta.title).toBe('nav.blog')
  expect(list.meta.auth).toBeUndefined()
  const category = router.resolve('/blog/category/news')
  const tag = router.resolve('/blog/tag/nbs')
  expect(category.params.slug).toBe('news')
  expect(tag.params.slug).toBe('nbs')
  expect(category.meta.auth).toBeUndefined()
  const view = list.matched[0]!.components!.default
  expect(category.matched[0]!.components!.default).toBe(view)
  expect(tag.matched[0]!.components!.default).toBe(view)
})

it('writing and editing posts need a verified account; reading is public', () => {
  const router = createAppRouter(createMemoryHistory())
  expect(router.resolve('/blog/new').meta.auth).toBe('verified')
  const edit = router.resolve('/blog/rain-gardens/edit')
  expect(edit.meta.auth).toBe('verified')
  expect(edit.params.slug).toBe('rain-gardens')
  expect(edit.matched[0]!.components!.default).toBe(
    router.resolve('/blog/new').matched[0]!.components!.default,
  )
  const post = router.resolve('/blog/rain-gardens')
  expect(post.meta.auth).toBeUndefined()
  expect(post.params.slug).toBe('rain-gardens')
})

it('the forum: list routes public and titled nav.forum, starting/editing a thread needs verified', () => {
  const router = createAppRouter(createMemoryHistory())
  const list = router.resolve('/forum')
  expect(list.meta.title).toBe('nav.forum')
  expect(list.meta.auth).toBeUndefined()
  const category = router.resolve('/forum/c/early-warning')
  expect(category.params.slug).toBe('early-warning')
  expect(category.meta.title).toBe('nav.forum')
  expect(category.matched[0]!.components!.default).toBe(list.matched[0]!.components!.default)
  expect(router.resolve('/forum/new').meta.auth).toBe('verified')
  const edit = router.resolve('/forum/t/sirens-or-sms/edit')
  expect(edit.meta.auth).toBe('verified')
  expect(edit.params.slug).toBe('sirens-or-sms')
  expect(edit.matched[0]!.components!.default).toBe(
    router.resolve('/forum/new').matched[0]!.components!.default,
  )
  const thread = router.resolve('/forum/t/sirens-or-sms')
  expect(thread.meta.auth).toBeUndefined()
  expect(thread.params.slug).toBe('sirens-or-sms')
})

it('the legal routes are public, titled legal.* and pass the document to LegalView', () => {
  const router = createAppRouter(createMemoryHistory())
  const terms = router.resolve('/terms')
  const privacy = router.resolve('/privacy')
  expect(terms.meta.title).toBe('legal.termsTitle')
  expect(privacy.meta.title).toBe('legal.privacyTitle')
  expect(terms.meta.auth).toBeUndefined()
  expect(privacy.meta.auth).toBeUndefined()
  expect(terms.matched[0]!.props.default).toEqual({ doc: 'terms' })
  expect(privacy.matched[0]!.props.default).toEqual({ doc: 'privacy' })
  const accessibility = router.resolve('/accessibility')
  const openData = router.resolve('/open-data')
  expect(accessibility.meta.title).toBe('legal.accessibilityTitle')
  expect(openData.meta.title).toBe('legal.openDataTitle')
  expect(accessibility.meta.auth).toBeUndefined()
  expect(openData.meta.auth).toBeUndefined()
  expect(accessibility.matched[0]!.props.default).toEqual({ doc: 'accessibility' })
  expect(openData.matched[0]!.props.default).toEqual({ doc: 'openData' })
})

describe('scrollBehavior', () => {
  const router = createAppRouter(createMemoryHistory())
  const at = (path: string) => router.resolve(path) as unknown as RouteLocationNormalized

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('restores the saved position on back/forward', () => {
    const saved = { left: 0, top: 420 }
    expect(scrollBehavior(at('/terms#x'), at('/'), saved)).toBe(saved)
  })

  it('scrolls to the hash target, below the sticky header', () => {
    document.body.innerHTML = '<header style="height: 72px"></header>'
    Object.defineProperty(document.querySelector('header')!, 'offsetHeight', { value: 72 })
    expect(scrollBehavior(at('/terms#section-8'), at('/terms'), null)).toEqual({
      el: '#section-8',
      top: 88,
    })
  })

  it('scrolls to the top otherwise', () => {
    expect(scrollBehavior(at('/about'), at('/'), null)).toEqual({
      top: 0,
    })
  })
})

describe('navigation', () => {
  afterEach(unmountAll)

  async function mountAt(path: string) {
    const router = createAppRouter(createMemoryHistory())
    const Root = defineComponent({ render: () => h(RouterView) })
    const wrapper = mount(Root, {
      global: { plugins: [createPinia(), router, i18n, ui] },
    })
    await router.push(path)
    await router.isReady()
    await flushPromises()
    return { wrapper, router }
  }

  it('renders the NotFound view for an unknown path', async () => {
    const { wrapper } = await mountAt('/nope/never')
    expect(wrapper.find('h1').text()).toBe(t('errors.notFound'))
    expect(wrapper.find('a[href="/"]').exists()).toBe(true)
  })

  // `document.title` is owned by `usePageHead` (App.vue keeps the route title as the fallback),
  // so these mount the whole app; unhead writes the DOM after a tick.
  it('sets document.title from meta.title and the app title', async () => {
    await mountApp('/about')
    await vi.waitFor(() => expect(document.title).toBe(`${t('nav.about')} · ${t('app.title')}`))
  })

  it('sets the blog page title', async () => {
    await mountApp('/blog')
    await vi.waitFor(() => expect(document.title).toBe(`${t('nav.blog')} · ${t('app.title')}`))
  })

  it('sets the legal page titles', async () => {
    const { router } = await mountApp('/terms')
    await vi.waitFor(() =>
      expect(document.title).toBe(`${t('legal.termsTitle')} · ${t('app.title')}`),
    )
    await router.push('/privacy')
    await vi.waitFor(() =>
      expect(document.title).toBe(`${t('legal.privacyTitle')} · ${t('app.title')}`),
    )
    await router.push('/accessibility')
    await vi.waitFor(() =>
      expect(document.title).toBe(`${t('legal.accessibilityTitle')} · ${t('app.title')}`),
    )
    await router.push('/open-data')
    await vi.waitFor(() =>
      expect(document.title).toBe(`${t('legal.openDataTitle')} · ${t('app.title')}`),
    )
  })

  it('titles the search page', async () => {
    await mountApp('/search')
    await vi.waitFor(() => expect(document.title).toBe(`${t('search.title')} · ${t('app.title')}`))
  })

  it('uses the bare app title on the home page', async () => {
    await mountApp('/about')
    await vi.waitFor(() => expect(document.title).toContain(t('nav.about')))
    unmountAll()
    await mountApp('/')
    await vi.waitFor(() => expect(document.title).toBe(t('app.title')))
  })
})

import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, RouterView, type RouteLocationNormalized } from 'vue-router'
import { createPinia } from 'pinia'
import ui from '@nuxt/ui/vue-plugin'
import { defineComponent, h } from 'vue'

import i18n from '@/i18n'
import { createAppRouter, scrollBehavior } from '@/router'

const t = i18n.global.t

describe('routes', () => {
  const router = createAppRouter(createMemoryHistory())

  it.each([
    ['/', 'home'],
    ['/partners', 'partners'],
    ['/about', 'about'],
    ['/network', 'network'],
    ['/u/5', 'profile'],
    ['/terms', 'terms'],
    ['/privacy', 'privacy'],
    ['/knowbase', 'knowbase'],
    ['/knowbase/measures', 'knowbase-measures'],
    ['/knowbase/measures/12', 'knowbase-measure'],
    ['/knowbase/documents', 'knowbase-documents'],
    ['/knowbase/documents/34', 'knowbase-document'],
    ['/blog', 'blog'],
    ['/blog/category/news', 'blog-category'],
    ['/blog/tag/nbs', 'blog-tag'],
    ['/blog/new', 'post-new'],
    ['/blog/rain-gardens', 'post'],
    ['/blog/rain-gardens/edit', 'post-edit'],
    ['/this/does/not/exist', 'not-found'],
  ])('%s resolves to %s with an i18n meta.title', (path, name) => {
    const resolved = router.resolve(path)
    expect(resolved.name).toBe(name)
    const title = resolved.meta.title
    expect(typeof title).toBe('string')
    expect(i18n.global.te(title as string, 'en')).toBe(true)
  })
})

it('the network route is titled nav.network and the profile route takes an id', () => {
  const router = createAppRouter(createMemoryHistory())
  expect(router.resolve('/network').meta.title).toBe('nav.network')
  const profile = router.resolve('/u/42')
  expect(profile.params.id).toBe('42')
  expect(profile.meta.auth).toBeUndefined()
})

it('the KNOWBASE routes are public, the landing is titled nav.knowbase, details take an id', () => {
  const router = createAppRouter(createMemoryHistory())
  expect(router.resolve('/knowbase').meta.title).toBe('nav.knowbase')
  expect(router.resolve('/knowbase/measures').meta.title).toBe('knowbase.measures.title')
  expect(router.resolve('/knowbase/documents').meta.title).toBe('knowbase.documents.title')
  const measure = router.resolve('/knowbase/measures/12')
  const doc = router.resolve('/knowbase/documents/34')
  expect(measure.params.id).toBe('12')
  expect(doc.params.id).toBe('34')
  for (const path of ['/knowbase', '/knowbase/measures', '/knowbase/measures/1']) {
    expect(router.resolve(path).meta.auth).toBeUndefined()
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

  it('sets document.title from meta.title and the app title', async () => {
    await mountAt('/about')
    expect(document.title).toBe(`${t('nav.about')} | ${t('app.title')}`)
  })

  it('sets the blog page title', async () => {
    await mountAt('/blog')
    expect(document.title).toBe(`${t('nav.blog')} | ${t('app.title')}`)
  })

  it('sets the legal page titles', async () => {
    await mountAt('/terms')
    expect(document.title).toBe(`${t('legal.termsTitle')} | ${t('app.title')}`)
    await mountAt('/privacy')
    expect(document.title).toBe(`${t('legal.privacyTitle')} | ${t('app.title')}`)
  })

  it('uses the bare app title on the home page', async () => {
    await mountAt('/')
    expect(document.title).toBe(t('app.title'))
  })
})

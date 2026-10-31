import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { defineComponent, h, ref, type PropType } from 'vue'

import i18n from '@/i18n'
import { formatPageTitle, usePageHead, type PageHead } from '@/composables/usePageHead'
import { mountApp, mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const APP = 'URBANFLOODS Cooperation Platform'

afterEach(async () => {
  unmountAll()
  await new Promise((resolve) => setTimeout(resolve, 0))
  document.head
    .querySelectorAll(
      'meta[property], meta[name="description"], link[rel="canonical"], script[type="application/ld+json"]',
    )
    .forEach((node) => node.remove())
})

const Probe = defineComponent({
  props: { head: { type: Object as PropType<PageHead | null>, default: null } },
  setup(props) {
    usePageHead(() => props.head)
    return () => h('div')
  },
})

/** Two independent `usePageHead` users in one app, each switchable. */
function harness(first: PageHead | null, second: PageHead | null = null) {
  const a = ref(first)
  const b = ref(second)
  const showA = ref(true)
  const showB = ref(second !== null)
  const Root = defineComponent({
    setup: () => () =>
      h('div', [
        showA.value ? h(Probe, { head: a.value }) : null,
        showB.value ? h(Probe, { head: b.value }) : null,
      ]),
  })
  return { Root, a, b, showA, showB }
}

const meta = (selector: string) => document.head.querySelector(selector)?.getAttribute('content')
const canonical = () => document.head.querySelector('link[rel="canonical"]')?.getAttribute('href')
const jsonLdScripts = () =>
  Array.from(document.head.querySelectorAll('script[type="application/ld+json"]'))
const settle = () => new Promise((resolve) => setTimeout(resolve, 20))

describe('formatPageTitle', () => {
  it('appends the platform name with a middle dot', () => {
    expect(t('app.title')).toBe(APP)
    expect(formatPageTitle('Rain gardens')).toBe(`Rain gardens · ${APP}`)
  })

  it('is the bare platform name without a title or for the platform name itself', () => {
    expect(formatPageTitle('')).toBe(APP)
    expect(formatPageTitle(null)).toBe(APP)
    expect(formatPageTitle(APP)).toBe(APP)
  })
})

describe('usePageHead', () => {
  it('sets the title, description and Open Graph tags', async () => {
    const { Root } = harness({
      title: 'Rain gardens',
      description: 'How Kozani reduces runoff.',
      type: 'article',
      image: '/static/uploads/cover.jpg',
    })
    await mountWithApp(Root, { path: '/blog/rain-gardens' })
    await vi.waitFor(() => expect(document.title).toBe(`Rain gardens · ${APP}`))
    expect(meta('meta[name="description"]')).toBe('How Kozani reduces runoff.')
    expect(meta('meta[property="og:title"]')).toBe('Rain gardens')
    expect(meta('meta[property="og:description"]')).toBe('How Kozani reduces runoff.')
    expect(meta('meta[property="og:type"]')).toBe('article')
    expect(meta('meta[property="og:image"]')).toBe(
      `${window.location.origin}/static/uploads/cover.jpg`,
    )
  })

  it('defaults canonical and og:url to the current path without the query', async () => {
    const { Root } = harness({ title: 'Rain gardens' })
    await mountWithApp(Root, { path: '/blog/rain-gardens?utm=x#top' })
    await vi.waitFor(() => expect(canonical()).toBe(`${window.location.origin}/blog/rain-gardens`))
    expect(meta('meta[property="og:url"]')).toBe(`${window.location.origin}/blog/rain-gardens`)
    expect(meta('meta[property="og:type"]')).toBe('website')
  })

  it('uses an explicit canonical URL for canonical and og:url', async () => {
    const { Root } = harness({ title: 'Search', canonical: '/search?q=flood' })
    await mountWithApp(Root, { path: '/search?q=flood&page=2' })
    await vi.waitFor(() => expect(canonical()).toBe(`${window.location.origin}/search?q=flood`))
    expect(meta('meta[property="og:url"]')).toBe(`${window.location.origin}/search?q=flood`)
  })

  it('follows changes of the input without duplicating tags', async () => {
    const { Root, a } = harness({ title: 'First', description: 'One' })
    await mountWithApp(Root)
    await vi.waitFor(() => expect(document.title).toBe(`First · ${APP}`))
    a.value = { title: 'Second', description: 'Two' }
    await flushPromises()
    await vi.waitFor(() => expect(document.title).toBe(`Second · ${APP}`))
    expect(meta('meta[name="description"]')).toBe('Two')
    expect(document.head.querySelectorAll('meta[name="description"]')).toHaveLength(1)
    expect(document.head.querySelectorAll('meta[property="og:title"]')).toHaveLength(1)
    expect(document.head.querySelectorAll('link[rel="canonical"]')).toHaveLength(1)
  })

  it('writes JSON-LD as one script and replaces it on change', async () => {
    const { Root, a } = harness({ title: 'X', jsonLd: { '@type': 'Article', headline: 'X' } })
    await mountWithApp(Root)
    await vi.waitFor(() => expect(jsonLdScripts()).toHaveLength(1))
    expect(JSON.parse(jsonLdScripts()[0]!.textContent!)).toEqual({
      '@type': 'Article',
      headline: 'X',
    })
    a.value = { title: 'Y', jsonLd: { '@type': 'Article', headline: 'Y' } }
    await flushPromises()
    await vi.waitFor(() => expect(JSON.parse(jsonLdScripts()[0]!.textContent!).headline).toBe('Y'))
    expect(jsonLdScripts()).toHaveLength(1)
  })

  it('keeps a single JSON-LD script when two components set one (the newer wins)', async () => {
    const { Root } = harness(
      { title: 'Base', jsonLd: { '@type': 'WebSite' } },
      { title: 'Page', jsonLd: { '@type': 'Article' } },
    )
    await mountWithApp(Root)
    await vi.waitFor(() => expect(document.title).toBe(`Page · ${APP}`))
    await settle()
    expect(jsonLdScripts()).toHaveLength(1)
    expect(JSON.parse(jsonLdScripts()[0]!.textContent!)['@type']).toBe('Article')
  })

  it('escapes "<" in JSON-LD so a title cannot close the script', async () => {
    const { Root } = harness({ title: 'X', jsonLd: { headline: '</script><b>x</b>' } })
    await mountWithApp(Root)
    await vi.waitFor(() => expect(jsonLdScripts()).toHaveLength(1))
    const text = jsonLdScripts()[0]!.textContent!
    expect(text).not.toContain('<')
    expect(JSON.parse(text).headline).toBe('</script><b>x</b>')
  })

  it('removes its tags when the component unmounts', async () => {
    const { Root, showA } = harness({
      title: 'Gone soon',
      description: 'Bye',
      canonical: '/blog/x',
      jsonLd: { '@type': 'Article' },
    })
    await mountWithApp(Root)
    await vi.waitFor(() => expect(jsonLdScripts()).toHaveLength(1))
    showA.value = false
    await flushPromises()
    await vi.waitFor(() => expect(jsonLdScripts()).toHaveLength(0))
    expect(document.head.querySelector('meta[name="description"]')).toBeNull()
    expect(document.head.querySelector('link[rel="canonical"]')).toBeNull()
  })

  it('sets nothing for a null input', async () => {
    const { Root } = harness(null)
    await mountWithApp(Root)
    await settle()
    expect(document.head.querySelector('meta[property="og:title"]')).toBeNull()
    expect(jsonLdScripts()).toHaveLength(0)
  })
})

describe('route title fallback (App.vue)', () => {
  it('uses the route meta title in the same format', async () => {
    await mountApp('/about')
    await vi.waitFor(() => expect(document.title).toBe(`${t('nav.about')} · ${APP}`))
  })

  it('comes back after a page with its own title is left', async () => {
    const { router } = await mountApp('/about')
    await router.push('/blog')
    await flushPromises()
    await vi.waitFor(() => expect(document.title).toBe(`${t('nav.blog')} · ${APP}`))
  })
})

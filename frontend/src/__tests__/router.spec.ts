import { describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, RouterView } from 'vue-router'
import { createPinia } from 'pinia'
import ui from '@nuxt/ui/vue-plugin'
import { defineComponent, h } from 'vue'

import i18n from '@/i18n'
import { createAppRouter } from '@/router'

const t = i18n.global.t

describe('routes', () => {
  const router = createAppRouter(createMemoryHistory())

  it.each([
    ['/', 'home'],
    ['/partners', 'partners'],
    ['/about', 'about'],
    ['/network', 'network'],
    ['/u/5', 'profile'],
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

  it('uses the bare app title on the home page', async () => {
    await mountAt('/')
    expect(document.title).toBe(t('app.title'))
  })
})

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createPinia } from 'pinia'
import { createHead } from '@unhead/vue/client'
import ui from '@nuxt/ui/vue-plugin'

import App from '@/App.vue'
import i18n, { SUPPORTED_LOCALES, setLocale } from '@/i18n'
import { createAppRouter } from '@/router'

const t = i18n.global.t

let wrapper: VueWrapper | undefined

async function mountApp(path = '/') {
  const router = createAppRouter(createMemoryHistory())
  wrapper = mount(App, {
    attachTo: document.body,
    global: { plugins: [createPinia(), router, i18n, createHead(), ui] },
  })
  await router.push(path)
  await router.isReady()
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  setLocale('en')
  localStorage.clear()
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  document.body.innerHTML = ''
})

describe('App layout', () => {
  it('renders a skip link to #main as the first focusable element', async () => {
    const { wrapper } = await mountApp()
    const skip = wrapper.find('a[href="#main"]')
    expect(skip.exists()).toBe(true)
    expect(skip.text()).toBe(t('app.skipToContent'))
    const firstFocusable = document.body.querySelector('a[href], button, select, input')
    expect(firstFocusable?.getAttribute('href')).toBe('#main')
  })

  it('renders exactly one of each landmark', async () => {
    await mountApp()
    expect(document.querySelectorAll('header')).toHaveLength(1)
    expect(document.querySelectorAll('main')).toHaveLength(1)
    expect(document.querySelectorAll('main#main')).toHaveLength(1)
    expect(document.querySelectorAll('footer')).toHaveLength(1)
    const navs = document.querySelectorAll('nav[aria-label]')
    expect(navs).toHaveLength(1)
    expect(navs[0]!.getAttribute('aria-label')).toBeTruthy()
  })

  it('shows the EU co-funding disclaimer in the footer', async () => {
    await mountApp()
    expect(document.querySelector('footer')?.textContent).toContain(t('footer.disclaimer'))
  })
})

describe('language switcher', () => {
  async function openSwitcher() {
    const trigger = document.querySelector<HTMLElement>(`[aria-label="${t('app.language')}"]`)
    expect(trigger).not.toBeNull()
    trigger!.focus()
    trigger!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flushPromises()
    return trigger!
  }

  it('offers the 9 supported locales', async () => {
    await mountApp()
    await openSwitcher()
    const options = document.querySelectorAll('[role="option"]')
    expect(options).toHaveLength(SUPPORTED_LOCALES.length)
  })

  it('switches to el: updates <html lang>, persists, re-renders text', async () => {
    await mountApp()
    await openSwitcher()
    const greek = Array.from(document.querySelectorAll<HTMLElement>('[role="option"]')).find((o) =>
      o.textContent?.includes('Ελληνικά'),
    )
    expect(greek).toBeDefined()
    greek!.focus()
    greek!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await flushPromises()

    expect(document.documentElement.lang).toBe('el')
    expect(localStorage.getItem('locale')).toBe('el')
    expect(document.querySelector('a[href="#main"]')?.textContent?.trim()).toBe(
      t('app.skipToContent'),
    )
    expect(i18n.global.locale.value).toBe('el')
  })
})

describe('focus management', () => {
  it('HomeView has a single h1 with tabindex=-1', async () => {
    await mountApp('/')
    const headings = document.querySelectorAll('main h1')
    expect(headings).toHaveLength(1)
    expect(headings[0]!.getAttribute('tabindex')).toBe('-1')
  })

  it('does not steal focus on the initial load', async () => {
    await mountApp('/')
    expect(document.activeElement?.tagName).not.toBe('H1')
  })

  it('moves focus to the new h1 and announces the title after navigation', async () => {
    const { router } = await mountApp('/')
    await router.push('/about')
    await flushPromises()

    const h1 = document.querySelector('main h1')
    expect(h1).not.toBeNull()
    expect(document.activeElement).toBe(h1)

    const live = document.querySelector('[aria-live="polite"]')
    expect(live?.textContent).toContain(t('nav.about'))
  })
})

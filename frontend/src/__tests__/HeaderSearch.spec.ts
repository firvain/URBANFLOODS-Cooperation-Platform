import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import HeaderSearch from '@/components/layout/HeaderSearch.vue'
import i18n from '@/i18n'
import { mockApi } from './helpers/api'
import { mountApp, mountWithApp, unmountAll } from './helpers/mount'
import { SEARCH, hitPages } from './helpers/search'

const t = i18n.global.t

afterEach(unmountAll)

async function submitIn(form: HTMLFormElement, text: string) {
  const input = form.querySelector<HTMLInputElement>('input[type="search"]')!
  input.value = text
  input.dispatchEvent(new Event('input'))
  await flushPromises()
  form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  await flushPromises()
}

describe('header search (desktop)', () => {
  it('is a labelled search form in the header, shown from xl', async () => {
    mockApi({ [SEARCH]: hitPages(1) })
    await mountApp('/about')
    const form = document.querySelector<HTMLFormElement>('header form[role="search"]')
    expect(form).not.toBeNull()
    expect(form!.getAttribute('aria-label')).toBe(t('search.formLabel'))
    expect(form!.className).toContain('hidden')
    expect(form!.className).toContain('xl:flex')
    expect(form!.className).not.toContain('2xl:flex')
    const input = form!.querySelector('input[type="search"]')!
    expect(input.getAttribute('aria-label')).toBe(t('search.inputLabel'))
  })

  it('submitting navigates to /search?q=… and renders the results page', async () => {
    mockApi({ [SEARCH]: hitPages(3) })
    const { router } = await mountApp('/about')
    const form = document.querySelector<HTMLFormElement>('header form[role="search"]')!
    await submitIn(form, '  rain gardens ')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/search'))
    expect(router.currentRoute.value.query).toEqual({ q: 'rain gardens' })
    await vi.waitFor(() =>
      expect(document.querySelector('main h1')?.textContent).toContain(t('search.title')),
    )
  })

  it('is collapsed to its icon and widens when focused or filled (no room in the row)', async () => {
    await mountApp('/about')
    const form = document.querySelector<HTMLFormElement>('header form[role="search"]')!
    const input = form.querySelector<HTMLInputElement>('input[type="search"]')!
    const field = input.parentElement! // the UInput root, which carries the width
    expect(field.classList.contains('w-8')).toBe(true)
    expect(field.classList.contains('focus-within:w-56')).toBe(true)
    input.value = 'flood'
    input.dispatchEvent(new Event('input'))
    await flushPromises()
    expect(field.classList.contains('w-56')).toBe(true)
    expect(field.classList.contains('w-8')).toBe(false)
  })

  it('has no separate icon link (the field fits from xl)', async () => {
    await mountApp('/about')
    expect(document.querySelector('[data-testid="header-search-link"]')).toBeNull()
  })

  it('an empty submit opens the search page without a query', async () => {
    const { router } = await mountApp('/about')
    const form = document.querySelector<HTMLFormElement>('header form[role="search"]')!
    await submitIn(form, '   ')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/search'))
    expect(router.currentRoute.value.query).toEqual({})
  })
})

describe('header search (mobile menu)', () => {
  it('renders a full-width field with a visible submit button', async () => {
    const { wrapper } = await mountWithApp(HeaderSearch, { props: { mobile: true } })
    const form = wrapper.find('form[role="search"]')
    expect(form.classes()).toContain('w-full')
    expect(form.classes()).not.toContain('hidden')
    expect(form.find('button[type="submit"]').attributes('aria-label')).toBe(t('search.submit'))
  })

  it('submitting navigates to /search?q=…', async () => {
    const { wrapper, router } = await mountWithApp(HeaderSearch, {
      path: '/forum',
      props: { mobile: true },
    })
    await submitIn(wrapper.find('form').element as HTMLFormElement, 'sirens')
    expect(router.currentRoute.value.fullPath).toBe('/search?q=sirens')
  })

  it('is in the menu body when the header menu is opened', async () => {
    mockApi({ [SEARCH]: hitPages(1) })
    const { router } = await mountApp('/about')
    const toggle = document.querySelector<HTMLButtonElement>('header button[data-slot="toggle"]')
    expect(toggle, 'menu toggle').not.toBeNull()
    toggle!.click()
    const mobileForm = () =>
      Array.from(document.querySelectorAll<HTMLFormElement>('form[role="search"]')).find((f) =>
        f.classList.contains('w-full'),
      )
    await vi.waitFor(() => expect(mobileForm(), 'mobile search form').toBeDefined())
    await submitIn(mobileForm()!, 'drought')
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/search?q=drought'))
  })
})

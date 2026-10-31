import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import LocaleSwitcher from '@/components/layout/LocaleSwitcher.vue'
import i18n, { setLocale } from '@/i18n'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t

beforeEach(() => setLocale('en'))
afterEach(() => {
  unmountAll()
  setLocale('en')
})

const trigger = () => document.querySelector<HTMLElement>('[data-testid="locale-switcher"]')!

describe('LocaleSwitcher', () => {
  it('names the full current language in its aria-label', async () => {
    await mountWithApp(LocaleSwitcher)
    expect(trigger().getAttribute('aria-label')).toBe(`${t('app.language')}: English`)
  })

  it('shows a globe and the uppercase ISO code below 2xl, the full name from 2xl', async () => {
    await mountWithApp(LocaleSwitcher)
    const short = trigger().querySelector('[data-testid="locale-code"]')!
    const full = trigger().querySelector('[data-testid="locale-name"]')!
    expect(short.textContent?.trim()).toBe('EN')
    expect(short.classList.contains('2xl:hidden')).toBe(true)
    expect(full.textContent?.trim()).toBe('English')
    expect(full.classList.contains('hidden')).toBe(true)
    expect(full.classList.contains('2xl:inline')).toBe(true)
    expect(trigger().querySelector('.iconify, [class*="i-lucide-globe"], svg')).not.toBeNull()
    expect(trigger().classList.contains('2xl:w-40')).toBe(true)
  })

  it('follows the locale (code, name and label)', async () => {
    await mountWithApp(LocaleSwitcher)
    setLocale('el')
    await flushPromises()
    expect(trigger().querySelector('[data-testid="locale-code"]')!.textContent?.trim()).toBe('EL')
    expect(trigger().getAttribute('aria-label')).toBe(`${t('app.language')}: Ελληνικά`)
  })

  it('the full variant (mobile menu) always shows the full name', async () => {
    await mountWithApp(LocaleSwitcher, { props: { full: true } })
    expect(trigger().querySelector('[data-testid="locale-code"]')).toBeNull()
    const full = trigger().querySelector('[data-testid="locale-name"]')!
    expect(full.textContent?.trim()).toBe('English')
    expect(full.classList.contains('hidden')).toBe(false)
  })
})

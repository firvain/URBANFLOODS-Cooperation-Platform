/**
 * Branding and visibility requirements (docs/branding.md): light mode only, project logo and
 * favicon assets, mandatory texts, the About page content and a guard against `dark:` classes.
 */
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import i18n, { setLocale } from '@/i18n'
import { EXTERNAL_LINKS } from '@/constants/links'
import { mountApp, unmountAll } from './helpers/mount'

const t = i18n.global.t

/** Absolute path of a file in the frontend project. */
const projectFile = (relative: string) => resolve(__dirname, '../..', relative)

/**
 * Storage key of Nuxt UI's colour mode in a plain Vue app: its `color-mode` plugin calls
 * `useDark()` from @vueuse/core, which persists to `vueuse-color-scheme` ("nuxt-ui-color-mode" is
 * the key of the Nuxt module only). Light mode is enforced by not installing that plugin at all.
 */
const COLOR_MODE_STORAGE_KEY = 'vueuse-color-scheme'

function preferDarkScheme() {
  vi.spyOn(window, 'matchMedia').mockImplementation(
    (query: string) =>
      ({
        matches: query.includes('prefers-color-scheme: dark'),
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(() => false),
      }) as unknown as MediaQueryList,
  )
}

beforeEach(() => {
  setLocale('en')
  localStorage.clear()
})

afterEach(() => {
  unmountAll()
  document.documentElement.classList.remove('dark', 'light')
})

describe('light mode only', () => {
  it('never adds the dark class, even when the OS prefers dark', async () => {
    preferDarkScheme()
    await mountApp()
    await flushPromises()
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('ignores a stored dark preference and stores no colour-mode preference itself', async () => {
    preferDarkScheme()
    await mountApp()
    await flushPromises()
    expect(localStorage.getItem(COLOR_MODE_STORAGE_KEY)).toBeNull()

    unmountAll()
    localStorage.setItem(COLOR_MODE_STORAGE_KEY, 'dark')
    await mountApp()
    await flushPromises()
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('offers no colour-mode toggle', async () => {
    await mountApp()
    const labelled = Array.from(document.querySelectorAll('[aria-label], [title]')).map((el) =>
      `${el.getAttribute('aria-label') ?? ''} ${el.getAttribute('title') ?? ''}`.toLowerCase(),
    )
    for (const label of labelled) {
      expect(label).not.toMatch(/dark|light mode|colou?r mode|theme/)
    }
    expect(document.body.textContent?.toLowerCase()).not.toMatch(/dark mode|light mode/)
  })

  it('index.html declares a light colour scheme and a white theme colour', () => {
    const html = readFileSync(projectFile('index.html'), 'utf8')
    expect(html).toMatch(/<meta name="color-scheme" content="light"\s*\/?>/)
    expect(html).toMatch(/<meta name="theme-color" content="#ffffff"\s*\/?>/)
  })
})

describe('no dark: variants in our own components', () => {
  const sources = import.meta.glob<string>(['../components/**/*.vue', '../views/**/*.vue', '../App.vue'], {
    query: '?raw',
    import: 'default',
    eager: true,
  })

  it('finds the components and views to check', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(10)
  })

  it.each(Object.entries(sources))('%s has no dark: class', (_path, source) => {
    expect(source).not.toMatch(/\bdark:/)
  })
})

describe('logo and favicon assets', () => {
  it.each([
    'src/assets/logos/interreg-urbanfloods-stacked.png',
    'src/assets/logos/interreg-urbanfloods-horizontal.png',
    'src/assets/logos/interreg-ipa-adrion.png',
    'src/assets/logos/urbanfloods-wordmark.svg',
    'public/favicon.ico',
    'public/favicon-16x16.png',
    'public/favicon-32x32.png',
    'public/apple-touch-icon.png',
    'public/android-chrome-192x192.png',
    'public/android-chrome-512x512.png',
    'public/site.webmanifest',
  ])('%s exists', (path) => {
    expect(existsSync(projectFile(path))).toBe(true)
  })

  it('site.webmanifest names the platform, is white and lists existing icons', () => {
    const manifest = JSON.parse(readFileSync(projectFile('public/site.webmanifest'), 'utf8'))
    expect(manifest.name).toBe('URBANFLOODS Cooperation Platform')
    expect(manifest.short_name).toBe('URBANFLOODS')
    expect(manifest.theme_color).toBe('#ffffff')
    expect(manifest.background_color).toBe('#ffffff')
    expect(manifest.icons.length).toBeGreaterThan(0)
    for (const icon of manifest.icons as { src: string }[]) {
      expect(existsSync(projectFile(`public${icon.src}`)), icon.src).toBe(true)
    }
  })

  it('index.html links the favicons and the manifest', () => {
    const html = readFileSync(projectFile('index.html'), 'utf8')
    for (const snippet of [
      '<link rel="icon" href="/favicon.ico" sizes="any"',
      '<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png"',
      '<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png"',
      '<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png"',
      '<link rel="manifest" href="/site.webmanifest"',
    ]) {
      expect(html).toContain(snippet)
    }
  })
})

describe('footer statement translations', () => {
  const localeFiles = import.meta.glob<{ footer?: { statement?: string } }>(
    '../i18n/locales/*.json',
    { eager: true, import: 'default' },
  )

  it('every locale translates footer.statement', () => {
    const english = t('footer.statement')
    for (const [path, messages] of Object.entries(localeFiles)) {
      const statement = messages.footer?.statement
      expect(statement, path).toBeTruthy()
      expect(statement, path).toContain('Interreg IPA ADRION')
      if (!path.endsWith('/en.json')) expect(statement, path).not.toBe(english)
    }
  })
})

describe('About page', () => {
  async function mountAbout() {
    await mountApp('/about')
    const main = document.querySelector('main')
    expect(main).not.toBeNull()
    return main!
  }

  it('has a single focusable h1 and the project description', async () => {
    const main = await mountAbout()
    const headings = main.querySelectorAll('h1')
    expect(headings).toHaveLength(1)
    expect(headings[0]!.getAttribute('tabindex')).toBe('-1')
    expect(headings[0]!.textContent?.trim()).toBe(t('about.title'))
    expect(main.textContent).toContain(t('about.description'))
    expect(t('about.description')).toContain('knowledge-sharing hub')
  })

  it('shows the stacked project logo', async () => {
    const main = await mountAbout()
    const img = main.querySelector<HTMLImageElement>('img[src*="interreg-urbanfloods-stacked"]')
    expect(img).not.toBeNull()
    expect(img!.getAttribute('alt')).toBeTruthy()
    expect(img!.classList.contains('min-w-[240px]')).toBe(true)
  })

  it('links to the project website and the KNOWBASE in a new tab', async () => {
    const main = await mountAbout()
    const hrefs = Array.from(main.querySelectorAll<HTMLAnchorElement>('a[target="_blank"]')).map(
      (a) => a.getAttribute('href'),
    )
    expect(hrefs).toEqual([EXTERNAL_LINKS.project, EXTERNAL_LINKS.knowbase])
    for (const link of main.querySelectorAll('a[target="_blank"]')) {
      expect(link.getAttribute('rel')).toContain('noopener')
      expect(link.querySelector('.sr-only')?.textContent?.trim()).toBe(t('a11y.opensInNewTab'))
    }
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import i18n, { SUPPORTED_LOCALES, setLocale } from '@/i18n'
import { EXTERNAL_LINKS } from '@/constants/links'
import { mountApp, unmountAll } from './helpers/mount'

const t = i18n.global.t

/** Required alt text of the project logo (docs/branding.md). */
const LOGO_ALT = 'Interreg IPA ADRION, co-funded by the European Union: URBANFLOODS'

beforeEach(() => {
  setLocale('en')
  localStorage.clear()
})

afterEach(() => {
  unmountAll()
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
    // One main navigation in the header and one external-links list in the footer, distinctly named.
    const headerNavs = document.querySelectorAll('header nav[aria-label]')
    const footerNavs = document.querySelectorAll('footer nav[aria-label]')
    expect(headerNavs).toHaveLength(1)
    expect(footerNavs).toHaveLength(1)
    expect(document.querySelectorAll('nav[aria-label]')).toHaveLength(2)
    expect(headerNavs[0]!.getAttribute('aria-label')).toBeTruthy()
    expect(footerNavs[0]!.getAttribute('aria-label')).toBe(t('footer.navLabel'))
    expect(footerNavs[0]!.getAttribute('aria-label')).not.toBe(
      headerNavs[0]!.getAttribute('aria-label'),
    )
  })

  it('shows the EU co-funding disclaimer in the footer', async () => {
    await mountApp()
    expect(document.querySelector('footer')?.textContent).toContain(t('footer.disclaimer'))
  })
})

describe('header branding', () => {
  function headerLogo() {
    const img = Array.from(document.querySelectorAll<HTMLImageElement>('header img')).find(
      (el) => el.getAttribute('alt') === LOGO_ALT,
    )
    expect(img, 'header logo with the required alt').toBeDefined()
    return img!
  }

  it('replaces the text title with the horizontal project logo linked to /', async () => {
    await mountApp('/about')
    const img = headerLogo()
    expect(img.getAttribute('src')).toMatch(/interreg-urbanfloods-horizontal/)
    const link = img.closest('a')
    expect(link?.getAttribute('href')).toBe('/')
    // UHeader puts `aria-label` on the link; it must name the logo, not "Nuxt UI".
    expect(link?.getAttribute('aria-label')).toBe(LOGO_ALT)
    expect(document.querySelector('header')?.textContent).not.toContain('Cooperation Platform')
  })

  // Minimum on-screen width (docs/branding.md): 240 px below lg, 300 px from lg, 384 px from xl.
  // Enforced with fixed Tailwind widths + matching min-widths + max-w-none on the <img>.
  it('declares the minimum logo width: 240 px, 300 px from lg, 384 px from xl, never shrinking', async () => {
    await mountApp()
    const classes = headerLogo().classList
    for (const cls of [
      'w-[240px]',
      'min-w-[240px]',
      'lg:w-[300px]',
      'lg:min-w-[300px]',
      'xl:w-[384px]',
      'xl:min-w-[384px]',
      'max-w-none',
      'shrink-0',
    ]) {
      expect(classes.contains(cls), cls).toBe(true)
    }
  })

  it('keeps clear space around the logo and a white header background', async () => {
    await mountApp()
    const link = headerLogo().closest('a')!
    expect(link.classList.contains('py-3')).toBe(true)
    expect(link.classList.contains('pe-4')).toBe(true)
    expect(document.querySelector('header')?.classList.contains('bg-white')).toBe(true)
  })
})

describe('page shell', () => {
  it('stacks header, main and footer in a full-height flex column', async () => {
    await mountApp()
    const main = document.querySelector('main#main')!
    const shell = main.parentElement!
    for (const cls of ['flex', 'min-h-screen', 'flex-col']) {
      expect(shell.classList.contains(cls), cls).toBe(true)
    }
    expect(main.classList.contains('flex-1')).toBe(true)
    expect(main.className).not.toContain('min-h-[calc')
    expect(document.querySelector('header')?.parentElement).toBe(shell)
    expect(document.querySelector('footer')?.parentElement).toBe(shell)
  })
})

describe('footer branding', () => {
  function footer() {
    const el = document.querySelector('footer')
    expect(el).not.toBeNull()
    return el!
  }

  /** The single inline list of external links (no column headings). */
  function externalNav() {
    const nav = footer().querySelector('nav[aria-label]')
    expect(nav, 'footer external-links nav').not.toBeNull()
    return nav!
  }

  it('shows the statement and, as the last text, the exact disclaimer in small print', async () => {
    await mountApp()
    expect(t('footer.statement')).toBe(
      'The project is co-funded by the European Union through the Interreg IPA ADRION programme.',
    )
    expect(t('footer.disclaimer')).toBe(
      'This website has been produced with the financial assistance of the European Union. The content of the website is the sole responsibility of the University of Western Macedonia and can under no circumstances be regarded as reflecting the position of the European Union and/or IPA ADRION programme authorities.',
    )
    const paragraphs = Array.from(footer().querySelectorAll('p'))
    const statement = paragraphs.find((p) => p.textContent?.trim() === t('footer.statement'))
    expect(statement).toBeDefined()
    expect(statement!.classList.contains('text-sm')).toBe(true)
    const last = paragraphs.at(-1)!
    expect(last.textContent?.trim()).toBe(t('footer.disclaimer'))
    expect(last.classList.contains('text-xs')).toBe(true)
  })

  // The footer carries the project's own illustrated logo (user decision 2026-10-30); the
  // official Interreg lock-up is in the header on every page, which satisfies the visibility rule.
  it('renders the illustrated URBANFLOODS project logo', async () => {
    await mountApp()
    expect(footer().querySelector('img[src*="interreg-urbanfloods-stacked"]')).toBeNull()
    const img = footer().querySelector<HTMLImageElement>('img[src*="urbanfloods-wordmark"]')
    expect(img).not.toBeNull()
    expect(img!.getAttribute('alt')).toBe(t('app.projectLogoAlt'))
    expect(t('app.projectLogoAlt')).toBe('URBANFLOODS project logo')
    for (const cls of ['h-12', 'w-auto', 'shrink-0']) {
      expect(img!.classList.contains(cls), cls).toBe(true)
    }
  })

  // Compact footer (2026-10-31): no columns, no headings, no internal page list (the header
  // carries the platform navigation).
  it('has no column headings and no internal page links outside the legal bar', async () => {
    await mountApp('/about')
    expect(footer().querySelectorAll('h1, h2, h3, h4, h5, h6')).toHaveLength(0)
    const internal = Array.from(footer().querySelectorAll('a'))
      .map((a) => a.getAttribute('href'))
      .filter((href) => href?.startsWith('/'))
    expect(internal).toEqual(['/terms', '/privacy'])
  })

  it('links to the project sites and LinkedIn in a new tab, announced, in one inline list', async () => {
    await mountApp()
    expect(EXTERNAL_LINKS).toEqual({
      programme: 'https://www.interreg-ipa-adrion.eu',
      project: 'https://urbanfloods.interreg-ipa-adrion.eu',
      knowbase: 'https://knowbase.urbanfloods.app',
      linkedin: 'https://www.linkedin.com/company/urbanfloods/',
    })
    expect(t('footer.navLabel')).toBe('Project links')

    const links = Array.from(footer().querySelectorAll<HTMLAnchorElement>('a[target="_blank"]'))
    expect(links.map((a) => a.getAttribute('href'))).toEqual([
      EXTERNAL_LINKS.project,
      EXTERNAL_LINKS.programme,
      EXTERNAL_LINKS.knowbase,
      EXTERNAL_LINKS.linkedin,
    ])
    // All four live in the one footer nav, as list items.
    const navLinks = Array.from(externalNav().querySelectorAll('li > a'))
    expect(navLinks).toEqual(links)
    for (const link of links) {
      const rel = link.getAttribute('rel') ?? ''
      expect(rel).toContain('noopener')
      expect(rel).toContain('noreferrer')
      expect(link.querySelector('.sr-only')?.textContent?.trim()).toBe(t('a11y.opensInNewTab'))
      expect(link.querySelector('[data-icon="i-lucide-arrow-up-right"]'), link.href).not.toBeNull()
    }
    expect(links[0]!.textContent).toContain(t('footer.links.project'))
    expect(links[1]!.textContent).toContain(t('footer.links.programme'))
    expect(links[2]!.textContent).toContain(t('footer.links.knowbase'))
    expect(t('footer.links.linkedin')).toBe('URBANFLOODS on LinkedIn')
    expect(links[3]!.textContent).toContain(t('footer.links.linkedin'))
    expect(links[3]!.querySelector('[data-icon="i-lucide-linkedin"]')).not.toBeNull()
  })

  it('styles the external links small and muted, underlined only on hover/focus', async () => {
    await mountApp()
    const links = externalNav().querySelectorAll('a')
    expect(links).toHaveLength(4)
    for (const link of links) {
      const classes = link.classList
      expect(classes.contains('text-sm')).toBe(true)
      expect(classes.contains('text-muted')).toBe(true)
      expect(classes.contains('hover:text-highlighted')).toBe(true)
      expect(classes.contains('underline')).toBe(false)
      expect(classes.contains('hover:underline')).toBe(true)
      expect(classes.contains('focus-visible:underline')).toBe(true)
    }
  })

  it('keeps the compact sizing: no large paddings or column gaps', async () => {
    await mountApp()
    const elements = [footer(), ...footer().querySelectorAll('*')]
    for (const cls of ['py-12', 'py-16', 'lg:py-16', 'gap-10', 'space-y-3', 'pb-8', 'pb-10']) {
      expect(
        elements.some((el) => el.classList.contains(cls)),
        cls,
      ).toBe(false)
    }
  })

  it('shows the copyright line with the current year in small print', async () => {
    await mountApp()
    const copyright = Array.from(footer().querySelectorAll('p')).find(
      (p) => p.textContent?.trim() === t('footer.copyright', { year: new Date().getFullYear() }),
    )
    expect(copyright).toBeDefined()
    expect(copyright!.classList.contains('text-xs')).toBe(true)
  })

  it('links the terms and privacy pages in the bottom bar, next to the copyright', async () => {
    await mountApp()
    const copyright = Array.from(footer().querySelectorAll('p')).find(
      (p) => p.textContent?.trim() === t('footer.copyright', { year: new Date().getFullYear() }),
    )!
    const bar = copyright.parentElement!
    const terms = bar.querySelector<HTMLAnchorElement>('a[href="/terms"]')
    const privacy = bar.querySelector<HTMLAnchorElement>('a[href="/privacy"]')
    expect(terms?.textContent?.trim()).toBe(t('legal.termsTitle'))
    expect(privacy?.textContent?.trim()).toBe(t('legal.privacyTitle'))
    for (const link of [terms!, privacy!]) {
      expect(link.classList.contains('text-xs')).toBe(true)
      expect(link.hasAttribute('target')).toBe(false)
    }
  })

  it('opens the legal pages from the footer links', async () => {
    const { router } = await mountApp('/')
    document.querySelector<HTMLAnchorElement>('footer a[href="/privacy"]')!.click()
    // The view is a lazy chunk: the route commits once it has loaded.
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('privacy'))
    await flushPromises()
    expect(document.querySelector('main h1')?.textContent?.trim()).toBe(t('legal.privacyTitle'))
  })

  it('is white with a top border and the green accent line', async () => {
    await mountApp()
    const classes = footer().classList
    for (const cls of [
      'bg-gradient-to-r',
      'from-primary-50',
      'to-secondary-50',
      'border-t-2',
      'border-secondary-300',
    ]) {
      expect(classes.contains(cls), cls).toBe(true)
    }
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

  it('does not move focus to the h1 when only the hash changes (in-page links)', async () => {
    const { router } = await mountApp('/terms')
    await router.push('/terms#section-8-licence-for-the-content-you-contribute')
    await flushPromises()
    expect(document.activeElement?.tagName).not.toBe('H1')
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

describe('main navigation and the Unified DSS', () => {
  const DSS = 'https://urbanfloods.finki.ukim.mk/'

  function navLinks() {
    const nav = document.querySelector('header nav[aria-label]')
    expect(nav).not.toBeNull()
    return Array.from(nav!.querySelectorAll('a'))
  }
  const label = (a: Element) => a.textContent?.replace(t('a11y.opensInNewTab'), '').trim()

  it('orders the items Home, Blog, Forum, Partners, Network, KNOWBASE, Unified DSS, About', async () => {
    vi.stubEnv('VITE_DSS_URL', DSS)
    await mountApp()
    expect(t('nav.network')).toBe('Network')
    expect(t('nav.knowbase')).toBe('KNOWBASE')
    expect(t('nav.dss')).toBe('Unified DSS')
    expect(navLinks().map(label)).toEqual([
      t('nav.home'),
      t('nav.blog'),
      t('nav.forum'),
      t('nav.partners'),
      t('nav.network'),
      t('nav.knowbase'),
      t('nav.dss'),
      t('nav.about'),
    ])
    expect(t('nav.forum')).toBe('Forum')
    expect(navLinks()[1]!.getAttribute('href')).toBe('/blog')
    expect(navLinks()[2]!.getAttribute('href')).toBe('/forum')
    expect(navLinks()[4]!.getAttribute('href')).toBe('/network')
    expect(navLinks()[5]!.getAttribute('href')).toBe('/knowbase')
    expect(navLinks()[5]!.getAttribute('target')).toBeNull()
  })

  it('links the DSS in a new tab, announced, with the URL from VITE_DSS_URL', async () => {
    vi.stubEnv('VITE_DSS_URL', DSS)
    await mountApp()
    const dss = navLinks().find((a) => label(a) === t('nav.dss'))!
    expect(dss.getAttribute('href')).toBe(DSS)
    expect(dss.getAttribute('target')).toBe('_blank')
    expect(dss.getAttribute('rel')).toContain('noopener')
    expect(dss.querySelector('.sr-only')?.textContent?.trim()).toBe(t('a11y.opensInNewTab'))
    // Internal items stay in the same tab.
    for (const a of navLinks().filter((l) => l !== dss)) expect(a.getAttribute('target')).toBeNull()
  })

  it('hides the DSS item when VITE_DSS_URL is empty', async () => {
    vi.stubEnv('VITE_DSS_URL', '')
    await mountApp()
    expect(navLinks().map(label)).toEqual([
      t('nav.home'),
      t('nav.blog'),
      t('nav.forum'),
      t('nav.partners'),
      t('nav.network'),
      t('nav.knowbase'),
      t('nav.about'),
    ])
    expect(document.querySelector('[data-testid="dss-card"]')).toBeNull()
  })

  it('shows the Unified DSS card on the home page with an external button', async () => {
    vi.stubEnv('VITE_DSS_URL', DSS)
    await mountApp('/')
    const card = document.querySelector('[data-testid="dss-card"]')
    expect(card).not.toBeNull()
    expect(card!.querySelector('h2')?.textContent).toContain(t('home.dss.title'))
    const button = card!.querySelector<HTMLAnchorElement>(`a[href="${DSS}"]`)
    expect(button).not.toBeNull()
    expect(button!.textContent).toContain(t('home.dss.open'))
    expect(t('home.dss.open')).toBe('Open the DSS')
    expect(button!.getAttribute('target')).toBe('_blank')
    expect(button!.getAttribute('rel')).toContain('noopener')
    expect(button!.querySelector('.sr-only')?.textContent?.trim()).toBe(t('a11y.opensInNewTab'))
  })
})

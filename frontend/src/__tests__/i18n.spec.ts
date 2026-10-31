import { afterEach, describe, expect, it, vi } from 'vitest'

import i18n, { SUPPORTED_LOCALES, resolveInitialLocale, setLocale } from '@/i18n'
import en from '@/i18n/locales/en.json'
import el from '@/i18n/locales/el.json'

/** Message trees may hold arrays (e.g. `about.summary.paragraphs`); they flatten to `.0`, `.1`, … */
type MessageValue = string | Messages | MessageValue[]
type Messages = { [key: string]: MessageValue }

function flatten(messages: Messages | MessageValue[], prefix = ''): Record<string, string> {
  return Object.entries(messages).reduce<Record<string, string>>((acc, [key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    if (typeof value === 'string') acc[path] = value
    else Object.assign(acc, flatten(value, path))
    return acc
  }, {})
}

const localeFiles = import.meta.glob<Messages>('../i18n/locales/*.json', {
  eager: true,
  import: 'default',
})

describe('SUPPORTED_LOCALES', () => {
  it('lists exactly the 9 project locales with names', () => {
    expect(SUPPORTED_LOCALES.map((l) => l.code)).toEqual([
      'en',
      'el',
      'sq',
      'mk',
      'sr',
      'bs',
      'sl',
      'hr',
      'it',
    ])
    for (const locale of SUPPORTED_LOCALES) {
      expect(locale.name).toBeTruthy()
      expect(locale.nativeName).toBeTruthy()
    }
  })
})

describe('locale files', () => {
  it('has one valid JSON object per supported locale', () => {
    const codes = Object.keys(localeFiles).map((path) => path.match(/([a-z]{2})\.json$/)?.[1])
    expect(codes.sort()).toEqual(SUPPORTED_LOCALES.map((l) => l.code).sort())
    for (const messages of Object.values(localeFiles)) {
      expect(typeof messages).toBe('object')
      expect(Object.keys(messages).length).toBeGreaterThan(0)
    }
  })

  it('en.json contains every key the layout relies on', () => {
    const keys = Object.keys(flatten(en))
    for (const key of [
      'nav.home',
      'nav.blog',
      'nav.forum',
      'nav.knowbase',
      'nav.partners',
      'nav.login',
      'nav.register',
      'app.title',
      'app.skipToContent',
      'footer.disclaimer',
      'errors.notFound',
    ]) {
      expect(keys).toContain(key)
    }
  })

  it('every locale names the forum (nav.forum and forum.title)', () => {
    for (const [path, messages] of Object.entries(localeFiles)) {
      const flat = flatten(messages)
      expect(flat['nav.forum'], `${path} nav.forum`).toBeTruthy()
      expect(flat['forum.title'], `${path} forum.title`).toBeTruthy()
    }
  })

  it('no locale keeps the removed KNOWBASE Library page keys (user decision 2026-10-31)', () => {
    const removed = ['knowbase.title', 'knowbase.intro', 'knowbase.toolkit.title']
    for (const [path, messages] of Object.entries(localeFiles)) {
      const flat = flatten(messages)
      for (const key of removed) expect(flat[key], `${path} ${key}`).toBeUndefined()
    }
  })

  it('every non-English locale translates nav.* and app.title', () => {
    const navKeys = Object.keys(flatten(en)).filter((k) => k.startsWith('nav.'))
    for (const [path, messages] of Object.entries(localeFiles)) {
      if (path.endsWith('/en.json')) continue
      const flat = flatten(messages)
      for (const key of [...navKeys, 'app.title']) {
        expect(flat[key], `${path} ${key}`).toBeTruthy()
      }
    }
  })

  it('every non-English locale translates the legal page titles and the English-only note', () => {
    const enFlat = flatten(en)
    for (const [path, messages] of Object.entries(localeFiles)) {
      if (path.endsWith('/en.json')) continue
      const flat = flatten(messages)
      for (const key of [
        'legal.termsTitle',
        'legal.privacyTitle',
        'legal.accessibilityTitle',
        'legal.openDataTitle',
        'legal.englishOnly',
      ]) {
        expect(flat[key], `${path} ${key}`).toBeTruthy()
        expect(flat[key], `${path} ${key} is translated`).not.toBe(enFlat[key])
      }
    }
  })

  it('no locale defines a key that en.json lacks', () => {
    const enKeys = new Set(Object.keys(flatten(en)))
    for (const [path, messages] of Object.entries(localeFiles)) {
      for (const key of Object.keys(flatten(messages))) {
        expect(enKeys.has(key), `${path} has stray key ${key}`).toBe(true)
      }
    }
  })
})

describe('fallback', () => {
  afterEach(() => setLocale('en'))

  it('falls back to en for a key missing from el', () => {
    const key = 'home.intro'
    expect(flatten(el)[key]).toBeUndefined()
    const english = flatten(en)[key]
    expect(english).toBeTruthy()

    setLocale('el')
    expect(i18n.global.t(key)).toBe(english)
    expect(i18n.global.t('nav.home')).toBe(flatten(el)['nav.home'])
  })
})

describe('setLocale', () => {
  afterEach(() => setLocale('en'))

  it('updates i18n, <html lang> and localStorage', () => {
    setLocale('hr')
    expect(i18n.global.locale.value).toBe('hr')
    expect(document.documentElement.lang).toBe('hr')
    expect(localStorage.getItem('locale')).toBe('hr')
  })
})

describe('resolveInitialLocale', () => {
  function stubLanguages(languages: string[]) {
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(languages)
  }

  it('prefers a supported locale stored in localStorage', () => {
    localStorage.setItem('locale', 'it')
    stubLanguages(['el-GR'])
    expect(resolveInitialLocale()).toBe('it')
  })

  it('ignores an unsupported stored value and uses navigator.languages prefix', () => {
    localStorage.setItem('locale', 'xx')
    stubLanguages(['fr-FR', 'sr-Latn-RS', 'en-GB'])
    expect(resolveInitialLocale()).toBe('sr')
  })

  it('defaults to en when nothing matches', () => {
    stubLanguages(['fr-FR', 'de'])
    expect(resolveInitialLocale()).toBe('en')
  })

  it('defaults to en when localStorage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    stubLanguages([])
    expect(resolveInitialLocale()).toBe('en')
  })
})

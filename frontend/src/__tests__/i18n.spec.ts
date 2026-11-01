import { afterEach, describe, expect, it, vi } from 'vitest'

import i18n, { SUPPORTED_LOCALES, resolveInitialLocale, setLocale, type LocaleCode } from '@/i18n'
import { PLURAL_CATEGORIES, pluralCategory, pluralRules } from '@/i18n/plural'
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

  it('no locale keeps the keys of the removed Partners page (merged into About, 2026-10-31)', () => {
    const removed = ['nav.partners', 'partners.title', 'about.partnersTitle', 'about.partnersLink']
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

  it('falls back to en for a key missing from el (the admin area is English-only)', () => {
    const key = 'admin.dashboard.intro'
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

// ---------------------------------------------------------------------------------------------
// Translation pass (increment 5f): every non-admin key in all eight non-English locales.
// ---------------------------------------------------------------------------------------------

const TRANSLATED_LOCALES = ['el', 'sq', 'mk', 'sr', 'bs', 'sl', 'hr', 'it'] as const
type TranslatedLocale = (typeof TRANSLATED_LOCALES)[number]

/** Admin screens are used by project partners only and stay English (docs: README). */
const isAdminKey = (key: string) => key === 'admin' || key.startsWith('admin.')

const enFlat = flatten(en)
const scopedKeys = Object.keys(enFlat).filter((key) => !isAdminKey(key))

function localeMessages(code: string): Messages {
  const entry = Object.entries(localeFiles).find(([path]) => path.endsWith(`/${code}.json`))
  if (!entry) throw new Error(`no locale file for ${code}`)
  return entry[1]
}

/** Project and programme names, never translated (docs/branding.md). */
const PROPER_NOUNS = ['URBANFLOODS', 'KNOWBASE', 'Interreg IPA ADRION', 'IPA ADRION', 'Unified DSS']
// The three brand strings (URBANFLOODS COOPERATION PLATFORM / KNOWBASE / DSS) are checked by
// exact equality below, since other keys may phrase them differently (e.g. "the KNOWBASE of
// URBANFLOODS" in Greek).

/**
 * A string may equal English only when nothing translatable is left once proper nouns,
 * placeholders, numbers, units and punctuation are removed ("© {year} URBANFLOODS", "+{count}",
 * "EUR 1.747.583,17", "Unified DSS").
 */
const UNTRANSLATABLE_TOKENS =
  /URBANFLOODS|KNOWBASE|COOPERATION|PLATFORM|Interreg|IPA|ADRION|Unified|DSS|EUR|LinkedIn|\{\w+\}|[\d\s.,:;/+–—()©%-]/g
const hasNothingToTranslate = (value: string) => value.replace(UNTRANSLATABLE_TOKENS, '') === ''

/** Keys whose English value is a proper name kept as is in every language. */
const IDENTICAL_KEYS = new Set([
  // Official project title as registered with the programme (a project name: not translated).
  'about.values.fullTitle',
  // A person's name; "Prof." is the same abbreviation in sq, bs, hr and sl.
  'about.leadPartner.coordinatorName',
])

/** Established loanwords that are spelled exactly like the English UI word. */
const LOANWORDS: Record<string, readonly TranslatedLocale[]> = {
  Blog: ['bs', 'hr', 'sl', 'it'],
  Forum: ['bs', 'hr', 'sl', 'it'],
  Home: ['it'],
  Account: ['it'],
  Email: ['it', 'sq'],
  Link: ['it'],
  Tag: ['it'],
  Password: ['it'],
}

function mayEqualEnglish(code: TranslatedLocale, key: string, value: string): boolean {
  return (
    hasNothingToTranslate(value) ||
    IDENTICAL_KEYS.has(key) ||
    (LOANWORDS[value]?.includes(code) ?? false)
  )
}

const placeholders = (value: string) =>
  [...new Set([...value.matchAll(/\{(\w+)\}/g)].map((m) => m[1]))].sort()

const pluralForms = (value: string) => value.split('|').length

/**
 * Forms a locale writes for a plural key: English writes `zero | one | other` (3) or
 * `one | other` (2); the locale keeps the optional zero form and writes one form per CLDR
 * category instead of English's two.
 */
const expectedForms = (code: LocaleCode, englishForms: number) =>
  englishForms - 2 + PLURAL_CATEGORIES[code].length

/** Latin words allowed inside Greek, Macedonian and Serbian (Cyrillic) strings. */
const LATIN_ALLOWED =
  /URBANFLOODS|KNOWBASE|COOPERATION|PLATFORM|Interreg|IPA|ADRION|Unified|DSS|LinkedIn|JPEG|PNG|WebP|MB|JSON|Atom|EUR|ZEP|\bI\b|SO2|https?|mailto|Enter|\{\w+\}/g
const NON_LATIN_SCRIPT: Partial<Record<TranslatedLocale, RegExp>> = {
  el: /\p{Script=Greek}/u,
  mk: /\p{Script=Cyrillic}/u,
  sr: /\p{Script=Cyrillic}/u,
}
/** Greek interfaces of public bodies (gov.gr) write "email" in Latin letters. */
const LATIN_ALLOWED_EXTRA: Partial<Record<TranslatedLocale, RegExp>> = { el: /email/gi }

describe.each(TRANSLATED_LOCALES)('%s translation', (code) => {
  const flat = flatten(localeMessages(code))

  it('translates every key outside the admin area', () => {
    const missing = scopedKeys.filter((key) => !flat[key]?.trim())
    expect(missing, `${code} missing keys`).toEqual([])
  })

  it('differs from English except for proper nouns and established loanwords', () => {
    const untranslated = scopedKeys.filter(
      (key) => flat[key] === enFlat[key] && !mayEqualEnglish(code, key, flat[key]!),
    )
    expect(untranslated, `${code} keys identical to English`).toEqual([])
  })

  it('keeps exactly the placeholders of English', () => {
    const mismatched = scopedKeys
      .filter((key) => flat[key] !== undefined)
      .filter((key) => placeholders(flat[key]!).join(',') !== placeholders(enFlat[key]!).join(','))
      .map((key) => `${key}: ${placeholders(flat[key]!)} vs ${placeholders(enFlat[key]!)}`)
    expect(mismatched).toEqual([])
  })

  it(`writes one plural form per CLDR category (${PLURAL_CATEGORIES[code].join('/')}), plus the zero form where English has one`, () => {
    const wrong = scopedKeys
      .filter((key) => flat[key] !== undefined)
      .map((key) => {
        const english = pluralForms(enFlat[key]!)
        const expected = english === 1 ? 1 : expectedForms(code, english)
        return { key, expected, actual: pluralForms(flat[key]!) }
      })
      .filter(({ expected, actual }) => expected !== actual)
    expect(wrong).toEqual([])
  })

  it('has no empty plural form, no HTML and no message-syntax characters English lacks', () => {
    const bad = scopedKeys.filter((key) => {
      const value = flat[key]
      if (value === undefined) return false
      if (value.split('|').some((form) => !form.trim())) return true
      if (/<\/?[a-z!]/i.test(value)) return true
      return /[@$]/.test(value) && !/[@$]/.test(enFlat[key]!)
    })
    expect(bad).toEqual([])
  })

  it('keeps the project and programme names untranslated', () => {
    const lost = scopedKeys.flatMap((key) =>
      PROPER_NOUNS.filter(
        (noun) => enFlat[key]!.includes(noun) && !(flat[key] ?? '').includes(noun),
      ).map((noun) => `${key}: ${noun}`),
    )
    expect(lost).toEqual([])
  })

  it('names the platform sections like the navigation does', () => {
    expect(flat['nav.knowbase']).toBe('KNOWBASE')
    expect(flat['nav.dss']).toBe('Unified DSS')
    expect(flat['home.dss.title']).toBe('URBANFLOODS DSS')
    expect(flat['home.cards.knowbase.title']).toBe('URBANFLOODS KNOWBASE')
    expect(flat['home.title']).toBe('URBANFLOODS COOPERATION PLATFORM')
  })

  it('leaves the admin area in English (absent, or identical to en)', () => {
    const adminKeys = Object.keys(flat).filter(isAdminKey)
    for (const key of adminKeys) expect(flat[key], `${code} ${key}`).toBe(enFlat[key])
  })

  it('renders every message without errors', () => {
    const onWarn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const onError = vi.spyOn(console, 'error').mockImplementation(() => {})
    setLocale(code)
    try {
      for (const key of scopedKeys) {
        const named = Object.fromEntries(placeholders(enFlat[key]!).map((p) => [p, 'X']))
        const output =
          pluralForms(enFlat[key]!) > 1 ? i18n.global.t(key, named, 5) : i18n.global.t(key, named)
        expect(output, `${code} ${key}`).not.toBe(key)
        expect(output.trim(), `${code} ${key}`).not.toBe('')
      }
      expect(onWarn).not.toHaveBeenCalled()
      expect(onError).not.toHaveBeenCalled()
    } finally {
      setLocale('en')
      onWarn.mockRestore()
      onError.mockRestore()
    }
  })

  const script = NON_LATIN_SCRIPT[code]
  if (script) {
    it(`writes in its own script (${code === 'el' ? 'Greek' : 'Cyrillic'})`, () => {
      const latin = scopedKeys
        .filter((key) => flat[key] !== undefined && !IDENTICAL_KEYS.has(key))
        .filter((key) => {
          let rest = flat[key]!.replace(LATIN_ALLOWED, '')
          const extra = LATIN_ALLOWED_EXTRA[code]
          if (extra) rest = rest.replace(extra, '')
          return /[A-Za-z]/.test(rest)
        })
        .map((key) => `${key}: ${flat[key]}`)
      expect(latin).toEqual([])
      expect(script.test(flat['home.intro'] ?? '')).toBe(true)
    })
  }
})

// ---------------------------------------------------------------------------------------------
// Plural rules (CLDR, https://www.unicode.org/cldr/charts/latest/supplemental/language_plural_rules.html)
// ---------------------------------------------------------------------------------------------

describe('plural categories', () => {
  it('lists the CLDR integer categories of every locale', () => {
    expect(PLURAL_CATEGORIES).toEqual({
      en: ['one', 'other'],
      el: ['one', 'other'],
      sq: ['one', 'other'],
      it: ['one', 'other'],
      mk: ['one', 'other'],
      sr: ['one', 'few', 'other'],
      bs: ['one', 'few', 'other'],
      hr: ['one', 'few', 'other'],
      sl: ['one', 'two', 'few', 'other'],
    })
  })

  it.each(['sr', 'hr', 'bs'] as const)(
    '%s: one (1, 21, 101), few (2–4, 22), other (5, 11–14)',
    (code) => {
      expect([1, 2, 5, 21, 101].map((n) => pluralCategory(code, n))).toEqual([
        'one',
        'few',
        'other',
        'one',
        'one',
      ])
      expect([0, 3, 4, 11, 12, 14, 22, 111, 112].map((n) => pluralCategory(code, n))).toEqual([
        'other',
        'few',
        'few',
        'other',
        'other',
        'other',
        'few',
        'other',
        'other',
      ])
    },
  )

  it('sl: one (1, 101), two (2, 102), few (3, 4, 103), other (5, 21, 0)', () => {
    expect([1, 2, 5, 21, 101].map((n) => pluralCategory('sl', n))).toEqual([
      'one',
      'two',
      'other',
      'other',
      'one',
    ])
    expect([0, 3, 4, 102, 103, 104, 111, 201].map((n) => pluralCategory('sl', n))).toEqual([
      'other',
      'few',
      'few',
      'two',
      'few',
      'few',
      'other',
      'one',
    ])
  })

  it('mk: two categories, but "one" also covers 21, 31, 101 (not 11)', () => {
    expect([1, 2, 5, 11, 21, 101, 111].map((n) => pluralCategory('mk', n))).toEqual([
      'one',
      'other',
      'other',
      'other',
      'one',
      'one',
      'other',
    ])
  })

  it.each(['el', 'sq', 'it', 'en'] as const)('%s: "one" is exactly 1', (code) => {
    expect([0, 1, 2, 5, 21, 101].map((n) => pluralCategory(code, n))).toEqual([
      'other',
      'one',
      'other',
      'other',
      'other',
      'other',
    ])
  })

  it.each(SUPPORTED_LOCALES.map((l) => l.code))(
    '%s agrees with Intl.PluralRules for 0–1000',
    (code) => {
      const intl = new Intl.PluralRules(code)
      for (let n = 0; n <= 1000; n++)
        expect(pluralCategory(code, n), `${code} ${n}`).toBe(intl.select(n))
    },
  )
})

describe('pluralRules (vue-i18n)', () => {
  it('registers a rule for every translated locale', () => {
    expect(Object.keys(pluralRules).sort()).toEqual([...TRANSLATED_LOCALES].sort())
  })

  it('sr/hr/bs: index of zero | one | few | other, and of one | few | other', () => {
    for (const code of ['sr', 'hr', 'bs'] as const) {
      const rule = pluralRules[code]!
      expect([0, 1, 2, 5, 21, 101].map((n) => rule(n, 4))).toEqual([0, 1, 2, 3, 1, 1])
      expect([0, 1, 2, 5, 21, 101].map((n) => rule(n, 3))).toEqual([2, 0, 1, 2, 0, 0])
    }
  })

  it('sl: index of zero | one | two | few | other, and of one | two | few | other', () => {
    const rule = pluralRules.sl!
    expect([0, 1, 2, 3, 5, 21, 101].map((n) => rule(n, 5))).toEqual([0, 1, 2, 3, 4, 4, 1])
    expect([0, 1, 2, 3, 5, 21, 101].map((n) => rule(n, 4))).toEqual([3, 0, 1, 2, 3, 3, 0])
  })

  it('mk: index of zero | one | other, and of one | other', () => {
    const rule = pluralRules.mk!
    expect([0, 1, 2, 5, 11, 21, 101].map((n) => rule(n, 3))).toEqual([0, 1, 2, 2, 2, 1, 1])
    expect([0, 1, 2, 5, 11, 21, 101].map((n) => rule(n, 2))).toEqual([1, 0, 1, 1, 1, 0, 0])
  })

  it('el/sq/it: two-form behaviour, same as English', () => {
    for (const code of ['el', 'sq', 'it'] as const) {
      const rule = pluralRules[code]!
      expect([0, 1, 2, 5, 21, 101].map((n) => rule(n, 3))).toEqual([0, 1, 2, 2, 2, 2])
      expect([0, 1, 2, 5, 21, 101].map((n) => rule(n, 2))).toEqual([1, 0, 1, 1, 1, 1])
    }
  })

  it('a message with an unexpected number of forms falls back to the default rule', () => {
    const rule = pluralRules.sr!
    const original = (choice: number, length: number) =>
      length === 2 ? (choice === 1 ? 0 : 1) : Math.min(choice, 2)
    expect(rule(5, 2, original)).toBe(1)
    expect(rule(1, 2, original)).toBe(0)
  })

  it('is used by the i18n instance (sr blog.count for 0, 1, 2, 5, 21)', () => {
    const forms = flatten(localeMessages('sr'))
      ['blog.count']!.split('|')
      .map((f) => f.trim())
    setLocale('sr')
    try {
      const fill = (form: string, n: number) => form.replace('{count}', String(n))
      expect(i18n.global.t('blog.count', 0)).toBe(fill(forms[0]!, 0))
      expect(i18n.global.t('blog.count', 1)).toBe(fill(forms[1]!, 1))
      expect(i18n.global.t('blog.count', 2)).toBe(fill(forms[2]!, 2))
      expect(i18n.global.t('blog.count', 5)).toBe(fill(forms[3]!, 5))
      expect(i18n.global.t('blog.count', 21)).toBe(fill(forms[1]!, 21))
    } finally {
      setLocale('en')
    }
  })
})

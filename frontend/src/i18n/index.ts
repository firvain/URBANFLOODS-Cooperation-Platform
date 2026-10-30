/**
 * vue-i18n setup (Composition API mode).
 *
 * Nine UI locales. `en.json` is complete; the others translate what they can and fall back to
 * English for the rest. The initial locale comes from the user's stored choice, then the browser
 * languages, then English.
 */
import { createI18n } from 'vue-i18n'

import en from './locales/en.json'
import el from './locales/el.json'
import sq from './locales/sq.json'
import mk from './locales/mk.json'
import sr from './locales/sr.json'
import bs from './locales/bs.json'
import sl from './locales/sl.json'
import hr from './locales/hr.json'
import it from './locales/it.json'

export const SUPPORTED_LOCALES = [
  { code: 'en', name: 'English', nativeName: 'English' },
  { code: 'el', name: 'Greek', nativeName: 'Ελληνικά' },
  { code: 'sq', name: 'Albanian', nativeName: 'Shqip' },
  { code: 'mk', name: 'Macedonian', nativeName: 'Македонски' },
  { code: 'sr', name: 'Serbian', nativeName: 'Српски' },
  { code: 'bs', name: 'Bosnian', nativeName: 'Bosanski' },
  { code: 'sl', name: 'Slovenian', nativeName: 'Slovenščina' },
  { code: 'hr', name: 'Croatian', nativeName: 'Hrvatski' },
  { code: 'it', name: 'Italian', nativeName: 'Italiano' },
] as const

export type LocaleCode = (typeof SUPPORTED_LOCALES)[number]['code']

export const DEFAULT_LOCALE: LocaleCode = 'en'
export const LOCALE_STORAGE_KEY = 'locale'

export function isSupportedLocale(value: unknown): value is LocaleCode {
  return SUPPORTED_LOCALES.some((l) => l.code === value)
}

function readStoredLocale(): string | null {
  try {
    return localStorage.getItem(LOCALE_STORAGE_KEY)
  } catch {
    // Storage can be unavailable (privacy mode, blocked cookies).
    return null
  }
}

/** Stored choice → first `navigator.languages` prefix match → `en`. */
export function resolveInitialLocale(): LocaleCode {
  const stored = readStoredLocale()
  if (isSupportedLocale(stored)) return stored

  const languages = typeof navigator !== 'undefined' ? (navigator.languages ?? []) : []
  for (const tag of languages) {
    const prefix = tag.toLowerCase().split('-')[0]
    if (isSupportedLocale(prefix)) return prefix
  }
  return DEFAULT_LOCALE
}

const i18n = createI18n({
  legacy: false,
  locale: resolveInitialLocale(),
  fallbackLocale: DEFAULT_LOCALE,
  messages: { en, el, sq, mk, sr, bs, sl, hr, it },
  missingWarn: false,
  fallbackWarn: false,
})

/** Switch the UI language, update `<html lang>` and remember the choice. */
export function setLocale(code: LocaleCode): void {
  i18n.global.locale.value = code
  document.documentElement.lang = code
  try {
    localStorage.setItem(LOCALE_STORAGE_KEY, code)
  } catch {
    // Not persisted; the choice still applies for this page view.
  }
}

if (typeof document !== 'undefined') {
  document.documentElement.lang = i18n.global.locale.value
}

export default i18n

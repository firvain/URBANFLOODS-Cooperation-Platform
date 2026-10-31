/**
 * CLDR plural rules for the UI locales, as vue-i18n `pluralRules`.
 *
 * Source: CLDR "Language Plural Rules",
 * https://www.unicode.org/cldr/charts/latest/supplemental/language_plural_rules.html
 * Only non-negative integer counts are pluralised in the UI, so the rules below are the integer
 * (v = 0) branches; a fractional count falls into "other" ("few" in Slovenian, where v != 0 is few).
 *
 * Message convention (as in en.json): a plural message lists one `|`-separated form per CLDR
 * category of its locale, in the order of `PLURAL_CATEGORIES`, optionally preceded by a zero form
 * ("No posts | …"). English `zero | one | other` therefore becomes
 * `zero | one | few | other` in Serbian, Croatian and Bosnian and
 * `zero | one | two | few | other` in Slovenian.
 */
import type { PluralizationRule } from 'vue-i18n'

import type { LocaleCode } from './index'

export type PluralCategory = 'one' | 'two' | 'few' | 'other'

/**
 * CLDR integer categories per locale, in the order the forms are written. Italian also has
 * "many" in CLDR 42+, but only for millions in compact notation (1 milione di …), never for the
 * counts this UI shows, so it is written with two forms.
 */
export const PLURAL_CATEGORIES: Record<LocaleCode, readonly PluralCategory[]> = {
  en: ['one', 'other'],
  el: ['one', 'other'],
  sq: ['one', 'other'],
  it: ['one', 'other'],
  mk: ['one', 'other'],
  sr: ['one', 'few', 'other'],
  bs: ['one', 'few', 'other'],
  hr: ['one', 'few', 'other'],
  sl: ['one', 'two', 'few', 'other'],
}

/** sr, hr, bs: one = i%10=1 ∧ i%100≠11; few = i%10∈2..4 ∧ i%100∉12..14; else other. */
function serboCroatian(n: number): PluralCategory {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'one'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'few'
  return 'other'
}

/** sl: one = i%100=1; two = i%100=2; few = i%100∈3..4; else other. */
function slovenian(n: number): PluralCategory {
  const mod100 = n % 100
  if (mod100 === 1) return 'one'
  if (mod100 === 2) return 'two'
  if (mod100 === 3 || mod100 === 4) return 'few'
  return 'other'
}

/** mk: one = i%10=1 ∧ i%100≠11 (so 21 and 101 are "one"); else other. */
function macedonian(n: number): PluralCategory {
  return n % 10 === 1 && n % 100 !== 11 ? 'one' : 'other'
}

/** en, el, sq, it: one = exactly 1 (integer); else other. */
function oneOther(n: number): PluralCategory {
  return n === 1 ? 'one' : 'other'
}

const CATEGORY_OF: Record<LocaleCode, (n: number) => PluralCategory> = {
  en: oneOther,
  el: oneOther,
  sq: oneOther,
  it: oneOther,
  mk: macedonian,
  sr: serboCroatian,
  bs: serboCroatian,
  hr: serboCroatian,
  sl: slovenian,
}

/** CLDR category of a count in a locale. */
export function pluralCategory(locale: LocaleCode, count: number): PluralCategory {
  const n = Math.abs(count)
  if (!Number.isInteger(n)) return locale === 'sl' ? 'few' : 'other'
  return CATEGORY_OF[locale](n)
}

/** Default vue-i18n rule, used when a message has an unexpected number of forms. */
function defaultRule(choice: number, choicesLength: number): number {
  const n = Math.abs(choice)
  if (choicesLength === 2) return n === 1 ? 0 : 1
  return Math.min(n, 2)
}

function ruleFor(locale: LocaleCode): PluralizationRule {
  const categories = PLURAL_CATEGORIES[locale]
  return (choice, choicesLength, orgRule) => {
    const index = categories.indexOf(pluralCategory(locale, choice))
    if (choicesLength === categories.length + 1) return choice === 0 ? 0 : index + 1
    if (choicesLength === categories.length) return index
    return (orgRule ?? defaultRule)(choice, choicesLength)
  }
}

/** vue-i18n `pluralRules` for the eight non-English locales (English uses the default rule). */
export const pluralRules: Partial<Record<LocaleCode, PluralizationRule>> = {
  el: ruleFor('el'),
  sq: ruleFor('sq'),
  mk: ruleFor('mk'),
  sr: ruleFor('sr'),
  bs: ruleFor('bs'),
  sl: ruleFor('sl'),
  hr: ruleFor('hr'),
  it: ruleFor('it'),
}

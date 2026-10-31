import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { PROJECT_COUNTRIES } from '@/constants/auth'
import { KNOWBASE_COUNTRY_ALIASES } from '@/constants/knowbase'

/** Sentinel select value: "my country is not in the list" (sent as `null`). */
export const OTHER_COUNTRY = 'other'

/**
 * Country names in the current UI locale (English fallback, then the ISO code), and the country
 * picker items shared by the register and profile forms.
 */
export function useCountries() {
  const { t, locale } = useI18n()

  const displayNames = computed(() => {
    try {
      return new Intl.DisplayNames([locale.value, 'en'], { type: 'region' })
    } catch {
      // Very old browsers: show the ISO codes.
      return null
    }
  })

  function countryName(code: string): string {
    const upper = code.toUpperCase()
    const iso = KNOWBASE_COUNTRY_ALIASES[upper] ?? upper
    try {
      return displayNames.value?.of(iso) ?? code
    } catch {
      return code
    }
  }

  /** The partner countries (plus `extra`, e.g. a profile's current country), sorted, then "Other". */
  function countryItems(extra?: string | null) {
    const codes = new Set<string>(PROJECT_COUNTRIES)
    if (extra) codes.add(extra.toUpperCase())
    const countries = [...codes].map((code) => ({ label: countryName(code), value: code }))
    countries.sort((a, b) => a.label.localeCompare(b.label, locale.value))
    return [...countries, { label: t('auth.fields.countryOther'), value: OTHER_COUNTRY }]
  }

  return { countryName, countryItems }
}

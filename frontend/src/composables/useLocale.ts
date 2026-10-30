import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { SUPPORTED_LOCALES, setLocale, type LocaleCode } from '@/i18n'

/** Current UI locale as a writable computed, plus the list of supported locales. */
export function useLocale() {
  const { locale: i18nLocale } = useI18n({ useScope: 'global' })

  const locale = computed<LocaleCode>({
    get: () => i18nLocale.value as LocaleCode,
    set: (code) => setLocale(code),
  })

  return { locale, locales: SUPPORTED_LOCALES, setLocale }
}

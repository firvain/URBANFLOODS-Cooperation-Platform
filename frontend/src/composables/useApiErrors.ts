import { useI18n } from 'vue-i18n'

import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from '@/constants/auth'
import { ApiError } from '@/services/api'

/**
 * Translate backend error codes. Request-level codes live under `errors.api.<code>`, field codes
 * (`ApiError.fields`, client validation) under `errors.fields.<code>`; unknown codes fall back to
 * a generic message, so a new backend code never shows up raw.
 */
export function useApiErrors() {
  const { t, te } = useI18n()
  const params = { min: PASSWORD_MIN_LENGTH, max: PASSWORD_MAX_LENGTH }

  const has = (key: string) => te(key) || te(key, 'en')

  /** One sentence for a failed request. */
  function errorMessage(error: unknown): string {
    if (error instanceof ApiError) {
      if (error.status === 429) return t('errors.tooManyRequests')
      if (error.code && has(`errors.api.${error.code}`)) return t(`errors.api.${error.code}`)
    }
    return t('errors.generic')
  }

  /** Message for a field error code such as `required` or `auth.password_too_common`. */
  function fieldMessage(code: string): string {
    const key = `errors.fields.${code}`
    return has(key) ? t(key, params) : t('errors.fields.invalid')
  }

  /** `ApiError.fields` translated, keyed by field name (empty for other errors). */
  function fieldErrors(error: unknown): Record<string, string> {
    if (!(error instanceof ApiError) || !error.fields) return {}
    return Object.fromEntries(
      Object.entries(error.fields).map(([field, code]) => [field, fieldMessage(code)]),
    )
  }

  return { errorMessage, fieldMessage, fieldErrors }
}

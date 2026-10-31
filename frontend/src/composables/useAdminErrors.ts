import { useI18n } from 'vue-i18n'

import { useApiErrors } from '@/composables/useApiErrors'
import { ApiError } from '@/services/api'

/**
 * Messages for failed admin requests: the admin-specific codes (`admin.last_superadmin`,
 * `categories.slug_taken`, `moderation.invalid_transition`, …) live under `admin.errors.<code>`;
 * anything else goes through the app-wide `useApiErrors`.
 */
export function useAdminErrors() {
  const { t, te } = useI18n()
  const { errorMessage } = useApiErrors()

  function adminError(error: unknown): string {
    if (error instanceof ApiError && error.code) {
      const key = `admin.errors.${error.code}`
      if (te(key) || te(key, 'en')) return t(key)
    }
    return errorMessage(error)
  }

  return { adminError }
}

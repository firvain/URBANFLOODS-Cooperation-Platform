/** Mirrors `backend/app/core/security.py` (NIST 800-63B: length only, no composition rules). */
export const PASSWORD_MIN_LENGTH = 10
export const PASSWORD_MAX_LENGTH = 128

/** ISO 3166-1 alpha-2 codes of the URBANFLOODS partner countries (register form picker). */
export const PROJECT_COUNTRIES = ['AL', 'BA', 'HR', 'GR', 'IT', 'MK', 'RS', 'SI'] as const

/** How long success screens wait before moving on (verify email). */
export const AUTH_REDIRECT_DELAY_MS = 2500

/** Mirrors the backend limit on `expertise_ids` (registration and profile). */
export const EXPERTISE_MAX = 8

/** Admin area settings. */

/** Rows per page of the queue, reports and users lists. */
export const ADMIN_PAGE_SIZE = 20
/** Rows per page of the tags list and the audit log. */
export const ADMIN_LONG_PAGE_SIZE = 50
/** How long the search boxes wait after the last keystroke before they filter. */
export const ADMIN_SEARCH_DEBOUNCE_MS = 300

/** Quick filters of the audit log (action prefixes). */
export const LOG_ACTION_PREFIXES = ['moderation.', 'admin.', 'report.', 'auth.'] as const
/** Audit `target_type` values (as written by the backend). */
export const LOG_TARGET_TYPES = [
  'post',
  'thread',
  'reply',
  'comment',
  'user',
  'report',
  'category',
  'tag',
  'organisation',
  'expertise_tag',
] as const

// Category limits, mirroring the backend (`schemas/category.py`).
export const CATEGORY_NAME_MIN_LENGTH = 2
export const CATEGORY_NAME_MAX_LENGTH = 80
export const CATEGORY_SLUG_MAX_LENGTH = 80
export const CATEGORY_DESCRIPTION_MAX_LENGTH = 500
export const CATEGORY_SORT_ORDER_MAX = 100_000
export const CATEGORY_SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/

// Organisation limits, mirroring the backend (`schemas/organisation.py`).
export const ORGANISATION_NAME_MIN_LENGTH = 2
export const ORGANISATION_NAME_MAX_LENGTH = 200
export const ORGANISATION_SHORT_NAME_MAX_LENGTH = 64
export const ORGANISATION_WEBSITE_MAX_LENGTH = 500
export const ORGANISATION_SORT_ORDER_MAX = 100_000
export const ORGANISATION_TYPES = ['PP', 'AP', 'other'] as const

// Expertise tag limits, mirroring the backend (`schemas/expertise.py`).
export const EXPERTISE_LABEL_MIN_LENGTH = 2
export const EXPERTISE_LABEL_MAX_LENGTH = 80
export const EXPERTISE_SLUG_MAX_LENGTH = 64
export const EXPERTISE_SORT_ORDER_MAX = 100_000
export const EXPERTISE_SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/

/** Forum settings shared by the list, the thread page, the replies and the editor. */

/** Threads per page on the forum list. */
export const FORUM_PAGE_SIZE = 20
/** How long the search box waits after the last keystroke before it filters. */
export const FORUM_SEARCH_DEBOUNCE_MS = 300
/** Top-level replies per "Load more replies" page. */
export const REPLIES_PAGE_SIZE = 20

// Editor limits, mirroring the backend (`schemas/thread.py`, `schemas/post.py`, replies in 3c).
// Body limits count characters of text.
export const THREAD_TITLE_MIN_LENGTH = 3
export const THREAD_TITLE_MAX_LENGTH = 200
export const THREAD_BODY_MAX_LENGTH = 50_000
export const THREAD_TAGS_MAX = 10
export const THREAD_TAG_MAX_LENGTH = 40
export const REPLY_BODY_MAX_LENGTH = 10_000

/** Authors may edit their reply for this long after posting it (admins always). */
export const REPLY_EDIT_WINDOW_MS = 24 * 60 * 60 * 1000

/** `sessionStorage` key prefix of thread editor drafts (followed by the route path). */
export const THREAD_DRAFT_KEY_PREFIX = 'thread-draft:'

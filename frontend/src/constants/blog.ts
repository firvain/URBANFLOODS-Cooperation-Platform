/** Blog settings shared by the list, the post page and the editor. */

/** Posts per page on the blog list. */
export const BLOG_PAGE_SIZE = 12
/** How long the search box waits after the last keystroke before it filters. */
export const BLOG_SEARCH_DEBOUNCE_MS = 300
/** Popular tags offered as filters on the blog list. */
export const POPULAR_TAGS_LIMIT = 12

// Editor limits. Title, excerpt, tags and links mirror the backend (`schemas/post.py`,
// `crud/tag.py`); the body limit counts characters of text, lower than the backend's HTML limit.
export const POST_TITLE_MIN_LENGTH = 3
export const POST_TITLE_MAX_LENGTH = 200
export const POST_EXCERPT_MAX_LENGTH = 500
export const POST_BODY_MAX_LENGTH = 50_000
export const POST_TAGS_MAX = 10
export const POST_TAG_MAX_LENGTH = 40

/** How long the editor waits after the last change before it saves the draft. */
export const DRAFT_SAVE_DELAY_MS = 500
/** `sessionStorage` key prefix of editor drafts (followed by the route path). */
export const DRAFT_KEY_PREFIX = 'post-draft:'

/** Comments per "Load more comments" page (the backend allows at most 100). */
export const COMMENTS_PAGE_SIZE = 50
/** Comment length in characters of text, mirroring the backend (`crud/comment.py`). */
export const COMMENT_BODY_MAX_LENGTH = 5_000
/** Authors may edit their comment for this long after posting it (admins always). */
export const COMMENT_EDIT_WINDOW_MS = 24 * 60 * 60 * 1000

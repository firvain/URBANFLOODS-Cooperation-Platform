/** Site search settings (`GET /api/v1/search/`, `schemas/search.py`). */

/** Hits per page on the search page (the backend allows at most 50). */
export const SEARCH_PAGE_SIZE = 20
/** Shorter queries (after trimming) are refused by the backend (422); the UI does not send them. */
export const SEARCH_MIN_LENGTH = 2
/** The backend's upper bound on the query length. */
export const SEARCH_MAX_LENGTH = 200

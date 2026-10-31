/** KNOWBASE Library settings shared by the list views. */

/** Items per page on the measures and documents lists. */
export const KB_PAGE_SIZE = 24
/** How long the search box waits after the last keystroke before it filters. */
export const KB_SEARCH_DEBOUNCE_MS = 300
/** The proxy rejects shorter `q` values (422), so shorter input is not sent. */
export const KB_MIN_SEARCH_LENGTH = 2

/**
 * Country codes the KNOWBASE uses that are not ISO 3166-1 alpha-2, mapped to the ISO code so
 * names resolve correctly (in ISO, "CR" is Costa Rica; the KNOWBASE means Croatia). The KNOWBASE
 * API still expects its own code in filters, so only the display name goes through this map.
 */
export const KNOWBASE_COUNTRY_ALIASES: Readonly<Record<string, string>> = { CR: 'HR' }

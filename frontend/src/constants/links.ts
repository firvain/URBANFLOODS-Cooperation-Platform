/** External sites the platform links to (docs/branding.md: footer and About page). */
export const EXTERNAL_LINKS = {
  programme: 'https://www.interreg-ipa-adrion.eu',
  project: 'https://urbanfloods.interreg-ipa-adrion.eu',
  knowbase: 'https://knowbase.urbanfloods.app',
  linkedin: 'https://www.linkedin.com/company/urbanfloods/',
} as const

/**
 * The Unified DSS web app (`VITE_DSS_URL`, user decision 2026-10-30). Empty means "not
 * configured": the header item and the home card are hidden. Read at call time (not cached at
 * import) so tests can stub the variable.
 */
export function dssUrl(): string {
  return (import.meta.env.VITE_DSS_URL ?? '').trim()
}

/** Licence of the content members contribute (Terms §8), named in the pages' JSON-LD. */
export const CONTENT_LICENCE_URL = 'https://creativecommons.org/licenses/by/4.0/'

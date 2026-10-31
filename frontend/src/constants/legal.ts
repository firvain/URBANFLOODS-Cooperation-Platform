/** The legal pages. Their texts live in `content/legal.ts`, loaded only by the legal view. */
export type LegalDoc = 'terms' | 'privacy' | 'accessibility' | 'openData'

/** i18n key of each document's page title (routes, footer and page heading). */
export const LEGAL_TITLE_KEYS: Record<LegalDoc, string> = {
  terms: 'legal.termsTitle',
  privacy: 'legal.privacyTitle',
  accessibility: 'legal.accessibilityTitle',
  openData: 'legal.openDataTitle',
}

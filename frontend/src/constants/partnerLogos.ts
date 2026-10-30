/**
 * Partner logos supplied by the lead partner (docs/about-partners-style.md), served from
 * `public/partners/`. Keyed by slug: the short name lower-cased, spaces/underscores as `-`.
 * A partner without an entry gets a text-only tile.
 */
export const PARTNER_LOGO_FILES: Readonly<Record<string, string>> = {
  uowm: 'uowm.png',
  heis: 'heis.png',
  dcms: 'dcms.png',
  mc: 'mc.svg',
  'rda-backa': 'rda-backa.png',
  deyak: 'deyak.png',
  hydrowateral: 'hydrowateral.png',
  'rda-porin': 'rda-porin.png',
  'fcse-ukim': 'fcse-ukim.png',
  svimed: 'svimed.png',
  ckm: 'ckm.png',
}

export function partnerSlug(shortName: string): string {
  return shortName
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, '-')
}

/** Public URL of the partner's logo, or null when no file was supplied. */
export function partnerLogoUrl(shortName: string): string | null {
  const file = PARTNER_LOGO_FILES[partnerSlug(shortName)]
  return file ? `${import.meta.env.BASE_URL}partners/${file}` : null
}

/**
 * Primary navigation. Labels are i18n keys. The forum joins this list in the increment that adds
 * its routes (M3), so the header never links to a 404.
 */
export const NAV_ITEMS = [
  { name: 'home', labelKey: 'nav.home', to: '/' },
  { name: 'blog', labelKey: 'nav.blog', to: '/blog' },
  { name: 'partners', labelKey: 'nav.partners', to: '/partners' },
  { name: 'network', labelKey: 'nav.network', to: '/network' },
  { name: 'knowbase', labelKey: 'nav.knowbase', to: '/knowbase' },
  { name: 'about', labelKey: 'nav.about', to: '/about' },
] as const

/**
 * The Unified DSS: an external web app (`VITE_DSS_URL`), shown in the header after the internal
 * item named `after`, and only when the URL is configured.
 */
export const DSS_NAV_ITEM = { name: 'dss', labelKey: 'nav.dss', after: 'knowbase' } as const

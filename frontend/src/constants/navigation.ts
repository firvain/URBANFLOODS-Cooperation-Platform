/** Primary navigation (header and the footer's Platform column). Labels are i18n keys. */
export const NAV_ITEMS = [
  { name: 'home', labelKey: 'nav.home', to: '/' },
  { name: 'blog', labelKey: 'nav.blog', to: '/blog' },
  { name: 'forum', labelKey: 'nav.forum', to: '/forum' },
  { name: 'network', labelKey: 'nav.network', to: '/network' },
  { name: 'knowbase', labelKey: 'nav.knowbase', to: '/knowbase' },
  { name: 'partners', labelKey: 'nav.partners', to: '/partners' },
  { name: 'about', labelKey: 'nav.about', to: '/about' },
] as const

/**
 * The Unified DSS: an external web app (`VITE_DSS_URL`), shown in the header after the internal
 * item named `after`, and only when the URL is configured.
 */
export const DSS_NAV_ITEM = { name: 'dss', labelKey: 'nav.dss', after: 'knowbase' } as const

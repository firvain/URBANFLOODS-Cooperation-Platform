/**
 * Primary navigation. Labels are i18n keys. Blog, forum and KNOWBASE join this list in the
 * increments that add their routes (M2/M3), so the header never links to a 404.
 */
export const NAV_ITEMS = [
  { name: 'home', labelKey: 'nav.home', to: '/' },
  { name: 'partners', labelKey: 'nav.partners', to: '/partners' },
  { name: 'about', labelKey: 'nav.about', to: '/about' },
] as const

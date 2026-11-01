import { EXTERNAL_LINKS } from './links'

/**
 * Primary navigation (header). Labels are i18n keys. `external` items are other sites: they open
 * in a new tab and are never marked active. The KNOWBASE is browsed on its own site (user decision
 * 2026-10-31); the platform keeps its item pages and, since 7c, "Flood Management Measures"
 * (`/knowbase/measures`, the "Measures" item, active on the measure pages too).
 * The partners are a section of About (`/about#partnership`), not a nav item (same decision date).
 */
export const NAV_ITEMS = [
  { name: 'home', labelKey: 'nav.home', to: '/' },
  { name: 'blog', labelKey: 'nav.blog', to: '/blog' },
  { name: 'forum', labelKey: 'nav.forum', to: '/forum' },
  { name: 'network', labelKey: 'nav.network', to: '/network' },
  { name: 'measures', labelKey: 'nav.measures', to: '/knowbase/measures' },
  { name: 'knowbase', labelKey: 'nav.knowbase', to: EXTERNAL_LINKS.knowbase, external: true },
  { name: 'about', labelKey: 'nav.about', to: '/about' },
] as const

/**
 * The Unified DSS: an external web app (`VITE_DSS_URL`), shown in the header after the item
 * named `after`, and only when the URL is configured.
 */
export const DSS_NAV_ITEM = { name: 'dss', labelKey: 'nav.dss', after: 'knowbase' } as const

/**
 * The single owner of the page `<head>` (through `@unhead/vue`, installed in `main.ts`):
 * `document.title` ("Post title · URBANFLOODS Cooperation Platform"), the description, Open Graph
 * tags, the canonical link and an optional JSON-LD block.
 *
 * `App.vue` calls it with the route title (`meta.title`) as the base entry; pages call it again
 * with their own values, which win while the page is mounted and are removed when it unmounts
 * (the route title comes back). Tags are deduplicated by unhead (`meta` by name/property, the
 * canonical link by `rel`, JSON-LD by a fixed key), so a value is replaced, never appended. The
 * input may be a getter, so the head follows data that loads after the page opens.
 */
import { computed, type MaybeRefOrGetter, toValue } from 'vue'
import { useRoute } from 'vue-router'
import { useHead } from '@unhead/vue'

import i18n from '@/i18n'

export type JsonLd = Record<string, unknown>

export interface PageHead {
  /** Page title without the platform name; omitted or empty leaves the current title. */
  title?: string | null
  description?: string | null
  /** Absolute or same-origin URL; defaults to the current path (without query or hash). */
  canonical?: string | null
  type?: 'website' | 'article'
  /** Absolute or same-origin image URL for `og:image`. */
  image?: string | null
  /** schema.org data, written as one `<script type="application/ld+json">`. */
  jsonLd?: JsonLd | JsonLd[] | null
}

/** unhead key of the JSON-LD script: one per page, whoever set it last. */
const JSON_LD_KEY = 'page-json-ld'

/** "Title · URBANFLOODS Cooperation Platform"; the bare platform name for none or itself. */
export function formatPageTitle(title?: string | null): string {
  const appTitle = i18n.global.t('app.title')
  const value = title?.trim()
  return !value || value === appTitle ? appTitle : `${value} · ${appTitle}`
}

/** Same-origin paths (`/static/...`) become absolute, as Open Graph and canonical links require. */
export function absoluteUrl(url: string): string {
  try {
    return new URL(url, window.location.origin).href
  } catch {
    return url
  }
}

/** JSON for a script element; `<` is escaped so no value can close the element. */
function serializeJsonLd(data: JsonLd | JsonLd[]): string {
  return JSON.stringify(data).replace(/</g, '\\u003c')
}

type MetaTag = { name: string; content: string } | { property: string; content: string }

export function usePageHead(input: MaybeRefOrGetter<PageHead | null>) {
  const route = useRoute()
  const head = computed(() => toValue(input))

  const canonical = computed(() => {
    const value = head.value
    if (!value) return undefined
    const url = value.canonical ?? route?.path
    return url ? absoluteUrl(url) : undefined
  })

  useHead({
    title: computed(() => (head.value?.title ? formatPageTitle(head.value.title) : undefined)),
    meta: computed(() => {
      const value = head.value
      if (!value) return []
      const meta: MetaTag[] = [{ property: 'og:type', content: value.type ?? 'website' }]
      if (value.title) meta.push({ property: 'og:title', content: value.title })
      if (value.description) {
        meta.push({ name: 'description', content: value.description })
        meta.push({ property: 'og:description', content: value.description })
      }
      if (canonical.value) meta.push({ property: 'og:url', content: canonical.value })
      if (value.image) meta.push({ property: 'og:image', content: absoluteUrl(value.image) })
      return meta
    }),
    link: computed(() =>
      canonical.value ? [{ rel: 'canonical' as const, href: canonical.value }] : [],
    ),
    script: computed(() => {
      const data = head.value?.jsonLd
      if (!data) return []
      return [
        {
          key: JSON_LD_KEY,
          type: 'application/ld+json' as const,
          textContent: serializeJsonLd(data),
        },
      ]
    }),
  })
}

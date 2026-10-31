/**
 * Page `<head>` for content pages: title ("Post title | Cooperation Platform"), description and
 * Open Graph tags, through `@unhead/vue` (installed in `main.ts`). Values are getters, so the
 * head follows data that loads after the page opens. Without a title the route title set by the
 * router (`meta.title`) stays.
 */
import { computed, type MaybeRefOrGetter, toValue } from 'vue'
import { useHead } from '@unhead/vue'

import i18n from '@/i18n'

export interface PageHead {
  title?: string | null
  description?: string | null
  /** Absolute or same-origin image URL for `og:image`. */
  image?: string | null
  type?: 'website' | 'article'
}

/** Same-origin paths (`/static/...`) become absolute, as Open Graph requires. */
function absolute(url: string): string {
  try {
    return new URL(url, window.location.origin).href
  } catch {
    return url
  }
}

export function usePageHead(input: MaybeRefOrGetter<PageHead | null>) {
  const head = computed(() => toValue(input))
  const fullTitle = computed(() => {
    const title = head.value?.title
    return title ? `${title} | ${i18n.global.t('app.title')}` : undefined
  })

  useHead({
    title: fullTitle,
    meta: computed(() => {
      const value = head.value
      if (!value?.title) return []
      const meta: ({ name: string; content: string } | { property: string; content: string })[] = [
        { property: 'og:title', content: value.title },
        { property: 'og:type', content: value.type ?? 'article' },
      ]
      if (value.description) {
        meta.push({ name: 'description', content: value.description })
        meta.push({ property: 'og:description', content: value.description })
      }
      if (value.image) meta.push({ property: 'og:image', content: absolute(value.image) })
      return meta
    }),
  })
}

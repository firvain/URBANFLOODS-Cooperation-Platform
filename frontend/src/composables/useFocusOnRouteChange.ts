import { nextTick, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'

import { pageTitle } from '@/router'

/**
 * After every client-side navigation (not the initial load), move focus to the page's
 * `h1[tabindex="-1"]` inside `<main>` and expose the new route's title for an `aria-live` region,
 * so screen-reader and keyboard users notice the page changed. A change of the `#hash` alone is
 * not a new page and leaves focus alone.
 */
function withoutHash(fullPath: string): string {
  const index = fullPath.indexOf('#')
  return index === -1 ? fullPath : fullPath.slice(0, index)
}

export function useFocusOnRouteChange() {
  const router = useRouter()
  const announcement = ref('')

  const removeHook = router.afterEach(async (to, from, failure) => {
    if (failure || from.matched.length === 0 || to.fullPath === from.fullPath) return
    // Same page, new #hash (an in-page link): the browser moves to the target; keep it there.
    if (withoutHash(to.fullPath) === withoutHash(from.fullPath)) return
    await nextTick()
    const heading = document.querySelector<HTMLElement>('main h1[tabindex="-1"]')
    // A new page opened at a `#hash` (e.g. `/about#partnership`): the router has scrolled to the
    // target; focusing the h1 must not scroll back to the top.
    heading?.focus(to.hash ? { preventScroll: true } : undefined)
    // The route title, not `document.title`: unhead writes the `<head>` asynchronously.
    announcement.value = pageTitle(to.meta.title)
  })

  onBeforeUnmount(removeHook)

  return { announcement }
}

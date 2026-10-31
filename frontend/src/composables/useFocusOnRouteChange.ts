import { nextTick, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'

/**
 * After every client-side navigation (not the initial load), move focus to the page's
 * `h1[tabindex="-1"]` inside `<main>` and expose the new page title for an `aria-live` region,
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
    heading?.focus()
    announcement.value = document.title
  })

  onBeforeUnmount(removeHook)

  return { announcement }
}

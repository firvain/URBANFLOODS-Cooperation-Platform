/**
 * A server-paginated list (`{total, items}`) for the admin stores: loading/failed flags, and only
 * the latest request's answer is kept (a slow earlier response never overwrites a newer one).
 */
import { reactive } from 'vue'

export interface PagedList<T> {
  items: T[]
  total: number
  loading: boolean
  failed: boolean
  /** True until the first answer arrived (for skeletons). */
  initial: boolean
}

export function pagedList<T, P>(load: (params: P) => Promise<{ total: number; items: T[] }>) {
  const state = reactive({
    items: [],
    total: 0,
    loading: false,
    failed: false,
    initial: true,
  }) as PagedList<T>
  let latest = 0
  let lastParams: P | undefined

  async function fetch(params: P): Promise<void> {
    const request = ++latest
    lastParams = params
    state.loading = true
    state.failed = false
    try {
      const page = await load(params)
      if (request !== latest) return
      state.items = page.items
      state.total = page.total
    } catch {
      if (request === latest) state.failed = true
    } finally {
      if (request === latest) {
        state.loading = false
        state.initial = false
      }
    }
  }

  /** Repeat the last request (the "Try again" button). */
  const reload = () => (lastParams === undefined ? Promise.resolve() : fetch(lastParams))

  return { state, fetch, reload }
}

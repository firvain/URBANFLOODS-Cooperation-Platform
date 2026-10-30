/**
 * Filters and page kept in the URL query, so a filtered list survives a reload, can be linked to
 * and works with the back button (as KNOWBASE `useFilters`).
 *
 * Each filter is declared with its kind: `string` (`?q=flood`), `number` (`?organisation_id=4`)
 * or `numbers` (repeated: `?expertise_ids=1&expertise_ids=2`). Empty values are left out of the
 * URL. Changing a filter resets `page`; changing the page keeps the filters.
 */
import { computed } from 'vue'
import { useRoute, useRouter, type LocationQuery, type LocationQueryRaw } from 'vue-router'

export type FilterKind = 'string' | 'number' | 'numbers'

type FilterValue<K extends FilterKind> = K extends 'numbers'
  ? number[]
  : K extends 'number'
    ? number | undefined
    : string

export type FilterValues<D extends Record<string, FilterKind>> = {
  [P in keyof D]: FilterValue<D[P]>
}

const PAGE = 'page'

function values(query: LocationQuery, key: string): string[] {
  const raw = query[key]
  const list = Array.isArray(raw) ? raw : raw == null ? [] : [raw]
  return list.filter((v): v is string => typeof v === 'string' && v !== '')
}

const toNumber = (value: string | undefined): number | undefined => {
  const n = Number(value)
  return value !== undefined && Number.isInteger(n) && n > 0 ? n : undefined
}

function parse(kind: FilterKind, list: string[]): FilterValue<FilterKind> {
  if (kind === 'numbers') return list.map(toNumber).filter((n): n is number => n !== undefined)
  if (kind === 'number') return toNumber(list[0])
  return list[0]?.trim() ?? ''
}

function serialize(value: unknown): LocationQueryRaw[string] {
  if (Array.isArray(value)) return value.length ? value.map(String) : undefined
  if (value === undefined || value === null || value === '') return undefined
  return String(value)
}

export function useQueryFilters<D extends Record<string, FilterKind>>(definition: D) {
  const route = useRoute()
  const router = useRouter()
  const keys = Object.keys(definition) as (keyof D & string)[]

  const filters = computed(
    () =>
      Object.fromEntries(
        keys.map((key) => [key, parse(definition[key]!, values(route.query, key))]),
      ) as FilterValues<D>,
  )

  const page = computed(() => toNumber(values(route.query, PAGE)[0]) ?? 1)

  const hasFilters = computed(() =>
    keys.some((key) => {
      const value = filters.value[key] as unknown
      return Array.isArray(value) ? value.length > 0 : value !== undefined && value !== ''
    }),
  )

  function withChanges(changes: Record<string, unknown>): LocationQueryRaw {
    const query: LocationQueryRaw = { ...route.query }
    for (const [key, value] of Object.entries(changes)) {
      const serialized = serialize(value)
      if (serialized === undefined) delete query[key]
      else query[key] = serialized
    }
    return query
  }

  /** Change some filters (back to page 1). Replaces the history entry, like typing would. */
  function setFilters(changes: Partial<FilterValues<D>>) {
    return router.replace({ query: withChanges({ ...changes, [PAGE]: undefined }) })
  }

  function setFilter<K extends keyof D & string>(key: K, value: FilterValue<D[K]>) {
    return setFilters({ [key]: value } as unknown as Partial<FilterValues<D>>)
  }

  /** Go to a page (a new history entry, so Back returns to the previous page). */
  function setPage(next: number) {
    return router.push({ query: withChanges({ [PAGE]: next > 1 ? next : undefined }) })
  }

  /** Remove every declared filter and the page; other query parameters stay. */
  function clearFilters() {
    return router.replace({
      query: withChanges(Object.fromEntries([...keys, PAGE].map((key) => [key, undefined]))),
    })
  }

  return { filters, page, hasFilters, setFilter, setFilters, setPage, clearFilters }
}

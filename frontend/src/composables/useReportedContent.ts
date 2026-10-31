import { computed, ref, toValue, type MaybeRefOrGetter } from 'vue'

import { REPORTED_STORAGE_KEY } from '@/constants/moderation'
import type { ContentStatus, ContentType } from '@/services/reports'
import { useAuthStore } from '@/stores/auth'

/** Bumped on every write so computeds reading the storage re-evaluate (storage is not reactive). */
const version = ref(0)

const keyOf = (type: ContentType, id: number) => `${type}:${id}`

function read(): Set<string> {
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(REPORTED_STORAGE_KEY) ?? '[]')
    return new Set(
      Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : [],
    )
  } catch {
    // Unavailable (privacy mode) or garbled storage: nothing remembered.
    return new Set()
  }
}

/**
 * The items this member reported in this browser session, so a report button still says
 * "Reported" after a reload. Best effort: without `sessionStorage` it is simply forgotten.
 */
export function useReportedContent() {
  function isReported(type: ContentType, id: number): boolean {
    void version.value
    return read().has(keyOf(type, id))
  }

  function markReported(type: ContentType, id: number): void {
    const items = read()
    items.add(keyOf(type, id))
    try {
      sessionStorage.setItem(REPORTED_STORAGE_KEY, JSON.stringify([...items]))
    } catch {
      // Not remembered across reloads; the caller keeps its own state for this page view.
    }
    version.value++
  }

  return { isReported, markReported }
}

export type ReportTarget = {
  /** `null` for content by a former member. */
  authorId: number | null
  status: ContentStatus
  /** Optimistic items (negative ids) cannot be reported yet. */
  contentId: number
}

/** Verified members may report published content that is not their own. */
export function useCanReport(target: MaybeRefOrGetter<ReportTarget>) {
  const auth = useAuthStore()
  return computed(() => {
    const { authorId, status, contentId } = toValue(target)
    return (
      auth.isVerified &&
      status === 'published' &&
      contentId > 0 &&
      (authorId === null || authorId !== auth.user?.id)
    )
  })
}

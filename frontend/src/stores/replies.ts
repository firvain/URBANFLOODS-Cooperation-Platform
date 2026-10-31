/**
 * Replies per thread, cached for the session. Top-level replies are paged ("Load more replies");
 * their children come with them. A new reply appears at once (optimistic insert) and is replaced
 * by the server's copy, or removed again if the request fails.
 *
 * Paging: `skip` is the number of top-level replies received from the server. Replies added
 * here are kept in `added` until a later page contains them, so the offsets stay right.
 */
import { reactive } from 'vue'
import { defineStore } from 'pinia'

import { REPLIES_PAGE_SIZE } from '@/constants/forum'
import { repliesService, type ReplyOut } from '@/services/replies'
import { useAuthStore } from '@/stores/auth'

export interface ThreadReplies {
  /** Top-level replies from the server pages, in order. */
  items: ReplyOut[]
  /** Top-level replies posted here that no server page has returned yet. */
  added: ReplyOut[]
  /** Top-level replies on the server (from the last page). */
  total: number
  loading: boolean
  failed: boolean
  loaded: boolean
  /** Replies posted (+) and deleted (−) here, for the thread's reply count. */
  delta: number
}

function empty(): ThreadReplies {
  return {
    items: [],
    added: [],
    total: 0,
    loading: false,
    failed: false,
    loaded: false,
    delta: 0,
  }
}

/** Temporary ids of optimistic replies are negative, so they never clash with real ones. */
let temporaryId = 0

export const useRepliesStore = defineStore('replies', () => {
  const threads = reactive<Record<number, ThreadReplies>>({})
  /** Ids of optimistic replies still being sent. */
  const sending = reactive(new Set<number>())

  function of(threadId: number): ThreadReplies {
    threads[threadId] ??= empty()
    return threads[threadId]
  }

  /** Every top-level reply shown: server pages, then the ones posted here. */
  function list(threadId: number): ReplyOut[] {
    const state = of(threadId)
    const ids = new Set(state.items.map((reply) => reply.id))
    return [...state.items, ...state.added.filter((reply) => !ids.has(reply.id))]
  }

  const hasMore = (threadId: number) => of(threadId).items.length < of(threadId).total

  async function fetchPage(threadId: number, reset: boolean) {
    const state = of(threadId)
    state.loading = true
    state.failed = false
    try {
      const page = await repliesService.list(threadId, {
        skip: reset ? 0 : state.items.length,
        limit: REPLIES_PAGE_SIZE,
      })
      if (reset) {
        state.items = page.items
        state.added = []
        state.delta = 0
      } else {
        const ids = new Set(state.items.map((reply) => reply.id))
        state.items.push(...page.items.filter((reply) => !ids.has(reply.id)))
      }
      state.total = page.total
      state.loaded = true
    } catch {
      state.failed = true
    } finally {
      state.loading = false
    }
  }

  /** The first page (again), dropping what was cached. */
  const load = (threadId: number) => fetchPage(threadId, true)
  const loadMore = (threadId: number) => fetchPage(threadId, false)

  function findTopLevel(threadId: number, id: number): ReplyOut | undefined {
    return list(threadId).find((reply) => reply.id === id)
  }

  /** Post a reply (to a top-level reply when `parentReplyId` is set); throws the `ApiError`. */
  async function create(
    threadId: number,
    bodyHtml: string,
    parentReplyId: number | null = null,
  ): Promise<ReplyOut> {
    const state = of(threadId)
    const parent = parentReplyId === null ? undefined : findTopLevel(threadId, parentReplyId)
    const siblings = parent ? parent.children : state.added
    const now = new Date().toISOString()
    const user = useAuthStore().user
    const optimistic: ReplyOut = {
      id: --temporaryId,
      thread_id: threadId,
      parent_reply_id: parentReplyId,
      author: user
        ? {
            id: user.id,
            display_name: user.display_name,
            organisation: user.organisation,
            avatar_url: null,
          }
        : null,
      body_html: bodyHtml,
      status: 'published',
      created_at: now,
      updated_at: now,
      is_edited: false,
      children: [],
    }
    siblings.push(optimistic)
    sending.add(optimistic.id)
    const index = () => siblings.findIndex((reply) => reply.id === optimistic.id)
    try {
      const saved = await repliesService.create(threadId, {
        body_html: bodyHtml,
        ...(parentReplyId !== null ? { parent_reply_id: parentReplyId } : {}),
      })
      siblings.splice(index(), 1, { ...saved, children: saved.children ?? [] })
      state.delta += 1
      return saved
    } catch (error) {
      siblings.splice(index(), 1)
      throw error
    } finally {
      sending.delete(optimistic.id)
    }
  }

  /** Every reply of the thread, top-level and children, with the array holding it. */
  function locate(threadId: number, id: number): { reply: ReplyOut; holder: ReplyOut[] } | null {
    const state = of(threadId)
    for (const holder of [state.items, state.added]) {
      for (const reply of holder) {
        if (reply.id === id) return { reply, holder }
        const child = reply.children.find((c) => c.id === id)
        if (child) return { reply: child, holder: reply.children }
      }
    }
    return null
  }

  /** Change a reply's text; throws the `ApiError`. */
  async function update(threadId: number, id: number, bodyHtml: string): Promise<ReplyOut> {
    const saved = await repliesService.update(id, { body_html: bodyHtml })
    const found = locate(threadId, id)
    if (found) Object.assign(found.reply, { ...saved, children: found.reply.children })
    return saved
  }

  /**
   * Delete a reply; throws the `ApiError`. A top-level reply with children stays as the
   * server lists it: a placeholder.
   */
  async function remove(threadId: number, id: number): Promise<void> {
    await repliesService.remove(id)
    const state = of(threadId)
    state.delta -= 1
    const found = locate(threadId, id)
    if (!found) return
    if (found.reply.children.length) {
      Object.assign(found.reply, { status: 'deleted', body_html: '', author: null })
      return
    }
    found.holder.splice(found.holder.indexOf(found.reply), 1)
    if (found.holder === state.items) state.total = Math.max(0, state.total - 1)
    prune(threadId)
  }

  /** A top-level placeholder whose last child went is no longer listed by the server either. */
  function prune(threadId: number) {
    const state = of(threadId)
    for (const holder of [state.items, state.added]) {
      for (let i = holder.length - 1; i >= 0; i--) {
        const reply = holder[i]!
        if (reply.status === 'deleted' && !reply.children.length) {
          holder.splice(i, 1)
          if (holder === state.items) state.total = Math.max(0, state.total - 1)
        }
      }
    }
  }

  return { threads, sending, of, list, hasMore, load, loadMore, create, update, remove, prune }
})

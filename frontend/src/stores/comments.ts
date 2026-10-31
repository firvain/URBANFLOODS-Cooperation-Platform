/**
 * Comments per post, cached for the session. Flat and oldest first, paged ("Load more
 * comments"). A new comment appears at once (optimistic insert) and is replaced by the server's
 * copy, or removed again if the request fails. A deleted comment simply disappears.
 *
 * Paging: `skip` is the number of comments received from the server. Comments added here are
 * kept in `added` until a later page contains them, so the offsets stay right.
 */
import { reactive } from 'vue'
import { defineStore } from 'pinia'

import { COMMENTS_PAGE_SIZE } from '@/constants/blog'
import { commentsService, type CommentOut } from '@/services/comments'
import { useAuthStore } from '@/stores/auth'

export interface PostComments {
  /** Comments from the server pages, in order. */
  items: CommentOut[]
  /** Comments posted here that no server page has returned yet. */
  added: CommentOut[]
  /** Comments on the server (from the last page, adjusted for deletions here). */
  total: number
  loading: boolean
  failed: boolean
  loaded: boolean
}

function empty(): PostComments {
  return { items: [], added: [], total: 0, loading: false, failed: false, loaded: false }
}

/** Temporary ids of optimistic comments are negative, so they never clash with real ones. */
let temporaryId = 0

export const useCommentsStore = defineStore('comments', () => {
  const posts = reactive<Record<number, PostComments>>({})
  /** Ids of optimistic comments still being sent. */
  const sending = reactive(new Set<number>())

  function of(postId: number): PostComments {
    posts[postId] ??= empty()
    return posts[postId]
  }

  /** Every comment shown: server pages, then the ones posted here. */
  function list(postId: number): CommentOut[] {
    const state = of(postId)
    const ids = new Set(state.items.map((comment) => comment.id))
    return [...state.items, ...state.added.filter((comment) => !ids.has(comment.id))]
  }

  const hasMore = (postId: number) => of(postId).items.length < of(postId).total

  /** Comments on the post: the ones not loaded yet plus every one shown. */
  function count(postId: number): number {
    const state = of(postId)
    return Math.max(0, state.total - state.items.length) + list(postId).length
  }

  async function fetchPage(postId: number, reset: boolean) {
    const state = of(postId)
    state.loading = true
    state.failed = false
    try {
      const page = await commentsService.list(postId, {
        skip: reset ? 0 : state.items.length,
        limit: COMMENTS_PAGE_SIZE,
      })
      if (reset) {
        state.items = page.items
        state.added = []
      } else {
        const ids = new Set(state.items.map((comment) => comment.id))
        state.items.push(...page.items.filter((comment) => !ids.has(comment.id)))
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
  const load = (postId: number) => fetchPage(postId, true)
  const loadMore = (postId: number) => fetchPage(postId, false)

  /** Post a comment; throws the `ApiError`. */
  async function create(postId: number, bodyHtml: string): Promise<CommentOut> {
    const state = of(postId)
    const now = new Date().toISOString()
    const user = useAuthStore().user
    const optimistic: CommentOut = {
      id: --temporaryId,
      post_id: postId,
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
    }
    state.added.push(optimistic)
    sending.add(optimistic.id)
    const index = () => state.added.findIndex((comment) => comment.id === optimistic.id)
    try {
      const saved = await commentsService.create(postId, { body_html: bodyHtml })
      state.added.splice(index(), 1, saved)
      return saved
    } catch (error) {
      state.added.splice(index(), 1)
      throw error
    } finally {
      sending.delete(optimistic.id)
    }
  }

  /** Change a comment's text; throws the `ApiError`. */
  async function update(postId: number, id: number, bodyHtml: string): Promise<CommentOut> {
    const saved = await commentsService.update(id, { body_html: bodyHtml })
    const state = of(postId)
    for (const holder of [state.items, state.added]) {
      const index = holder.findIndex((comment) => comment.id === id)
      if (index >= 0) holder.splice(index, 1, saved)
    }
    return saved
  }

  /** Delete a comment; throws the `ApiError`. It disappears from the list. */
  async function remove(postId: number, id: number): Promise<void> {
    await commentsService.remove(id)
    const state = of(postId)
    const index = state.items.findIndex((comment) => comment.id === id)
    if (index >= 0) {
      state.items.splice(index, 1)
      state.total = Math.max(0, state.total - 1)
    }
    state.added = state.added.filter((comment) => comment.id !== id)
  }

  return { posts, sending, of, list, hasMore, count, load, loadMore, create, update, remove }
})

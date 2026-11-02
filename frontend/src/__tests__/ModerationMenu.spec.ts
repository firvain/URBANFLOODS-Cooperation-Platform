import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import i18n from '@/i18n'
import type { UserMe } from '@/services/auth'
import type { ContentStatus } from '@/services/moderation'
import type { PostDetail } from '@/services/posts'
import { callsTo, makeUser, mockApi, reply, replyError, type Handler } from './helpers/api'
import { findButton, menuItemTexts, openMenu } from './helpers/admin'
import { makePostDetail } from './helpers/blog'
import { buttonIn, dialog, field } from './helpers/editor'
import { makeThreadDetail, repliesOf } from './helpers/forum'
import { mountApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'
const POST_SLUG = 'rain-gardens-in-kozani'
const THREAD_SLUG = 'sirens-or-sms'
const GET_POST = `GET /api/v1/posts/${POST_SLUG}`
const GET_THREAD = `GET /api/v1/threads/${THREAD_SLUG}`
const MOD = '/api/v1/moderation'
const ADMIN = makeUser({ id: 99, role: 'admin' })
const SUPERADMIN = makeUser({ id: 98, role: 'superadmin' })
const MENU = () => t('moderation.menu')

afterEach(unmountAll)

const result = (status: ContentStatus, type = 'post', hidden_reason: string | null = null) => ({
  content_type: type,
  id: 42,
  status,
  hidden_reason,
  published_at: '2026-10-20T09:00:00Z',
  deleted_at: status === 'deleted' ? '2026-10-31T09:00:00Z' : null,
  author_trusted: true,
})

async function mountPost(
  status: ContentStatus = 'published',
  user: UserMe | null = ADMIN,
  extra: Record<string, Handler> = {},
  post: Partial<PostDetail> = {},
) {
  const fetchMock = mockApi({
    [GET_POST]: reply(
      200,
      makePostDetail({ status, hidden_reason: status === 'hidden' ? 'admin' : null, ...post }),
    ),
    'GET /api/v1/posts/42/comments/': reply(200, { total: 0, items: [] }),
    ...(user ? { [ME]: reply(200, user) } : {}),
    ...extra,
  })
  const mounted = await mountApp(`/blog/${POST_SLUG}`)
  await flushPromises()
  return { ...mounted, fetchMock }
}

async function mountThread(
  status: ContentStatus = 'published',
  extra: Record<string, Handler> = {},
) {
  const fetchMock = mockApi({
    [GET_THREAD]: reply(200, makeThreadDetail({ status })),
    [`GET ${repliesOf(42)}`]: reply(200, { total: 0, items: [] }),
    [ME]: reply(200, ADMIN),
    ...extra,
  })
  const mounted = await mountApp(`/forum/t/${THREAD_SLUG}`)
  await flushPromises()
  return { ...mounted, fetchMock }
}

async function choose(item: string) {
  const items = await openMenu(MENU())
  const found = items.find((i) => i.textContent?.trim() === item)
  expect(found, `menu item ${item}`).toBeDefined()
  found!.click()
  await flushPromises()
}

const badge = () => document.querySelector('[data-testid="post-status"]')?.textContent?.trim()
const toastShown = (text: string) =>
  vi.waitFor(() => expect(document.body.textContent).toContain(text))

describe('ModerationMenu visibility', () => {
  it('is not shown to visitors', async () => {
    await mountPost('published', null)
    expect(findButton(MENU())).toBeUndefined()
  })

  it.each([
    ['a member', makeUser({ id: 50 })],
    ['the author', makeUser({ id: 11 })],
  ])('is not shown to %s', async (_who, user) => {
    await mountPost('published', user)
    expect(findButton(MENU())).toBeUndefined()
  })

  it.each([
    ['an admin', ADMIN],
    ['a superadmin', SUPERADMIN],
  ])('is shown to %s on a post', async (_who, user) => {
    await mountPost('published', user)
    expect(findButton(MENU())).toBeDefined()
  })

  it('is shown to an admin on a thread', async () => {
    await mountThread()
    expect(findButton(MENU())).toBeDefined()
  })
})

describe('ModerationMenu actions per status', () => {
  it.each<[ContentStatus, string[]]>([
    ['pending', ['moderation.approve', 'moderation.delete', 'moderation.purge']],
    ['published', ['moderation.hide', 'moderation.delete', 'moderation.purge']],
    ['hidden', ['moderation.unhide', 'moderation.delete', 'moderation.purge']],
    ['deleted', ['moderation.restore', 'moderation.purge']],
  ])('offers the valid actions for %s content', async (status, keys) => {
    await mountPost(status)
    await openMenu(MENU())
    expect(menuItemTexts()).toEqual(keys.map((key) => t(key)))
  })
})

describe('ModerationMenu state changes', () => {
  it('approves a pending post in place', async () => {
    const route = `POST ${MOD}/post/42/approve`
    const { fetchMock } = await mountPost('pending', ADMIN, {
      [route]: reply(200, result('published')),
    })
    expect(badge()).toBe(t('post.status.pending'))
    await choose(t('moderation.approve'))
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(badge()).toBeUndefined()
    expect(document.querySelector('[data-testid="status-hint"]')).toBeNull()
    await toastShown(t('moderation.done.approve'))
  })

  it('hides a published post with a reason', async () => {
    const route = `POST ${MOD}/post/42/hide`
    const { fetchMock } = await mountPost('published', ADMIN, {
      [route]: reply(200, result('hidden', 'post', 'admin')),
    })
    await choose(t('moderation.hide'))
    expect(callsTo(fetchMock, route)).toHaveLength(0)
    const box = dialog()
    expect(box.textContent).toContain(t('moderation.hideTitle'))
    await field(box, t('admin.queue.reason')).setValue('Advertising')
    buttonIn(box, t('moderation.hide')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)[0]!.body).toEqual({ reason: 'Advertising' })
    expect(badge()).toBe(t('post.status.hidden'))
    expect(document.querySelector('[data-testid="status-hint"]')?.textContent).toContain(
      t('post.statusHint.hidden'),
    )
    await toastShown(t('moderation.done.hide'))
  })

  it('unhides a hidden post', async () => {
    const route = `POST ${MOD}/post/42/unhide`
    const { fetchMock } = await mountPost('hidden', ADMIN, {
      [route]: reply(200, result('published')),
    })
    await choose(t('moderation.unhide'))
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(badge()).toBeUndefined()
    await toastShown(t('moderation.done.unhide'))
  })

  it('deletes after confirming, then offers Restore', async () => {
    const route = `POST ${MOD}/post/42/delete`
    const { fetchMock, router } = await mountPost('published', ADMIN, {
      [route]: reply(200, result('deleted')),
    })
    await choose(t('moderation.delete'))
    expect(dialog().textContent).toContain(t('moderation.deleteTitle'))
    buttonIn(dialog(), t('moderation.delete')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(badge()).toBe(t('post.status.deleted'))
    expect(router.currentRoute.value.path).toBe(`/blog/${POST_SLUG}`)
    await openMenu(MENU())
    expect(menuItemTexts()).toEqual([t('moderation.restore'), t('moderation.purge')])
  })

  it('restores a deleted post', async () => {
    const route = `POST ${MOD}/post/42/restore`
    const { fetchMock } = await mountPost('deleted', ADMIN, {
      [route]: reply(200, result('published')),
    })
    await choose(t('moderation.restore'))
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(badge()).toBeUndefined()
    await toastShown(t('moderation.done.restore'))
  })

  it('restores a deleted post that was hidden: it stays hidden and the toast says so', async () => {
    const route = `POST ${MOD}/post/42/restore`
    await mountPost('deleted', ADMIN, {
      [route]: reply(200, result('hidden', 'post', 'admin')),
    })
    await choose(t('moderation.restore'))
    expect(badge()).toBe(t('post.status.hidden'))
    await toastShown(t('moderation.done.restoreHidden'))
    expect(t('moderation.done.restoreHidden')).not.toMatch(/publish/i)
  })

  it('shows a refused action as a translated error', async () => {
    const route = `POST ${MOD}/post/42/approve`
    await mountPost('pending', ADMIN, {
      [route]: replyError(409, 'moderation.invalid_transition'),
    })
    await choose(t('moderation.approve'))
    await toastShown(t('admin.errors.moderation.invalid_transition'))
    expect(badge()).toBe(t('post.status.pending'))
  })

  it('hides a thread from its page', async () => {
    const route = `POST ${MOD}/thread/42/hide`
    const { fetchMock } = await mountThread('published', {
      [route]: reply(200, result('hidden', 'thread', 'admin')),
    })
    await choose(t('moderation.hide'))
    buttonIn(dialog(), t('moderation.hide')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)[0]!.body).toEqual({ reason: null })
    expect(badge()).toBe(t('post.status.hidden'))
  })
})

describe('ModerationMenu permanent delete', () => {
  const PURGE = `POST ${MOD}/post/42/purge`
  const purged = {
    content_type: 'post',
    id: 42,
    purged: true,
    children_deleted: 3,
    attachments_deleted: 1,
    reports_resolved: 0,
  }

  async function openPurge(extra: Record<string, Handler> = {}) {
    const mounted = await mountPost('published', ADMIN, { [PURGE]: reply(200, purged), ...extra })
    await choose(t('moderation.purge'))
    return mounted
  }

  const confirmButton = () => buttonIn(dialog(), t('moderation.purgeDialog.confirm'))
  const typed = () => field(dialog(), t('moderation.purgeDialog.typeLabel', { word: 'DELETE' }))

  it('explains what is removed for a post', async () => {
    await openPurge()
    const text = dialog().textContent ?? ''
    expect(text).toContain(t('moderation.purgeDialog.title'))
    expect(text).toContain(t('moderation.purgeDialog.content.post'))
    expect(text).toContain(t('moderation.purgeDialog.children.post'))
    expect(text).toContain(t('moderation.purgeDialog.images'))
  })

  it('stays disabled until DELETE is typed exactly', async () => {
    const { fetchMock } = await openPurge()
    expect(confirmButton().disabled).toBe(true)
    await typed().setValue('delete')
    expect(confirmButton().disabled).toBe(true)
    confirmButton().click()
    await flushPromises()
    expect(callsTo(fetchMock, PURGE)).toHaveLength(0)
    await typed().setValue('DELETE')
    expect(confirmButton().disabled).toBe(false)
  })

  it('starts empty every time it opens', async () => {
    await openPurge()
    await typed().setValue('DELETE')
    buttonIn(dialog(), t('common.cancel')).click()
    await flushPromises()
    await choose(t('moderation.purge'))
    expect(typed().element.value).toBe('')
  })

  it('purges after confirmation and goes to the blog with a toast', async () => {
    const { fetchMock, router } = await openPurge()
    await typed().setValue('DELETE')
    confirmButton().click()
    await flushPromises()
    expect(callsTo(fetchMock, PURGE)).toHaveLength(1)
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/blog'))
    await toastShown(t('moderation.done.purge'))
  })

  it('cancelling sends nothing', async () => {
    const { fetchMock, router } = await openPurge()
    buttonIn(dialog(), t('common.cancel')).click()
    await flushPromises()
    expect(callsTo(fetchMock, PURGE)).toHaveLength(0)
    expect(router.currentRoute.value.path).toBe(`/blog/${POST_SLUG}`)
  })

  it('shows an error in the dialog and stays on the page', async () => {
    const { router } = await openPurge({
      [PURGE]: replyError(404, 'moderation.content_not_found'),
    })
    await typed().setValue('DELETE')
    confirmButton().click()
    await flushPromises()
    expect(dialog().textContent).toContain(t('admin.errors.moderation.content_not_found'))
    expect(router.currentRoute.value.path).toBe(`/blog/${POST_SLUG}`)
  })

  it('purges a thread and goes to the forum', async () => {
    const route = `POST ${MOD}/thread/42/purge`
    const { fetchMock, router } = await mountThread('hidden', {
      [route]: reply(200, { ...purged, content_type: 'thread' }),
    })
    await choose(t('moderation.purge'))
    expect(dialog().textContent).toContain(t('moderation.purgeDialog.children.thread'))
    await typed().setValue('DELETE')
    confirmButton().click()
    await flushPromises()
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/forum'))
  })
})

describe('ModerationMenu page update', () => {
  const postDate = () =>
    document.querySelector('[data-testid="post-author"] time')?.getAttribute('datetime')
  const deletedAt = () => document.querySelector('[data-testid="deleted-at"]')

  it('restoring a never-approved post shows it pending, without a publication date', async () => {
    const route = `POST ${MOD}/post/42/restore`
    await mountPost(
      'deleted',
      ADMIN,
      {
        [route]: reply(200, {
          ...result('pending'),
          published_at: null,
          deleted_at: null,
        }),
      },
      { created_at: '2026-10-18T08:00:00Z', published_at: '2026-10-20T09:00:00Z' },
    )
    expect(postDate()).toBe('2026-10-20T09:00:00Z')
    await choose(t('moderation.restore'))
    expect(badge()).toBe(t('post.status.pending'))
    expect(postDate()).toBe('2026-10-18T08:00:00Z')
  })

  it('shows the deletion date after a delete and clears it on restore', async () => {
    await mountPost('published', ADMIN, {
      [`POST ${MOD}/post/42/delete`]: reply(200, result('deleted')),
      [`POST ${MOD}/post/42/restore`]: reply(200, result('published')),
    })
    expect(deletedAt()).toBeNull()
    await choose(t('moderation.delete'))
    buttonIn(dialog(), t('moderation.delete')).click()
    await flushPromises()
    expect(deletedAt()?.getAttribute('datetime')).toBe('2026-10-31T09:00:00Z')
    await choose(t('moderation.restore'))
    expect(badge()).toBeUndefined()
    expect(deletedAt()).toBeNull()
  })

  it('applies the thread result as returned, deletion date included', async () => {
    await mountThread('published', {
      [`POST ${MOD}/thread/42/delete`]: reply(200, result('deleted', 'thread')),
    })
    await choose(t('moderation.delete'))
    buttonIn(dialog(), t('moderation.delete')).click()
    await flushPromises()
    expect(badge()).toBe(t('post.status.deleted'))
    expect(deletedAt()?.getAttribute('datetime')).toBe('2026-10-31T09:00:00Z')
  })
})

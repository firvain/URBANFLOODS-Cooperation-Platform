import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import i18n from '@/i18n'
import { callsTo, reply, replyError } from './helpers/api'
import { click, makeDeletedItem, mountAdmin, page, queryOf, tableRows } from './helpers/admin'
import { buttonIn, dialog, field } from './helpers/editor'
import { enterOption, openSelect } from './helpers/select'
import { unmountAll } from './helpers/mount'

const t = i18n.global.t
const DELETED = 'GET /api/v1/moderation/deleted/'
const POST = makeDeletedItem()
const THREAD = makeDeletedItem(
  {
    content_type: 'thread',
    id: 12,
    title: 'Sandbags or barriers?',
    slug: 'sandbags-or-barriers',
    author: null,
    deleted_by: { id: 8, display_name: 'Ana' },
  },
  0.4,
)
const result = (status: string, type = 'post', id = 1) => ({
  content_type: type,
  id,
  status,
  hidden_reason: null,
  published_at: '2026-10-01T08:00:00Z',
  deleted_at: null,
  author_trusted: true,
})

const rows = () => tableRows('deleted')
const lastQuery = (fetchMock: Parameters<typeof callsTo>[0]) =>
  queryOf(callsTo(fetchMock, DELETED).at(-1)!.url)

afterEach(unmountAll)

describe('Admin deleted content', () => {
  it('lists deleted items with type, link, author, who deleted them and days left', async () => {
    await mountAdmin('/admin/deleted', { [DELETED]: reply(200, page([POST, THREAD])) })
    expect(rows()).toHaveLength(2)
    const table = document.querySelector('table')!
    expect(table.querySelector('caption')?.textContent).toContain(t('admin.deleted.caption'))
    const [post, thread] = rows()
    expect(post!.textContent).toContain(t('admin.contentType.post'))
    expect(post!.querySelector('a[href="/blog/green-roofs-in-kozani"]')?.textContent).toContain(
      'Green roofs in Kozani',
    )
    expect(post!.querySelector('a[href="/u/7"]')?.textContent).toContain('Nikos')
    expect(post!.querySelector('a[href="/u/1"]')?.textContent).toContain('Ada Admin')
    expect(post!.querySelector('time')).not.toBeNull()
    expect(post!.textContent).toContain(t('admin.deleted.daysLeft', 6))
    expect(thread!.querySelector('a[href="/forum/t/sandbags-or-barriers"]')).not.toBeNull()
    expect(thread!.querySelector('a[href="/u/8"]')?.textContent).toContain('Ana')
    expect(thread!.textContent).toContain(t('admin.deleted.daysLeft', 0))
    expect(t('admin.deleted.daysLeft', 0)).toBe('today')
    expect(t('admin.deleted.daysLeft', 6)).toBe('6 days')
  })

  it('says how many days items are kept, from the response', async () => {
    await mountAdmin('/admin/deleted', { [DELETED]: reply(200, page([POST])) })
    expect(document.body.textContent).toContain(t('admin.deleted.introDays', { days: 7 }))
    expect(t('admin.deleted.introDays', { days: 7 })).toBe(
      'Deleted posts and discussions are kept for 7 days so they can be restored, then removed for good.',
    )
  })

  it('says items are kept when automatic removal is off', async () => {
    const kept = makeDeletedItem({ purge_at: null })
    await mountAdmin('/admin/deleted', { [DELETED]: reply(200, page([kept])) })
    expect(document.body.textContent).toContain(t('admin.deleted.introKept'))
    expect(rows()[0]!.textContent).toContain(t('admin.deleted.never'))
  })

  it('shows an empty state', async () => {
    await mountAdmin('/admin/deleted', { [DELETED]: reply(200, page([])) })
    expect(document.body.textContent).toContain(t('admin.deleted.empty'))
  })

  it('asks for the page and type from the URL', async () => {
    const { fetchMock } = await mountAdmin('/admin/deleted?type=thread&page=2', {
      [DELETED]: reply(200, page([THREAD], 45)),
    })
    const query = lastQuery(fetchMock)
    expect(query.get('type')).toBe('thread')
    expect(query.get('skip')).toBe('20')
    expect(
      document.querySelector(`nav[aria-label="${t('admin.common.pagination')}"]`),
    ).not.toBeNull()
  })

  it('changing the type filter updates the URL and the request', async () => {
    const { fetchMock, router, wrapper } = await mountAdmin('/admin/deleted', {
      [DELETED]: reply(200, page([POST])),
    })
    expect(lastQuery(fetchMock).get('type')).toBeNull()
    await openSelect(wrapper, t('admin.deleted.type'))
    await enterOption(t('admin.deleted.types.post'))
    await flushPromises()
    expect(router.currentRoute.value.query.type).toBe('post')
    expect(lastQuery(fetchMock).get('type')).toBe('post')
  })

  it('restores after confirmation: the row goes and a toast confirms', async () => {
    const route = 'POST /api/v1/moderation/post/1/restore'
    const { fetchMock } = await mountAdmin('/admin/deleted', {
      [DELETED]: reply(200, page([POST, THREAD])),
      [route]: reply(200, result('published')),
    })
    await click(t('admin.deleted.restoreLabel', { title: POST.title }))
    const box = dialog()
    expect(box.textContent).toContain(t('admin.deleted.restoreTitle', { title: POST.title }))
    expect(callsTo(fetchMock, route)).toHaveLength(0)
    buttonIn(box, t('admin.deleted.restore')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(rows()).toHaveLength(1)
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain(
        t('admin.deleted.restored', { title: POST.title }),
      ),
    )
  })

  it('keeps the row and explains when the restore fails', async () => {
    await mountAdmin('/admin/deleted', {
      [DELETED]: reply(200, page([POST])),
      'POST /api/v1/moderation/post/1/restore': replyError(404, 'moderation.content_not_found'),
    })
    await click(t('admin.deleted.restoreLabel', { title: POST.title }))
    buttonIn(dialog(), t('admin.deleted.restore')).click()
    await flushPromises()
    expect(rows()).toHaveLength(1)
    expect(dialog().textContent).toContain(t('admin.errors.moderation.content_not_found'))
  })

  it('deletes permanently through the typed confirmation', async () => {
    const route = 'POST /api/v1/moderation/thread/12/purge'
    const { fetchMock } = await mountAdmin('/admin/deleted', {
      [DELETED]: reply(200, page([POST, THREAD])),
      [route]: reply(200, {
        content_type: 'thread',
        id: 12,
        purged: true,
        children_deleted: 2,
        attachments_deleted: 0,
        reports_resolved: 0,
      }),
    })
    await click(t('admin.deleted.purgeLabel', { title: THREAD.title }))
    const box = dialog()
    expect(box.textContent).toContain(t('moderation.purgeDialog.children.thread'))
    const confirm = buttonIn(box, t('moderation.purgeDialog.confirm'))
    expect(confirm.disabled).toBe(true)
    await field(box, t('moderation.purgeDialog.typeLabel', { word: 'DELETE' })).setValue('DELETE')
    expect(confirm.disabled).toBe(false)
    confirm.click()
    await flushPromises()
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(rows()).toHaveLength(1)
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain(
        t('admin.deleted.purged', { title: THREAD.title }),
      ),
    )
  })
})

import { afterEach, describe, expect, it, vi } from 'vitest'
import { DOMWrapper, flushPromises } from '@vue/test-utils'

import i18n from '@/i18n'
import { callsTo, deferred, jsonResponse, reply, replyError } from './helpers/api'
import { click, makeQueueItem, mountAdmin, page, queryOf, tableRows } from './helpers/admin'
import { buttonIn, dialog } from './helpers/editor'
import { unmountAll } from './helpers/mount'

const t = i18n.global.t
const QUEUE = 'GET /api/v1/moderation/queue/'
const POST = makeQueueItem()
const THREAD = makeQueueItem({
  content_type: 'thread',
  id: 12,
  title: 'Sandbags or barriers?',
  slug: 'sandbags-or-barriers',
  author: { id: 8, display_name: 'Ana', trusted: true },
  category: { id: 5, name: 'Preparedness', slug: 'preparedness' },
})
const result = (status: string) => ({
  content_type: 'post',
  id: 11,
  status,
  hidden_reason: null,
  published_at: null,
  deleted_at: null,
  author_trusted: true,
})

const rows = () => tableRows('queue')

afterEach(unmountAll)

describe('Admin queue', () => {
  it('lists pending items with type, link, author, category and excerpt', async () => {
    await mountAdmin('/admin/queue', { [QUEUE]: reply(200, page([POST, THREAD])) })
    expect(rows()).toHaveLength(2)
    const table = document.querySelector('table')!
    expect(table.querySelector('caption')?.textContent).toContain(t('admin.queue.caption'))
    expect(table.querySelectorAll('th[scope="col"]').length).toBeGreaterThan(3)
    const [post, thread] = rows()
    expect(post!.textContent).toContain(t('admin.contentType.post'))
    expect(post!.querySelector('a[href="/blog/green-roofs-in-kozani"]')?.textContent).toContain(
      'Green roofs in Kozani',
    )
    expect(post!.textContent).toContain('Nature-based solutions')
    expect(post!.textContent).toContain('How the municipality retrofitted public buildings.')
    expect(post!.textContent).not.toContain(t('admin.queue.trusted'))
    expect(thread!.querySelector('a[href="/forum/t/sandbags-or-barriers"]')).not.toBeNull()
    expect(thread!.textContent).toContain(t('admin.queue.trusted'))
  })

  it('marks an item its author resubmitted after a rejection', async () => {
    const again = makeQueueItem({ id: 13, slug: 'again', title: 'Again', resubmitted: true })
    await mountAdmin('/admin/queue', { [QUEUE]: reply(200, page([POST, again])) })
    const [first, second] = rows()
    expect(first!.querySelector('[data-testid="queue-resubmitted"]')).toBeNull()
    expect(second!.querySelector('[data-testid="queue-resubmitted"]')?.textContent).toContain(
      t('admin.queue.resubmitted'),
    )
    expect(t('admin.queue.resubmitted')).toBe('Resubmitted')
  })

  it('shows an empty state', async () => {
    await mountAdmin('/admin/queue', { [QUEUE]: reply(200, page([])) })
    expect(document.body.textContent).toContain(t('admin.queue.empty'))
  })

  it('asks for the page from the URL', async () => {
    const { fetchMock } = await mountAdmin('/admin/queue?page=2', {
      [QUEUE]: reply(200, page([POST], 45)),
    })
    expect(queryOf(callsTo(fetchMock, QUEUE)[0]!.url).get('skip')).toBe('20')
    expect(
      document.querySelector(`nav[aria-label="${t('admin.common.pagination')}"]`),
    ).not.toBeNull()
  })

  it('approves a row: removed at once, then a toast', async () => {
    const held = deferred<Response>()
    const route = 'POST /api/v1/moderation/post/11/approve'
    const { fetchMock } = await mountAdmin('/admin/queue', {
      [QUEUE]: reply(200, page([POST, THREAD])),
      [route]: () => held.promise,
    })
    await click(t('admin.queue.approveLabel', { title: POST.title }))
    expect(rows()).toHaveLength(1)
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    held.resolve(jsonResponse(result('published')))
    await flushPromises()
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain(t('admin.queue.approved', { title: POST.title })),
    )
  })

  it('puts the row back and explains when the approval fails', async () => {
    await mountAdmin('/admin/queue', {
      [QUEUE]: reply(200, page([POST])),
      'POST /api/v1/moderation/post/11/approve': replyError(409, 'moderation.invalid_transition'),
    })
    await click(t('admin.queue.approveLabel', { title: POST.title }))
    expect(rows()).toHaveLength(1)
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain(t('admin.errors.moderation.invalid_transition')),
    )
  })

  it('rejects with the reason typed in the dialog', async () => {
    const route = 'POST /api/v1/moderation/thread/12/reject'
    const { fetchMock } = await mountAdmin('/admin/queue', {
      [QUEUE]: reply(200, page([POST, THREAD])),
      [route]: reply(200, { ...result('hidden'), content_type: 'thread', id: 12 }),
    })
    await click(t('admin.queue.rejectLabel', { title: THREAD.title }))
    const box = dialog()
    expect(box.textContent).toContain(t('admin.queue.rejectTitle', { title: THREAD.title }))
    const textarea = box.querySelector('textarea')!
    expect(textarea.id).toBeTruthy()
    expect(box.querySelector(`label[for="${textarea.id}"]`)?.textContent).toContain(
      t('admin.queue.reason'),
    )
    await new DOMWrapper(textarea).setValue('Advertising')
    buttonIn(box, t('admin.queue.reject')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)[0]!.body).toEqual({ reason: 'Advertising' })
    expect(rows()).toHaveLength(1)
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain(
        t('admin.queue.rejected', { title: THREAD.title }),
      ),
    )
  })

  it('rejects without a reason', async () => {
    const route = 'POST /api/v1/moderation/post/11/reject'
    const { fetchMock } = await mountAdmin('/admin/queue', {
      [QUEUE]: reply(200, page([POST])),
      [route]: reply(200, result('hidden')),
    })
    await click(t('admin.queue.rejectLabel', { title: POST.title }))
    buttonIn(dialog(), t('admin.queue.reject')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)[0]!.body).toEqual({ reason: null })
  })
})

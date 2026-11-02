import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import i18n from '@/i18n'
import { callsTo, reply } from './helpers/api'
import {
  button,
  chooseMenuItem,
  makeReport,
  menuItemTexts,
  mountAdmin,
  openMenu,
  page,
  queryOf,
  tableRows,
} from './helpers/admin'
import { buttonIn, dialog } from './helpers/editor'
import { enterOption, openSelect } from './helpers/select'
import { unmountAll } from './helpers/mount'

const t = i18n.global.t
const REPORTS = 'GET /api/v1/reports/'
const REPORT = makeReport()
const COMMENT_REPORT = makeReport({
  id: 40,
  content_type: 'comment',
  content_id: 77,
  reason: 'abuse',
  details: null,
  reporter: null,
  content: {
    type: 'comment',
    id: 77,
    title: null,
    excerpt: 'You are all idiots',
    status: 'hidden',
    author_id: 9,
    url_slug: 'green-roofs-in-kozani',
  },
})
const result = (status: string) => ({
  content_type: 'thread',
  id: 12,
  status,
  hidden_reason: status === 'hidden' ? 'admin' : null,
  published_at: null,
  deleted_at: null,
  author_trusted: false,
})
const rows = () => tableRows('reports')
const lastQuery = (fetchMock: Parameters<typeof callsTo>[0]) =>
  queryOf(callsTo(fetchMock, REPORTS).at(-1)!.url)
const actions = (id: number) => t('admin.reports.actionsFor', { id })

afterEach(unmountAll)

describe('Admin reports', () => {
  it('asks for open reports by default and lists them', async () => {
    const { fetchMock } = await mountAdmin('/admin/reports', {
      [REPORTS]: reply(200, page([REPORT, COMMENT_REPORT])),
    })
    expect(lastQuery(fetchMock).get('status')).toBe('open')
    expect(lastQuery(fetchMock).get('content_type')).toBeNull()
    const [thread, comment] = rows()
    expect(thread!.textContent).toContain(t('admin.reports.reasons.spam'))
    expect(thread!.textContent).toContain('Advertises a pump shop.')
    expect(thread!.textContent).toContain('Elena')
    expect(thread!.textContent).toContain(t('admin.contentStatus.published'))
    expect(thread!.querySelector('a[href="/forum/t/cheap-pumps-here"]')?.textContent).toContain(
      'Cheap pumps here',
    )
    expect(comment!.textContent).toContain('You are all idiots')
    expect(comment!.textContent).toContain(t('admin.reports.deletedAccount'))
    expect(
      comment!.querySelector('a[href="/blog/green-roofs-in-kozani#comment-77"]'),
    ).not.toBeNull()
  })

  it('takes the filters from the URL', async () => {
    const { fetchMock } = await mountAdmin('/admin/reports?status=resolved&content_type=reply', {
      [REPORTS]: reply(200, page([])),
    })
    expect(lastQuery(fetchMock).get('status')).toBe('resolved')
    expect(lastQuery(fetchMock).get('content_type')).toBe('reply')
    expect(document.body.textContent).toContain(t('admin.reports.empty'))
  })

  it('"all" statuses sends no status filter', async () => {
    const { fetchMock } = await mountAdmin('/admin/reports?status=all', {
      [REPORTS]: reply(200, page([])),
    })
    expect(lastQuery(fetchMock).get('status')).toBeNull()
  })

  it('changing the type filter updates the URL and the request', async () => {
    const { fetchMock, router, wrapper } = await mountAdmin('/admin/reports', {
      [REPORTS]: reply(200, page([REPORT])),
    })
    await openSelect(wrapper, t('admin.reports.type'))
    await enterOption(t('admin.contentType.comment'))
    await flushPromises()
    expect(router.currentRoute.value.query.content_type).toBe('comment')
    expect(lastQuery(fetchMock).get('content_type')).toBe('comment')
    expect(lastQuery(fetchMock).get('status')).toBe('open')
  })

  it('resolves a report and shows its new status', async () => {
    const route = 'POST /api/v1/reports/31/resolve'
    const { fetchMock } = await mountAdmin('/admin/reports', {
      [REPORTS]: reply(200, page([REPORT])),
      [route]: reply(200, makeReport({ status: 'resolved' })),
    })
    await chooseMenuItem(actions(31), t('admin.reports.resolve'))
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(rows()[0]!.textContent).toContain(t('admin.reports.statuses.resolved'))
    await vi.waitFor(() => expect(document.body.textContent).toContain(t('admin.reports.resolved')))
  })

  it('dismisses a report', async () => {
    const route = 'POST /api/v1/reports/31/dismiss'
    const { fetchMock } = await mountAdmin('/admin/reports', {
      [REPORTS]: reply(200, page([REPORT])),
      [route]: reply(200, makeReport({ status: 'dismissed' })),
    })
    await chooseMenuItem(actions(31), t('admin.reports.dismiss'))
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(rows()[0]!.textContent).toContain(t('admin.reports.statuses.dismissed'))
  })

  it('hides the content after confirming, with an optional reason', async () => {
    const route = 'POST /api/v1/moderation/thread/12/hide'
    const { fetchMock } = await mountAdmin('/admin/reports', {
      [REPORTS]: reply(200, page([REPORT])),
      [route]: reply(200, result('hidden')),
    })
    await chooseMenuItem(actions(31), t('admin.reports.hide'))
    expect(callsTo(fetchMock, route)).toHaveLength(0)
    const box = dialog()
    expect(box.textContent).toContain(t('admin.reports.hideTitle'))
    buttonIn(box, t('admin.reports.hide')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)[0]!.body).toEqual({ reason: null })
    expect(rows()[0]!.textContent).toContain(t('admin.contentStatus.hidden'))
  })

  it('offers Unhide (not Hide) for hidden content', async () => {
    const route = 'POST /api/v1/moderation/comment/77/unhide'
    const { fetchMock } = await mountAdmin('/admin/reports', {
      [REPORTS]: reply(200, page([COMMENT_REPORT])),
      [route]: reply(200, { ...result('published'), content_type: 'comment', id: 77 }),
    })
    await chooseMenuItem(actions(40), t('admin.reports.unhide'))
    buttonIn(dialog(), t('admin.reports.unhide')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(rows()[0]!.textContent).toContain(t('admin.contentStatus.published'))
  })

  it('deletes the content only after confirming', async () => {
    const route = 'POST /api/v1/moderation/thread/12/delete'
    const { fetchMock } = await mountAdmin('/admin/reports', {
      [REPORTS]: reply(200, page([REPORT])),
      [route]: reply(200, result('deleted')),
    })
    await chooseMenuItem(actions(31), t('admin.reports.delete'))
    expect(dialog().textContent).toContain(t('admin.reports.deleteTitle'))
    buttonIn(dialog(), t('common.cancel')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)).toHaveLength(0)

    await chooseMenuItem(actions(31), t('admin.reports.delete'))
    buttonIn(dialog(), t('admin.reports.delete')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(rows()[0]!.textContent).toContain(t('admin.contentStatus.deleted'))
  })

  it('links each report to the audit log of its content type', async () => {
    await mountAdmin('/admin/reports', { [REPORTS]: reply(200, page([REPORT])) })
    const link = rows()[0]!.querySelector('a[href="/admin/log?target_type=thread"]')
    expect(link).not.toBeNull()
    expect(button(actions(31))).toBeTruthy()
  })

  it('offers Restore (and no Delete) for deleted content and restores it', async () => {
    const route = 'POST /api/v1/moderation/thread/12/restore'
    const deleted = makeReport({ content: { ...REPORT.content!, status: 'deleted' } })
    const { fetchMock } = await mountAdmin('/admin/reports', {
      [REPORTS]: reply(200, page([deleted])),
      [route]: reply(200, result('published')),
    })
    await openMenu(actions(31))
    expect(menuItemTexts()).toContain(t('admin.reports.restore'))
    expect(menuItemTexts()).not.toContain(t('admin.reports.delete'))
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    await chooseMenuItem(actions(31), t('admin.reports.restore'))
    const box = dialog()
    expect(box.textContent).toContain(t('admin.reports.restoreTitle'))
    buttonIn(box, t('admin.reports.restore')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(rows()[0]!.textContent).toContain(t('admin.contentStatus.published'))
    await vi.waitFor(() => expect(document.body.textContent).toContain(t('admin.reports.restored')))
  })

  it('says the content stays hidden when the restore brings it back hidden', async () => {
    const route = 'POST /api/v1/moderation/thread/12/restore'
    const deleted = makeReport({ content: { ...REPORT.content!, status: 'deleted' } })
    await mountAdmin('/admin/reports', {
      [REPORTS]: reply(200, page([deleted])),
      [route]: reply(200, result('hidden')),
    })
    await chooseMenuItem(actions(31), t('admin.reports.restore'))
    expect(dialog().textContent).toContain(t('admin.reports.restoreDescription'))
    expect(t('admin.reports.restoreDescription')).toContain('hidden')
    buttonIn(dialog(), t('admin.reports.restore')).click()
    await flushPromises()
    expect(rows()[0]!.textContent).toContain(t('admin.contentStatus.hidden'))
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain(t('admin.reports.restoredHidden')),
    )
  })

  it('does not offer Restore for content that is not deleted', async () => {
    await mountAdmin('/admin/reports', { [REPORTS]: reply(200, page([REPORT])) })
    await openMenu(actions(31))
    expect(menuItemTexts()).not.toContain(t('admin.reports.restore'))
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import i18n from '@/i18n'
import { localDateInput } from '@/utils/datetime'
import { callsTo, replyError, reply } from './helpers/api'
import { button, click, makeStats, mountAdmin, queryOf } from './helpers/admin'
import { dialog, buttonIn, field } from './helpers/editor'
import { unmountAll } from './helpers/mount'

const t = i18n.global.t
const STATS = 'GET /api/v1/admin/stats'
const EXPORT = 'GET /api/v1/admin/stats/export.csv'
const CLEAR = 'POST /api/v1/admin/knowbase/cache/clear'
const FILENAME = 'urbanfloods-report-2024-09-01-2026-10-31.csv'

const csvResponse = () =>
  new Response('section,count\n', {
    status: 200,
    headers: {
      'content-type': 'text/csv',
      'content-disposition': `attachment; filename="${FILENAME}"`,
    },
  })

const stat = (key: string) => document.querySelector(`[data-testid="stat-${key}"]`)?.textContent

let clicked: HTMLAnchorElement[]

beforeEach(() => {
  Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:report'), revokeObjectURL: vi.fn() })
  clicked = []
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clicked.push(this)
  })
})

afterEach(unmountAll)

describe('Admin dashboard', () => {
  it('shows the user, content and report counts', async () => {
    await mountAdmin('/admin', { [STATS]: reply(200, makeStats()) })
    expect(stat('users-total')).toContain('128')
    expect(stat('users-verified')).toContain('120')
    expect(stat('users-trusted')).toContain('42')
    expect(stat('users-admins')).toContain('3')
    expect(stat('users-new30d')).toContain('17')
    expect(stat('content-posts')).toContain('64')
    expect(stat('content-threads')).toContain('23')
    expect(stat('content-replies')).toContain('311')
    expect(stat('content-comments')).toContain('95')
    expect(stat('content-pending')).toContain('4')
    expect(stat('reports-open')).toContain('6')
  })

  it('shows the KNOWBASE as reachable with its cache sizes', async () => {
    await mountAdmin('/admin', { [STATS]: reply(200, makeStats()) })
    const kb = document.querySelector('[data-testid="knowbase-status"]')!
    expect(kb.textContent).toContain(t('admin.dashboard.knowbase.reachable'))
    expect(stat('cache-lists')).toContain('11')
    expect(stat('cache-details')).toContain('7')
    expect(stat('cache-lookups')).toContain('5')
    expect(stat('cache-stale')).toContain('2')
  })

  it('shows an unreachable KNOWBASE with its last error as text', async () => {
    const stats = makeStats()
    stats.knowbase = {
      ...stats.knowbase,
      reachable: false,
      last_error_at: '2026-10-31T09:30:00Z',
      last_error: '<b>ConnectTimeout</b>',
    }
    await mountAdmin('/admin', { [STATS]: reply(200, stats) })
    const kb = document.querySelector('[data-testid="knowbase-status"]')!
    expect(kb.textContent).toContain(t('admin.dashboard.knowbase.unreachable'))
    expect(kb.textContent).toContain('<b>ConnectTimeout</b>')
    expect(kb.querySelector('b')).toBeNull()
  })

  it('says so when the stats cannot be loaded', async () => {
    await mountAdmin('/admin', { [STATS]: replyError(500, 'server.error') })
    expect(document.body.textContent).toContain(t('admin.dashboard.loadError'))
  })

  it('clears the KNOWBASE cache after confirming and reports the count', async () => {
    const { fetchMock } = await mountAdmin('/admin', {
      [STATS]: reply(200, makeStats()),
      [CLEAR]: reply(200, { cleared: 23 }),
    })
    await click(t('admin.dashboard.knowbase.clear'))
    expect(callsTo(fetchMock, CLEAR)).toHaveLength(0)
    buttonIn(dialog(), t('admin.dashboard.knowbase.clearConfirm')).click()
    await flushPromises()
    expect(callsTo(fetchMock, CLEAR)).toHaveLength(1)
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain(
        t('admin.dashboard.knowbase.cleared', { count: 23 }, 23),
      ),
    )
  })

  it('downloads the CSV for the default range (project start to today)', async () => {
    const { fetchMock } = await mountAdmin('/admin', {
      [STATS]: reply(200, makeStats()),
      [EXPORT]: () => csvResponse(),
    })
    await click(t('admin.dashboard.export.download'))
    await vi.waitFor(() => expect(clicked).toHaveLength(1))
    const call = callsTo(fetchMock, EXPORT)[0]!
    expect(queryOf(call.url).get('from')).toBe('2024-09-01')
    expect(queryOf(call.url).get('to')).toBe(localDateInput())
    const init = fetchMock.mock.calls.find(([input]) => String(input).includes('export.csv'))![1]
    expect(init?.credentials).toBe('include')
    expect(clicked[0]!.download).toBe(FILENAME)
  })

  it('sends the chosen dates and refuses a reversed range', async () => {
    const { fetchMock } = await mountAdmin('/admin', {
      [STATS]: reply(200, makeStats()),
      [EXPORT]: () => csvResponse(),
    })
    const root = document.body
    await field(root, t('admin.dashboard.export.from')).setValue('2026-06-01')
    await field(root, t('admin.dashboard.export.to')).setValue('2026-01-01')
    await click(t('admin.dashboard.export.download'))
    expect(callsTo(fetchMock, EXPORT)).toHaveLength(0)
    expect(document.body.textContent).toContain(t('admin.dashboard.export.invalidRange'))

    await field(root, t('admin.dashboard.export.to')).setValue('2026-06-30')
    await click(t('admin.dashboard.export.download'))
    await vi.waitFor(() => expect(clicked).toHaveLength(1))
    const query = queryOf(callsTo(fetchMock, EXPORT)[0]!.url)
    expect(query.get('from')).toBe('2026-06-01')
    expect(query.get('to')).toBe('2026-06-30')
  })

  it('says so when the export fails', async () => {
    await mountAdmin('/admin', {
      [STATS]: reply(200, makeStats()),
      [EXPORT]: replyError(500, 'server.error'),
    })
    await click(t('admin.dashboard.export.download'))
    expect(clicked).toHaveLength(0)
    expect(document.body.textContent).toContain(t('admin.dashboard.export.failed'))
    expect(button(t('admin.dashboard.export.download'))).toBeTruthy()
  })
})

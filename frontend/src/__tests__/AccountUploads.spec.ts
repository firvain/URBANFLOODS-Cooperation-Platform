import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import i18n from '@/i18n'
import type { MyUpload } from '@/services/uploads'
import { formatDate } from '@/utils/datetime'
import { callsTo, makeUser, mockApi, reply, replyError, type Handler } from './helpers/api'
import { buttonIn, dialog } from './helpers/editor'
import { mountApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'
const MINE = 'GET /api/v1/uploads/mine/'
const DELETE_FREE = 'DELETE /api/v1/uploads/7'

afterEach(unmountAll)

function makeUpload(id: number, overrides: Partial<MyUpload> = {}): MyUpload {
  return {
    id,
    width: 1200,
    height: 800,
    size_bytes: 245_760,
    mime: 'image/webp',
    alt_text: `Flooded street ${id}`,
    created_at: '2026-10-20T09:00:00Z',
    url: `/static/uploads/2026/10/u${id}.webp`,
    thumb_url: `/static/uploads/2026/10/u${id}_thumb.webp`,
    used_in: [],
    ...overrides,
  }
}

const FREE = makeUpload(7)
const USED = makeUpload(8, {
  used_in: [
    {
      content_type: 'post',
      id: 42,
      title: 'Rain gardens in Kozani',
      slug: 'rain-gardens-in-kozani',
      status: 'published',
      by_uploader: true,
    },
    {
      content_type: 'reply',
      id: 5,
      title: 'Sirens or SMS?',
      slug: 'sirens-or-sms',
      status: 'deleted',
      by_uploader: true,
    },
  ],
})

async function mountUploads(routes: Record<string, Handler> = {}) {
  const fetchMock = mockApi({
    [ME]: reply(200, makeUser()),
    [MINE]: reply(200, { total: 2, items: [FREE, USED] }),
    ...routes,
  })
  const mounted = await mountApp('/account?tab=uploads')
  await flushPromises()
  return { ...mounted, fetchMock }
}

const rows = () => Array.from(document.querySelectorAll<HTMLElement>('[data-testid="upload-row"]'))
const deleteButton = (row: HTMLElement) =>
  buttonIn(row, t('account.uploads.deleteLabel', { alt: row.dataset.alt ?? '' }))

describe('Account uploads tab', () => {
  it('lists the uploads with thumbnail, alt text, size and date', async () => {
    const { fetchMock } = await mountUploads()
    expect(callsTo(fetchMock, MINE)).toHaveLength(1)
    const [free, used] = rows()
    const img = free!.querySelector('img')!
    expect(img.getAttribute('src')).toBe(FREE.thumb_url)
    expect(img.getAttribute('alt')).toBe(FREE.alt_text)
    expect(free!.textContent).toContain(FREE.alt_text)
    expect(free!.textContent).toContain('240 kB')
    expect(free!.textContent).toContain(formatDate(FREE.created_at, 'en'))
    expect(free!.textContent).toContain(t('account.uploads.notUsed'))
    expect(used!.textContent).toContain(t('account.uploads.usedIn'))
  })

  it('links "used in" to the content, replies with their anchor, with the status when not published', async () => {
    await mountUploads()
    const used = rows()[1]!
    const post = used.querySelector('a[href="/blog/rain-gardens-in-kozani"]')
    expect(post?.textContent).toContain('Rain gardens in Kozani')
    const replyLink = used.querySelector('a[href="/forum/t/sirens-or-sms#reply-5"]')
    expect(replyLink?.textContent).toContain('Sirens or SMS?')
    expect(used.textContent).toContain(t('post.status.deleted'))
  })

  it('disables Delete for a used image and says why in visible text', async () => {
    await mountUploads()
    const used = rows()[1]!
    const button = deleteButton(used)
    expect(button.disabled).toBe(true)
    const hint = document.getElementById(button.getAttribute('aria-describedby')!)!
    expect(hint.textContent).toContain(t('account.uploads.inUse'))
    expect(hint.classList.contains('sr-only')).toBe(false)
    expect(used.contains(hint)).toBe(true)
    expect(deleteButton(rows()[0]!).disabled).toBe(false)
  })

  it('has no focusable element without a name', async () => {
    await mountUploads()
    for (const row of rows()) {
      for (const el of row.querySelectorAll<HTMLElement>('[tabindex]')) {
        const name = el.getAttribute('aria-label') || el.textContent?.trim()
        expect(name, el.outerHTML).toBeTruthy()
      }
      expect(row.querySelector('span[tabindex="0"]')).toBeNull()
    }
  })

  it('lets the owner delete an image used only by deleted content, with a note', async () => {
    const onlyDeleted = makeUpload(9, {
      used_in: [
        {
          content_type: 'post',
          id: 43,
          title: 'An old post',
          slug: 'an-old-post',
          status: 'deleted',
          by_uploader: true,
        },
      ],
    })
    const route = 'DELETE /api/v1/uploads/9'
    const { fetchMock } = await mountUploads({
      [MINE]: reply(200, { total: 1, items: [onlyDeleted] }),
      [route]: reply(204),
    })
    const row = rows()[0]!
    const button = deleteButton(row)
    expect(button.disabled).toBe(false)
    const hint = document.getElementById(button.getAttribute('aria-describedby')!)!
    expect(hint.textContent).toContain(t('account.uploads.onlyDeleted'))
    button.click()
    await flushPromises()
    buttonIn(dialog(), t('account.uploads.deleteConfirm')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(rows()).toHaveLength(0)
  })

  it('allows deleting an image only other members use, warning that it leaves their content', async () => {
    const othersOnly = makeUpload(10, {
      used_in: [
        {
          content_type: 'thread',
          id: 61,
          title: 'Their discussion',
          slug: 'their-discussion',
          status: 'published',
          by_uploader: false,
        },
        {
          content_type: 'post',
          id: 62,
          title: 'My old post',
          slug: 'my-old-post',
          status: 'deleted',
          by_uploader: true,
        },
      ],
    })
    const route = 'DELETE /api/v1/uploads/10'
    const { fetchMock } = await mountUploads({
      [MINE]: reply(200, { total: 1, items: [othersOnly] }),
      [route]: reply(204),
    })
    const row = rows()[0]!
    const button = deleteButton(row)
    expect(button.disabled).toBe(false)
    const hint = document.getElementById(button.getAttribute('aria-describedby')!)!
    expect(hint.textContent).toContain(t('account.uploads.usedByOthers'))
    button.click()
    await flushPromises()
    expect(dialog().textContent).toContain(t('account.uploads.deleteOthersWarning'))
    buttonIn(dialog(), t('account.uploads.deleteConfirm')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(rows()).toHaveLength(0)
  })

  it("blocks the delete when the member's own live content uses it, whoever else does", async () => {
    const mixed = makeUpload(11, {
      used_in: [
        {
          content_type: 'post',
          id: 71,
          title: 'Mine',
          slug: 'mine',
          status: 'pending',
          by_uploader: true,
        },
        {
          content_type: 'post',
          id: 72,
          title: 'Theirs',
          slug: 'theirs',
          status: 'published',
          by_uploader: false,
        },
      ],
    })
    await mountUploads({ [MINE]: reply(200, { total: 1, items: [mixed] }) })
    const button = deleteButton(rows()[0]!)
    expect(button.disabled).toBe(true)
    const hint = document.getElementById(button.getAttribute('aria-describedby')!)!
    expect(hint.textContent).toContain(t('account.uploads.inUse'))
  })

  it('shows an empty state', async () => {
    await mountUploads({ [MINE]: reply(200, { total: 0, items: [] }) })
    expect(rows()).toHaveLength(0)
    expect(document.body.textContent).toContain(t('account.uploads.empty'))
  })

  it('deletes an unused image after confirming', async () => {
    const { fetchMock } = await mountUploads({ [DELETE_FREE]: reply(204) })
    deleteButton(rows()[0]!).click()
    await flushPromises()
    const box = dialog()
    expect(box.textContent).toContain(t('account.uploads.deleteTitle'))
    expect(box.textContent).not.toContain(t('account.uploads.deleteOthersWarning'))
    expect(callsTo(fetchMock, DELETE_FREE)).toHaveLength(0)
    buttonIn(box, t('account.uploads.deleteConfirm')).click()
    await flushPromises()
    expect(callsTo(fetchMock, DELETE_FREE)).toHaveLength(1)
    expect(rows()).toHaveLength(1)
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain(t('account.uploads.deleted')),
    )
  })

  it('cancelling the dialog keeps the image', async () => {
    const { fetchMock } = await mountUploads({ [DELETE_FREE]: reply(204) })
    deleteButton(rows()[0]!).click()
    await flushPromises()
    buttonIn(dialog(), t('common.cancel')).click()
    await flushPromises()
    expect(callsTo(fetchMock, DELETE_FREE)).toHaveLength(0)
    expect(rows()).toHaveLength(2)
  })

  it('shows "in use" from the server in the dialog', async () => {
    await mountUploads({ [DELETE_FREE]: replyError(409, 'uploads.in_use') })
    deleteButton(rows()[0]!).click()
    await flushPromises()
    buttonIn(dialog(), t('account.uploads.deleteConfirm')).click()
    await flushPromises()
    expect(dialog().textContent).toContain(t('errors.api.uploads.in_use'))
    expect(rows()).toHaveLength(2)
  })

  it('shows a load error with retry', async () => {
    let calls = 0
    const { fetchMock } = await mountUploads({
      [MINE]: () => {
        calls += 1
        return calls === 1
          ? replyError(500, 'server.error')({} as never)
          : reply(200, { total: 1, items: [FREE] })({} as never)
      },
    })
    expect(document.body.textContent).toContain(t('account.uploads.loadError'))
    buttonIn(document.body, t('account.uploads.retry')).click()
    await flushPromises()
    expect(callsTo(fetchMock, MINE)).toHaveLength(2)
    expect(rows()).toHaveLength(1)
  })

  it('loads more when there are more uploads than one page', async () => {
    const first = Array.from({ length: 50 }, (_, i) => makeUpload(100 + i))
    const { fetchMock } = await mountUploads({
      [MINE]: ({ url }) => {
        const skip = Number(new URL(url, 'http://x.invalid').searchParams.get('skip') ?? 0)
        return reply(200, { total: 51, items: skip ? [makeUpload(999)] : first })({} as never)
      },
    })
    expect(rows()).toHaveLength(50)
    buttonIn(document.body, t('account.uploads.loadMore')).click()
    await flushPromises()
    expect(callsTo(fetchMock, MINE)).toHaveLength(2)
    expect(rows()).toHaveLength(51)
  })
})

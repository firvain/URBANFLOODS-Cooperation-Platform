import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import ReportButton from '@/components/moderation/ReportButton.vue'
import { REPORTED_STORAGE_KEY } from '@/constants/moderation'
import i18n from '@/i18n'
import type { UserMe } from '@/services/auth'
import { callsTo, makeUser, mockApi, reply, replyError, type Handler } from './helpers/api'
import { buttonIn, dialog } from './helpers/editor'
import { mountWithApp, unmountAll } from './helpers/mount'

const toastAdd = vi.hoisted(() => vi.fn())
vi.mock('@nuxt/ui/composables', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@nuxt/ui/composables')>()),
  useToast: () => ({ add: toastAdd }),
}))

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'
const CREATE = 'POST /api/v1/reports/'
/** The author of the reported item in these tests (the viewer is user 1 unless said otherwise). */
const AUTHOR_ID = 11

const created = (overrides: Record<string, unknown> = {}) => ({
  id: 7,
  content_type: 'post',
  content_id: 42,
  reason: 'spam',
  status: 'open',
  created_at: '2026-10-31T10:00:00Z',
  auto_hidden: false,
  ...overrides,
})

beforeEach(() => {
  toastAdd.mockClear()
  sessionStorage.clear()
})

afterEach(() => {
  sessionStorage.clear()
  unmountAll()
})

function routes(user: UserMe | null = makeUser(), extra: Record<string, Handler> = {}) {
  return { ...(user ? { [ME]: reply(200, user) } : {}), ...extra }
}

const mountButton = (props: Record<string, unknown> = {}) =>
  mountWithApp(ReportButton, {
    props: { contentType: 'post', contentId: 42, authorId: AUTHOR_ID, ...props },
  })

const reportButton = (wrapper: VueWrapper) => wrapper.find('[data-testid="report-button"]')

async function openDialog(wrapper: VueWrapper) {
  await reportButton(wrapper).trigger('click')
  await flushPromises()
  return dialog()
}

/** Click the radio whose label is `text`. */
async function chooseReason(box: HTMLElement, text: string) {
  const label = Array.from(box.querySelectorAll('label')).find(
    (l) => l.textContent?.trim() === text,
  )
  expect(label, `reason ${text}`).toBeDefined()
  const radio = document.getElementById(label!.htmlFor)
  expect(radio?.getAttribute('role')).toBe('radio')
  radio!.click()
  await flushPromises()
}

async function typeDetails(box: HTMLElement, text: string) {
  const area = box.querySelector('textarea')!
  area.value = text
  area.dispatchEvent(new Event('input', { bubbles: true }))
  await flushPromises()
}

async function submit(box: HTMLElement) {
  buttonIn(box, t('report.submit')).click()
  await flushPromises()
}

const isDialogOpen = () => document.querySelector('[role="dialog"]') !== null
const lastToast = () => toastAdd.mock.calls.at(-1)?.[0] as Record<string, unknown> | undefined

describe('ReportButton', () => {
  it('is not shown to anonymous visitors', async () => {
    mockApi(routes(null))
    const { wrapper } = await mountButton()
    expect(reportButton(wrapper).exists()).toBe(false)
  })

  it('is not shown to unverified members', async () => {
    mockApi(routes(makeUser({ is_verified: false })))
    const { wrapper } = await mountButton()
    expect(reportButton(wrapper).exists()).toBe(false)
  })

  it('is not shown to the author', async () => {
    mockApi(routes(makeUser({ id: AUTHOR_ID })))
    const { wrapper } = await mountButton()
    expect(reportButton(wrapper).exists()).toBe(false)
  })

  it.each(['pending', 'hidden', 'deleted'] as const)(
    'is not shown on %s content',
    async (status) => {
      mockApi(routes())
      const { wrapper } = await mountButton({ status })
      expect(reportButton(wrapper).exists()).toBe(false)
    },
  )

  it('is shown on content by a former member (no author)', async () => {
    mockApi(routes())
    const { wrapper } = await mountButton({ authorId: null })
    expect(reportButton(wrapper).exists()).toBe(true)
  })

  it.each([
    ['post', 'Report this post'],
    ['thread', 'Report this discussion'],
    ['reply', 'Report this reply'],
    ['comment', 'Report this comment'],
  ] as const)('a verified member sees a labelled button for a %s', async (contentType, label) => {
    mockApi(routes())
    const { wrapper } = await mountButton({ contentType })
    const button = reportButton(wrapper)
    expect(button.element.tagName).toBe('BUTTON')
    expect(button.attributes('aria-label')).toBe(label)
    expect(button.attributes('aria-label')).toBe(t(`report.title.${contentType}`))
    expect(button.text()).toBe(t('report.button'))
    expect(button.attributes('disabled')).toBeUndefined()
  })

  it('opens a dialog labelled by its title, with focus inside and the five reasons', async () => {
    mockApi(routes())
    const { wrapper } = await mountButton({ contentType: 'reply' })
    const box = await openDialog(wrapper)
    const labelledBy = box.getAttribute('aria-labelledby')
    expect(labelledBy).toBeTruthy()
    expect(document.getElementById(labelledBy!)?.textContent?.trim()).toBe(t('report.title.reply'))
    await vi.waitFor(() => expect(box.contains(document.activeElement)).toBe(true))
    expect(box.querySelectorAll('[role="radio"]')).toHaveLength(5)
    for (const reason of ['spam', 'abuse', 'off_topic', 'misinformation', 'other']) {
      expect(box.textContent).toContain(t(`report.reasons.${reason}`))
    }
  })

  it('caps the optional details at 1000 characters with a counter', async () => {
    mockApi(routes())
    const { wrapper } = await mountButton()
    const box = await openDialog(wrapper)
    const area = box.querySelector('textarea')!
    expect(area.getAttribute('maxlength')).toBe('1000')
    expect(box.textContent).toContain('0/1000')
    await typeDetails(box, 'Advert')
    expect(box.textContent).toContain('6/1000')
    // The textarea is labelled.
    const label = box.querySelector(`label[for="${area.id}"]`)
    expect(label?.textContent).toContain(t('report.details'))
  })

  it('requires a reason before sending', async () => {
    const fetchMock = mockApi(routes(makeUser(), { [CREATE]: reply(201, created()) }))
    const { wrapper } = await mountButton()
    const box = await openDialog(wrapper)
    await submit(box)
    expect(callsTo(fetchMock, CREATE)).toHaveLength(0)
    expect(box.textContent).toContain(t('report.reasonRequired'))
    const fieldset = box.querySelector('fieldset')!
    expect(fieldset.getAttribute('aria-invalid')).toBe('true')
    const describedBy = fieldset.getAttribute('aria-describedby')!
    expect(document.getElementById(describedBy)?.textContent).toContain(t('report.reasonRequired'))
  })

  it('sends the report, closes, thanks the member and marks the item reported', async () => {
    const fetchMock = mockApi(routes(makeUser(), { [CREATE]: reply(201, created()) }))
    const { wrapper } = await mountButton({ contentType: 'comment', contentId: 9 })
    const box = await openDialog(wrapper)
    await chooseReason(box, t('report.reasons.misinformation'))
    await typeDetails(box, '  The figures are made up.  ')
    await submit(box)
    expect(callsTo(fetchMock, CREATE)[0]!.body).toEqual({
      content_type: 'comment',
      content_id: 9,
      reason: 'misinformation',
      details: 'The figures are made up.',
    })
    await vi.waitFor(() => expect(isDialogOpen()).toBe(false))
    expect(lastToast()).toMatchObject({ title: t('report.sent'), color: 'success' })
    const button = reportButton(wrapper)
    expect(button.text()).toBe(t('report.reported'))
    expect(button.attributes('disabled')).toBeDefined()
  })

  it('leaves out empty details', async () => {
    const fetchMock = mockApi(routes(makeUser(), { [CREATE]: reply(201, created()) }))
    const { wrapper } = await mountButton()
    const box = await openDialog(wrapper)
    await chooseReason(box, t('report.reasons.spam'))
    await typeDetails(box, '   ')
    await submit(box)
    expect(callsTo(fetchMock, CREATE)[0]!.body).toEqual({
      content_type: 'post',
      content_id: 42,
      reason: 'spam',
    })
  })

  it('says when the report hid the content', async () => {
    mockApi(routes(makeUser(), { [CREATE]: reply(201, created({ auto_hidden: true })) }))
    const { wrapper } = await mountButton()
    const box = await openDialog(wrapper)
    await chooseReason(box, t('report.reasons.abuse'))
    await submit(box)
    expect(lastToast()).toMatchObject({ title: t('report.autoHidden') })
    expect(t('report.autoHidden')).toBe('This content has been hidden pending review.')
  })

  it('an earlier report: info toast and the button becomes "Reported"', async () => {
    mockApi(routes(makeUser(), { [CREATE]: replyError(409, 'report.already_reported') }))
    const { wrapper } = await mountButton()
    const box = await openDialog(wrapper)
    await chooseReason(box, t('report.reasons.spam'))
    await submit(box)
    await vi.waitFor(() => expect(isDialogOpen()).toBe(false))
    expect(lastToast()).toMatchObject({ title: t('report.alreadyReported'), color: 'info' })
    expect(reportButton(wrapper).text()).toBe(t('report.reported'))
    expect(reportButton(wrapper).attributes('disabled')).toBeDefined()
  })

  it.each([
    [400, 'report.own_content', 'report.errors.ownContent'],
    [404, 'report.content_not_found', 'report.errors.contentNotFound'],
    [429, 'rate_limit.exceeded', 'report.errors.rateLimited'],
  ])('%i %s: closes with a toast and stays reportable', async (status, code, key) => {
    mockApi(routes(makeUser(), { [CREATE]: replyError(status, code) }))
    const { wrapper } = await mountButton()
    const box = await openDialog(wrapper)
    await chooseReason(box, t('report.reasons.other'))
    await submit(box)
    await vi.waitFor(() => expect(isDialogOpen()).toBe(false))
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ title: t(key) }))
    expect(reportButton(wrapper).text()).toBe(t('report.button'))
    expect(reportButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('keeps the dialog open with an error when the server fails', async () => {
    mockApi(routes(makeUser(), { [CREATE]: replyError(500, 'server.error') }))
    const { wrapper } = await mountButton()
    const box = await openDialog(wrapper)
    await chooseReason(box, t('report.reasons.spam'))
    await submit(box)
    expect(isDialogOpen()).toBe(true)
    expect(dialog().querySelector('[role="alert"]')?.textContent).toContain(t('errors.generic'))
  })

  it('cancel closes the dialog without sending', async () => {
    const fetchMock = mockApi(routes(makeUser(), { [CREATE]: reply(201, created()) }))
    const { wrapper } = await mountButton()
    const box = await openDialog(wrapper)
    buttonIn(box, t('report.cancel')).click()
    await flushPromises()
    await vi.waitFor(() => expect(isDialogOpen()).toBe(false))
    expect(callsTo(fetchMock, CREATE)).toHaveLength(0)
  })

  it('remembers reported items for the session (after a reload)', async () => {
    mockApi(routes(makeUser(), { [CREATE]: reply(201, created()) }))
    const first = await mountButton()
    const box = await openDialog(first.wrapper)
    await chooseReason(box, t('report.reasons.spam'))
    await submit(box)
    expect(JSON.parse(sessionStorage.getItem(REPORTED_STORAGE_KEY)!)).toContain('post:42')
    unmountAll()

    mockApi(routes())
    const again = await mountButton()
    expect(reportButton(again.wrapper).text()).toBe(t('report.reported'))
    expect(reportButton(again.wrapper).attributes('disabled')).toBeDefined()
    // Other items stay reportable.
    unmountAll()
    const other = await mountButton({ contentId: 43 })
    expect(reportButton(other.wrapper).text()).toBe(t('report.button'))
  })

  it('ignores a broken or unavailable sessionStorage', async () => {
    sessionStorage.setItem(REPORTED_STORAGE_KEY, '{not json')
    mockApi(routes(makeUser(), { [CREATE]: reply(201, created()) }))
    const { wrapper } = await mountButton()
    expect(reportButton(wrapper).text()).toBe(t('report.button'))

    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })
    const box = await openDialog(wrapper)
    await chooseReason(box, t('report.reasons.spam'))
    await submit(box)
    expect(lastToast()).toMatchObject({ title: t('report.sent') })
    expect(reportButton(wrapper).text()).toBe(t('report.reported'))
  })
})

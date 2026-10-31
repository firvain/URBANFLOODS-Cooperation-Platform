import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DOMWrapper, flushPromises } from '@vue/test-utils'

import AccountView from '@/views/AccountView.vue'
import i18n from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import type { UserMe } from '@/services/auth'
import { callsTo, makeUser, mockApi, reply, replyError, type Handler } from './helpers/api'
import { buttonIn, dialog } from './helpers/editor'
import { mountApp, mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'
const EXPORT = 'GET /api/v1/auth/me/export'
const DELETE_ME = 'DELETE /api/v1/auth/me'
const FILENAME = 'urbanfloods-account-1-20261031.json'

function exportResponse(): Response {
  return new Response(JSON.stringify({ user: { id: 1 } }), {
    status: 200,
    headers: {
      'content-type': 'application/json',
      'content-disposition': `attachment; filename="${FILENAME}"`,
    },
  })
}

function routes(user: UserMe = makeUser(), extra: Record<string, Handler> = {}) {
  return { [ME]: reply(200, user), [EXPORT]: () => exportResponse(), ...extra }
}

const mountTab = () => mountWithApp(AccountView, { path: '/account?tab=data' })
const button = (text: string) =>
  Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === text)

let createObjectURL: ReturnType<typeof vi.fn>
let revokeObjectURL: ReturnType<typeof vi.fn>
let clicked: HTMLAnchorElement[]

beforeEach(() => {
  createObjectURL = vi.fn(() => 'blob:urbanfloods/export')
  revokeObjectURL = vi.fn()
  Object.assign(URL, { createObjectURL, revokeObjectURL })
  clicked = []
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clicked.push(this)
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  unmountAll()
})

async function openDelete() {
  button(t('account.data.delete.button'))!.click()
  await flushPromises()
  return dialog()
}

async function typePassword(box: HTMLElement, value: string) {
  const input = box.querySelector<HTMLInputElement>('input[autocomplete="current-password"]')
  expect(input).not.toBeNull()
  await new DOMWrapper(input!).setValue(value)
}

async function confirm(box: HTMLElement) {
  buttonIn(box, t('account.data.delete.confirm')).click()
  await flushPromises()
}

describe('Account → Data', () => {
  it('downloads the export with the session cookie and the server’s filename', async () => {
    const fetchMock = mockApi(routes())
    await mountTab()
    button(t('account.data.export.button'))!.click()
    await flushPromises()
    await vi.waitFor(() => expect(clicked).toHaveLength(1))

    const calls = fetchMock.mock.calls.filter(([input]) =>
      String(input instanceof Request ? input.url : input).includes('/api/v1/auth/me/export'),
    )
    expect(calls).toHaveLength(1)
    expect(calls[0]![1]?.credentials).toBe('include')
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(createObjectURL.mock.calls[0]![0]).toBeInstanceOf(Blob)
    expect(clicked[0]!.download).toBe(FILENAME)
    expect(clicked[0]!.getAttribute('href')).toBe('blob:urbanfloods/export')
  })

  it('says so when the export fails', async () => {
    mockApi(routes(makeUser(), { [EXPORT]: replyError(500, 'server.error') }))
    const { wrapper } = await mountTab()
    button(t('account.data.export.button'))!.click()
    await flushPromises()
    expect(clicked).toHaveLength(0)
    expect(wrapper.find('[data-testid="export-error"]').text()).toContain(
      t('account.data.export.failed'),
    )
  })

  it('asks for the current password before deleting', async () => {
    const fetchMock = mockApi(routes(makeUser(), { [DELETE_ME]: reply(204) }))
    await mountTab()
    const box = await openDelete()
    expect(box.textContent).toContain(t('account.data.delete.dialogTitle'))
    await confirm(box)
    expect(callsTo(fetchMock, DELETE_ME)).toHaveLength(0)
    expect(dialog().textContent).toContain(t('errors.fields.required'))
  })

  it('shows the mapped error for a wrong password and keeps the account', async () => {
    mockApi(routes(makeUser(), { [DELETE_ME]: replyError(400, 'auth.invalid_credentials') }))
    const { auth, router } = await mountTab()
    const box = await openDelete()
    await typePassword(box, 'wrong-password')
    await confirm(box)
    expect(dialog().textContent).toContain(t('account.data.delete.wrongPassword'))
    expect(auth.isAuthenticated).toBe(true)
    expect(router.currentRoute.value.path).toBe('/account')
  })

  it('deletes the account, signs out locally and goes home with a toast', async () => {
    const fetchMock = mockApi(routes(makeUser(), { [DELETE_ME]: reply(204) }))
    // The whole app, so the toast has somewhere to appear.
    const { router } = await mountApp('/account?tab=data')
    const auth = useAuthStore()
    const box = await openDelete()
    await typePassword(box, 'correct horse battery')
    await confirm(box)
    expect(callsTo(fetchMock, DELETE_ME)[0]!.body).toEqual({
      current_password: 'correct horse battery',
    })
    expect(auth.isAuthenticated).toBe(false)
    expect(auth.user).toBeNull()
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/'))
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain(t('account.data.delete.done')),
    )
  })

  it('explains that the last superadmin cannot delete their account', async () => {
    mockApi(
      routes(makeUser({ role: 'superadmin' }), {
        [DELETE_ME]: replyError(409, 'admin.last_superadmin'),
      }),
    )
    const { auth } = await mountTab()
    const box = await openDelete()
    await typePassword(box, 'correct horse battery')
    await confirm(box)
    expect(dialog().textContent).toContain(t('account.data.delete.lastSuperadmin'))
    expect(auth.isAuthenticated).toBe(true)
  })
})

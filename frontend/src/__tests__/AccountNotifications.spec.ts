import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import AccountView from '@/views/AccountView.vue'
import i18n from '@/i18n'
import type { UserMe } from '@/services/auth'
import {
  callsTo,
  deferred,
  jsonResponse,
  makeUser,
  mockApi,
  reply,
  replyError,
  type Handler,
} from './helpers/api'
import { mountApp, mountWithApp, unmountAll } from './helpers/mount'
import { controlFor } from './helpers/select'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'
const GET_PREFS = 'GET /api/v1/auth/me/notifications'
const PUT_PREFS = 'PUT /api/v1/auth/me/notifications'

afterEach(unmountAll)

const PREFS = {
  reply_to_my_thread: true,
  comment_on_my_post: true,
  reply_to_my_reply: false,
  admin_digest: true,
  moderation_decisions: false,
  digest_frequency: 'daily',
}

function routes(user: UserMe = makeUser(), extra: Record<string, Handler> = {}) {
  return { [ME]: reply(200, user), [GET_PREFS]: reply(200, PREFS), ...extra }
}

const mountTab = () => mountWithApp(AccountView, { path: '/account?tab=notifications' })

const LABELS = {
  reply_to_my_thread: 'account.notifications.replyToMyThread',
  comment_on_my_post: 'account.notifications.commentOnMyPost',
  reply_to_my_reply: 'account.notifications.replyToMyReply',
  moderation_decisions: 'account.notifications.moderationDecisions',
  admin_digest: 'account.notifications.adminDigest',
} as const

function switchFor(wrapper: VueWrapper, field: keyof typeof LABELS): HTMLElement {
  const el = controlFor(wrapper, t(LABELS[field]))
  expect(el.getAttribute('role')).toBe('switch')
  return el
}

const hasLabel = (wrapper: VueWrapper, text: string) =>
  wrapper.findAll('label').some((l) => l.text().startsWith(text))

async function save(wrapper: VueWrapper) {
  await wrapper.find('[data-testid="notifications-form"]').trigger('submit')
  await flushPromises()
}

describe('Account → Notifications', () => {
  it('opens from ?tab=notifications and shows the saved preferences', async () => {
    mockApi(routes())
    const { wrapper } = await mountTab()
    const selected = wrapper.find('[role="tab"][aria-selected="true"]')
    expect(selected.text()).toBe(t('account.tabs.notifications'))
    expect(switchFor(wrapper, 'reply_to_my_thread').getAttribute('aria-checked')).toBe('true')
    expect(switchFor(wrapper, 'comment_on_my_post').getAttribute('aria-checked')).toBe('true')
    expect(switchFor(wrapper, 'reply_to_my_reply').getAttribute('aria-checked')).toBe('false')
  })

  it('shows the moderation decisions switch to members with its hint and loaded value', async () => {
    mockApi(routes())
    const { wrapper } = await mountTab()
    const el = switchFor(wrapper, 'moderation_decisions')
    expect(el.getAttribute('aria-checked')).toBe('false')
    expect(wrapper.text()).toContain(t('account.notifications.moderationDecisionsHint'))
    unmountAll()

    mockApi(
      routes(makeUser(), { [GET_PREFS]: reply(200, { ...PREFS, moderation_decisions: true }) }),
    )
    const again = await mountTab()
    expect(switchFor(again.wrapper, 'moderation_decisions').getAttribute('aria-checked')).toBe(
      'true',
    )
  })

  it('saves the moderation decisions switch', async () => {
    const saved = { ...PREFS, moderation_decisions: true }
    const fetchMock = mockApi(routes(makeUser(), { [PUT_PREFS]: reply(200, saved) }))
    const { wrapper } = await mountTab()
    switchFor(wrapper, 'moderation_decisions').click()
    await flushPromises()
    await save(wrapper)
    expect(callsTo(fetchMock, PUT_PREFS)[0]!.body).toEqual(saved)
    expect(switchFor(wrapper, 'moderation_decisions').getAttribute('aria-checked')).toBe('true')
  })

  it('the email opt-out link /account?tab=notifications lands on the tab after login', async () => {
    mockApi(routes())
    const { router, wrapper } = await mountApp('/account?tab=notifications')
    expect(router.currentRoute.value.fullPath).toBe('/account?tab=notifications')
    expect(wrapper.find('[data-testid="notifications-form"]').exists()).toBe(true)
    unmountAll()

    // Signed out, the login page keeps the tab in ?next=.
    mockApi({ [GET_PREFS]: reply(200, PREFS) })
    const anonymous = await mountApp('/account?tab=notifications')
    expect(anonymous.router.currentRoute.value.name).toBe('login')
    expect(anonymous.router.currentRoute.value.query.next).toBe('/account?tab=notifications')
  })

  it('hides the admin digest settings from members', async () => {
    mockApi(routes())
    const { wrapper } = await mountTab()
    expect(hasLabel(wrapper, t('account.notifications.adminDigest'))).toBe(false)
    expect(wrapper.findAll('[role="radio"]')).toHaveLength(0)
  })

  it.each(['admin', 'superadmin'] as const)(
    'shows the admin digest settings to a %s',
    async (role) => {
      mockApi(routes(makeUser({ role })))
      const { wrapper } = await mountTab()
      expect(switchFor(wrapper, 'admin_digest').getAttribute('aria-checked')).toBe('true')
      const radios = wrapper.findAll('[role="radio"]')
      expect(radios).toHaveLength(2)
      expect(hasLabel(wrapper, t('account.notifications.daily'))).toBe(true)
      expect(hasLabel(wrapper, t('account.notifications.weekly'))).toBe(true)
      expect(
        controlFor(wrapper, t('account.notifications.daily')).getAttribute('aria-checked'),
      ).toBe('true')
    },
  )

  it('saves the full object, keeping the admin fields for members', async () => {
    const saved = { ...PREFS, comment_on_my_post: false, reply_to_my_reply: true }
    const fetchMock = mockApi(routes(makeUser(), { [PUT_PREFS]: reply(200, saved) }))
    const { wrapper } = await mountTab()
    switchFor(wrapper, 'comment_on_my_post').click()
    switchFor(wrapper, 'reply_to_my_reply').click()
    await flushPromises()
    await save(wrapper)
    const calls = callsTo(fetchMock, PUT_PREFS)
    expect(calls).toHaveLength(1)
    expect(calls[0]!.body).toEqual(saved)
    expect(wrapper.find('[aria-live="polite"]').text()).toContain(t('account.notifications.saved'))
    expect(document.body.textContent).toContain(t('account.notifications.saved'))
  })

  it('an admin changes the digest switch and frequency', async () => {
    const fetchMock = mockApi(
      routes(makeUser({ role: 'admin' }), {
        [PUT_PREFS]: reply(200, { ...PREFS, admin_digest: false, digest_frequency: 'weekly' }),
      }),
    )
    const { wrapper } = await mountTab()
    controlFor(wrapper, t('account.notifications.weekly')).click()
    switchFor(wrapper, 'admin_digest').click()
    await flushPromises()
    await save(wrapper)
    expect(callsTo(fetchMock, PUT_PREFS)[0]!.body).toEqual({
      ...PREFS,
      admin_digest: false,
      digest_frequency: 'weekly',
    })
  })

  it('shows the server error when saving fails', async () => {
    mockApi(
      routes(makeUser(), {
        [PUT_PREFS]: replyError(422, 'validation.failed', { digest_frequency: 'invalid' }),
      }),
    )
    const { wrapper } = await mountTab()
    await save(wrapper)
    const alert = wrapper.find('[data-testid="notifications-form"] [role="alert"]')
    expect(alert.text()).toContain(t('errors.api.validation.failed'))
    expect(wrapper.find('[aria-live="polite"]').text()).not.toContain(
      t('account.notifications.saved'),
    )
  })

  it('shows one placeholder row per member switch while loading', async () => {
    const held = deferred<Response>()
    mockApi(routes(makeUser(), { [GET_PREFS]: () => held.promise }))
    const { wrapper } = await mountTab()
    const busy = wrapper.find('[aria-busy="true"]')
    expect(busy.exists()).toBe(true)
    expect(busy.findAll(':scope > :not(.sr-only)')).toHaveLength(4)
    held.resolve(jsonResponse(PREFS))
    await flushPromises()
    expect(wrapper.find('[aria-busy="true"]').exists()).toBe(false)
    expect(switchFor(wrapper, 'moderation_decisions').getAttribute('aria-checked')).toBe('false')
  })

  it('offers a retry when the preferences cannot be loaded', async () => {
    mockApi(routes(makeUser(), { [GET_PREFS]: replyError(500, 'server.error') }))
    const { wrapper } = await mountTab()
    expect(wrapper.find('[role="alert"]').text()).toContain(t('account.notifications.loadError'))
    expect(wrapper.find('[data-testid="notifications-form"]').exists()).toBe(false)
  })
})

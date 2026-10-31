import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import AccountView from '@/views/AccountView.vue'
import i18n from '@/i18n'
import {
  callsTo,
  makeUser,
  mockApi,
  ORGANISATIONS,
  reply,
  replyError,
  type Handler,
} from './helpers/api'
import { EXPERTISE, EXPERTISE_RESPONSE } from './helpers/members'
import { mountWithApp, unmountAll } from './helpers/mount'
import { clickOption, controlFor, openSelect, option } from './helpers/select'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'
const PATCH_ME = 'PATCH /api/v1/auth/me'
const PASSWORD = 'POST /api/v1/auth/me/password'
const SESSIONS = 'GET /api/v1/auth/me/sessions'

afterEach(unmountAll)

const USER = makeUser({
  display_name: 'Maria',
  country: 'GR',
  locale: 'en',
  bio: 'Hydrologist in Kozani.',
  organisation: {
    id: 1,
    short_name: 'UOWM',
    name: 'University of Western Macedonia',
    country: 'GR',
    type: 'PP',
  },
})

function routes(extra: Record<string, Handler> = {}) {
  return {
    [ME]: reply(200, USER),
    'GET /api/v1/organisations/': reply(200, ORGANISATIONS),
    'GET /api/v1/expertise/': reply(200, EXPERTISE_RESPONSE),
    ...extra,
  }
}

async function mountAccount(tab?: string) {
  const { wrapper, auth } = await mountWithApp(AccountView, {
    path: tab ? `/account?tab=${tab}` : '/account',
  })
  return { wrapper, auth }
}

async function submit(wrapper: VueWrapper) {
  await wrapper.find('form').trigger('submit')
  await flushPromises()
}

function describedText(input: Element): string {
  return (input.getAttribute('aria-describedby') ?? '')
    .split(' ')
    .map((id) => document.getElementById(id)?.textContent ?? '')
    .join(' ')
}

describe('AccountView', () => {
  it('has a focusable h1 and six tabs: profile, password, sessions, notifications, uploads, data', async () => {
    mockApi(routes())
    const { wrapper } = await mountAccount()
    expect(wrapper.find('h1').attributes('tabindex')).toBe('-1')
    const tabs = wrapper.findAll('[role="tab"]').map((tab) => tab.text())
    expect(tabs).toEqual([
      t('account.tabs.profile'),
      t('account.tabs.password'),
      t('account.tabs.sessions'),
      t('account.tabs.notifications'),
      t('account.tabs.uploads'),
      t('account.tabs.data'),
    ])
  })

  it('opens the tab named in ?tab=', async () => {
    mockApi(routes({ [SESSIONS]: reply(200, { total: 0, items: [] }) }))
    const { wrapper } = await mountWithApp(AccountView, { path: '/account?tab=password' })
    expect(wrapper.find('input[autocomplete="current-password"]').exists()).toBe(true)
  })

  describe('profile', () => {
    it('is prefilled from the signed-in user', async () => {
      mockApi(routes())
      const { wrapper } = await mountAccount()
      expect(
        (wrapper.find('input[autocomplete="nickname"]').element as HTMLInputElement).value,
      ).toBe('Maria')
      expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe(
        'Hydrologist in Kozani.',
      )
      expect(wrapper.text()).toContain('UOWM – University of Western Macedonia')
      expect(wrapper.text()).toContain('Greece')
      expect(wrapper.text()).toContain(`${'Hydrologist in Kozani.'.length}/2000`)
    })

    it('sends only the changed fields and updates the store', async () => {
      const updated = { ...USER, display_name: 'Maria P.', bio: 'Flood modeller.' }
      const fetchMock = mockApi(routes({ [PATCH_ME]: reply(200, updated) }))
      const { wrapper, auth } = await mountAccount()
      await wrapper.find('input[autocomplete="nickname"]').setValue('Maria P.')
      await wrapper.find('textarea').setValue('Flood modeller.')
      await submit(wrapper)

      const calls = callsTo(fetchMock, PATCH_ME)
      expect(calls).toHaveLength(1)
      expect(calls[0]!.body).toEqual({ display_name: 'Maria P.', bio: 'Flood modeller.' })
      expect(auth.user?.display_name).toBe('Maria P.')
      expect(wrapper.find('[aria-live="polite"]').text()).toContain(t('account.profile.saved'))
    })

    it('does not call the server when nothing changed', async () => {
      const fetchMock = mockApi(routes())
      const { wrapper } = await mountAccount()
      await submit(wrapper)
      expect(callsTo(fetchMock, PATCH_ME)).toHaveLength(0)
      expect(wrapper.find('[aria-live="polite"]').text()).toContain(t('account.profile.noChanges'))
    })

    it('clears the bio with null', async () => {
      const fetchMock = mockApi(routes({ [PATCH_ME]: reply(200, { ...USER, bio: null }) }))
      const { wrapper } = await mountAccount()
      await wrapper.find('textarea').setValue('   ')
      await submit(wrapper)
      expect(callsTo(fetchMock, PATCH_ME)[0]!.body).toEqual({ bio: null })
    })

    it('shows a server field error on its field', async () => {
      mockApi(
        routes({
          [PATCH_ME]: replyError(422, 'validation.failed', { display_name: 'value_error' }),
        }),
      )
      const { wrapper } = await mountAccount()
      await wrapper.find('input[autocomplete="nickname"]').setValue('Mx')
      await submit(wrapper)
      const input = wrapper.find('input[autocomplete="nickname"]')
      expect(input.attributes('aria-invalid')).toBe('true')
      expect(describedText(input.element)).toContain(t('errors.fields.value_error'))
      expect(wrapper.text()).toContain(t('errors.api.validation.failed'))
    })

    it('limits the bio to 2000 characters', async () => {
      mockApi(routes())
      const { wrapper } = await mountAccount()
      expect(wrapper.find('textarea').attributes('maxlength')).toBe('2000')
    })

    describe('expertise and network visibility', () => {
      const EXPERT = {
        ...USER,
        expertise: [EXPERTISE[0]!],
        show_email: false,
        show_in_directory: true,
      }

      function switchFor(wrapper: VueWrapper, label: string) {
        const el = controlFor(wrapper, label)
        expect(el.getAttribute('role')).toBe('switch')
        return el
      }

      it('shows the current expertise and both switches', async () => {
        mockApi(routes({ [ME]: reply(200, EXPERT) }))
        const { wrapper } = await mountAccount()
        expect(t('account.profile.showEmail')).toBe('Show my email address to other members')
        expect(t('account.profile.showInDirectory')).toBe('List me in the Collaboration Network')
        expect(controlFor(wrapper, t('account.profile.expertise')).textContent).toContain(
          'Hydrology',
        )
        expect(
          switchFor(wrapper, t('account.profile.showEmail')).getAttribute('aria-checked'),
        ).toBe('false')
        expect(
          switchFor(wrapper, t('account.profile.showInDirectory')).getAttribute('aria-checked'),
        ).toBe('true')
      })

      it('sends expertise_ids when the expertise changes', async () => {
        const fetchMock = mockApi(
          routes({
            [ME]: reply(200, EXPERT),
            [PATCH_ME]: reply(200, { ...EXPERT, expertise: [EXPERTISE[0]!, EXPERTISE[4]!] }),
          }),
        )
        const { wrapper, auth } = await mountAccount()
        await openSelect(wrapper, t('account.profile.expertise'))
        await clickOption('GIS and remote sensing')
        await submit(wrapper)
        const calls = callsTo(fetchMock, PATCH_ME)
        expect(calls).toHaveLength(1)
        expect(calls[0]!.body).toEqual({ expertise_ids: [1, 5] })
        expect(auth.user?.expertise.map((e) => e.id)).toEqual([1, 5])
      })

      it('sends the visibility flags when the switches change', async () => {
        const fetchMock = mockApi(
          routes({
            [ME]: reply(200, EXPERT),
            [PATCH_ME]: reply(200, { ...EXPERT, show_email: true, show_in_directory: false }),
          }),
        )
        const { wrapper } = await mountAccount()
        switchFor(wrapper, t('account.profile.showEmail')).click()
        switchFor(wrapper, t('account.profile.showInDirectory')).click()
        await flushPromises()
        await submit(wrapper)
        const calls = callsTo(fetchMock, PATCH_ME)
        expect(calls).toHaveLength(1)
        expect(calls[0]!.body).toEqual({ show_email: true, show_in_directory: false })
      })

      it('sends nothing when a switch is toggled back', async () => {
        const fetchMock = mockApi(routes({ [ME]: reply(200, EXPERT) }))
        const { wrapper } = await mountAccount()
        const toggle = switchFor(wrapper, t('account.profile.showEmail'))
        toggle.click()
        await flushPromises()
        toggle.click()
        await flushPromises()
        await submit(wrapper)
        expect(callsTo(fetchMock, PATCH_ME)).toHaveLength(0)
        expect(wrapper.find('[aria-live="polite"]').text()).toContain(
          t('account.profile.noChanges'),
        )
      })

      it('allows at most 8 expertise areas', async () => {
        const full = { ...EXPERT, expertise: EXPERTISE.slice(0, 8) }
        mockApi(routes({ [ME]: reply(200, full) }))
        const { wrapper } = await mountAccount()
        expect(wrapper.text()).toContain(t('account.profile.expertiseHint', { max: 8 }))
        await openSelect(wrapper, t('account.profile.expertise'))
        expect(option('Climate adaptation').getAttribute('data-disabled')).not.toBeNull()
        expect(option('Hydrology').getAttribute('data-disabled')).toBeNull()
      })
    })
  })

  describe('password', () => {
    async function fill(wrapper: VueWrapper, current: string, next: string, confirm = next) {
      await wrapper.find('input[autocomplete="current-password"]').setValue(current)
      const fresh = wrapper.findAll('input[autocomplete="new-password"]')
      await fresh[0]!.setValue(next)
      await fresh[1]!.setValue(confirm)
    }

    it('posts the current and new password and shows success', async () => {
      const fetchMock = mockApi(routes({ [PASSWORD]: reply(204) }))
      const { wrapper } = await mountAccount('password')
      await fill(wrapper, 'old password 123', 'a brand new passphrase')
      await submit(wrapper)
      const calls = callsTo(fetchMock, PASSWORD)
      expect(calls).toHaveLength(1)
      expect(calls[0]!.body).toEqual({
        current_password: 'old password 123',
        new_password: 'a brand new passphrase',
      })
      expect(wrapper.find('[aria-live="polite"]').text()).toContain(t('account.password.changed'))
      expect(t('account.password.changed')).toBe('Password changed')
      // The form is cleared.
      expect(
        (wrapper.find('input[autocomplete="current-password"]').element as HTMLInputElement).value,
      ).toBe('')
    })

    it('checks the confirmation on the client', async () => {
      const fetchMock = mockApi(routes())
      const { wrapper } = await mountAccount('password')
      await fill(wrapper, 'old password 123', 'a brand new passphrase', 'something else entirely')
      await submit(wrapper)
      expect(callsTo(fetchMock, PASSWORD)).toHaveLength(0)
      expect(wrapper.text()).toContain(t('errors.fields.password_mismatch'))
    })

    it('maps auth.invalid_credentials to the current password field', async () => {
      mockApi(routes({ [PASSWORD]: replyError(400, 'auth.invalid_credentials') }))
      const { wrapper, auth } = await mountAccount('password')
      await fill(wrapper, 'wrong password 1', 'a brand new passphrase')
      await submit(wrapper)
      const current = wrapper.find('input[autocomplete="current-password"]')
      expect(current.attributes('aria-invalid')).toBe('true')
      expect(describedText(current.element)).toContain(t('account.password.wrongCurrent'))
      expect(auth.isAuthenticated).toBe(true)
    })

    it('maps fields.new_password to the new password field', async () => {
      mockApi(
        routes({
          [PASSWORD]: replyError(422, 'validation.failed', {
            new_password: 'auth.password_too_common',
          }),
        }),
      )
      const { wrapper } = await mountAccount('password')
      await fill(wrapper, 'old password 123', 'qwertyuiop1')
      await submit(wrapper)
      const fresh = wrapper.findAll('input[autocomplete="new-password"]')[0]!
      expect(fresh.attributes('aria-invalid')).toBe('true')
      expect(describedText(fresh.element)).toContain(t('errors.fields.auth.password_too_common'))
    })
  })

  describe('sessions', () => {
    const SESSION_LIST = {
      total: 3,
      items: [
        {
          id: '0b6e7c1e-0000-4000-8000-000000000001',
          created_at: '2026-10-30T09:00:00Z',
          last_seen_at: '2026-10-30T10:00:00Z',
          expires_at: '2026-11-29T09:00:00Z',
          user_agent: 'Mozilla/5.0 (Macintosh) Firefox/140.0',
          is_current: true,
        },
        {
          id: '0b6e7c1e-0000-4000-8000-000000000002',
          created_at: '2026-10-20T09:00:00Z',
          last_seen_at: '2026-10-25T10:00:00Z',
          expires_at: '2026-11-19T09:00:00Z',
          user_agent: 'Mozilla/5.0 (Linux; Android 15) Chrome/140.0 Mobile',
          is_current: false,
        },
        {
          id: '0b6e7c1e-0000-4000-8000-000000000003',
          created_at: '2026-10-10T09:00:00Z',
          last_seen_at: '2026-10-11T10:00:00Z',
          expires_at: '2026-11-09T09:00:00Z',
          user_agent: null,
          is_current: false,
        },
      ],
    }
    const rows = (wrapper: VueWrapper) => wrapper.findAll('[data-testid="session-row"]')
    const signOutButton = (row: ReturnType<typeof rows>[number]) =>
      row.findAll('button').find((b) => b.text() === t('account.sessions.signOut'))

    it('lists the sessions and marks the current one without a sign-out button', async () => {
      mockApi(routes({ [SESSIONS]: reply(200, SESSION_LIST) }))
      const { wrapper } = await mountAccount('sessions')
      const list = rows(wrapper)
      expect(list).toHaveLength(3)
      expect(list[0]!.text()).toContain(t('account.sessions.current'))
      expect(list[0]!.text()).toContain('Firefox')
      expect(signOutButton(list[0]!)).toBeUndefined()
      expect(list[1]!.text()).not.toContain(t('account.sessions.current'))
      expect(signOutButton(list[1]!)).toBeDefined()
      expect(list[2]!.text()).toContain(t('account.sessions.unknownDevice'))
    })

    it('signs out another device and removes its row', async () => {
      const id = SESSION_LIST.items[1]!.id
      const fetchMock = mockApi(
        routes({
          [SESSIONS]: reply(200, SESSION_LIST),
          [`DELETE /api/v1/auth/me/sessions/${id}`]: reply(204),
        }),
      )
      const { wrapper } = await mountAccount('sessions')
      await signOutButton(rows(wrapper)[1]!)!.trigger('click')
      await flushPromises()
      expect(callsTo(fetchMock, `DELETE /api/v1/auth/me/sessions/${id}`)).toHaveLength(1)
      expect(rows(wrapper)).toHaveLength(2)
      expect(wrapper.text()).not.toContain('Android')
      expect(wrapper.find('[aria-live="polite"]').text()).toContain(t('account.sessions.signedOut'))
    })

    it('shows an error with retry when the list fails to load', async () => {
      let calls = 0
      const fetchMock = mockApi(
        routes({
          [SESSIONS]: (r) =>
            ++calls === 1 ? replyError(500, 'server.error')(r) : reply(200, SESSION_LIST)(r),
        }),
      )
      const { wrapper } = await mountAccount('sessions')
      expect(wrapper.text()).toContain(t('account.sessions.loadError'))
      await wrapper
        .findAll('button')
        .find((b) => b.text() === t('account.sessions.retry'))!
        .trigger('click')
      await flushPromises()
      expect(callsTo(fetchMock, SESSIONS)).toHaveLength(2)
      expect(rows(wrapper)).toHaveLength(3)
    })
  })
})

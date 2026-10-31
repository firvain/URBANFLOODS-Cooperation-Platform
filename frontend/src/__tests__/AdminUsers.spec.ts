import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import i18n from '@/i18n'
import { callsTo, reply, replyError } from './helpers/api'
import {
  ADMIN_ME,
  SUPERADMIN_ME,
  chooseMenuItem,
  findButton,
  makeAdminUser,
  menuItemTexts,
  mountAdmin,
  openMenu,
  page,
  queryOf,
  tableRows,
} from './helpers/admin'
import { buttonIn, dialog, field } from './helpers/editor'
import { unmountAll } from './helpers/mount'

const t = i18n.global.t
const USERS = 'GET /api/v1/admin/users/'
const MEMBER = makeAdminUser()
const ADMIN = makeAdminUser({ id: 8, display_name: 'Ana', email: 'ana@example.org', role: 'admin' })
const SUPER = makeAdminUser({
  id: 9,
  display_name: 'Petros',
  email: 'petros@example.org',
  role: 'superadmin',
  is_trusted: true,
  trusted_at: '2026-01-01T00:00:00Z',
})
const UNVERIFIED = makeAdminUser({
  id: 10,
  display_name: 'Lena',
  email: 'lena@example.org',
  is_verified: false,
})
const SELF = makeAdminUser({ id: 1, display_name: 'Ada Admin', role: 'admin' })
const ALL = [MEMBER, ADMIN, SUPER, UNVERIFIED, SELF]

const a = (key: string) => t(`admin.users.actions.${key}`)
const menu = (name: string) => t('admin.users.menu', { name })
const rows = () => tableRows('users')
const lastQuery = (fetchMock: Parameters<typeof callsTo>[0]) =>
  queryOf(callsTo(fetchMock, USERS).at(-1)!.url)

async function itemsFor(name: string) {
  await openMenu(menu(name))
  const texts = menuItemTexts()
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  document.activeElement?.dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
  )
  await flushPromises()
  return texts
}

afterEach(unmountAll)

describe('Admin users', () => {
  it('lists accounts with role, verified, trusted, active and created', async () => {
    await mountAdmin('/admin/users', {
      [USERS]: reply(
        200,
        page([MEMBER, makeAdminUser({ id: 11, display_name: 'Bo', is_active: false })]),
      ),
    })
    const table = document.querySelector('table')!
    expect(table.querySelector('caption')?.textContent).toContain(t('admin.users.caption'))
    const [member, banned] = rows()
    expect(member!.textContent).toContain('Nikos')
    expect(member!.textContent).toContain('nikos@example.org')
    expect(member!.textContent).toContain(t('admin.role.member'))
    expect(banned!.textContent).toContain(t('admin.users.banned'))
  })

  it('sends the URL filters to the API', async () => {
    const { fetchMock } = await mountAdmin(
      '/admin/users?q=nik&role=admin&verified=false&trusted=true&active=true&page=3',
      { [USERS]: reply(200, page([ADMIN], 60)) },
    )
    const query = lastQuery(fetchMock)
    expect(query.get('q')).toBe('nik')
    expect(query.get('role')).toBe('admin')
    expect(query.get('verified')).toBe('false')
    expect(query.get('trusted')).toBe('true')
    expect(query.get('active')).toBe('true')
    expect(query.get('skip')).toBe('40')
  })

  it('typing in the search updates the URL and the request', async () => {
    const { fetchMock, router } = await mountAdmin('/admin/users', {
      [USERS]: reply(200, page(ALL)),
    })
    await field(document.body, t('admin.users.search')).setValue('ana')
    await vi.waitFor(() => expect(router.currentRoute.value.query.q).toBe('ana'))
    await flushPromises()
    expect(lastQuery(fetchMock).get('q')).toBe('ana')
  })

  it('an admin promotes a member after confirming, with a toast', async () => {
    const route = 'POST /api/v1/admin/users/7/promote'
    const { fetchMock } = await mountAdmin('/admin/users', {
      [USERS]: reply(200, page(ALL)),
      [route]: reply(200, { ...MEMBER, role: 'admin' }),
    })
    await chooseMenuItem(menu('Nikos'), a('makeAdmin'))
    const box = dialog()
    expect(box.textContent).toContain(t('admin.users.confirm.makeAdmin', { name: 'Nikos' }))
    expect(callsTo(fetchMock, route)).toHaveLength(0)
    buttonIn(box, a('makeAdmin')).click()
    await flushPromises()
    expect(queryOf(callsTo(fetchMock, route)[0]!.url).get('to')).toBe('admin')
    expect(rows()[0]!.textContent).toContain(t('admin.role.admin'))
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain(
        t('admin.users.done.makeAdmin', { name: 'Nikos' }),
      ),
    )
  })

  it('an admin sees no superadmin-only actions', async () => {
    await mountAdmin('/admin/users', { [USERS]: reply(200, page(ALL)) }, ADMIN_ME)
    const forAdmin = await itemsFor('Ana')
    expect(forAdmin).toContain(a('makeMember'))
    expect(forAdmin).not.toContain(a('makeSuperadmin'))
    const forSuper = await itemsFor('Petros')
    expect(forSuper).not.toContain(a('demoteToAdmin'))
    expect(forSuper).not.toContain(a('ban'))
    expect(forSuper).toContain(a('untrust'))
  })

  it('a superadmin can promote to superadmin, demote and ban a superadmin', async () => {
    await mountAdmin('/admin/users', { [USERS]: reply(200, page(ALL)) }, SUPERADMIN_ME)
    expect(await itemsFor('Ana')).toEqual(
      expect.arrayContaining([a('makeSuperadmin'), a('makeMember')]),
    )
    expect(await itemsFor('Petros')).toEqual(expect.arrayContaining([a('demoteToAdmin'), a('ban')]))
  })

  it('offers no role change or ban on your own account', async () => {
    await mountAdmin('/admin/users', { [USERS]: reply(200, page(ALL)) }, ADMIN_ME)
    const own = await itemsFor('Ada Admin')
    expect(own).not.toContain(a('makeMember'))
    expect(own).not.toContain(a('makeSuperadmin'))
    expect(own).not.toContain(a('ban'))
    expect(rows()[4]!.textContent).toContain(t('admin.users.you'))
  })

  it('offers "resend verification" only for unverified accounts', async () => {
    const route = 'POST /api/v1/admin/users/10/resend-verification'
    const { fetchMock } = await mountAdmin('/admin/users', {
      [USERS]: reply(200, page(ALL)),
      [route]: reply(202, { code: 'admin.verification_sent', message: 'Sent' }),
    })
    expect(await itemsFor('Nikos')).not.toContain(a('resend'))
    await chooseMenuItem(menu('Lena'), a('resend'))
    buttonIn(dialog(), a('resend')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)).toHaveLength(1)
  })

  it('bans and trusts with the matching endpoints', async () => {
    const ban = 'POST /api/v1/admin/users/7/ban'
    const trust = 'POST /api/v1/admin/users/7/trust'
    const { fetchMock } = await mountAdmin('/admin/users', {
      [USERS]: reply(200, page(ALL)),
      [ban]: reply(200, { ...MEMBER, is_active: false }),
      [trust]: reply(200, { ...MEMBER, is_active: false, is_trusted: true }),
    })
    await chooseMenuItem(menu('Nikos'), a('ban'))
    buttonIn(dialog(), a('ban')).click()
    await flushPromises()
    expect(callsTo(fetchMock, ban)).toHaveLength(1)
    expect(rows()[0]!.textContent).toContain(t('admin.users.banned'))
    expect(await itemsFor('Nikos')).toContain(a('unban'))

    await chooseMenuItem(menu('Nikos'), a('trust'))
    buttonIn(dialog(), a('trust')).click()
    await flushPromises()
    expect(callsTo(fetchMock, trust)).toHaveLength(1)
  })

  it('explains the last-superadmin refusal in the dialog', async () => {
    await mountAdmin(
      '/admin/users',
      {
        [USERS]: reply(200, page(ALL)),
        'POST /api/v1/admin/users/9/demote': replyError(409, 'admin.last_superadmin'),
      },
      SUPERADMIN_ME,
    )
    await chooseMenuItem(menu('Petros'), a('demoteToAdmin'))
    buttonIn(dialog(), a('demoteToAdmin')).click()
    await flushPromises()
    expect(dialog().textContent).toContain(t('admin.errors.admin.last_superadmin'))
    expect(rows()[2]!.textContent).toContain(t('admin.role.superadmin'))
  })

  it('shows deleted accounts without actions', async () => {
    await mountAdmin('/admin/users', {
      [USERS]: reply(200, page([makeAdminUser({ deleted_at: '2026-10-01T00:00:00Z' })])),
    })
    expect(rows()[0]!.textContent).toContain(t('admin.users.deleted'))
    expect(findButton(menu('Nikos'))).toBeUndefined()
  })

  it('a deleted account is "Deleted" in the Active column, not "Banned"', async () => {
    // Deleting an account also switches it off (is_active false), like a ban.
    await mountAdmin('/admin/users', {
      [USERS]: reply(
        200,
        page([makeAdminUser({ is_active: false, deleted_at: '2026-10-01T00:00:00Z' })]),
      ),
    })
    const active = rows()[0]!.querySelectorAll('td')[4]!
    expect(active.textContent?.trim()).toBe(t('admin.users.deleted'))
    expect(rows()[0]!.textContent).not.toContain(t('admin.users.banned'))
  })
})

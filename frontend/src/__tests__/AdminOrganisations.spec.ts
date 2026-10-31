import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import i18n from '@/i18n'
import { callsTo, reply, replyError } from './helpers/api'
import {
  click,
  findButton,
  makeOrganisation,
  mountAdmin,
  openSelectInDialog,
  page,
  queryOf,
  tableRows,
} from './helpers/admin'
import { buttonIn, dialog, field } from './helpers/editor'
import { enterOption } from './helpers/select'
import { unmountAll } from './helpers/mount'

const t = i18n.global.t
const LIST = 'GET /api/v1/organisations/'
const o = (key: string, params: Record<string, unknown> = {}) =>
  t(`admin.organisations.${key}`, params)

afterEach(unmountAll)

describe('Admin organisations', () => {
  const UOWM = makeOrganisation()
  const OTHER = makeOrganisation({
    id: 140,
    name: 'Adriatic Flood Forum',
    short_name: 'AFF',
    country: 'HR',
    type: 'other',
    website: null,
    is_partner: false,
    sort_order: 0,
    member_count: 0,
  })

  it('lists every organisation with short name, country, type, partner, members and order', async () => {
    const { fetchMock } = await mountAdmin('/admin/organisations', {
      [LIST]: reply(200, page([OTHER, UOWM])),
    })
    expect(queryOf(callsTo(fetchMock, LIST)[0]!.url).get('limit')).toBe('200')
    const rows = tableRows('organisations')
    expect(rows).toHaveLength(2)
    // Partners first, as the backend orders them.
    expect(rows[0]!.textContent).toContain('University of Western Macedonia')
    expect(rows[0]!.textContent).toContain('UOWM')
    expect(rows[0]!.textContent).toContain('Greece')
    expect(rows[0]!.textContent).toContain(o('types.PP'))
    expect(rows[0]!.textContent).toContain(t('admin.common.yes'))
    expect(rows[1]!.textContent).toContain(o('types.other'))
    expect(rows[1]!.textContent).toContain(t('admin.common.no'))
    expect(findButton(o('editLabel', { name: 'AFF' }))).toBeDefined()
  })

  it('validates the new organisation before sending it', async () => {
    const { fetchMock } = await mountAdmin('/admin/organisations', {
      [LIST]: reply(200, page([UOWM])),
    })
    await click(o('create'))
    const box = dialog()
    await field(box, o('website')).setValue('ftp://example.org')
    buttonIn(box, o('save')).click()
    await flushPromises()
    expect(callsTo(fetchMock, 'POST /api/v1/organisations/')).toHaveLength(0)
    const text = dialog().textContent
    expect(text).toContain(o('validation.nameRequired', { min: 2 }))
    expect(text).toContain(o('validation.shortNameRequired'))
    expect(text).toContain(o('validation.countryRequired'))
    expect(text).toContain(o('validation.websiteInvalid'))
  })

  it('creates an organisation and lists it', async () => {
    const created = makeOrganisation({
      id: 150,
      name: 'Kozani Civil Protection',
      short_name: 'KCP',
      type: 'other',
      website: null,
      is_partner: false,
      sort_order: 5,
      member_count: 0,
    })
    const { fetchMock } = await mountAdmin('/admin/organisations', {
      [LIST]: reply(200, page([UOWM])),
      'POST /api/v1/organisations/': reply(201, created),
    })
    await click(o('create'))
    const box = dialog()
    await field(box, o('name')).setValue('  Kozani Civil Protection ')
    await field(box, o('shortName')).setValue('KCP')
    await field(box, o('sortOrder')).setValue('5')
    await openSelectInDialog(o('country'))
    await enterOption('Greece')
    buttonIn(dialog(), o('save')).click()
    await flushPromises()
    expect(callsTo(fetchMock, 'POST /api/v1/organisations/')[0]!.body).toEqual({
      name: 'Kozani Civil Protection',
      short_name: 'KCP',
      country: 'GR',
      type: 'other',
      website: null,
      is_partner: false,
      sort_order: 5,
    })
    expect(tableRows('organisations')).toHaveLength(2)
  })

  it('shows a name conflict from the server in the dialog', async () => {
    await mountAdmin('/admin/organisations', {
      [LIST]: reply(200, page([UOWM])),
      'PATCH /api/v1/organisations/101': replyError(409, 'organisations.name_taken'),
    })
    await click(o('editLabel', { name: 'UOWM' }))
    await field(dialog(), o('name')).setValue('Macerata Municipality')
    buttonIn(dialog(), o('save')).click()
    await flushPromises()
    expect(dialog().textContent).toContain(t('admin.errors.organisations.name_taken'))
  })

  it('edits only the changed fields; clearing the website sends null', async () => {
    const route = 'PATCH /api/v1/organisations/101'
    const { fetchMock } = await mountAdmin('/admin/organisations', {
      [LIST]: reply(200, page([UOWM])),
      [route]: reply(200, { ...UOWM, short_name: 'UoWM', website: null, type: 'AP' }),
    })
    await click(o('editLabel', { name: 'UOWM' }))
    const box = dialog()
    await field(box, o('shortName')).setValue('UoWM')
    await field(box, o('website')).setValue('')
    await openSelectInDialog(o('type'))
    await enterOption(o('types.AP'))
    buttonIn(dialog(), o('save')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)[0]!.body).toEqual({
      short_name: 'UoWM',
      type: 'AP',
      website: null,
    })
    expect(tableRows('organisations')[0]!.textContent).toContain('UoWM')
  })

  it('an unchanged edit sends nothing', async () => {
    const { fetchMock } = await mountAdmin('/admin/organisations', {
      [LIST]: reply(200, page([UOWM])),
    })
    await click(o('editLabel', { name: 'UOWM' }))
    buttonIn(dialog(), o('save')).click()
    await flushPromises()
    expect(callsTo(fetchMock, 'PATCH /api/v1/organisations/101')).toHaveLength(0)
  })
})

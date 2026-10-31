import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import i18n from '@/i18n'
import { callsTo, reply, replyError } from './helpers/api'
import {
  click,
  findButton,
  makeExpertise,
  mountAdmin,
  page,
  queryOf,
  tableRows,
} from './helpers/admin'
import { buttonIn, dialog, field } from './helpers/editor'
import { unmountAll } from './helpers/mount'

const t = i18n.global.t
const LIST = 'GET /api/v1/expertise/'
const e = (key: string, params: Record<string, unknown> = {}) =>
  t(`admin.expertise.${key}`, params)

afterEach(unmountAll)

describe('Admin expertise areas', () => {
  const HYDROLOGY = makeExpertise()
  const RETIRED = makeExpertise({
    id: 30,
    slug: 'retired-area',
    label: 'Retired area',
    sort_order: 40,
    is_active: false,
  })

  it('lists active and deactivated areas with slug and order', async () => {
    const { fetchMock } = await mountAdmin('/admin/expertise', {
      [LIST]: reply(200, page([RETIRED, HYDROLOGY])),
    })
    expect(queryOf(callsTo(fetchMock, LIST)[0]!.url).get('include_inactive')).toBe('true')
    const rows = tableRows('expertise')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.textContent).toContain('Hydrology')
    expect(rows[0]!.textContent).toContain('hydrology')
    expect(rows[0]!.textContent).toContain(e('active'))
    expect(rows[1]!.textContent).toContain(e('inactive'))
    expect(findButton(e('deactivateLabel', { name: 'Hydrology' }))).toBeDefined()
    expect(findButton(e('reactivateLabel', { name: 'Retired area' }))).toBeDefined()
  })

  it('validates the new area before sending it', async () => {
    const { fetchMock } = await mountAdmin('/admin/expertise', {
      [LIST]: reply(200, page([HYDROLOGY])),
    })
    await click(e('create'))
    const box = dialog()
    await field(box, e('label')).setValue('x')
    await field(box, e('slug')).setValue('Bad Slug!')
    buttonIn(box, e('save')).click()
    await flushPromises()
    expect(callsTo(fetchMock, 'POST /api/v1/expertise/')).toHaveLength(0)
    expect(dialog().textContent).toContain(e('validation.labelRequired', { min: 2 }))
    expect(dialog().textContent).toContain(e('validation.slugInvalid'))
  })

  it('creates an area and lists it', async () => {
    const created = makeExpertise({ id: 31, slug: 'drones', label: 'Drones', sort_order: 23 })
    const { fetchMock } = await mountAdmin('/admin/expertise', {
      [LIST]: reply(200, page([HYDROLOGY])),
      'POST /api/v1/expertise/': reply(201, created),
    })
    await click(e('create'))
    const box = dialog()
    await field(box, e('label')).setValue(' Drones ')
    await field(box, e('sortOrder')).setValue('23')
    buttonIn(box, e('save')).click()
    await flushPromises()
    expect(callsTo(fetchMock, 'POST /api/v1/expertise/')[0]!.body).toEqual({
      label: 'Drones',
      slug: null,
      sort_order: 23,
    })
    expect(tableRows('expertise')).toHaveLength(2)
  })

  it('shows a slug conflict from the server in the dialog', async () => {
    await mountAdmin('/admin/expertise', {
      [LIST]: reply(200, page([HYDROLOGY])),
      'POST /api/v1/expertise/': replyError(409, 'expertise.slug_taken'),
    })
    await click(e('create'))
    await field(dialog(), e('label')).setValue('Hydrology')
    buttonIn(dialog(), e('save')).click()
    await flushPromises()
    expect(dialog().textContent).toContain(t('admin.errors.expertise.slug_taken'))
  })

  it('edits only the changed fields', async () => {
    const route = 'PATCH /api/v1/expertise/1'
    const { fetchMock } = await mountAdmin('/admin/expertise', {
      [LIST]: reply(200, page([HYDROLOGY])),
      [route]: reply(200, { ...HYDROLOGY, label: 'Hydrology and hydrometry' }),
    })
    await click(e('editLabel', { name: 'Hydrology' }))
    await field(dialog(), e('label')).setValue('Hydrology and hydrometry')
    buttonIn(dialog(), e('save')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)[0]!.body).toEqual({ label: 'Hydrology and hydrometry' })
    expect(tableRows('expertise')[0]!.textContent).toContain('Hydrology and hydrometry')
  })

  it('deactivates after a confirmation that explains members keep the area', async () => {
    const route = 'PATCH /api/v1/expertise/1'
    const { fetchMock } = await mountAdmin('/admin/expertise', {
      [LIST]: reply(200, page([HYDROLOGY])),
      [route]: reply(200, { ...HYDROLOGY, is_active: false }),
    })
    await click(e('deactivateLabel', { name: 'Hydrology' }))
    const box = dialog()
    expect(box.textContent).toContain(e('deactivateTitle', { name: 'Hydrology' }))
    expect(box.textContent).toContain(e('deactivateDescription'))
    expect(callsTo(fetchMock, route)).toHaveLength(0)
    buttonIn(box, e('deactivate')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)[0]!.body).toEqual({ is_active: false })
    expect(tableRows('expertise')[0]!.textContent).toContain(e('inactive'))
  })

  it('reactivates a deactivated area', async () => {
    const route = 'PATCH /api/v1/expertise/30'
    const { fetchMock } = await mountAdmin('/admin/expertise', {
      [LIST]: reply(200, page([RETIRED])),
      [route]: reply(200, { ...RETIRED, is_active: true }),
    })
    await click(e('reactivateLabel', { name: 'Retired area' }))
    expect(callsTo(fetchMock, route)[0]!.body).toEqual({ is_active: true })
    expect(tableRows('expertise')[0]!.textContent).toContain(e('active'))
  })
})

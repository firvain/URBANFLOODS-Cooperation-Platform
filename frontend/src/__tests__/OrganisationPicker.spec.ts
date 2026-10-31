import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import OrganisationPicker from '@/components/common/OrganisationPicker.vue'
import i18n from '@/i18n'
import type { OrganisationChoice } from '@/services/organisations'
import { callsTo, mockApi, ORGANISATIONS, reply } from './helpers/api'
import { mountWithApp, unmountAll } from './helpers/mount'
import { openSelect } from './helpers/select'

const t = i18n.global.t

afterEach(unmountAll)

async function mountPicker(modelValue: OrganisationChoice) {
  const { wrapper } = await mountWithApp(OrganisationPicker, {
    props: {
      modelValue,
      'onUpdate:modelValue': (value: OrganisationChoice) => wrapper.setProps({ modelValue: value }),
    },
  })
  return wrapper
}

function emitted(wrapper: VueWrapper): OrganisationChoice[] {
  return (wrapper.emitted('update:modelValue') ?? []).map((args) => args[0] as OrganisationChoice)
}

async function pick(wrapper: VueWrapper, text: string) {
  const label = wrapper
    .findAll('label')
    .find((l) => l.text().startsWith(t('auth.fields.organisation')))
  const el = wrapper.find(`#${label!.attributes('for')}`).element as HTMLElement
  el.focus()
  el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await flushPromises()
  if (!document.querySelector('[role="option"]')) {
    el.click()
    await flushPromises()
  }
  const option = Array.from(document.querySelectorAll<HTMLElement>('[role="option"]')).find((o) =>
    o.textContent?.includes(text),
  )
  expect(option, `option ${text}`).toBeDefined()
  option!.click()
  await flushPromises()
}

describe('OrganisationPicker', () => {
  it('loads the organisations once (cached in the store)', async () => {
    const fetchMock = mockApi({ 'GET /api/v1/organisations/': reply(200, ORGANISATIONS) })
    await mountPicker({ organisation_id: null, organisation_other: null })
    expect(callsTo(fetchMock, 'GET /api/v1/organisations/')).toHaveLength(1)
  })

  it('labels each listed organisation with its full name only (no short name)', async () => {
    mockApi({ 'GET /api/v1/organisations/': reply(200, ORGANISATIONS) })
    const wrapper = await mountPicker({ organisation_id: null, organisation_other: null })
    await openSelect(wrapper, t('auth.fields.organisation'))
    const labels = Array.from(document.querySelectorAll('[role="option"]')).map((o) =>
      o.textContent?.trim(),
    )
    expect(labels).toEqual([
      'University of Western Macedonia',
      'Macerata Municipality',
      t('auth.fields.organisationOtherOption'),
    ])
  })

  it('emits organisation_id when a listed organisation is picked', async () => {
    mockApi({ 'GET /api/v1/organisations/': reply(200, ORGANISATIONS) })
    const wrapper = await mountPicker({ organisation_id: null, organisation_other: null })
    await pick(wrapper, 'Macerata Municipality')
    expect(emitted(wrapper).at(-1)).toEqual({ organisation_id: 4, organisation_other: null })
    expect(wrapper.find('input[name="organisation_other"]').exists()).toBe(false)
  })

  it('"Other…" reveals the text input and emits organisation_other', async () => {
    mockApi({ 'GET /api/v1/organisations/': reply(200, ORGANISATIONS) })
    const wrapper = await mountPicker({ organisation_id: 1, organisation_other: null })
    await pick(wrapper, t('auth.fields.organisationOtherOption'))
    expect(emitted(wrapper).at(-1)).toEqual({ organisation_id: null, organisation_other: '' })

    const input = wrapper.find('input[name="organisation_other"]')
    expect(input.exists()).toBe(true)
    await input.setValue('Civil Protection of Epirus')
    expect(emitted(wrapper).at(-1)).toEqual({
      organisation_id: null,
      organisation_other: 'Civil Protection of Epirus',
    })
  })

  it('shows an existing free-text organisation in "Other…" mode', async () => {
    mockApi({ 'GET /api/v1/organisations/': reply(200, ORGANISATIONS) })
    const wrapper = await mountPicker({ organisation_id: null, organisation_other: 'ACME' })
    const input = wrapper.find('input[name="organisation_other"]')
    expect((input.element as HTMLInputElement).value).toBe('ACME')
  })

  it('shows the errors passed in on the matching field', async () => {
    mockApi({ 'GET /api/v1/organisations/': reply(200, ORGANISATIONS) })
    const { wrapper } = await mountWithApp(OrganisationPicker, {
      props: {
        modelValue: { organisation_id: null, organisation_other: '' },
        otherError: 'Required here',
      },
    })
    expect(wrapper.find('input[name="organisation_other"]').attributes('aria-invalid')).toBe('true')
    expect(wrapper.text()).toContain('Required here')
  })
})

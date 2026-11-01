import { afterEach, describe, expect, it } from 'vitest'
import type { VueWrapper } from '@vue/test-utils'

import ExpertisePicker from '@/components/common/ExpertisePicker.vue'
import i18n from '@/i18n'
import { mockApi, reply } from './helpers/api'
import { EXPERTISE_RESPONSE } from './helpers/members'
import { mountWithApp, unmountAll } from './helpers/mount'
import { controlFor } from './helpers/select'

const t = i18n.global.t

afterEach(unmountAll)

async function mountPicker(props: Record<string, unknown> = {}) {
  mockApi({ 'GET /api/v1/expertise/': reply(200, EXPERTISE_RESPONSE) })
  const { wrapper } = await mountWithApp(ExpertisePicker, {
    props: {
      label: 'Areas of expertise',
      modelValue: [],
      other: '',
      'onUpdate:other': (value: string) => wrapper.setProps({ other: value }),
      ...props,
    },
  })
  return wrapper
}

const otherInput = (wrapper: VueWrapper) => wrapper.find('input[name="expertise_other"]')

function describedText(el: Element): string {
  return (el.getAttribute('aria-describedby') ?? '')
    .split(' ')
    .map((id) => document.getElementById(id)?.textContent ?? '')
    .join(' ')
}

describe('ExpertisePicker: free-text "other" area', () => {
  it('has a labelled optional text input with a hint, limited to 200 characters', async () => {
    const wrapper = await mountPicker()
    expect(t('auth.expertiseOtherLabel')).toBe('Other area of expertise (optional)')
    expect(t('auth.expertiseOtherHint')).toBe('If your field is not in the list')

    const input = controlFor(wrapper, t('auth.expertiseOtherLabel'))
    expect(input).toBe(otherInput(wrapper).element)
    expect(input.getAttribute('maxlength')).toBe('200')
    expect(input.hasAttribute('required')).toBe(false)
    expect(describedText(input)).toContain(t('auth.expertiseOtherHint'))
  })

  it('shows a character counter', async () => {
    const wrapper = await mountPicker({ other: 'Coastal engineering' })
    expect(wrapper.text()).toContain(t('auth.expertiseOtherCount', { count: 19, max: 200 }))
  })

  it('shows the current text and emits what the user types', async () => {
    const wrapper = await mountPicker({ other: 'Coastal engineering' })
    expect((otherInput(wrapper).element as HTMLInputElement).value).toBe('Coastal engineering')

    await otherInput(wrapper).setValue('Sediment transport')
    expect(wrapper.emitted('update:other')!.at(-1)).toEqual(['Sediment transport'])
  })

  it('shows an error passed in on the text input', async () => {
    const wrapper = await mountPicker({ otherError: 'Too long here' })
    const input = otherInput(wrapper).element
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect(describedText(input)).toContain('Too long here')
  })

  it('keeps the expertise select labelled', async () => {
    const wrapper = await mountPicker()
    expect(controlFor(wrapper, 'Areas of expertise')).not.toBe(otherInput(wrapper).element)
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import KnowbaseLinkPicker, {
  type KnowbaseLinkValue,
} from '@/components/editor/KnowbaseLinkPicker.vue'
import { callsTo, mockApi, reply, type FetchMock } from './helpers/api'
import { buttonIn, field } from './helpers/editor'
import { mountWithApp, unmountAll } from './helpers/mount'

const MEASURES = 'GET /api/v1/knowbase/measures/'
const DOCUMENTS = 'GET /api/v1/knowbase/documents/'

const MEASURE_PAGE = {
  total: 2,
  items: [
    { id: 5, measure_code: 'NBS-04', title_en: 'green roofs' },
    { id: 9, measure_code: 'STR-11', title_en: 'green retention basin' },
  ],
}
const DOCUMENT_PAGE = {
  total: 1,
  items: [{ id: 31, name_of_document_en: 'Law on Waters', country: 'RS' }],
}

let fetchMock: FetchMock

beforeEach(() => {
  fetchMock = mockApi({
    [MEASURES]: reply(200, MEASURE_PAGE),
    [DOCUMENTS]: reply(200, DOCUMENT_PAGE),
  })
})

afterEach(() => {
  vi.useRealTimers()
  unmountAll()
})

async function mountPicker(modelValue: KnowbaseLinkValue[] = []) {
  const { wrapper } = await mountWithApp(KnowbaseLinkPicker, { props: { modelValue } })
  wrapper.setProps({
    'onUpdate:modelValue': (value: KnowbaseLinkValue[]) => wrapper.setProps({ modelValue: value }),
  })
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  return wrapper
}

async function search(wrapper: VueWrapper, text: string) {
  await field(wrapper.element as HTMLElement, 'Search the KNOWBASE').setValue(text)
}

async function settle() {
  vi.advanceTimersByTime(400)
  await flushPromises()
}

const paramsOf = (url: string) => new URL(url, 'http://x.invalid').searchParams

function lastValue(wrapper: VueWrapper): KnowbaseLinkValue[] {
  return wrapper.emitted<[KnowbaseLinkValue[]]>('update:modelValue')!.at(-1)![0]
}

function linked(n: number): KnowbaseLinkValue[] {
  return Array.from({ length: n }, (_, i) => ({
    kb_type: 'document' as const,
    kb_id: 100 + i,
    title: `Document ${i + 1}`,
  }))
}

describe('KnowbaseLinkPicker', () => {
  it('debounces the search and queries measures by default', async () => {
    const wrapper = await mountPicker()
    await search(wrapper, 'g')
    await search(wrapper, 'gre')
    await search(wrapper, 'green')
    vi.advanceTimersByTime(100)
    await flushPromises()
    expect(callsTo(fetchMock, MEASURES)).toHaveLength(0)
    await settle()
    const calls = callsTo(fetchMock, MEASURES)
    expect(calls).toHaveLength(1)
    expect(paramsOf(calls[0]!.url).get('q')).toBe('green')
    expect(paramsOf(calls[0]!.url).get('limit')).toBe('10')
    expect(wrapper.text()).toContain('Green Roofs')
    expect(wrapper.text()).toContain('NBS-04')
  })

  it('switches the endpoint when the type is toggled', async () => {
    const wrapper = await mountPicker()
    const documents = buttonIn(wrapper.element as HTMLElement, 'Documents')
    expect(buttonIn(wrapper.element as HTMLElement, 'Measures').getAttribute('aria-pressed')).toBe(
      'true',
    )
    await search(wrapper, 'water')
    await settle()
    documents.click()
    await settle()
    expect(documents.getAttribute('aria-pressed')).toBe('true')
    const calls = callsTo(fetchMock, DOCUMENTS)
    expect(calls).toHaveLength(1)
    expect(paramsOf(calls[0]!.url).get('q')).toBe('water')
    expect(wrapper.text()).toContain('Law on Waters')
    expect(wrapper.text()).not.toContain('Green Roofs')
  })

  it('adds a result as a chip and removes it again', async () => {
    const wrapper = await mountPicker()
    await search(wrapper, 'green')
    await settle()
    buttonIn(wrapper.element as HTMLElement, 'Add Green Roofs').click()
    await flushPromises()
    expect(lastValue(wrapper)).toEqual([{ kb_type: 'measure', kb_id: 5, title: 'green roofs' }])
    const added = buttonIn(wrapper.element as HTMLElement, 'Add Green Roofs')
    expect(added.disabled).toBe(true)

    buttonIn(wrapper.element as HTMLElement, 'Remove Green Roofs').click()
    await flushPromises()
    expect(lastValue(wrapper)).toEqual([])
    expect(wrapper.find('[aria-label="Remove Green Roofs"]').exists()).toBe(false)
  })

  it('adds documents with their document type', async () => {
    const wrapper = await mountPicker()
    buttonIn(wrapper.element as HTMLElement, 'Documents').click()
    await search(wrapper, 'law')
    await settle()
    buttonIn(wrapper.element as HTMLElement, 'Add Law on Waters').click()
    await flushPromises()
    expect(lastValue(wrapper)).toEqual([{ kb_type: 'document', kb_id: 31, title: 'Law on Waters' }])
  })

  it('refuses an 11th item and says why', async () => {
    const wrapper = await mountPicker(linked(10))
    await search(wrapper, 'green')
    await settle()
    buttonIn(wrapper.element as HTMLElement, 'Add Green Roofs').click()
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(wrapper.find('[role="status"]').text()).toContain(
      'You can link at most 10 KNOWBASE items.',
    )
  })

  it('does not search for blank input', async () => {
    const wrapper = await mountPicker()
    await search(wrapper, '   ')
    await settle()
    expect(callsTo(fetchMock, MEASURES)).toHaveLength(0)
  })
})

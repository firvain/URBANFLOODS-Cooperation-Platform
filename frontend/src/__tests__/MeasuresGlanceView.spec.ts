import { flushPromises, type DOMWrapper, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import MeasuresGlanceView from '@/views/MeasuresGlanceView.vue'
import i18n, { setLocale } from '@/i18n'
import en from '@/i18n/locales/en.json'
import type { Measure, MeasureRef } from '@/services/knowbase'
import { callsTo, deferred, mockApi, replyError, type Handler } from './helpers/api'
import { MEASURES, kbReply, makeMeasure } from './helpers/knowbase'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t

afterEach(() => {
  setLocale('en')
  unmountAll()
})

/** The KNOWBASE reference values as the live proxy returns them (codes verified 2026-11-01). */
const ref = (id: number, code: string, label_en: string): MeasureRef => ({
  id,
  code,
  label_en,
  label_local: null,
})
const TYPE = {
  STR: ref(1, 'STR', 'Structural'),
  HYB: ref(2, 'HYB', 'Hybrid'),
  NBS: ref(3, 'NBS', 'Nature-based Solution'),
  NS: ref(4, 'NS', 'Non-structural'),
}
const PHASE = {
  PRO: ref(1, 'PRO', 'Protection'),
  PRE: ref(2, 'PRE', 'Preparedness'),
  REC: ref(3, 'REC', 'Recovery'),
  MIT: ref(4, 'MIT', 'Mitigation'),
}
const SCALE = {
  PROP: ref(1, 'PROP', 'Property'),
  LOC: ref(2, 'LOC', 'Local'),
  REG: ref(3, 'REG', 'Regional'),
  NAT: ref(4, 'NAT', 'National'),
}

function measure(
  id: number,
  category: MeasureRef | null,
  phases: MeasureRef[],
  scales: MeasureRef[],
  overrides: Partial<Measure> = {},
): Measure {
  return makeMeasure(id, {
    category,
    levels_of_application: phases,
    scales,
    ...overrides,
  })
}

/**
 * Seven measures, in an order that is not the grouping order:
 * NBS 1, 2 · STR 3, 4 · NS 5 · HYB 6 · no category 7.
 */
const ITEMS = [
  measure(6, TYPE.HYB, [PHASE.MIT], [SCALE.PROP]),
  measure(3, TYPE.STR, [PHASE.PRO], [SCALE.REG]),
  measure(5, TYPE.NS, [PHASE.PRE], [SCALE.NAT]),
  measure(1, TYPE.NBS, [PHASE.PRO], [SCALE.LOC]),
  measure(7, null, [PHASE.PRE], [SCALE.LOC]),
  measure(4, TYPE.STR, [PHASE.PRE, PHASE.REC], [SCALE.LOC, SCALE.REG]),
  measure(2, TYPE.NBS, [PHASE.PRE], [SCALE.LOC]),
]

const page = (items: Measure[] = ITEMS) => kbReply({ total: items.length, items })

function routes(measures: Handler = page()) {
  return { [MEASURES]: measures }
}

const mountGlance = (path = '/knowbase/measures') => mountWithApp(MeasuresGlanceView, { path })

const groups = (wrapper: VueWrapper) => wrapper.findAll('section[data-testid="measure-group"]')
const groupHeadings = (wrapper: VueWrapper) => groups(wrapper).map((g) => g.find('h2').text())
const cardIds = (wrapper: VueWrapper) =>
  wrapper
    .findAll('[data-testid="measure-card"] h3 a')
    .map((a) => Number(a.attributes('href')!.split('/').pop()))
const chipGroup = (wrapper: VueWrapper, label: string) =>
  wrapper.find(`[role="group"][aria-label="${label}"]`)
const chips = (group: DOMWrapper<Element>) => group.findAll('button').map((b) => b.text())
const chip = (group: DOMWrapper<Element>, label: string) =>
  group.findAll('button').find((b) => b.text().startsWith(`${label} (`))!
const phaseGroup = (wrapper: VueWrapper) => chipGroup(wrapper, t('knowbase.glance.phase'))
const scaleGroup = (wrapper: VueWrapper) => chipGroup(wrapper, t('knowbase.glance.scale'))
const clearButton = (wrapper: VueWrapper) =>
  wrapper.findAll('button').find((b) => b.text() === t('knowbase.glance.clearFilters'))

describe('MeasuresGlanceView', () => {
  it('has one focusable h1 and the intro, and no link out to the KNOWBASE', async () => {
    mockApi(routes())
    const { wrapper } = await mountGlance()
    const headings = wrapper.findAll('h1')
    expect(headings).toHaveLength(1)
    expect(headings[0]!.text()).toBe(t('knowbase.glance.title'))
    expect(t('knowbase.glance.title')).toBe('Measures at a glance')
    expect(headings[0]!.attributes('tabindex')).toBe('-1')
    expect(wrapper.text()).toContain(t('knowbase.glance.intro'))
    // The KNOWBASE stays one click away in the header menu and on each measure page.
    expect(wrapper.find('a[href^="https://knowbase.urbanfloods.app"]').exists()).toBe(false)
  })

  it('loads all measures in one request with limit=200 and no other filter', async () => {
    const fetchMock = mockApi(routes())
    await mountGlance('/knowbase/measures?phase=PRE&scale=LOC')
    const calls = callsTo(fetchMock, MEASURES)
    expect(calls).toHaveLength(1)
    const query = new URL(calls[0]!.url, 'http://test.invalid').searchParams
    expect([...query.keys()]).toEqual(['limit'])
    expect(query.get('limit')).toBe('200')
  })

  it('groups the measures by type (NBS, STR, NS, HYB, then Other) with counts in the h2', async () => {
    mockApi(routes())
    const { wrapper } = await mountGlance()
    expect(groupHeadings(wrapper)).toEqual([
      `${t('knowbase.types.NBS')} (2)`,
      `${t('knowbase.types.STR')} (2)`,
      `${t('knowbase.types.NS')} (1)`,
      `${t('knowbase.types.HYB')} (1)`,
      `${t('knowbase.types.other')} (1)`,
    ])
    for (const group of groups(wrapper)) {
      const id = group.attributes('aria-labelledby')
      expect(id).toBeTruthy()
      expect(group.find('h2').attributes('id')).toBe(id)
    }
    expect(cardIds(wrapper)).toEqual([1, 2, 3, 4, 5, 6, 7])
  })

  it('shows measure names in title case, as the KNOWBASE shows them', async () => {
    const items = [
      measure(1, TYPE.NBS, [PHASE.PRO], [SCALE.LOC], { title_en: 'floodplain reconnection' }),
    ]
    mockApi(routes(page(items)))
    const { wrapper } = await mountGlance()
    expect(wrapper.find('[data-testid="measure-card"] h3 a').text()).toBe('Floodplain Reconnection')
  })

  it('a card shows the photo (decorative), the title linked to the measure page and badges', async () => {
    mockApi(routes())
    const { wrapper } = await mountGlance()
    const card = wrapper.findAll('[data-testid="measure-card"]')[3]! // measure 4
    const img = card.find('img')
    expect(img.attributes('src')).toBe('https://knowbase.test/static/measures/photos/m4.jpg')
    expect(img.attributes('alt')).toBe('')
    expect(img.attributes('loading')).toBe('lazy')
    const link = card.find('h3 a')
    expect(link.attributes('href')).toBe('/knowbase/measures/4')
    expect(link.text()).toBe('Measure 4')
    const text = card.text()
    for (const label of ['Preparedness', 'Recovery', 'Local', 'Regional']) {
      expect(text).toContain(label)
    }
  })

  it('a card without a photo shows a placeholder and no image', async () => {
    mockApi(routes(page([measure(1, TYPE.NBS, [PHASE.PRO], [SCALE.LOC], { photo_url: null })])))
    const { wrapper } = await mountGlance()
    const card = wrapper.find('[data-testid="measure-card"]')
    expect(card.find('img').exists()).toBe(false)
    expect(card.find('[data-testid="measure-photo-placeholder"]').exists()).toBe(true)
  })

  it('shows phase and scale chips for the codes in the data, with counts and All', async () => {
    mockApi(routes())
    const { wrapper } = await mountGlance()
    expect(chips(phaseGroup(wrapper))).toEqual([
      `${t('knowbase.glance.all')} (7)`,
      'Protection (2)',
      'Preparedness (4)',
      'Recovery (1)',
      'Mitigation (1)',
    ])
    expect(chips(scaleGroup(wrapper))).toEqual([
      `${t('knowbase.glance.all')} (7)`,
      'Property (1)',
      'Local (4)',
      'Regional (2)',
      'National (1)',
    ])
    const all = phaseGroup(wrapper).findAll('button')[0]!
    expect(all.attributes('aria-pressed')).toBe('true')
    expect(chip(phaseGroup(wrapper), 'Preparedness').attributes('aria-pressed')).toBe('false')
    expect(clearButton(wrapper)).toBeUndefined()
  })

  it('omits chips for codes that do not occur in the data', async () => {
    mockApi(routes(page([measure(1, TYPE.NBS, [PHASE.PRO], [SCALE.LOC])])))
    const { wrapper } = await mountGlance()
    expect(chips(phaseGroup(wrapper))).toEqual([
      `${t('knowbase.glance.all')} (1)`,
      'Protection (1)',
    ])
    expect(chips(scaleGroup(wrapper))).toEqual([`${t('knowbase.glance.all')} (1)`, 'Local (1)'])
  })

  it('a phase chip puts the code in the URL, hides other measures and empty groups', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper, router } = await mountGlance()
    await chip(phaseGroup(wrapper), 'Protection').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ phase: 'PRO' })
    expect(chip(phaseGroup(wrapper), 'Protection').attributes('aria-pressed')).toBe('true')
    expect(groupHeadings(wrapper)).toEqual([
      `${t('knowbase.types.NBS')} (1)`,
      `${t('knowbase.types.STR')} (1)`,
    ])
    expect(cardIds(wrapper)).toEqual([1, 3])
    // Filtering is client-side: still one request.
    expect(callsTo(fetchMock, MEASURES)).toHaveLength(1)
  })

  it('reads ?phase=PRE&scale=LOC from the URL and counts each chip given the other filter', async () => {
    mockApi(routes())
    const { wrapper } = await mountGlance('/knowbase/measures?phase=PRE&scale=LOC')
    expect(cardIds(wrapper)).toEqual([2, 4, 7])
    expect(groupHeadings(wrapper)).toEqual([
      `${t('knowbase.types.NBS')} (1)`,
      `${t('knowbase.types.STR')} (1)`,
      `${t('knowbase.types.other')} (1)`,
    ])
    // Phase counts given scale=LOC: 1, 2, 4, 7 are local.
    expect(chips(phaseGroup(wrapper))).toEqual([
      `${t('knowbase.glance.all')} (4)`,
      'Protection (1)',
      'Preparedness (3)',
      'Recovery (1)',
      'Mitigation (0)',
    ])
    // Scale counts given phase=PRE: 2, 4, 5, 7 are preparedness.
    expect(chips(scaleGroup(wrapper))).toEqual([
      `${t('knowbase.glance.all')} (4)`,
      'Property (0)',
      'Local (3)',
      'Regional (1)',
      'National (1)',
    ])
    expect(chip(phaseGroup(wrapper), 'Preparedness').attributes('aria-pressed')).toBe('true')
    expect(chip(scaleGroup(wrapper), 'Local').attributes('aria-pressed')).toBe('true')
  })

  it('the All chip removes that filter from the URL', async () => {
    mockApi(routes())
    const { wrapper, router } = await mountGlance('/knowbase/measures?phase=PRE&scale=LOC')
    await phaseGroup(wrapper).findAll('button')[0]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ scale: 'LOC' })
    expect(cardIds(wrapper)).toEqual([1, 2, 4, 7])
  })

  it('Clear filters removes both filters and shows every measure', async () => {
    mockApi(routes())
    const { wrapper, router } = await mountGlance('/knowbase/measures?phase=PRE&scale=LOC')
    await clearButton(wrapper)!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({})
    expect(cardIds(wrapper)).toHaveLength(7)
    expect(clearButton(wrapper)).toBeUndefined()
  })

  it('shows an empty state with Clear filters when nothing matches', async () => {
    mockApi(routes())
    const { wrapper, router } = await mountGlance('/knowbase/measures?phase=MIT&scale=LOC')
    expect(groups(wrapper)).toHaveLength(0)
    expect(t('knowbase.glance.empty')).toBe('No measures match these filters.')
    expect(wrapper.text()).toContain(t('knowbase.glance.empty'))
    const clears = wrapper
      .findAll('button')
      .filter((b) => b.text() === t('knowbase.glance.clearFilters'))
    expect(clears.length).toBeGreaterThan(0)
    await clears.at(-1)!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({})
    expect(cardIds(wrapper)).toHaveLength(7)
  })

  it('translates types, phases and scales by code', async () => {
    setLocale('it')
    mockApi(routes())
    const { wrapper } = await mountGlance()
    expect(groupHeadings(wrapper)[0]).toBe(`${t('knowbase.types.NBS')} (2)`)
    expect(t('knowbase.types.NBS')).not.toBe(en.knowbase.types.NBS)
    const phaseLabel = t('knowbase.phases.PRE')
    expect(phaseLabel).not.toBe(en.knowbase.phases.PRE)
    expect(chip(chipGroup(wrapper, t('knowbase.glance.phase')), phaseLabel).exists()).toBe(true)
    const scaleLabel = t('knowbase.scales.LOC')
    expect(chip(chipGroup(wrapper, t('knowbase.glance.scale')), scaleLabel).exists()).toBe(true)
    const card = wrapper.find('[data-testid="measure-card"]')
    expect(card.text()).toContain(t('knowbase.phases.PRO'))
    // Measure titles stay as the KNOWBASE gives them.
    expect(card.find('h3 a').text()).toBe('Measure 1')
  })

  it('falls back to the KNOWBASE label for an unknown code', async () => {
    mockApi(
      routes(
        page([
          measure(
            1,
            ref(9, 'XYZ', 'Experimental'),
            [ref(9, 'ZZZ', 'Adaptation')],
            [ref(9, 'GLB', 'Global')],
          ),
          measure(2, TYPE.NBS, [PHASE.PRO], [SCALE.LOC]),
        ]),
      ),
    )
    const { wrapper } = await mountGlance()
    // Known types first, unknown ones after them.
    expect(groupHeadings(wrapper)).toEqual([`${t('knowbase.types.NBS')} (1)`, 'Experimental (1)'])
    expect(chips(phaseGroup(wrapper))).toContain('Adaptation (1)')
    expect(chips(scaleGroup(wrapper))).toContain('Global (1)')
  })

  it('is busy while loading', async () => {
    const pending = deferred<Response>()
    mockApi(routes(() => pending.promise))
    const { wrapper } = await mountGlance()
    const busy = wrapper.find('[aria-busy="true"]')
    expect(busy.exists()).toBe(true)
    expect(busy.find('.sr-only').text()).toBe(t('knowbase.loading'))
    expect(wrapper.findAll('h1')).toHaveLength(1)
    pending.resolve(page()({} as never) as Response)
    await flushPromises()
    expect(wrapper.find('[aria-busy="true"]').exists()).toBe(false)
    expect(cardIds(wrapper)).toHaveLength(7)
  })

  it('keeps one focusable h1 and shows an alert with retry when the KNOWBASE is unavailable', async () => {
    const fetchMock = mockApi(routes(replyError(503, 'knowbase.unavailable')))
    const { wrapper } = await mountGlance()
    const headings = wrapper.findAll('h1')
    expect(headings).toHaveLength(1)
    expect(headings[0]!.attributes('tabindex')).toBe('-1')
    expect(headings[0]!.text()).toBe(t('knowbase.glance.title'))
    const alert = wrapper.find('[role="alert"]')
    expect(alert.text()).toContain(t('knowbase.glance.loadError'))
    expect(phaseGroup(wrapper).exists()).toBe(false)
    const retry = alert.findAll('button').find((b) => b.text().includes(t('knowbase.retry')))
    await retry!.trigger('click')
    await flushPromises()
    expect(callsTo(fetchMock, MEASURES)).toHaveLength(2)
  })

  it('is not a second library: no search box, no pagination', async () => {
    mockApi(routes())
    const { wrapper } = await mountGlance()
    expect(wrapper.find('input').exists()).toBe(false)
    expect(wrapper.find('[role="search"]').exists()).toBe(false)
    expect(wrapper.find('nav[aria-label]').exists()).toBe(false)
    expect(wrapper.find('[data-slot="next"]').exists()).toBe(false)
  })
})

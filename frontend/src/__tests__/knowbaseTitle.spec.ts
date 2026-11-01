import { describe, expect, it } from 'vitest'

import { kbTitle, measureTitle } from '@/utils/knowbase'

/**
 * Measure names are stored in lower case by the KNOWBASE and shown in title case by its own
 * frontend (`toTitleCase` in its MeasureCard.vue): lower-case everything, then capitalise the
 * first letter at the start and after a space or "(". The platform shows them the same way.
 */
describe('measureTitle', () => {
  it.each([
    ['floodplain reconnection', 'Floodplain Reconnection'],
    ['river flow restoration and re-meandering', 'River Flow Restoration And Re-meandering'],
    ['water squares (urban water plazas)', 'Water Squares (Urban Water Plazas)'],
    ['rooftop rainwater storage/retention tanks', 'Rooftop Rainwater Storage/retention Tanks'],
    ['no / low tillage agriculture', 'No / Low Tillage Agriculture'],
    ['dredging, sediment/debris removal', 'Dredging, Sediment/debris Removal'],
    ['Floodplain Reconnection', 'Floodplain Reconnection'],
    ['EARLY WARNING SYSTEMS', 'Early Warning Systems'],
  ])('%s → %s', (stored, shown) => {
    expect(measureTitle(stored)).toBe(shown)
  })

  it('keeps an empty name empty', () => {
    expect(measureTitle('')).toBe('')
  })
})

describe('kbTitle', () => {
  it('title-cases measures only; document names are shown as stored', () => {
    expect(kbTitle('measure', 'early warning systems')).toBe('Early Warning Systems')
    expect(kbTitle('document', 'Law on waters (Official Gazette 70/2006)')).toBe(
      'Law on waters (Official Gazette 70/2006)',
    )
  })
})

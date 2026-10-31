import { describe, expect, it } from 'vitest'
import { createApp, defineComponent, h } from 'vue'

import i18n from '@/i18n'
import { useCountries } from '@/composables/useCountries'

/** Runs the composable inside a mounted component so useI18n works. */
function withCountries<T>(fn: (c: ReturnType<typeof useCountries>) => T): T {
  let result!: T
  const Probe = defineComponent({
    setup() {
      result = fn(useCountries())
      return () => h('div')
    },
  })
  const app = createApp(Probe).use(i18n)
  app.mount(document.createElement('div'))
  app.unmount()
  return result
}

describe('useCountries.countryName', () => {
  it('names ISO codes in the UI locale', () => {
    expect(withCountries((c) => c.countryName('HR'))).toBe('Croatia')
    expect(withCountries((c) => c.countryName('gr'))).toBe('Greece')
  })

  // The KNOWBASE stores Croatia as "CR" (not ISO 3166-1, where CR is Costa Rica).
  it('maps the KNOWBASE country aliases before looking the name up', () => {
    expect(withCountries((c) => c.countryName('CR'))).toBe('Croatia')
  })
})

import { afterEach, beforeEach, vi } from 'vitest'

import { mockApi } from './helpers/api'

// happy-dom does not implement matchMedia fully for Nuxt UI color mode; provide a stable stub.
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  })
}

// No test touches the network: every test starts with a fetch stub (anonymous `GET /auth/me`,
// 404 for anything unmocked). Tests override it with their own `mockApi(...)`/`vi.stubGlobal`.
beforeEach(() => {
  mockApi()
})

afterEach(() => {
  localStorage.clear()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

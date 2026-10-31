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

// happy-dom defines `Node.prototype.nodeName` as `''` and overrides it in each subclass, whereas
// browsers (per the DOM spec) have one getter on Node.prototype. DOMPurify reads nodeName through
// the Node.prototype getter (clobbering protection), so under happy-dom every element looked
// nameless and was stripped. Make the base getter dispatch to the subclass getter, as in a browser.
{
  const base = Object.getOwnPropertyDescriptor(Node.prototype, 'nodeName')!.get!
  Object.defineProperty(Node.prototype, 'nodeName', {
    configurable: true,
    get(this: Node) {
      for (let proto = Object.getPrototypeOf(this); proto && proto !== Node.prototype;) {
        const getter = Object.getOwnPropertyDescriptor(proto, 'nodeName')?.get
        if (getter) return getter.call(this)
        proto = Object.getPrototypeOf(proto)
      }
      return base.call(this)
    },
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

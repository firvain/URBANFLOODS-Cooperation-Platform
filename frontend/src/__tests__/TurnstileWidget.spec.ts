/**
 * Increment 7d: the Turnstile widget renders explicitly with per-instance callbacks, can be reset
 * after a spent token, removes itself on unmount, and loads the Cloudflare script only once. A fake
 * `window.turnstile` stands in for Cloudflare.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import TurnstileWidget from '@/components/auth/TurnstileWidget.vue'
import { TURNSTILE_ONLOAD, TURNSTILE_SCRIPT_SRC } from '@/constants/turnstile'
import { mountWithApp, unmountAll } from './helpers/mount'

const SITE_KEY = 'site-key-123'

type Params = {
  sitekey: string
  language: string
  callback: (token: string) => void
  'expired-callback': () => void
  'error-callback': () => void
}
type Fake = {
  render: ReturnType<typeof vi.fn<(el: HTMLElement, params: Params) => string>>
  reset: ReturnType<typeof vi.fn<(id: string) => void>>
  remove: ReturnType<typeof vi.fn<(id: string) => void>>
}
type TestWindow = Window & { turnstile?: Fake } & Record<string, unknown>

const w = window as unknown as TestWindow

function fakeTurnstile(): Fake {
  let n = 0
  return {
    render: vi.fn<(el: HTMLElement, params: Params) => string>(() => `w${++n}`),
    reset: vi.fn<(id: string) => void>(),
    remove: vi.fn<(id: string) => void>(),
  }
}

function scripts() {
  return document.head.querySelectorAll('script[src^="https://challenges.cloudflare.com/"]')
}

/** happy-dom refuses to load scripts (and fires `error`): record the ones the widget adds. */
function captureScripts(): HTMLScriptElement[] {
  const added: HTMLScriptElement[] = []
  vi.spyOn(document.head, 'appendChild').mockImplementation(<T extends Node>(node: T) => {
    if (node instanceof HTMLScriptElement) added.push(node)
    return node
  })
  return added
}

async function mountWidget() {
  const { wrapper } = await mountWithApp(TurnstileWidget, { props: { token: null } })
  await flushPromises()
  return wrapper as VueWrapper<InstanceType<typeof TurnstileWidget>>
}

const emitted = (wrapper: VueWrapper) =>
  (wrapper.emitted('update:token') ?? []).map(([value]) => value)

beforeEach(() => {
  vi.stubEnv('VITE_TURNSTILE_SITE_KEY', SITE_KEY)
})

afterEach(() => {
  unmountAll()
  delete w.turnstile
  delete w[TURNSTILE_ONLOAD]
  scripts().forEach((s) => s.remove())
})

describe('TurnstileWidget with the script loaded', () => {
  let api: Fake
  beforeEach(() => {
    api = fakeTurnstile()
    w.turnstile = api
  })

  it('renders explicitly with the site key, its own callbacks and the UI language', async () => {
    const wrapper = await mountWidget()

    expect(api.render).toHaveBeenCalledTimes(1)
    const [el, params] = api.render.mock.calls[0]!
    expect(el).toBe(wrapper.element)
    expect(params).toMatchObject({ sitekey: SITE_KEY, language: 'en' })
    expect(params.callback).toBeTypeOf('function')
    expect(params['expired-callback']).toBeTypeOf('function')
    expect(params['error-callback']).toBeTypeOf('function')
    expect(scripts()).toHaveLength(0)
  })

  it('updates v-model from the callback; expiry and errors clear the token', async () => {
    const wrapper = await mountWidget()
    const params = api.render.mock.calls[0]![1]

    params.callback('tok-a')
    params['expired-callback']()
    params.callback('tok-b')
    params['error-callback']()

    expect(emitted(wrapper)).toEqual(['tok-a', null, 'tok-b', null])
  })

  it('reset() clears the token and resets its own widget', async () => {
    const wrapper = await mountWidget()
    api.render.mock.calls[0]![1].callback('tok-a')

    wrapper.vm.reset()

    expect(emitted(wrapper)).toEqual(['tok-a', null])
    expect(api.reset).toHaveBeenCalledWith('w1')
  })

  it('removes its widget on unmount', async () => {
    const wrapper = await mountWidget()
    wrapper.unmount()
    expect(api.remove).toHaveBeenCalledWith('w1')
  })

  it('keeps two instances apart: one unmounting does not break the other', async () => {
    const first = await mountWidget()
    const second = await mountWidget()
    const [, firstParams] = api.render.mock.calls[0]!
    const [, secondParams] = api.render.mock.calls[1]!

    firstParams.callback('tok-first')
    expect(emitted(first)).toEqual(['tok-first'])
    expect(emitted(second)).toEqual([])
    first.unmount()
    secondParams.callback('tok-second')
    second.vm.reset()

    expect(emitted(second)).toEqual(['tok-second', null])
    expect(api.remove).toHaveBeenCalledWith('w1')
    expect(api.remove).not.toHaveBeenCalledWith('w2')
    expect(api.reset).toHaveBeenCalledWith('w2')
  })
})

describe('TurnstileWidget loading the script', () => {
  it('adds one explicit-render script for several widgets and renders them once it loads', async () => {
    const added = captureScripts()
    const first = await mountWidget()
    const second = await mountWidget()
    const gone = await mountWidget()
    gone.unmount()

    expect(added.map((script) => script.getAttribute('src'))).toEqual([TURNSTILE_SCRIPT_SRC])
    expect(added[0]!.async).toBe(true)
    expect(TURNSTILE_SCRIPT_SRC).toContain('render=explicit')
    expect(TURNSTILE_SCRIPT_SRC).toContain(`onload=${TURNSTILE_ONLOAD}`)

    const api = fakeTurnstile()
    w.turnstile = api
    ;(w[TURNSTILE_ONLOAD] as () => void)()
    await flushPromises()

    // The widget unmounted before the script arrived is never rendered.
    expect(api.render.mock.calls.map(([el]) => el)).toEqual([first.element, second.element])
    expect(added).toHaveLength(1)
  })

  it('renders nothing and loads no script without a site key', async () => {
    vi.stubEnv('VITE_TURNSTILE_SITE_KEY', '')
    const api = fakeTurnstile()
    w.turnstile = api

    const wrapper = await mountWidget()
    wrapper.vm.reset()

    expect(wrapper.find('div').exists()).toBe(false)
    expect(api.render).not.toHaveBeenCalled()
    expect(api.reset).not.toHaveBeenCalled()
    delete w.turnstile
    const added = captureScripts()
    await mountWidget()
    expect(added).toHaveLength(0)
    expect(scripts()).toHaveLength(0)
  })
})

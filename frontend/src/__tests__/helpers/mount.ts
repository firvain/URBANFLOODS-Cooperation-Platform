/** Mount a component inside the real app plugins (Pinia, router, i18n, Nuxt UI). */
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import ui from '@nuxt/ui/vue-plugin'
import type { Component } from 'vue'

import i18n from '@/i18n'
import { createAppRouter } from '@/router'
import { useAuthStore } from '@/stores/auth'

const mounted: VueWrapper[] = []

export async function mountWithApp(
  component: Component,
  { path = '/', props = {} }: { path?: string; props?: Record<string, unknown> } = {},
) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()

  const wrapper = mount(component, {
    props,
    attachTo: document.body,
    global: { plugins: [pinia, router, i18n, ui] },
  })
  mounted.push(wrapper)
  await flushPromises()
  return { wrapper, router, auth: useAuthStore() }
}

export function unmountAll() {
  while (mounted.length) mounted.pop()!.unmount()
  document.body.innerHTML = ''
}

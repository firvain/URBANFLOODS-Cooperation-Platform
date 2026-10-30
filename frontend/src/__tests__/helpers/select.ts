/** Drive Nuxt UI select menus (reka-ui comboboxes and selects) in happy-dom. */
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { expect } from 'vitest'

/** The control a `<label>` starting with `labelText` points to (`for` → id). */
export function controlFor(wrapper: VueWrapper, labelText: string): HTMLElement {
  const label = wrapper.findAll('label').find((l) => l.text().startsWith(labelText))
  expect(label, `label ${labelText}`).toBeDefined()
  const el = document.getElementById(label!.attributes('for')!)
  expect(el, `control for ${labelText}`).not.toBeNull()
  return el!
}

/** Open the select labelled `labelText` (keyboard first, click as a fallback). */
export async function openSelect(wrapper: VueWrapper, labelText: string): Promise<void> {
  const el = controlFor(wrapper, labelText)
  el.focus()
  el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await flushPromises()
  if (!document.querySelector('[role="option"]')) {
    el.click()
    await flushPromises()
  }
}

export function option(text: string): HTMLElement {
  const found = Array.from(document.querySelectorAll<HTMLElement>('[role="option"]')).find((o) =>
    o.textContent?.includes(text),
  )
  expect(found, `option ${text}`).toBeDefined()
  return found!
}

/** Click an option of an open `USelectMenu` (combobox). */
export async function clickOption(text: string): Promise<void> {
  option(text).click()
  await flushPromises()
}

/** Choose an option of an open `USelect` with the keyboard. */
export async function enterOption(text: string): Promise<void> {
  const el = option(text)
  el.focus()
  el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await flushPromises()
}

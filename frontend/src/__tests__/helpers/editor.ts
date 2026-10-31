/** Drive `RichTextEditor` (Tiptap) and its dialogs in happy-dom. */
import { DOMWrapper, flushPromises, type VueWrapper } from '@vue/test-utils'
import type { Editor } from '@tiptap/vue-3'
import { expect } from 'vitest'

import RichTextEditor from '@/components/editor/RichTextEditor.vue'
import { mountWithApp } from './mount'

export const LABEL_ID = 'body-label'

/** Mount the editor with v-model wired back into its props, labelled by `#body-label`. */
export async function mountEditor(props: Record<string, unknown> = {}) {
  const label = document.createElement('span')
  label.id = LABEL_ID
  label.textContent = 'Body'
  document.body.appendChild(label)
  const { wrapper } = await mountWithApp(RichTextEditor, {
    props: { modelValue: '', labelId: LABEL_ID, ...props },
  })
  wrapper.setProps({
    'onUpdate:modelValue': (value: string) => wrapper.setProps({ modelValue: value }),
  })
  await flushPromises()
  const editor = (wrapper.vm as unknown as { editor: Editor }).editor
  expect(editor, 'exposed editor').toBeTruthy()
  return { wrapper, editor }
}

/** The last HTML the editor emitted through `update:modelValue`. */
export function lastHtml(wrapper: VueWrapper): string {
  const events = wrapper.emitted<[string]>('update:modelValue') ?? []
  expect(events.length, 'update:modelValue emitted').toBeGreaterThan(0)
  return events.at(-1)![0]
}

/** The contenteditable region. */
export function editable(): HTMLElement {
  const el = document.querySelector<HTMLElement>('[contenteditable]')
  expect(el, 'contenteditable').not.toBeNull()
  return el!
}

/** Paste HTML (and/or files) into the editor as a browser would. */
export async function paste(
  editor: Editor,
  { html, files = [] }: { html?: string; files?: File[] },
) {
  const data = new DataTransfer()
  if (html) data.setData('text/html', html)
  for (const file of files) data.items.add(file)
  editor.view.dom.dispatchEvent(
    new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }),
  )
  await flushPromises()
}

/** A toolbar button by its accessible name. */
export function toolButton(name: string): HTMLButtonElement {
  const el = document.querySelector<HTMLButtonElement>(
    `[role="toolbar"] button[aria-label="${name}"]`,
  )
  expect(el, `toolbar button ${name}`).not.toBeNull()
  return el!
}

/** The open dialog (Nuxt UI modals are teleported to <body>). */
export function dialog(): HTMLElement {
  const el = document.querySelector<HTMLElement>('[role="dialog"]')
  expect(el, 'dialog').not.toBeNull()
  return el!
}

/** The control a `<label>` inside `root` points to. */
export function field(root: HTMLElement, labelText: string): DOMWrapper<HTMLInputElement> {
  const label = Array.from(root.querySelectorAll('label')).find((l) =>
    l.textContent?.trim().startsWith(labelText),
  )
  expect(label, `label ${labelText}`).toBeDefined()
  const el = document.getElementById(label!.htmlFor) as HTMLInputElement | null
  expect(el, `control for ${labelText}`).not.toBeNull()
  return new DOMWrapper(el!)
}

export function buttonIn(root: HTMLElement, text: string): HTMLButtonElement {
  const el = Array.from(root.querySelectorAll('button')).find(
    (b) => b.textContent?.trim() === text || b.getAttribute('aria-label') === text,
  )
  expect(el, `button ${text}`).toBeDefined()
  return el!
}

/** Choose `file` in a file input (happy-dom lets tests assign `files`). */
export async function chooseFile(input: HTMLInputElement, file: File) {
  const data = new DataTransfer()
  data.items.add(file)
  input.files = data.files
  input.dispatchEvent(new Event('change', { bubbles: true }))
  await flushPromises()
}

export function pngFile(name = 'street.png', type = 'image/png'): File {
  return new File([new Uint8Array([137, 80, 78, 71])], name, { type })
}

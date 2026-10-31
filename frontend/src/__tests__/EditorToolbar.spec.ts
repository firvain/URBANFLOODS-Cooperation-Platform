import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import EditorToolbar from '@/components/editor/EditorToolbar.vue'
import type { ToolbarItem } from '@/components/editor/useRichEditor'
import { lastHtml, mountEditor, toolButton } from './helpers/editor'
import { mountWithApp, unmountAll } from './helpers/mount'

afterEach(unmountAll)

const ITEMS: ToolbarItem[] = [
  { action: 'bold', label: 'Bold', icon: 'i-lucide-bold', toggle: true, active: true },
  { action: 'italic', label: 'Italic', icon: 'i-lucide-italic', toggle: true, active: false },
  { action: 'undo', label: 'Undo', icon: 'i-lucide-undo-2', disabled: true },
  { action: 'image', label: 'Insert image', icon: 'i-lucide-image-plus' },
]

async function mountToolbar(items = ITEMS) {
  const { wrapper } = await mountWithApp(EditorToolbar, { props: { items, label: 'Formatting' } })
  const buttons = () =>
    Array.from(document.querySelectorAll<HTMLButtonElement>('[role="toolbar"] button'))
  return { wrapper, buttons }
}

function key(el: HTMLElement, name: string) {
  el.dispatchEvent(new KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true }))
}

describe('EditorToolbar', () => {
  it('is a labelled toolbar of real buttons with accessible names', async () => {
    const { buttons } = await mountToolbar()
    const toolbar = document.querySelector('[role="toolbar"]')!
    expect(toolbar.getAttribute('aria-label')).toBe('Formatting')
    expect(buttons()).toHaveLength(4)
    for (const button of buttons()) {
      expect(button.getAttribute('type')).toBe('button')
      expect(button.getAttribute('aria-label')).toBeTruthy()
      // The icon is decorative; the name is also in a visually hidden span.
      expect(button.querySelector('.sr-only')?.textContent).toBe(button.getAttribute('aria-label'))
    }
  })

  it('exposes aria-pressed on toggles only', async () => {
    const { buttons } = await mountToolbar()
    const [bold, italic, undo, image] = buttons()
    expect(bold!.getAttribute('aria-pressed')).toBe('true')
    expect(italic!.getAttribute('aria-pressed')).toBe('false')
    expect(undo!.hasAttribute('aria-pressed')).toBe(false)
    expect(image!.hasAttribute('aria-pressed')).toBe(false)
    expect(undo!.disabled).toBe(true)
  })

  it('has one tab stop and moves focus with the arrow keys, Home and End (skipping disabled)', async () => {
    const { buttons } = await mountToolbar()
    const [bold, italic, , image] = buttons()
    expect(buttons().map((b) => b.tabIndex)).toEqual([0, -1, -1, -1])

    bold!.focus()
    key(bold!, 'ArrowRight')
    await flushPromises()
    expect(document.activeElement).toBe(italic)
    expect(italic!.tabIndex).toBe(0)
    expect(bold!.tabIndex).toBe(-1)

    key(italic!, 'ArrowRight')
    await flushPromises()
    expect(document.activeElement).toBe(image)

    key(image!, 'ArrowRight')
    await flushPromises()
    expect(document.activeElement).toBe(bold)

    key(bold!, 'ArrowLeft')
    await flushPromises()
    expect(document.activeElement).toBe(image)

    key(image!, 'Home')
    await flushPromises()
    expect(document.activeElement).toBe(bold)

    key(bold!, 'End')
    await flushPromises()
    expect(document.activeElement).toBe(image)
  })

  it('activates a button with Enter, Space and click', async () => {
    const { wrapper, buttons } = await mountToolbar()
    const [bold, italic, , image] = buttons()
    key(bold!, 'Enter')
    key(italic!, ' ')
    image!.click()
    await flushPromises()
    expect(wrapper.emitted('action')).toEqual([['bold'], ['italic'], ['image']])
  })

  it('reflects the editor state: Bold becomes pressed after applying bold', async () => {
    const { editor } = await mountEditor({ modelValue: '<p>Hello</p>' })
    const bold = toolButton('Bold')
    expect(bold.getAttribute('aria-pressed')).toBe('false')
    editor.commands.selectAll()
    bold.click()
    await flushPromises()
    expect(editor.getHTML()).toBe('<p><strong>Hello</strong></p>')
    expect(toolButton('Bold').getAttribute('aria-pressed')).toBe('true')
    expect(toolButton('Italic').getAttribute('aria-pressed')).toBe('false')
  })

  it('offers every formatting command of the editor', async () => {
    await mountEditor()
    for (const name of [
      'Bold',
      'Italic',
      'Underline',
      'Strikethrough',
      'Heading',
      'Subheading',
      'Bulleted list',
      'Numbered list',
      'Quote',
      'Code block',
      'Link',
      'Insert image',
      'Undo',
      'Redo',
    ]) {
      expect(toolButton(name)).toBeTruthy()
    }
  })

  it('toggles a heading from the toolbar', async () => {
    const { wrapper, editor } = await mountEditor({ modelValue: '<p>Title</p>' })
    editor.commands.focus()
    toolButton('Heading').click()
    await flushPromises()
    expect(lastHtml(wrapper)).toBe('<h2>Title</h2>')
    expect(toolButton('Heading').getAttribute('aria-pressed')).toBe('true')
  })
})

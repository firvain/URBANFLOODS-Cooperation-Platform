import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import { EDITOR_ALLOWED_TAGS } from '@/utils/sanitize'
import {
  LABEL_ID,
  buttonIn,
  dialog,
  editable,
  field,
  lastHtml,
  mountEditor,
  paste,
  toolButton,
} from './helpers/editor'
import { unmountAll } from './helpers/mount'

afterEach(unmountAll)

function tagsIn(html: string): string[] {
  const div = document.createElement('div')
  div.innerHTML = html
  return [...new Set(Array.from(div.querySelectorAll('*'), (el) => el.tagName.toLowerCase()))]
}

describe('RichTextEditor', () => {
  it('renders the initial HTML in a labelled multi-line textbox', async () => {
    const { editor } = await mountEditor({ modelValue: '<p>Hello <strong>world</strong></p>' })
    expect(editor.getHTML()).toBe('<p>Hello <strong>world</strong></p>')
    const box = editable()
    expect(box.getAttribute('role')).toBe('textbox')
    expect(box.getAttribute('aria-multiline')).toBe('true')
    expect(box.getAttribute('aria-labelledby')).toBe(LABEL_ID)
    expect(box.textContent).toContain('Hello world')
  })

  it('emits the updated HTML on input', async () => {
    const { wrapper, editor } = await mountEditor({ modelValue: '<p>Hello</p>' })
    editor.chain().focus().selectAll().toggleBold().run()
    await flushPromises()
    expect(lastHtml(wrapper)).toBe('<p><strong>Hello</strong></p>')
  })

  it('emits only backend-allowed tags for a bold + list sample', async () => {
    const { wrapper, editor } = await mountEditor({ modelValue: '<p>Intro</p>' })
    editor.chain().focus().selectAll().toggleBold().run()
    editor.chain().focus('end').splitBlock().toggleBulletList().insertContent('first').run()
    await flushPromises()
    const html = lastHtml(wrapper)
    expect(html).toContain('<strong>Intro</strong>')
    expect(html).toContain('<ul>')
    for (const tag of tagsIn(html)) expect(EDITOR_ALLOWED_TAGS).toContain(tag)
  })

  it('removes a pasted <script> and <div onclick>, keeping the text', async () => {
    const { wrapper, editor } = await mountEditor()
    editor.commands.focus()
    await paste(editor, {
      html: '<p>Safe</p><script>alert(1)</script><div onclick="alert(1)">Clicked</div>',
    })
    const html = lastHtml(wrapper)
    expect(html).not.toMatch(/script|onclick|<div/)
    expect(html).toContain('Safe')
    expect(html).toContain('Clicked')
  })

  it('explains when a pasted image from another website is dropped (7n)', async () => {
    const { wrapper, editor } = await mountEditor()
    editor.commands.focus()
    expect(document.body.textContent).not.toContain('Images from other websites')

    await paste(editor, {
      html: '<p>Report</p><img src="https://elsewhere.example/flood.png" alt="Flood">',
    })

    expect(lastHtml(wrapper)).not.toContain('<img')
    const notice = document.querySelector('[role="status"]')
    expect(notice?.textContent).toContain(
      'Images from other websites are not allowed. Upload the image instead.',
    )
  })

  it('shows no image notice when pasted images are allowed', async () => {
    const { wrapper, editor } = await mountEditor()
    editor.commands.focus()

    await paste(editor, {
      html: '<p>Report</p><img src="/static/uploads/2026/10/a.webp" alt="Flood">',
    })

    expect(lastHtml(wrapper)).toContain('<img src="/static/uploads/2026/10/a.webp"')
    expect(document.body.textContent).not.toContain('Images from other websites')
  })

  const EXTERNAL = '<p>Old</p><img src="https://elsewhere.example/flood.png" alt="Flood">'
  const NOTICE = 'Images from other websites are not allowed. Upload the image instead.'
  const statusText = () => document.querySelector('[role="status"]')?.textContent?.trim() ?? ''
  const statusNode = () => document.querySelector('[role="status"] > *')

  it('explains when loaded content loses an image from another website', async () => {
    const { editor } = await mountEditor({ modelValue: EXTERNAL })

    expect(editor.getHTML()).not.toContain('<img')
    expect(statusText()).toBe(NOTICE)
  })

  it('explains when content set by the parent loses an image', async () => {
    const { wrapper, editor } = await mountEditor({ modelValue: '<p>Loading</p>' })
    expect(statusText()).toBe('')

    await wrapper.setProps({ modelValue: EXTERNAL })
    await flushPromises()

    expect(editor.getHTML()).not.toContain('<img')
    expect(statusText()).toBe(NOTICE)
  })

  it('clears the notice on a clean paste after a dropped one', async () => {
    const { editor } = await mountEditor()
    editor.commands.focus()
    await paste(editor, { html: EXTERNAL })
    expect(statusText()).toBe(NOTICE)

    await paste(editor, { html: '<p>Clean text</p>' })

    expect(statusText()).toBe('')
  })

  it('re-announces the notice when another paste drops an image', async () => {
    const { editor } = await mountEditor()
    editor.commands.focus()
    await paste(editor, { html: EXTERNAL })
    const first = statusNode()
    expect(first?.textContent?.trim()).toBe(NOTICE)

    await paste(editor, { html: EXTERNAL })

    const second = statusNode()
    expect(second?.textContent?.trim()).toBe(NOTICE)
    expect(second).not.toBe(first)
  })

  it('sanitises the initial value too', async () => {
    const { editor } = await mountEditor({
      modelValue: '<p onclick="x()">Body</p><img src="x" onerror="alert(1)" alt="x">',
    })
    expect(editor.getHTML()).toBe('<p>Body</p>')
  })

  it('turns h1 into h2 (headings are limited to levels 2-4)', async () => {
    const initial = await mountEditor({ modelValue: '<h1>Initial</h1>' })
    expect(initial.editor.getHTML()).toBe('<h2>Initial</h2>')
    unmountAll()

    const { wrapper, editor } = await mountEditor()
    editor.commands.focus()
    await paste(editor, { html: '<p>Intro</p><h1>Pasted</h1><h6>Small</h6>' })
    const html = lastHtml(wrapper)
    expect(html).toContain('<h2>Pasted</h2>')
    expect(html).toContain('<h4>Small</h4>')
    expect(html).not.toMatch(/<h[156]/)
  })

  it('emits an empty string when the editor is emptied', async () => {
    const { wrapper, editor } = await mountEditor({ modelValue: '<p>Text</p>' })
    editor.chain().focus().selectAll().deleteSelection().run()
    await flushPromises()
    expect(lastHtml(wrapper)).toBe('')
  })

  it('follows modelValue changes from the parent without echoing them', async () => {
    const { wrapper, editor } = await mountEditor({ modelValue: '<p>One</p>' })
    await wrapper.setProps({ modelValue: '<p>Two</p>' })
    expect(editor.getHTML()).toBe('<p>Two</p>')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('emits blur and exposes focus()', async () => {
    const { wrapper, editor } = await mountEditor({ modelValue: '<p>Text</p>' })
    ;(wrapper.vm as unknown as { focus: () => void }).focus()
    await flushPromises()
    expect(editor.isFocused).toBe(true)
    editor.view.dom.dispatchEvent(new FocusEvent('blur'))
    editor.commands.blur()
    await flushPromises()
    expect(wrapper.emitted('blur')).toBeTruthy()
  })

  it('is read-only and its toolbar disabled when disabled', async () => {
    const { editor } = await mountEditor({ modelValue: '<p>Text</p>', disabled: true })
    expect(editor.isEditable).toBe(false)
    expect(editable().getAttribute('contenteditable')).toBe('false')
    expect(toolButton('Bold').disabled).toBe(true)
  })

  describe('links', () => {
    async function linkWith(url: string, newTab: boolean) {
      const mounted = await mountEditor({ modelValue: '<p>Read the report</p>' })
      mounted.editor.chain().focus().setTextSelection({ from: 10, to: 16 }).run()
      toolButton('Link').click()
      await flushPromises()
      const box = dialog()
      await field(box, 'Web address').setValue(url)
      if (newTab) {
        const checkbox = box.querySelector<HTMLElement>('[role="checkbox"], input[type="checkbox"]')
        checkbox!.click()
        await flushPromises()
      }
      buttonIn(box, 'Apply').click()
      await flushPromises()
      return { ...mounted, box }
    }

    it('applies an https link without a target', async () => {
      const { wrapper } = await linkWith('https://example.org/report', false)
      expect(lastHtml(wrapper)).toBe(
        '<p>Read the <a href="https://example.org/report">report</a></p>',
      )
      expect(document.querySelector('[role="dialog"]')).toBeNull()
    })

    it('adds rel="noopener noreferrer" to links opening in a new tab', async () => {
      const { wrapper } = await linkWith('https://example.org/report', true)
      const html = lastHtml(wrapper)
      expect(html).toContain('target="_blank"')
      expect(html).toContain('rel="noopener noreferrer"')
    })

    it('accepts mailto: links', async () => {
      const { wrapper } = await linkWith('mailto:info@example.org', false)
      expect(lastHtml(wrapper)).toContain('href="mailto:info@example.org"')
    })

    it('rejects a javascript: link with an inline error', async () => {
      const { wrapper, box } = await linkWith('javascript:alert(1)', false)
      expect(document.querySelector('[role="dialog"]')).not.toBeNull()
      const input = field(box, 'Web address')
      expect(input.attributes('aria-invalid')).toBe('true')
      const describedBy = input.attributes('aria-describedby') ?? ''
      const messages = describedBy
        .split(' ')
        .map((id) => document.getElementById(id)?.textContent ?? '')
        .join(' ')
      expect(messages).toMatch(/https:\/\//)
      expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    })
  })

  describe('maxLength', () => {
    it('shows a character counter', async () => {
      await mountEditor({ modelValue: '<p>Hello</p>', maxLength: 10 })
      expect(document.body.textContent).toContain('5 / 10')
      expect(editable().getAttribute('aria-invalid')).toBeNull()
    })

    it('flags the over-limit state', async () => {
      const { wrapper, editor } = await mountEditor({ modelValue: '<p>Hello</p>', maxLength: 10 })
      editor.chain().focus('end').insertContent(' wide world').run()
      await flushPromises()
      expect(document.body.textContent).toContain('16 / 10')
      expect(editable().getAttribute('aria-invalid')).toBe('true')
      expect(document.body.textContent).toContain('6 characters too long')
      expect((wrapper.vm as unknown as { isOverLimit: boolean }).isOverLimit).toBe(true)
      expect(editable().getAttribute('aria-describedby')).toBeTruthy()
    })
  })

  it('compact offers the comment subset: no headings, code blocks or images', async () => {
    await mountEditor({ compact: true, maxLength: 10_000 })
    const labels = Array.from(document.querySelectorAll('[role="toolbar"] button'), (b) =>
      b.getAttribute('aria-label'),
    )
    expect(labels).toContain('Bold')
    expect(labels).toContain('Link')
    expect(labels).toContain('Quote')
    for (const missing of ['Heading', 'Subheading', 'Code block', 'Insert image']) {
      expect(labels).not.toContain(missing)
    }
    expect(document.body.textContent).toContain('0 / 10000')
  })
})

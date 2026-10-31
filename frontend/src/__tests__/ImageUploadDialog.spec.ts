import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { Slice } from '@tiptap/pm/model'

import ImageUploadDialog from '@/components/editor/ImageUploadDialog.vue'
import { callsTo, mockApi, reply, replyError } from './helpers/api'
import {
  buttonIn,
  chooseFile,
  dialog,
  field,
  lastHtml,
  mountEditor,
  paste,
  pngFile,
  toolButton,
} from './helpers/editor'
import { mountWithApp, unmountAll } from './helpers/mount'

afterEach(unmountAll)

const UPLOAD = 'POST /api/v1/uploads/images/'

const UPLOADED = {
  id: 7,
  url: '/static/uploads/2026/10/abc.webp',
  thumb_url: '/static/uploads/2026/10/abc_thumb.webp',
  width: 1200,
  height: 800,
  size_bytes: 52_000,
  mime: 'image/webp',
  alt_text: 'Flooded street in Kozani',
  created_at: '2026-10-31T10:00:00Z',
}

async function mountDialog(props: Record<string, unknown> = {}) {
  const { wrapper } = await mountWithApp(ImageUploadDialog, { props: { open: true, ...props } })
  await flushPromises()
  return { wrapper, box: dialog() }
}

function fileInput(box: HTMLElement): HTMLInputElement {
  return field(box, 'Image file').element
}

function submit(box: HTMLElement): HTMLButtonElement {
  return buttonIn(box, 'Upload and insert')
}

describe('ImageUploadDialog', () => {
  it('accepts only JPEG, PNG and WebP files', async () => {
    const { box } = await mountDialog()
    expect(fileInput(box).accept).toBe('image/jpeg,image/png,image/webp')
  })

  it('keeps upload disabled until a file and non-blank alt text are given', async () => {
    const { box } = await mountDialog()
    expect(submit(box).disabled).toBe(true)
    await chooseFile(fileInput(box), pngFile())
    expect(submit(box).disabled).toBe(true)
    await field(box, 'Alternative text').setValue('   ')
    expect(submit(box).disabled).toBe(true)
    await field(box, 'Alternative text').setValue('Flooded street')
    expect(submit(box).disabled).toBe(false)
    expect(field(box, 'Alternative text').attributes('required')).toBeDefined()
  })

  it('shows a preview of the chosen file', async () => {
    const { box } = await mountDialog()
    await chooseFile(fileInput(box), pngFile())
    const preview = box.querySelector('img')
    expect(preview?.getAttribute('src')).toMatch(/^blob:/)
  })

  it('rejects other file types on the client', async () => {
    const fetchMock = mockApi()
    const { box } = await mountDialog()
    await chooseFile(fileInput(box), pngFile('anim.gif', 'image/gif'))
    await field(box, 'Alternative text').setValue('Animation')
    expect(box.textContent).toContain('Choose a JPEG, PNG or WebP image.')
    expect(submit(box).disabled).toBe(true)
    expect(callsTo(fetchMock, UPLOAD)).toHaveLength(0)
  })

  it('uploads the file with the trimmed alt text and kind, then emits the image', async () => {
    const fetchMock = mockApi({ [UPLOAD]: reply(201, UPLOADED) })
    const { wrapper, box } = await mountDialog({ kind: 'cover' })
    await chooseFile(fileInput(box), pngFile())
    await field(box, 'Alternative text').setValue('  Flooded street in Kozani ')
    submit(box).click()
    await flushPromises()

    const [call] = callsTo(fetchMock, UPLOAD)
    const body = call!.body as FormData
    expect(body).toBeInstanceOf(FormData)
    expect((body.get('file') as File).name).toBe('street.png')
    expect(body.get('alt_text')).toBe('Flooded street in Kozani')
    expect(body.get('kind')).toBe('cover')
    expect(wrapper.emitted('uploaded')?.[0]?.[0]).toMatchObject({
      src: UPLOADED.url,
      alt: 'Flooded street in Kozani',
      width: 1200,
      height: 800,
    })
    expect(wrapper.emitted('update:open')?.at(-1)).toEqual([false])
  })

  it.each([
    [413, 'uploads.too_large', 'The image is too large'],
    [415, 'uploads.unsupported_type', 'Only JPEG, PNG and WebP images'],
    [409, 'uploads.daily_limit', 'upload limit'],
  ])('maps a %s %s error to a readable message', async (status, code, text) => {
    mockApi({ [UPLOAD]: replyError(status, code) })
    const { wrapper, box } = await mountDialog()
    await chooseFile(fileInput(box), pngFile())
    await field(box, 'Alternative text').setValue('Street')
    submit(box).click()
    await flushPromises()
    expect(box.querySelector('[role="alert"]')?.textContent).toContain(text)
    expect(wrapper.emitted('uploaded')).toBeUndefined()
    expect(document.querySelector('[role="dialog"]')).not.toBeNull()
  })

  it('shows an alt text field error from the server on the field', async () => {
    mockApi({ [UPLOAD]: replyError(422, 'validation.failed', { alt_text: 'required' }) })
    const { box } = await mountDialog()
    await chooseFile(fileInput(box), pngFile())
    await field(box, 'Alternative text').setValue('x')
    submit(box).click()
    await flushPromises()
    expect(field(box, 'Alternative text').attributes('aria-invalid')).toBe('true')
    expect(box.textContent).toContain('This field is required.')
  })
})

describe('ImageUploadDialog in the editor', () => {
  it('inserts the uploaded image with its alt text, src and size', async () => {
    mockApi({ [UPLOAD]: reply(201, UPLOADED) })
    const { wrapper, editor } = await mountEditor({ modelValue: '<p>Before</p>' })
    editor.commands.focus('end')
    toolButton('Insert image').click()
    await flushPromises()
    const box = dialog()
    await chooseFile(fileInput(box), pngFile())
    await field(box, 'Alternative text').setValue('Flooded street in Kozani')
    submit(box).click()
    await flushPromises()

    const html = lastHtml(wrapper)
    expect(html).toContain(
      '<img src="/static/uploads/2026/10/abc.webp" alt="Flooded street in Kozani" width="1200" height="800">',
    )
    expect(document.querySelector('[role="dialog"]')).toBeNull()
  })

  it('inserts nothing when cancelled', async () => {
    const fetchMock = mockApi()
    const { wrapper } = await mountEditor({ modelValue: '<p>Before</p>' })
    toolButton('Insert image').click()
    await flushPromises()
    const box = dialog()
    await chooseFile(fileInput(box), pngFile())
    await field(box, 'Alternative text').setValue('Street')
    buttonIn(box, 'Cancel').click()
    await flushPromises()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(callsTo(fetchMock, UPLOAD)).toHaveLength(0)
  })

  it('opens the dialog pre-filled when an image is pasted (alt text still required)', async () => {
    const { wrapper, editor } = await mountEditor({ modelValue: '<p>Before</p>' })
    editor.commands.focus('end')
    await paste(editor, { files: [pngFile('pasted.png')] })
    const box = dialog()
    expect(box.querySelector('img')?.getAttribute('src')).toMatch(/^blob:/)
    expect(box.textContent).toContain('pasted.png')
    expect(submit(box).disabled).toBe(true)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('opens the dialog pre-filled when an image is dropped', async () => {
    const { editor } = await mountEditor({ modelValue: '<p>Before</p>' })
    const data = new DataTransfer()
    data.items.add(pngFile('dropped.png'))
    const event = new DragEvent('drop', { cancelable: true })
    Object.defineProperty(event, 'dataTransfer', { value: data }) // happy-dom ignores the init
    // ProseMirror resolves drop coordinates through layout APIs happy-dom lacks, so call the
    // editor's drop handler directly, as ProseMirror does for an external drop.
    const handled = editor.view.someProp('handleDrop', (handle) =>
      handle(editor.view, event, Slice.empty, false),
    )
    await flushPromises()
    expect(handled).toBe(true)
    expect(dialog().textContent).toContain('dropped.png')
    expect(submit(dialog()).disabled).toBe(true)
  })
})

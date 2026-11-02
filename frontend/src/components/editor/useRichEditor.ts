/**
 * The Tiptap instance behind `RichTextEditor.vue`, wrapped so components talk to a small API
 * (toolbar state, commands, links, images) and views can mock this module instead of mounting
 * Tiptap.
 *
 * Output guarantee: everything that enters the editor (initial value, pasted HTML) and everything
 * it emits goes through `normalizeHtml`, the client copy of the backend allow-list, so the
 * emitted HTML is stored unchanged by the backend.
 */
import { computed, ref, watch, type ComputedRef, type ShallowRef } from 'vue'
import { useEditor, type Editor } from '@tiptap/vue-3'
import type { ChainedCommands, Editor as CoreEditor } from '@tiptap/core'
import type { EditorView } from '@tiptap/pm/view'
import StarterKit from '@tiptap/starter-kit'
import Image from '@tiptap/extension-image'
import Placeholder from '@tiptap/extension-placeholder'

import { normalizeHtml } from '@/utils/sanitize'

export type ToolbarAction =
  | 'bold'
  | 'italic'
  | 'underline'
  | 'strike'
  | 'heading2'
  | 'heading3'
  | 'bulletList'
  | 'orderedList'
  | 'blockquote'
  | 'codeBlock'
  | 'link'
  | 'image'
  | 'undo'
  | 'redo'

/** One toolbar button. `toggle` buttons expose `aria-pressed` (= `active`). */
export interface ToolbarItem {
  action: ToolbarAction
  label: string
  /** A bundled Lucide icon (`i-lucide-*`). */
  icon: string
  toggle?: boolean
  active?: boolean
  disabled?: boolean
  /** Starts a new visual group. */
  groupStart?: boolean
}

export interface LinkInput {
  href: string
  newTab: boolean
}

export interface ImageInput {
  src: string
  alt: string
  width?: number | null
  height?: number | null
}

export interface RichEditorOptions {
  /** Initial HTML (normalised before it is loaded). */
  content: string
  placeholder: () => string
  editable: () => boolean
  /**
   * Attributes of the editable element (ARIA wiring), given the current text length; re-applied
   * when they change.
   */
  attributes: (textLength: number) => Record<string, string>
  /** The normalised HTML after every change (`''` when the editor is empty). */
  onChange: (html: string) => void
  onBlur?: () => void
  /** An image file was pasted or dropped. */
  onImageFile?: (file: File) => void
  /**
   * Called after every load (initial content, `setContent`) and every paste or drop of HTML,
   * with the number of images dropped for their source (other websites; 0 when none).
   */
  onImagesChecked?: (dropped: number) => void
}

const LINK_PATTERN = /^(?:https?:\/\/[^\s/?#]+[^\s]*|mailto:[^\s@]+@[^\s@]+)$/i

/** The trimmed URL when it is an absolute http(s) or a mailto: link, else `null`. */
export function validLinkUrl(raw: string): string | null {
  const url = raw.trim()
  if (!LINK_PATTERN.test(url)) return null
  if (/^https?:/i.test(url)) {
    try {
      new URL(url)
    } catch {
      return null
    }
  }
  return url
}

/** Link rules for pasted/auto-linked URLs: the schemes the backend keeps. */
const isAllowedUri = (url: string) => /^(?:https?:|mailto:)/i.test(url.trim())

type Command = (chain: ChainedCommands) => ChainedCommands

const COMMANDS: Partial<Record<ToolbarAction, Command>> = {
  bold: (c) => c.toggleBold(),
  italic: (c) => c.toggleItalic(),
  underline: (c) => c.toggleUnderline(),
  strike: (c) => c.toggleStrike(),
  heading2: (c) => c.toggleHeading({ level: 2 }),
  heading3: (c) => c.toggleHeading({ level: 3 }),
  bulletList: (c) => c.toggleBulletList(),
  orderedList: (c) => c.toggleOrderedList(),
  blockquote: (c) => c.toggleBlockquote(),
  codeBlock: (c) => c.toggleCodeBlock(),
  undo: (c) => c.undo(),
  redo: (c) => c.redo(),
}

const ACTIVE: Partial<Record<ToolbarAction, [string, Record<string, unknown>?]>> = {
  bold: ['bold'],
  italic: ['italic'],
  underline: ['underline'],
  strike: ['strike'],
  heading2: ['heading', { level: 2 }],
  heading3: ['heading', { level: 3 }],
  bulletList: ['bulletList'],
  orderedList: ['orderedList'],
  blockquote: ['blockquote'],
  codeBlock: ['codeBlock'],
  link: ['link'],
}

/** Normalised HTML of the document; Tiptap's trailing empty paragraph is not content. */
function serialize(editor: CoreEditor): string {
  if (editor.isEmpty) return ''
  return normalizeHtml(editor.getHTML()).replace(/(?:<p><\/p>)+$/, '')
}

function imageFile(files: FileList | null | undefined): File | null {
  return Array.from(files ?? []).find((file) => file.type.startsWith('image/')) ?? null
}

export interface RichEditor {
  editor: ShallowRef<Editor | undefined>
  isActive: (action: ToolbarAction) => boolean
  isDisabled: (action: ToolbarAction) => boolean
  run: (action: ToolbarAction) => void
  /** The link at the cursor, if any. */
  currentLink: () => LinkInput | null
  setLink: (link: LinkInput) => void
  unsetLink: () => void
  insertImage: (image: ImageInput) => void
  /** Replace the content without emitting a change (parent-driven `v-model` updates). */
  setContent: (html: string) => void
  /** Characters of text (not markup). */
  textLength: ComputedRef<number>
  focus: () => void
}

export function useRichEditor(options: RichEditorOptions): RichEditor {
  /** Bumped on every transaction/focus change, so state read through it is reactive. */
  const version = ref(0)
  const bump = () => version.value++
  // Assigned right below (`useEditor` already asks for the attributes); `onCreate` bumps
  // `version`, so the computed properties re-read it once the editor exists.
  // eslint-disable-next-line prefer-const
  let editor: ShallowRef<Editor | undefined> | undefined

  const textLength = computed(() => {
    void version.value
    return editor?.value?.state.doc.textContent.length ?? 0
  })
  const attributes = () => options.attributes(textLength.value)

  /** Incoming HTML normalised, reporting how many images it lost for their source. */
  function checkedHtml(html: string): string {
    let dropped = 0
    const normalized = normalizeHtml(html, { onImageDropped: () => dropped++ })
    options.onImagesChecked?.(dropped)
    return normalized
  }

  const editorProps = () => ({
    attributes: attributes(),
    transformPastedHTML: (html: string) => checkedHtml(html),
    handlePaste: (_view: EditorView, event: ClipboardEvent) => {
      const file = imageFile(event.clipboardData?.files)
      if (!file || !options.onImageFile) return false
      event.preventDefault()
      options.onImageFile(file)
      return true
    },
    handleDrop: (view: EditorView, event: DragEvent, _slice: unknown, moved: boolean) => {
      const file = moved ? null : imageFile(event.dataTransfer?.files)
      if (!file || !options.onImageFile) return false
      event.preventDefault()
      const target = view.posAtCoords({ left: event.clientX, top: event.clientY })
      if (target) editor?.value?.commands.setTextSelection(target.pos)
      options.onImageFile(file)
      return true
    },
  })

  editor = useEditor({
    content: checkedHtml(options.content),
    editable: options.editable(),
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3, 4] },
        codeBlock: { languageClassPrefix: 'language-' },
        link: {
          openOnClick: false,
          autolink: true,
          defaultProtocol: 'https',
          // No target/rel unless the author asks for a new tab (then rel is set with it).
          HTMLAttributes: { target: null, rel: null, class: null },
          isAllowedUri,
        },
      }),
      Image.configure({ inline: false, allowBase64: false }),
      Placeholder.configure({ placeholder: () => options.placeholder() }),
    ],
    editorProps: editorProps(),
    onUpdate: ({ editor: e }) => options.onChange(serialize(e)),
    onCreate: bump,
    onTransaction: bump,
    onFocus: bump,
    onBlur: () => {
      bump()
      options.onBlur?.()
    },
  })
  const instance = editor

  watch(attributes, () => instance.value?.setOptions({ editorProps: editorProps() }), {
    deep: true,
  })
  watch(options.editable, (editable) => {
    instance.value?.setEditable(editable, false)
    bump()
  })

  function chain(): ChainedCommands | null {
    return instance.value ? instance.value.chain().focus() : null
  }

  function isActive(action: ToolbarAction): boolean {
    void version.value
    const spec = ACTIVE[action]
    return !!(spec && instance.value?.isActive(...spec))
  }

  function isDisabled(action: ToolbarAction): boolean {
    void version.value
    const e = instance.value
    if (!e || !e.isEditable) return true
    const command = COMMANDS[action]
    return command ? !command(e.can().chain()).run() : false
  }

  function run(action: ToolbarAction) {
    const command = COMMANDS[action]
    const c = chain()
    if (command && c) command(c).run()
  }

  function currentLink(): LinkInput | null {
    const e = instance.value
    if (!e?.isActive('link')) return null
    const attrs = e.getAttributes('link')
    return { href: String(attrs.href ?? ''), newTab: attrs.target === '_blank' }
  }

  function setLink({ href, newTab }: LinkInput) {
    const e = instance.value
    const c = chain()
    if (!e || !c) return
    const attrs = newTab
      ? { href, target: '_blank', rel: 'noopener noreferrer' }
      : { href, target: null, rel: null }
    if (e.state.selection.empty && !e.isActive('link')) {
      // Nothing selected: insert the address itself as the link text.
      c.insertContent({ type: 'text', text: href, marks: [{ type: 'link', attrs }] }).run()
    } else {
      c.extendMarkRange('link').setLink(attrs).run()
    }
  }

  function unsetLink() {
    chain()?.extendMarkRange('link').unsetLink().run()
  }

  function insertImage({ src, alt, width, height }: ImageInput) {
    chain()
      ?.setImage({ src, alt, width: width ?? undefined, height: height ?? undefined })
      .run()
  }

  function setContent(html: string) {
    instance.value?.commands.setContent(checkedHtml(html), { emitUpdate: false })
  }

  return {
    editor: instance,
    isActive,
    isDisabled,
    run,
    currentLink,
    setLink,
    unsetLink,
    insertImage,
    setContent,
    textLength,
    focus: () => instance.value?.commands.focus(),
  }
}

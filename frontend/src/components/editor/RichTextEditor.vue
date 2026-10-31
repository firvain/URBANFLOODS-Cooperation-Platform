<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { EditorContent } from '@tiptap/vue-3'

import type { UploadKind } from '@/services/uploads'
import EditorToolbar from './EditorToolbar.vue'
import ImageUploadDialog from './ImageUploadDialog.vue'
import LinkDialog from './LinkDialog.vue'
import {
  useRichEditor,
  type ImageInput,
  type LinkInput,
  type ToolbarAction,
  type ToolbarItem,
} from './useRichEditor'

/**
 * Rich-text editor (Tiptap) with `v-model` of an HTML string. The emitted HTML only ever holds
 * the backend allow-list (`normalizeHtml`), `''` when empty. Label it with `labelId` (the id of
 * the visible label); `maxLength` counts characters of text and shows a counter. Images are
 * uploaded through `ImageUploadDialog` (alt text required), also when pasted or dropped.
 * `compact` offers the comment subset (replies, comments): no headings, code blocks or images,
 * and a lower editing area.
 */
const props = withDefaults(
  defineProps<{
    labelId?: string
    placeholder?: string
    disabled?: boolean
    uploadKind?: UploadKind
    maxLength?: number
    compact?: boolean
  }>(),
  {
    labelId: undefined,
    placeholder: undefined,
    disabled: false,
    uploadKind: 'image',
    maxLength: undefined,
    compact: false,
  },
)
const model = defineModel<string>({ default: '' })
const emit = defineEmits<{ blur: [] }>()

const { t } = useI18n()
const counterId = useId()
const overId = useId()

/** The last value this editor emitted, so the echo from the parent is not reloaded. */
let emitted = model.value

/** Characters over `maxLength` (0 without a limit). */
const overByFor = (length: number) =>
  props.maxLength === undefined ? 0 : Math.max(0, length - props.maxLength)

const linkOpen = ref(false)
const linkInitial = ref<LinkInput | null>(null)
const imageOpen = ref(false)
const pendingFile = ref<File | null>(null)

const api = useRichEditor({
  content: model.value,
  placeholder: () => props.placeholder ?? t('editor.placeholder'),
  editable: () => !props.disabled,
  attributes: (length) => {
    const over = overByFor(length) > 0
    const attrs: Record<string, string> = {
      role: 'textbox',
      'aria-multiline': 'true',
      class: `tiptap-content ${props.compact ? 'min-h-24' : 'min-h-40'} px-3 py-2 text-default focus:outline-none focus-visible:focus-ring`,
    }
    if (props.labelId) attrs['aria-labelledby'] = props.labelId
    if (props.disabled) attrs['aria-disabled'] = 'true'
    const describedBy = [props.maxLength !== undefined ? counterId : '', over ? overId : '']
    if (describedBy.some(Boolean)) attrs['aria-describedby'] = describedBy.filter(Boolean).join(' ')
    if (over) attrs['aria-invalid'] = 'true'
    return attrs
  },
  onChange: (html) => {
    emitted = html
    model.value = html
  },
  onBlur: () => emit('blur'),
  onImageFile: (file) => {
    if (props.disabled || props.compact) return
    pendingFile.value = file
    imageOpen.value = true
  },
})

const textLength = api.textLength
const overBy = computed(() => overByFor(textLength.value))
const isOverLimit = computed(() => overBy.value > 0)

watch(model, (value) => {
  if (value === emitted) return
  emitted = value
  api.setContent(value)
})

const toolbarItems = computed<ToolbarItem[]>(() => {
  const item = (
    action: ToolbarAction,
    icon: string,
    extra: Partial<ToolbarItem> = {},
  ): ToolbarItem => ({
    action,
    icon,
    label: t(`editor.actions.${action}`),
    active: api.isActive(action),
    disabled: props.disabled || api.isDisabled(action),
    ...extra,
  })
  const toggle = { toggle: true }
  if (props.compact) {
    return [
      item('bold', 'i-lucide-bold', toggle),
      item('italic', 'i-lucide-italic', toggle),
      item('underline', 'i-lucide-underline', toggle),
      item('strike', 'i-lucide-strikethrough', toggle),
      item('bulletList', 'i-lucide-list', { toggle: true, groupStart: true }),
      item('orderedList', 'i-lucide-list-ordered', toggle),
      item('blockquote', 'i-lucide-text-quote', toggle),
      item('link', 'i-lucide-link', { toggle: true, groupStart: true }),
      item('undo', 'i-lucide-undo-2', { groupStart: true }),
      item('redo', 'i-lucide-redo-2'),
    ]
  }
  return [
    item('bold', 'i-lucide-bold', toggle),
    item('italic', 'i-lucide-italic', toggle),
    item('underline', 'i-lucide-underline', toggle),
    item('strike', 'i-lucide-strikethrough', toggle),
    item('heading2', 'i-lucide-heading-2', { toggle: true, groupStart: true }),
    item('heading3', 'i-lucide-heading-3', toggle),
    item('bulletList', 'i-lucide-list', { toggle: true, groupStart: true }),
    item('orderedList', 'i-lucide-list-ordered', toggle),
    item('blockquote', 'i-lucide-text-quote', toggle),
    item('codeBlock', 'i-lucide-square-code', toggle),
    item('link', 'i-lucide-link', { toggle: true, groupStart: true }),
    item('image', 'i-lucide-image-plus'),
    item('undo', 'i-lucide-undo-2', { groupStart: true }),
    item('redo', 'i-lucide-redo-2'),
  ]
})

function onAction(action: ToolbarAction) {
  if (action === 'link') {
    linkInitial.value = api.currentLink()
    linkOpen.value = true
  } else if (action === 'image') {
    pendingFile.value = null
    imageOpen.value = true
  } else {
    api.run(action)
  }
}

function onLinkApply(link: LinkInput) {
  api.setLink(link)
}

function onImageUploaded(image: ImageInput) {
  api.insertImage(image)
}

defineExpose({
  /** Move focus into the editor. */
  focus: () => api.focus(),
  /** The Tiptap instance (tests, advanced callers). */
  editor: api.editor,
  /** More text than `maxLength`: forms should refuse to submit. */
  isOverLimit,
})
</script>

<template>
  <div
    class="rich-text-editor rounded-md border bg-default"
    :class="isOverLimit ? 'border-error' : 'border-accented'"
  >
    <EditorToolbar :items="toolbarItems" :label="t('editor.toolbar')" @action="onAction" />
    <EditorContent :editor="api.editor.value" />
    <div
      v-if="maxLength !== undefined"
      class="flex flex-wrap items-center justify-between gap-2 border-t border-default px-3 py-1 text-sm"
    >
      <p :id="overId" aria-live="polite" class="text-error">
        {{ isOverLimit ? t('editor.overLimit', overBy) : '' }}
      </p>
      <p
        :id="counterId"
        class="ms-auto tabular-nums"
        :class="isOverLimit ? 'text-error' : 'text-muted'"
      >
        <span aria-hidden="true">{{
          t('editor.counter', { count: textLength, max: maxLength })
        }}</span>
        <span class="sr-only">{{
          t('editor.counterLabel', { count: textLength, max: maxLength })
        }}</span>
      </p>
    </div>

    <LinkDialog
      v-model:open="linkOpen"
      :initial="linkInitial"
      @apply="onLinkApply"
      @remove="api.unsetLink()"
    />
    <ImageUploadDialog
      v-if="!compact"
      v-model:open="imageOpen"
      :kind="uploadKind"
      :file="pendingFile"
      @uploaded="onImageUploaded"
    />
  </div>
</template>

<style scoped>
/* Tailwind's preflight resets lists and headings; give the editing surface readable defaults. */
.rich-text-editor :deep(.tiptap-content) {
  line-height: 1.6;
}
.rich-text-editor :deep(.tiptap-content > * + *) {
  margin-top: 0.75em;
}
.rich-text-editor :deep(.tiptap-content h2) {
  font-size: 1.375rem;
  font-weight: 700;
}
.rich-text-editor :deep(.tiptap-content h3) {
  font-size: 1.175rem;
  font-weight: 700;
}
.rich-text-editor :deep(.tiptap-content h4) {
  font-weight: 700;
}
.rich-text-editor :deep(.tiptap-content ul) {
  list-style: disc;
  padding-inline-start: 1.5rem;
}
.rich-text-editor :deep(.tiptap-content ol) {
  list-style: decimal;
  padding-inline-start: 1.5rem;
}
.rich-text-editor :deep(.tiptap-content blockquote) {
  border-inline-start: 3px solid var(--ui-border-accented);
  padding-inline-start: 1rem;
  color: var(--ui-text-muted);
}
.rich-text-editor :deep(.tiptap-content pre) {
  background: var(--ui-bg-elevated);
  border-radius: 0.375rem;
  padding: 0.75rem 1rem;
  font-family: var(--font-mono, ui-monospace, monospace);
  overflow-x: auto;
}
.rich-text-editor :deep(.tiptap-content code) {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.9em;
}
.rich-text-editor :deep(.tiptap-content a) {
  color: var(--ui-primary);
  text-decoration: underline;
}
.rich-text-editor :deep(.tiptap-content img) {
  max-width: 100%;
  height: auto;
}
.rich-text-editor :deep(.tiptap-content img.ProseMirror-selectednode) {
  outline: 3px solid var(--focus-ring-color);
}
.rich-text-editor :deep(.tiptap-content hr) {
  border-color: var(--ui-border-accented);
}
.rich-text-editor :deep(.tiptap-content p.is-editor-empty:first-child::before) {
  content: attr(data-placeholder);
  float: inline-start;
  height: 0;
  color: var(--ui-text-dimmed);
  pointer-events: none;
}
</style>

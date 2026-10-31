<script setup lang="ts">
import { computed, ref } from 'vue'

import type { ToolbarAction, ToolbarItem } from './useRichEditor'

/**
 * Formatting toolbar of the rich-text editor (WAI-ARIA toolbar pattern): one tab stop, arrow
 * keys / Home / End move between the enabled buttons, Enter and Space activate. Real
 * `<button type="button">`s with `aria-label` (and the same text visually hidden), `aria-pressed`
 * on toggles. Buttons do not take focus on mouse down, so the editor keeps its selection.
 */
const props = defineProps<{ items: ToolbarItem[]; label: string }>()
const emit = defineEmits<{ action: [action: ToolbarAction] }>()

const buttons: (HTMLButtonElement | null)[] = []
const current = ref(0)

const enabled = computed(() => props.items.flatMap((item, index) => (item.disabled ? [] : [index])))

/** The button that is in the tab order: the last focused one, or the first enabled one. */
const tabStop = computed(() =>
  enabled.value.includes(current.value) ? current.value : (enabled.value[0] ?? 0),
)

function move(from: number, key: string): number | undefined {
  const list = enabled.value
  if (!list.length) return undefined
  const at = list.indexOf(from)
  switch (key) {
    case 'ArrowRight':
      return list[(at + 1) % list.length]
    case 'ArrowLeft':
      return list[(at - 1 + list.length) % list.length]
    case 'Home':
      return list[0]
    case 'End':
      return list[list.length - 1]
  }
  return undefined
}

function activate(index: number) {
  const item = props.items[index]
  if (item && !item.disabled) emit('action', item.action)
}

function onKeydown(event: KeyboardEvent, index: number) {
  if (event.key === 'Enter' || event.key === ' ') {
    // Handled here, so the native click that would follow does not fire a second time.
    event.preventDefault()
    activate(index)
    return
  }
  const next = move(index, event.key)
  if (next === undefined) return
  event.preventDefault()
  current.value = next
  buttons[next]?.focus()
}
</script>

<template>
  <div
    role="toolbar"
    :aria-label="label"
    class="flex flex-wrap items-center gap-0.5 border-b border-default bg-elevated/50 p-1"
  >
    <template v-for="(item, index) in items" :key="item.action">
      <span
        v-if="item.groupStart && index > 0"
        aria-hidden="true"
        class="mx-1 h-5 w-px bg-(--ui-border-accented)"
      />
      <button
        :ref="(el) => (buttons[index] = el as HTMLButtonElement | null)"
        type="button"
        :aria-label="item.label"
        :title="item.label"
        :aria-pressed="item.toggle ? (item.active ? 'true' : 'false') : undefined"
        :disabled="item.disabled"
        :tabindex="index === tabStop ? 0 : -1"
        class="inline-flex size-8 items-center justify-center rounded-md text-default hover:bg-accented focus-visible:focus-ring disabled:cursor-not-allowed disabled:opacity-40 aria-pressed:bg-primary-100 aria-pressed:text-primary-800"
        @mousedown.prevent
        @focus="current = index"
        @click="activate(index)"
        @keydown="onKeydown($event, index)"
      >
        <UIcon :name="item.icon" class="size-4" aria-hidden="true" />
        <span class="sr-only">{{ item.label }}</span>
      </button>
    </template>
  </div>
</template>

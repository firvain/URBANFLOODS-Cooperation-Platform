<script setup lang="ts">
import { computed } from 'vue'

/**
 * An audit row's metadata as a compact key/value list. Values are shown as text (objects as
 * JSON), never as HTML, and long values are shortened (the full value is in `title`).
 */
const props = defineProps<{ metadata: Record<string, unknown> }>()

const MAX_LENGTH = 120

function asText(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

const entries = computed(() =>
  Object.entries(props.metadata).map(([key, value]) => {
    const full = asText(value)
    const short = full.length > MAX_LENGTH ? `${full.slice(0, MAX_LENGTH - 1)}…` : full
    return { key, full, short }
  }),
)
</script>

<template>
  <dl v-if="entries.length" class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs">
    <template v-for="entry in entries" :key="entry.key">
      <dt class="font-mono text-muted">{{ entry.key }}</dt>
      <dd class="break-words" :title="entry.full !== entry.short ? entry.full : undefined">
        {{ entry.short }}
      </dd>
    </template>
  </dl>
  <span v-else class="text-muted">—</span>
</template>

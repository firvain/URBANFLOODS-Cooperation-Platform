<script setup lang="ts">
/** A labelled block of a KNOWBASE detail page (plain text, line breaks kept). */
defineProps<{ label: string; text?: string | null; lang?: string }>()
</script>

<template>
  <section v-if="text || $slots.default" class="space-y-1.5">
    <h2 class="text-sm font-semibold tracking-wide text-gray-700 uppercase">{{ label }}</h2>
    <slot>
      <p :lang="lang" class="leading-relaxed whitespace-pre-line text-gray-900">{{ text }}</p>
    </slot>
  </section>
</template>

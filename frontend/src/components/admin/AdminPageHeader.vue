<script setup lang="ts">
/** Title (the page's focus target on navigation) and intro of an admin page. */
defineProps<{ title: string; intro?: string }>()
</script>

<template>
  <div class="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
    <div>
      <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none">
        {{ title }}
      </h1>
      <p v-if="intro" class="mt-2 max-w-3xl text-muted">{{ intro }}</p>
    </div>
    <slot name="actions" />
  </div>
</template>

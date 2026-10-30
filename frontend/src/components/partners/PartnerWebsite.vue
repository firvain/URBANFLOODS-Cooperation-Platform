<script setup lang="ts">
import { computed } from 'vue'

import ExternalLink from '@/components/common/ExternalLink.vue'

/** A partner website link labelled with its host name (unique, unlike a repeated "Website"). */
const props = defineProps<{ href: string }>()

const host = computed(() => {
  try {
    return new URL(props.href).hostname.replace(/^www\./, '')
  } catch {
    return props.href
  }
})
</script>

<template>
  <ExternalLink :href="href" trailing-icon="i-lucide-external-link" class="text-sm break-all">
    {{ host }}
  </ExternalLink>
</template>

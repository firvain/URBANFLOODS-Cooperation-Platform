<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { partnerLogoUrl } from '@/constants/partnerLogos'

/**
 * A partner logo in a fixed-height white box, or nothing when no file was supplied. Capped at
 * h-10 / lg:h-12 so no partner logo is taller than the EU emblem inside the stacked project logo
 * on the same page (docs/branding.md).
 */
const props = defineProps<{ shortName: string; name: string }>()

const { t } = useI18n()
const src = computed(() => partnerLogoUrl(props.shortName))
</script>

<template>
  <div
    v-if="src"
    class="flex h-10 items-center justify-center rounded border border-default bg-white p-1 lg:h-12"
  >
    <img
      :src="src"
      :alt="t('partners.logoAlt', { name })"
      loading="lazy"
      class="h-full w-auto max-w-full object-contain"
    />
  </div>
</template>

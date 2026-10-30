<script setup lang="ts">
// flag-icons is only needed on the pages that show partner countries; keep it out of the main CSS.
import 'flag-icons/css/flag-icons.min.css'

import { useCountries } from '@/composables/useCountries'

/** Flag (decorative) and country name for an ISO 3166-1 alpha-2 code. */
defineProps<{ code: string }>()

const { countryName } = useCountries()
</script>

<template>
  <span class="inline-flex items-center gap-1.5">
    <span :class="['fi', `fi-${code.toLowerCase()}`, 'rounded-sm shadow-xs']" aria-hidden="true" />
    <span>{{ countryName(code) }}</span>
  </span>
</template>

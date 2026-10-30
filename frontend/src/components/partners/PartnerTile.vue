<script setup lang="ts">
import PartnerCountry from './PartnerCountry.vue'
import PartnerLogo from './PartnerLogo.vue'
import PartnerWebsite from './PartnerWebsite.vue'
import type { Organisation } from '@/services/organisations'

/** One project or associated partner in the KNOWBASE About-page tile style. */
defineProps<{ organisation: Organisation }>()
</script>

<template>
  <li
    data-testid="partner-tile"
    :data-short-name="organisation.short_name"
    class="flex flex-col gap-2 rounded border border-secondary-200 bg-secondary-50 p-3"
  >
    <PartnerLogo :short-name="organisation.short_name" :name="organisation.name" />
    <p class="text-sm font-medium text-gray-900">{{ organisation.name }}</p>
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-700">
      <PartnerCountry :code="organisation.country" />
    </div>
    <PartnerWebsite v-if="organisation.website" :href="organisation.website" />
  </li>
</template>

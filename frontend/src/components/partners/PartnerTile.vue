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
    class="flex items-center gap-3 rounded border border-secondary-200 bg-secondary-50 px-2.5 py-2"
  >
    <div class="w-24 shrink-0">
      <PartnerLogo :short-name="organisation.short_name" :name="organisation.name" />
    </div>
    <div class="min-w-0 flex-1">
      <p class="text-sm leading-snug font-medium text-gray-900">{{ organisation.name }}</p>
      <div class="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-gray-700">
        <PartnerCountry :code="organisation.country" />
        <PartnerWebsite v-if="organisation.website" :href="organisation.website" />
      </div>
    </div>
  </li>
</template>

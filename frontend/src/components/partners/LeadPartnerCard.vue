<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import PartnerCountry from './PartnerCountry.vue'
import PartnerLogo from './PartnerLogo.vue'
import PartnerWebsite from './PartnerWebsite.vue'

/**
 * The lead partner, highlighted as on the KNOWBASE About page. The default slot holds an optional
 * contact block (shown under a divider).
 */
defineProps<{
  name: string
  shortName: string
  country: string
  address?: string
  website?: string | null
}>()

const { t } = useI18n()
</script>

<template>
  <div data-testid="lead-partner" class="rounded-lg border-2 border-primary-500 bg-primary-100 p-4">
    <div class="flex items-start gap-3">
      <UBadge color="primary" variant="solid" size="xs" class="mt-1">
        {{ t('partners.leadBadge') }}
      </UBadge>
      <div class="min-w-0 flex-1 space-y-2">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <p class="text-base font-bold text-primary-700">{{ name }}</p>
          <PartnerLogo :short-name="shortName" :name="name" class="shrink-0" />
        </div>
        <div class="space-y-1 text-sm text-gray-700">
          <p v-if="address">{{ address }}</p>
          <PartnerCountry :code="country" />
          <p v-if="website"><PartnerWebsite :href="website" /></p>
        </div>
        <div v-if="$slots.default" class="mt-2 border-t border-primary-200 pt-2 text-sm">
          <slot />
        </div>
      </div>
    </div>
  </div>
</template>

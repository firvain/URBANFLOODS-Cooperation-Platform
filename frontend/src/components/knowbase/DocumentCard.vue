<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import PartnerCountry from '@/components/partners/PartnerCountry.vue'
import type { KbDocument } from '@/services/knowbase'

/** One legislation or policy document in the KNOWBASE list. */
const props = defineProps<{ document: KbDocument }>()

const { t } = useI18n()

/** At most this many keyword badges on a card. */
const MAX_KEYWORDS = 3

const title = computed(() => props.document.name_of_document_en || t('knowbase.documents.untitled'))
const keywords = computed(() => props.document.all_keywords.slice(0, MAX_KEYWORDS))
</script>

<template>
  <li
    data-testid="document-card"
    class="flex h-full flex-col gap-3 rounded border border-default bg-white p-4 shadow-xs"
  >
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-700">
      <PartnerCountry v-if="document.country" :code="document.country" />
      <UBadge v-if="document.level" color="primary" variant="subtle" size="sm">
        {{ document.level.label }}
      </UBadge>
      <UBadge v-if="document.subject" color="secondary" variant="subtle" size="sm">
        {{ document.subject.label }}
      </UBadge>
    </div>
    <h2 class="text-base leading-snug font-semibold">
      <ULink
        :to="`/knowbase/documents/${document.id}`"
        raw
        class="text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
      >
        {{ title }}
      </ULink>
    </h2>
    <p v-if="document.extended_description_en" class="line-clamp-3 text-sm text-gray-700">
      {{ document.extended_description_en }}
    </p>
    <ul
      v-if="keywords.length"
      class="mt-auto flex flex-wrap gap-1.5"
      :aria-label="t('knowbase.fields.keywords')"
    >
      <li v-for="keyword in keywords" :key="keyword">
        <UBadge color="neutral" variant="outline" size="sm">{{ keyword }}</UBadge>
      </li>
    </ul>
  </li>
</template>

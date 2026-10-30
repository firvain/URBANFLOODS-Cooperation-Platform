<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import logoStacked from '@/assets/logos/interreg-urbanfloods-stacked.png'
import ExternalLink from '@/components/common/ExternalLink.vue'
import { EXTERNAL_LINKS } from '@/constants/links'

const { t } = useI18n()

/** Rows of the "Project details" list; label and value are `about.details.<key>.*`. */
const DETAILS = ['programme', 'priority', 'duration', 'leadPartner', 'funding'] as const
</script>

<!-- Project web presence content (docs/branding.md, guidelines §2.2). -->
<template>
  <UContainer class="py-12">
    <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none">
      {{ t('about.title') }}
    </h1>

    <!-- Wide enough that the Interreg logotype + EU emblem part reaches 300 px on desktop. -->
    <img
      :src="logoStacked"
      :alt="t('app.logoAlt')"
      width="1599"
      height="833"
      class="mt-6 block h-auto w-full min-w-[240px] max-w-[560px]"
    />

    <div class="mt-6 max-w-3xl">
      <p class="text-lg text-default">{{ t('about.description') }}</p>

      <h2 class="mt-10 text-xl font-semibold text-highlighted">{{ t('about.details.title') }}</h2>
      <dl class="mt-4 divide-y divide-default border-y border-default">
        <div v-for="key in DETAILS" :key="key" class="grid gap-1 py-3 sm:grid-cols-3 sm:gap-4">
          <dt class="font-medium text-highlighted">{{ t(`about.details.${key}.label`) }}</dt>
          <dd class="text-default sm:col-span-2">{{ t(`about.details.${key}.value`) }}</dd>
        </div>
      </dl>
      <!-- Placeholder until the lead partner supplies the EU financial support figures. -->
      <p class="mt-4 text-sm text-toned">{{ t('about.budgetPlaceholder') }}</p>

      <h2 class="mt-10 text-xl font-semibold text-highlighted">{{ t('about.links.title') }}</h2>
      <ul class="mt-4 flex flex-col gap-2">
        <li>
          <ExternalLink :href="EXTERNAL_LINKS.project">{{ t('about.links.project') }}</ExternalLink>
        </li>
        <li>
          <ExternalLink :href="EXTERNAL_LINKS.knowbase">
            {{ t('about.links.knowbase') }}
          </ExternalLink>
        </li>
      </ul>

      <p class="mt-6">
        <ULink to="/partners" class="font-medium text-primary underline underline-offset-2">
          {{ t('about.partnersLink') }}
        </ULink>
      </p>
    </div>
  </UContainer>
</template>

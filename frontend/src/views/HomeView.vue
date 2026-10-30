<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'

import SuggestedCollaborators from '@/components/network/SuggestedCollaborators.vue'
import { dssUrl } from '@/constants/links'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const { isVerified } = storeToRefs(useAuthStore())

/** The Unified DSS web app; the card is hidden when it is not configured. */
const dss = dssUrl()

// Placeholders until the blog (M2), forum (M3) and KNOWBASE browser (M2) routes exist.
const sections = [
  { key: 'blog', icon: 'i-lucide-newspaper' },
  { key: 'forum', icon: 'i-lucide-messages-square' },
  { key: 'knowbase', icon: 'i-lucide-library' },
] as const
</script>

<template>
  <UContainer class="py-12">
    <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none sm:text-4xl">
      {{ t('home.title') }}
    </h1>
    <p class="mt-4 max-w-3xl text-lg text-muted">{{ t('home.intro') }}</p>

    <ul class="mt-10 grid gap-6 md:grid-cols-3">
      <li v-for="section in sections" :key="section.key">
        <UCard class="h-full">
          <template #header>
            <div class="flex items-center justify-between gap-2">
              <h2 class="flex items-center gap-2 text-lg font-semibold text-highlighted">
                <UIcon :name="section.icon" class="size-5 text-primary" aria-hidden="true" />
                {{ t(`home.cards.${section.key}.title`) }}
              </h2>
              <UBadge color="neutral" variant="subtle" size="sm">{{ t('home.comingSoon') }}</UBadge>
            </div>
          </template>
          <p class="text-muted">{{ t(`home.cards.${section.key}.description`) }}</p>
        </UCard>
      </li>
    </ul>

    <UCard v-if="dss" data-testid="dss-card" class="mt-6">
      <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 class="flex items-center gap-2 text-lg font-semibold text-highlighted">
            <UIcon name="i-lucide-map" class="size-5 text-primary" aria-hidden="true" />
            {{ t('home.dss.title') }}
          </h2>
          <p class="mt-2 max-w-3xl text-muted">{{ t('home.dss.description') }}</p>
        </div>
        <UButton
          :to="dss"
          target="_blank"
          rel="noopener noreferrer"
          trailing-icon="i-lucide-arrow-up-right"
          class="shrink-0 self-start md:self-center"
        >
          {{ t('home.dss.open') }}
          <span class="sr-only">{{ ` ${t('a11y.opensInNewTab')}` }}</span>
        </UButton>
      </div>
    </UCard>

    <SuggestedCollaborators v-if="isVerified" class="mt-12" />
  </UContainer>
</template>

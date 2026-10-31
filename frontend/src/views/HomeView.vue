<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'

import CompleteProfileBanner from '@/components/account/CompleteProfileBanner.vue'
import SuggestedCollaborators from '@/components/network/SuggestedCollaborators.vue'
import { dssUrl } from '@/constants/links'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const { isVerified } = storeToRefs(useAuthStore())

/** The Unified DSS web app; the card is hidden when it is not configured. */
const dss = dssUrl()

/** Sections of the platform; blog (M2) and forum (M3) stay placeholders until their routes exist. */
const sections: { key: string; icon: string; to?: string }[] = [
  { key: 'blog', icon: 'i-lucide-newspaper' },
  { key: 'forum', icon: 'i-lucide-messages-square' },
  { key: 'knowbase', icon: 'i-lucide-library', to: '/knowbase' },
]
</script>

<template>
  <UContainer class="py-12">
    <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none sm:text-4xl">
      {{ t('home.title') }}
    </h1>
    <p class="mt-4 max-w-3xl text-lg text-muted">{{ t('home.intro') }}</p>

    <CompleteProfileBanner class="mt-8" />

    <ul class="mt-10 grid gap-6 md:grid-cols-3">
      <li v-for="section in sections" :key="section.key" :data-testid="`home-card-${section.key}`">
        <UCard class="h-full">
          <template #header>
            <div class="flex items-center justify-between gap-2">
              <h2 class="flex items-center gap-2 text-lg font-semibold text-highlighted">
                <UIcon :name="section.icon" class="size-5 text-primary" aria-hidden="true" />
                <ULink
                  v-if="section.to"
                  :to="section.to"
                  raw
                  class="text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
                >
                  {{ t(`home.cards.${section.key}.title`) }}
                </ULink>
                <template v-else>{{ t(`home.cards.${section.key}.title`) }}</template>
              </h2>
              <UBadge v-if="!section.to" color="neutral" variant="subtle" size="sm">
                {{ t('home.comingSoon') }}
              </UBadge>
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

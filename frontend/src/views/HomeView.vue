<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'

import CompleteProfileBanner from '@/components/account/CompleteProfileBanner.vue'
import SuggestedCollaborators from '@/components/network/SuggestedCollaborators.vue'
import { absoluteUrl, usePageHead } from '@/composables/usePageHead'
import { dssUrl, EXTERNAL_LINKS } from '@/constants/links'
import { useAuthStore } from '@/stores/auth'

const { t, locale } = useI18n()
const { isVerified } = storeToRefs(useAuthStore())

/** The Unified DSS web app; the card is hidden when it is not configured. */
const dss = dssUrl()

/**
 * Card colours follow the KNOWBASE wordmark: navy titles with the project green as the accent
 * (green only on backgrounds and borders, per docs/branding.md and the contrast guard).
 */
const CARD_UI = {
  root: 'border-t-4 border-t-secondary-500 shadow-sm',
  header: 'bg-primary-50',
} as const
const ICON_DISC =
  'inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary-500 text-white'

/**
 * Sections of the platform: internal ones have a linked title (`to`), the KNOWBASE is another
 * site browsed there (user decision 2026-10-31), so like the DSS card it has a plain title and an
 * "Open" button (`external`).
 */
const sections: { key: string; icon: string; to?: string; external?: string }[] = [
  { key: 'blog', icon: 'i-lucide-newspaper', to: '/blog' },
  { key: 'forum', icon: 'i-lucide-messages-square', to: '/forum' },
  { key: 'knowbase', icon: 'i-lucide-library', external: EXTERNAL_LINKS.knowbase },
]

// The site's schema.org WebSite entry, with the search box search engines may offer.
usePageHead(() => ({
  title: t('app.title'),
  description: t('head.homeDescription'),
  type: 'website',
  canonical: '/',
  jsonLd: {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: t('app.title'),
    url: absoluteUrl('/'),
    inLanguage: locale.value,
    potentialAction: {
      '@type': 'SearchAction',
      target: {
        '@type': 'EntryPoint',
        urlTemplate: `${absoluteUrl('/search')}?q={search_term_string}`,
      },
      'query-input': 'required name=search_term_string',
    },
  },
}))
</script>

<template>
  <UContainer class="py-12">
    <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none sm:text-4xl">
      {{ t('home.title') }}
    </h1>
    <p class="mt-4 max-w-3xl text-lg text-muted">{{ t('home.intro') }}</p>

    <CompleteProfileBanner class="mt-8" />

    <!-- Two rows of two: Blog and Forum, then the KNOWBASE and the Unified DSS (user decision). -->
    <ul class="mt-10 grid gap-6 md:grid-cols-2">
      <li v-for="section in sections" :key="section.key" :data-testid="`home-card-${section.key}`">
        <UCard class="h-full" :ui="CARD_UI">
          <template #header>
            <h2 class="flex items-center gap-2 text-lg font-semibold text-primary-800">
              <span :class="ICON_DISC"
                ><UIcon :name="section.icon" class="size-4" aria-hidden="true"
              /></span>
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
          </template>
          <div class="flex h-full flex-col gap-4">
            <p class="text-muted">{{ t(`home.cards.${section.key}.description`) }}</p>
            <UButton
              v-if="section.external"
              :to="section.external"
              target="_blank"
              rel="noopener noreferrer"
              trailing-icon="i-lucide-arrow-up-right"
              class="self-start"
            >
              {{ t(`home.cards.${section.key}.open`) }}
              <span class="sr-only">{{ ` ${t('a11y.opensInNewTab')}` }}</span>
            </UButton>
          </div>
        </UCard>
      </li>

      <li v-if="dss" data-testid="dss-card">
        <UCard class="h-full" :ui="CARD_UI">
          <template #header>
            <h2 class="flex items-center gap-2 text-lg font-semibold text-primary-800">
              <span :class="ICON_DISC"
                ><UIcon name="i-lucide-map" class="size-4" aria-hidden="true"
              /></span>
              {{ t('home.dss.title') }}
            </h2>
          </template>
          <div class="flex h-full flex-col gap-4">
            <p class="text-muted">{{ t('home.dss.description') }}</p>
            <UButton
              :to="dss"
              target="_blank"
              rel="noopener noreferrer"
              trailing-icon="i-lucide-arrow-up-right"
              class="self-start"
            >
              {{ t('home.dss.open') }}
              <span class="sr-only">{{ ` ${t('a11y.opensInNewTab')}` }}</span>
            </UButton>
          </div>
        </UCard>
      </li>
    </ul>

    <SuggestedCollaborators v-if="isVerified" class="mt-12" />
  </UContainer>
</template>

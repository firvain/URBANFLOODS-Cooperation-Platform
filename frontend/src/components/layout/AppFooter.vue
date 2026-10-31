<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import logoProject from '@/assets/logos/urbanfloods-wordmark.svg'
import ExternalLink from '@/components/common/ExternalLink.vue'
import { EXTERNAL_LINKS } from '@/constants/links'
import { LEGAL_TITLE_KEYS } from '@/constants/legal'

const { t } = useI18n()
const year = new Date().getFullYear()

const LEGAL_LINK_CLASS =
  'text-xs text-muted underline-offset-2 hover:text-highlighted hover:underline focus-visible:underline'

const legalLinks = [
  { to: '/terms', labelKey: LEGAL_TITLE_KEYS.terms },
  { to: '/privacy', labelKey: LEGAL_TITLE_KEYS.privacy },
] as const

const externalLinks = [
  { key: 'project', href: EXTERNAL_LINKS.project },
  { key: 'programme', href: EXTERNAL_LINKS.programme },
  { key: 'knowbase', href: EXTERNAL_LINKS.knowbase },
  { key: 'linkedin', href: EXTERNAL_LINKS.linkedin, icon: 'i-lucide-linkedin' },
] as const
</script>

<!--
  Compact footer (docs/branding.md). Mandatory: the illustrated project mark at 48 px beside the
  co-funding statement, and the disclaimer as the last text, in small print. The green line
  (border-secondary-300) is the one accent use of the project green. The header carries the
  platform navigation, so the footer only lists the external project links. From lg the brand and
  the links share one row (the links wrap into two right-aligned lines) to keep the footer short.
  A plain <footer> rather than UFooter: three short rows need none of its slots.
-->
<template>
  <footer class="bg-gradient-to-r from-primary-50 to-secondary-50 border-t-2 border-secondary-300">
    <UContainer>
      <div class="flex flex-wrap items-center justify-between gap-6 py-6 lg:flex-nowrap">
        <div class="flex items-center gap-4">
          <img
            :src="logoProject"
            :alt="t('app.projectLogoAlt')"
            class="block h-12 w-auto shrink-0"
          />
          <p class="max-w-md text-sm font-semibold text-primary-700">{{ t('footer.statement') }}</p>
        </div>

        <nav :aria-label="t('footer.navLabel')">
          <ul class="flex flex-wrap items-center gap-x-5 gap-y-1.5 lg:justify-end">
            <li v-for="link in externalLinks" :key="link.key">
              <ExternalLink
                :href="link.href"
                :icon="'icon' in link ? link.icon : undefined"
                trailing-icon="i-lucide-arrow-up-right"
                subtle
              >
                {{ t(`footer.links.${link.key}`) }}
              </ExternalLink>
            </li>
          </ul>
        </nav>
      </div>

      <!-- A later increment adds the Accessibility statement and Open data links here. -->
      <div class="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-secondary-200 py-3">
        <p class="text-xs text-muted">{{ t('footer.copyright', { year }) }}</p>
        <ULink
          v-for="link in legalLinks"
          :key="link.to"
          :to="link.to"
          raw
          :class="LEGAL_LINK_CLASS"
        >
          {{ t(link.labelKey) }}
        </ULink>
      </div>

      <p class="max-w-5xl pb-5 text-xs leading-relaxed text-muted">{{ t('footer.disclaimer') }}</p>
    </UContainer>
  </footer>
</template>

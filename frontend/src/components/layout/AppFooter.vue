<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import logoProject from '@/assets/logos/urbanfloods-wordmark.svg'
import ExternalLink from '@/components/common/ExternalLink.vue'
import { EXTERNAL_LINKS } from '@/constants/links'
import { NAV_ITEMS } from '@/constants/navigation'

const { t } = useI18n()
const year = new Date().getFullYear()

const LINK_CLASS =
  'text-sm text-muted underline-offset-2 hover:text-highlighted hover:underline focus-visible:underline'
const HEADING_CLASS = 'text-xs font-semibold uppercase tracking-wider text-highlighted'

const projectLinks = [
  { key: 'project', href: EXTERNAL_LINKS.project },
  { key: 'programme', href: EXTERNAL_LINKS.programme },
  { key: 'knowbase', href: EXTERNAL_LINKS.knowbase },
] as const
</script>

<!--
  Mandatory visibility (docs/branding.md): the stacked project logo on white, the statement on the
  Interreg support, and the disclaimer as the last thing on the page. The logo renders at 448 px
  (560 px from lg) so its Interreg logotype + EU emblem part reaches ~240/300 px; that is why the
  brand block takes a full row until xl, where half the 12-column grid is wide enough.
  The green line above the border is the one accent use of the project green.
-->
<template>
  <UFooter
    :ui="{
      root: 'relative bg-white border-t border-default before:absolute before:inset-x-0 before:-top-[5px] before:h-1 before:bg-secondary-500',
      top: 'py-12 lg:py-16',
      container: 'border-t border-default py-6 lg:py-6',
      left: 'mt-0 justify-start',
      center: 'hidden',
      right: 'hidden',
      bottom: 'pt-0 pb-8 lg:pt-0 lg:pb-10',
    }"
  >
    <template #top>
      <UContainer class="grid grid-cols-1 gap-10 sm:grid-cols-2 md:grid-cols-12">
        <div class="sm:col-span-2 md:col-span-12 lg:col-span-4">
          <img
            :src="logoProject"
            :alt="t('app.projectLogoAlt')"
            class="block h-auto w-[112px] lg:w-[128px]"
          />
          <p class="mt-6 max-w-md text-sm text-muted">{{ t('footer.statement') }}</p>
        </div>

        <div class="md:col-span-4 lg:col-span-3">
          <h2 :class="HEADING_CLASS">{{ t('footer.columns.platform') }}</h2>
          <ul class="mt-4 space-y-3">
            <li v-for="item in NAV_ITEMS" :key="item.name">
              <ULink :to="item.to" raw :class="LINK_CLASS">{{ t(item.labelKey) }}</ULink>
            </li>
          </ul>
        </div>

        <div class="md:col-span-4 lg:col-span-3">
          <h2 :class="HEADING_CLASS">{{ t('footer.columns.project') }}</h2>
          <ul class="mt-4 space-y-3">
            <li v-for="link in projectLinks" :key="link.key">
              <ExternalLink :href="link.href" trailing-icon="i-lucide-arrow-up-right" subtle>
                {{ t(`footer.links.${link.key}`) }}
              </ExternalLink>
            </li>
          </ul>
        </div>

        <div class="md:col-span-4 lg:col-span-2">
          <h2 :class="HEADING_CLASS">{{ t('footer.columns.follow') }}</h2>
          <ul class="mt-4 space-y-3">
            <li>
              <ExternalLink
                :href="EXTERNAL_LINKS.linkedin"
                icon="i-lucide-linkedin"
                trailing-icon="i-lucide-arrow-up-right"
                subtle
              >
                {{ t('footer.links.linkedin') }}
              </ExternalLink>
            </li>
          </ul>
        </div>
      </UContainer>
    </template>

    <template #left>
      <p class="text-xs text-muted">{{ t('footer.copyright', { year }) }}</p>
    </template>

    <template #bottom>
      <UContainer>
        <p class="max-w-5xl text-xs leading-relaxed text-muted">{{ t('footer.disclaimer') }}</p>
      </UContainer>
    </template>
  </UFooter>
</template>

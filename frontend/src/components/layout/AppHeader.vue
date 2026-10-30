<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import logoHorizontal from '@/assets/logos/interreg-urbanfloods-horizontal.png'
import { dssUrl } from '@/constants/links'
import { DSS_NAV_ITEM, NAV_ITEMS } from '@/constants/navigation'
import LocaleSwitcher from './LocaleSwitcher.vue'
import UserMenu from './UserMenu.vue'

const { t } = useI18n()
const route = useRoute()

interface NavLink {
  name: string
  label: string
  to: string
  /** Another site: opens in a new tab, announced to screen readers. */
  external: boolean
}

const dss = dssUrl()

/** Internal pages, with the Unified DSS (when configured) after its anchor item. */
const navItems = computed<NavLink[]>(() =>
  NAV_ITEMS.flatMap((item) => {
    const link: NavLink = { name: item.name, label: t(item.labelKey), to: item.to, external: false }
    if (item.name !== DSS_NAV_ITEM.after || !dss) return [link]
    return [
      link,
      { name: DSS_NAV_ITEM.name, label: t(DSS_NAV_ITEM.labelKey), to: dss, external: true },
    ]
  }),
)

function isActive(item: NavLink): boolean {
  if (item.external) return false
  return item.to === '/' ? route.path === '/' : route.path.startsWith(item.to)
}

/** Link attributes: external items open in a new tab without `window.opener` or a referrer. */
function linkAttrs(item: NavLink) {
  return item.external
    ? { target: '_blank', rel: 'noopener noreferrer', trailingIcon: 'i-lucide-arrow-up-right' }
    : {}
}
</script>

<template>
  <!--
    Project logo (docs/branding.md): the official horizontal image, on white, never narrower than
    240 px (384 px from lg). Fixed widths + matching min-widths + max-w-none keep it from
    shrinking; the navigation collapses into the menu instead. py-3/pe-4 plus the header height
    (main.css) keep clear space of at least half the EU emblem height around it.
  -->
  <UHeader
    to="/"
    :title="t('app.logoAlt')"
    :ui="{
      root: 'bg-white backdrop-blur-none border-b border-default',
      title: 'items-center py-3 pe-4',
    }"
  >
    <template #title>
      <img
        :src="logoHorizontal"
        :alt="t('app.logoAlt')"
        width="1481"
        height="258"
        class="block h-auto w-[240px] min-w-[240px] max-w-none shrink-0 lg:w-[384px] lg:min-w-[384px]"
      />
    </template>

    <nav :aria-label="t('app.mainNavigation')" class="hidden items-center gap-1 lg:flex">
      <UButton
        v-for="item in navItems"
        :key="item.name"
        :to="item.to"
        v-bind="linkAttrs(item)"
        :variant="isActive(item) ? 'soft' : 'ghost'"
        :color="isActive(item) ? 'primary' : 'neutral'"
        size="sm"
      >
        {{ item.label }}
        <span v-if="item.external" class="sr-only">{{ ` ${t('a11y.opensInNewTab')}` }}</span>
      </UButton>
    </nav>

    <template #right>
      <UserMenu class="hidden lg:flex" />
      <!-- Below sm the logo needs the room; the language switcher moves into the menu. -->
      <div class="hidden sm:block">
        <LocaleSwitcher />
      </div>
    </template>

    <template #body>
      <ul class="flex flex-col gap-1">
        <li v-for="item in navItems" :key="item.name">
          <UButton
            :to="item.to"
            v-bind="linkAttrs(item)"
            :variant="isActive(item) ? 'soft' : 'ghost'"
            :color="isActive(item) ? 'primary' : 'neutral'"
            block
            class="justify-start"
          >
            {{ item.label }}
            <span v-if="item.external" class="sr-only">{{ ` ${t('a11y.opensInNewTab')}` }}</span>
          </UButton>
        </li>
      </ul>
      <USeparator class="my-4" />
      <UserMenu mobile />
      <div class="mt-4 sm:hidden">
        <LocaleSwitcher class="w-full" />
      </div>
    </template>
  </UHeader>
</template>

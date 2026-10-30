<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import { NAV_ITEMS } from '@/constants/navigation'
import LocaleSwitcher from './LocaleSwitcher.vue'
import UserMenu from './UserMenu.vue'

const { t } = useI18n()
const route = useRoute()

const navItems = computed(() => NAV_ITEMS.map((item) => ({ ...item, label: t(item.labelKey) })))

function isActive(to: string): boolean {
  return to === '/' ? route.path === '/' : route.path.startsWith(to)
}
</script>

<template>
  <UHeader to="/" :ui="{ root: 'border-b border-default' }">
    <template #title>
      <span class="font-bold leading-tight">
        <span class="text-primary-600 dark:text-primary-300">URBANFLOODS</span>
        <span class="text-highlighted"> Cooperation Platform</span>
      </span>
    </template>

    <nav :aria-label="t('app.mainNavigation')" class="hidden items-center gap-1 lg:flex">
      <UButton
        v-for="item in navItems"
        :key="item.name"
        :to="item.to"
        :variant="isActive(item.to) ? 'soft' : 'ghost'"
        :color="isActive(item.to) ? 'primary' : 'neutral'"
        size="sm"
      >
        {{ item.label }}
      </UButton>
    </nav>

    <template #right>
      <UserMenu class="hidden lg:flex" />
      <LocaleSwitcher />
    </template>

    <template #body>
      <ul class="flex flex-col gap-1">
        <li v-for="item in navItems" :key="item.name">
          <UButton
            :to="item.to"
            :variant="isActive(item.to) ? 'soft' : 'ghost'"
            :color="isActive(item.to) ? 'primary' : 'neutral'"
            block
            class="justify-start"
          >
            {{ item.label }}
          </UButton>
        </li>
      </ul>
      <USeparator class="my-4" />
      <UserMenu mobile />
    </template>
  </UHeader>
</template>

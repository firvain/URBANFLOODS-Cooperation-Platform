<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import type { NavigationMenuItem } from '@nuxt/ui'

/**
 * The admin area: a vertical section menu beside the page on large screens, a section select
 * above it on small ones. Every child page renders its own `h1` (the focus target).
 */
const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const SECTIONS = [
  { key: 'dashboard', to: '/admin', icon: 'i-lucide-layout-dashboard' },
  { key: 'queue', to: '/admin/queue', icon: 'i-lucide-hourglass' },
  { key: 'reports', to: '/admin/reports', icon: 'i-lucide-flag' },
  { key: 'users', to: '/admin/users', icon: 'i-lucide-users' },
  { key: 'categories', to: '/admin/categories', icon: 'i-lucide-folder-tree' },
  { key: 'tags', to: '/admin/tags', icon: 'i-lucide-tags' },
  { key: 'organisations', to: '/admin/organisations', icon: 'i-lucide-building-2' },
  { key: 'expertise', to: '/admin/expertise', icon: 'i-lucide-brain' },
  { key: 'log', to: '/admin/log', icon: 'i-lucide-scroll-text' },
] as const

const navItems = computed<NavigationMenuItem[]>(() =>
  SECTIONS.map((section) => ({
    label: t(`admin.nav.${section.key}`),
    icon: section.icon,
    to: section.to,
    // `/admin` would otherwise count as active on every admin page.
    exact: section.to === '/admin',
  })),
)

const selectItems = computed(() =>
  SECTIONS.map((section) => ({
    label: t(`admin.nav.${section.key}`),
    value: section.to as string,
  })),
)

/** The section select on small screens: the current section; choosing one navigates. */
const currentSection = computed<string>({
  get: () =>
    [...SECTIONS].reverse().find((s) => route.path === s.to || route.path.startsWith(`${s.to}/`))
      ?.to ?? '/admin',
  set: (to) => void router.push(to),
})
</script>

<template>
  <UContainer class="py-8 lg:py-12">
    <p class="text-sm font-semibold tracking-wide text-primary-700 uppercase">
      {{ t('admin.title') }}
    </p>
    <div class="mt-4 grid gap-6 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-10">
      <div>
        <UNavigationMenu
          orientation="vertical"
          :items="navItems"
          :aria-label="t('admin.nav.label')"
          class="hidden lg:flex"
        />
        <UFormField :label="t('admin.nav.section')" name="admin-section" class="lg:hidden">
          <USelect v-model="currentSection" :items="selectItems" class="w-full" />
        </UFormField>
      </div>
      <div class="min-w-0">
        <RouterView />
      </div>
    </div>
  </UContainer>
</template>

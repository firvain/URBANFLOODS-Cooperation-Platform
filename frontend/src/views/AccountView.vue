<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import type { TabsItem } from '@nuxt/ui'

import DataPanel from '@/components/account/DataPanel.vue'
import NotificationsForm from '@/components/account/NotificationsForm.vue'
import PasswordForm from '@/components/account/PasswordForm.vue'
import ProfileForm from '@/components/account/ProfileForm.vue'
import SessionList from '@/components/account/SessionList.vue'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const TABS = [
  { value: 'profile', icon: 'i-lucide-user-round' },
  { value: 'password', icon: 'i-lucide-key-round' },
  { value: 'sessions', icon: 'i-lucide-monitor-smartphone' },
  // Linked from the opt-out line of every notification email: `/account?tab=notifications`.
  { value: 'notifications', icon: 'i-lucide-bell' },
  { value: 'data', icon: 'i-lucide-database' },
] as const
type TabValue = (typeof TABS)[number]['value']

const isTab = (value: unknown): value is TabValue => TABS.some((tab) => tab.value === value)

const items = computed(
  () =>
    TABS.map((tab) => ({
      label: t(`account.tabs.${tab.value}`),
      value: tab.value,
      icon: tab.icon,
      slot: tab.value,
    })) satisfies TabsItem[],
)

/** The open tab lives in `?tab=` so it survives a reload and can be linked to. */
const activeTab = computed<string>({
  get: () => (isTab(route.query.tab) ? route.query.tab : 'profile'),
  set: (value) => {
    void router.replace({ query: { ...route.query, tab: value === 'profile' ? undefined : value } })
  },
})
</script>

<template>
  <UContainer class="max-w-3xl py-12">
    <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none">
      {{ t('nav.account') }}
    </h1>
    <p class="mt-3 text-muted">{{ t('account.intro') }}</p>

    <!-- The tabs need the user; it is gone right after the account is deleted. -->
    <UTabs
      v-if="auth.user"
      v-model="activeTab"
      :items="items"
      variant="link"
      class="mt-8 w-full gap-6"
      :ui="{ list: 'overflow-x-auto' }"
    >
      <template #profile>
        <ProfileForm />
      </template>
      <template #password>
        <PasswordForm />
      </template>
      <template #sessions>
        <SessionList />
      </template>
      <template #notifications>
        <NotificationsForm />
      </template>
      <template #data>
        <DataPanel />
      </template>
    </UTabs>
  </UContainer>
</template>

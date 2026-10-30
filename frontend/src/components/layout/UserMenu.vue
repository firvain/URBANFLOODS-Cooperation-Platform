<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router'
import { useToast } from '@nuxt/ui/composables'
import type { DropdownMenuItem } from '@nuxt/ui'

import { useAuthStore } from '@/stores/auth'

/**
 * Header account controls. Logged out: "Log in" / "Register". Logged in: a dropdown with the
 * display name, "Account" and "Log out" (or, with `mobile`, the same actions as plain buttons for
 * the header's mobile menu).
 */
defineProps<{ mobile?: boolean }>()

const { t } = useI18n()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const toast = useToast()

/** Come back to the current page after logging in (not from home or the auth pages). */
const loginTarget = computed<RouteLocationRaw>(() =>
  route.fullPath === '/' || route.meta.guestOnly
    ? '/login'
    : { name: 'login', query: { next: route.fullPath } },
)

const signedInAs = computed(() => t('auth.menu.signedInAs', { name: auth.user?.display_name }))

async function logout() {
  await auth.logout()
  toast.add({ title: t('auth.loggedOut'), color: 'neutral', icon: 'i-lucide-log-out' })
  if (route.meta.auth) await router.push('/')
}

const items = computed<DropdownMenuItem[][]>(() => [
  [{ type: 'label', label: signedInAs.value }],
  [{ label: t('nav.account'), icon: 'i-lucide-user-round', to: '/account' }],
  [{ label: t('auth.logout'), icon: 'i-lucide-log-out', onSelect: logout }],
])
</script>

<template>
  <div
    v-if="!auth.isAuthenticated"
    :class="mobile ? 'flex flex-col gap-2' : 'flex items-center gap-2'"
  >
    <UButton
      :to="loginTarget"
      color="neutral"
      variant="ghost"
      :size="mobile ? 'md' : 'sm'"
      :block="mobile"
    >
      {{ t('nav.login') }}
    </UButton>
    <UButton to="/register" :size="mobile ? 'md' : 'sm'" :block="mobile">
      {{ t('nav.register') }}
    </UButton>
  </div>

  <div v-else-if="mobile" class="flex flex-col gap-1">
    <p class="px-2.5 py-1.5 text-sm text-muted">{{ signedInAs }}</p>
    <UButton
      to="/account"
      color="neutral"
      variant="ghost"
      icon="i-lucide-user-round"
      block
      class="justify-start"
    >
      {{ t('nav.account') }}
    </UButton>
    <UButton
      color="neutral"
      variant="ghost"
      icon="i-lucide-log-out"
      block
      class="justify-start"
      @click="logout"
    >
      {{ t('auth.logout') }}
    </UButton>
  </div>

  <div v-else class="flex items-center">
    <UDropdownMenu :items="items" :content="{ align: 'end' }">
      <UButton
        color="neutral"
        variant="ghost"
        size="sm"
        icon="i-lucide-circle-user-round"
        trailing-icon="i-lucide-chevron-down"
        class="max-w-48"
      >
        <span class="truncate">{{ auth.user?.display_name }}</span>
      </UButton>
    </UDropdownMenu>
  </div>
</template>

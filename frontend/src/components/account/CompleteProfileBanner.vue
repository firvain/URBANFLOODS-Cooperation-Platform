<script lang="ts">
/** `sessionStorage` key: the reminder stays hidden for the rest of the browser session. */
export const NUDGE_DISMISSED_KEY = 'profileNudgeDismissed'
/** Where members add their expertise. */
export const PROFILE_TAB_LINK = '/account?tab=profile'
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import type { AlertProps } from '@nuxt/ui'

import { useAuthStore } from '@/stores/auth'

/**
 * Profile-completion reminder for verified members whose profile lists no expertise areas (so
 * matchmaking and the network filters cannot find them). A free-text "other" area alone counts as
 * expertise: the member has said what they work on. Dismissible for the session.
 */
const { t } = useI18n()
const { user, isVerified } = storeToRefs(useAuthStore())

/** The close button names what it dismisses (Nuxt UI's default label is a bare "Close"). */
const closeButton = computed(
  () => ({ 'aria-label': t('account.nudge.dismiss') }) as AlertProps['close'],
)

function readDismissed(): boolean {
  try {
    return sessionStorage.getItem(NUDGE_DISMISSED_KEY) === '1'
  } catch {
    return false
  }
}

const dismissed = ref(readDismissed())

const visible = computed(
  () =>
    isVerified.value &&
    user.value!.expertise.length === 0 &&
    !user.value!.expertise_other &&
    !dismissed.value,
)

function dismiss() {
  dismissed.value = true
  try {
    sessionStorage.setItem(NUDGE_DISMISSED_KEY, '1')
  } catch {
    // Storage blocked: hidden until the next page load.
  }
}
</script>

<template>
  <UAlert
    v-if="visible"
    data-testid="complete-profile-banner"
    color="secondary"
    variant="subtle"
    icon="i-lucide-user-pen"
    :title="t('account.nudge.title')"
    :description="t('account.nudge.description')"
    :actions="[
      {
        label: t('account.nudge.action'),
        to: PROFILE_TAB_LINK,
        color: 'secondary',
        variant: 'solid',
        icon: 'i-lucide-tags',
      },
    ]"
    :close="closeButton"
    @update:open="dismiss"
  />
</template>

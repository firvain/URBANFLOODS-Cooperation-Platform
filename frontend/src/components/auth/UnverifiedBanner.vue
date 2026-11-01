<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useApiErrors } from '@/composables/useApiErrors'
import { useAuthStore } from '@/stores/auth'

/**
 * Shown to logged-in users who have not verified their email yet (they can read, not post). The
 * resend needs no Turnstile token: the backend accepts the session of the account being resent.
 */
const { t } = useI18n()
const auth = useAuthStore()
const { errorMessage } = useApiErrors()

const pending = ref(false)
const status = ref('')

const visible = computed(() => auth.isAuthenticated && !auth.isVerified)

async function resend() {
  if (!auth.user) return
  status.value = ''
  pending.value = true
  try {
    await auth.resendVerification(auth.user.email)
    status.value = t('auth.resent')
  } catch (e) {
    status.value = errorMessage(e)
  } finally {
    pending.value = false
  }
}

const actions = computed(() => [
  {
    label: t('auth.unverified.resend'),
    icon: 'i-lucide-send',
    color: 'warning' as const,
    variant: 'outline' as const,
    loading: pending.value,
    onClick: resend,
  },
])
</script>

<template>
  <UContainer v-if="visible" class="pt-4">
    <UAlert
      color="warning"
      variant="subtle"
      icon="i-lucide-mail-warning"
      orientation="horizontal"
      :title="t('auth.unverified.title')"
      :description="t('auth.unverified.description', { email: auth.user?.email })"
      :actions="actions"
    />
    <p aria-live="polite" class="mt-2 text-sm text-muted empty:hidden">{{ status }}</p>
  </UContainer>
</template>

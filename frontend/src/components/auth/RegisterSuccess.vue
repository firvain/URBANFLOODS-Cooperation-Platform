<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { useApiErrors } from '@/composables/useApiErrors'
import { useAuthStore } from '@/stores/auth'

/** "Check your email" state after registering, with a resend button. */
const props = defineProps<{ email: string }>()

const { t } = useI18n()
const auth = useAuthStore()
const { errorMessage } = useApiErrors()

const pending = ref(false)
const status = ref('')
const error = ref('')

async function resend() {
  status.value = ''
  error.value = ''
  pending.value = true
  try {
    await auth.resendVerification(props.email)
    status.value = t('auth.resent')
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <UAlert
      color="success"
      variant="subtle"
      icon="i-lucide-mail-check"
      :description="t('auth.registerSuccess.body', { email })"
    />
    <p class="text-muted">{{ t('auth.registerSuccess.noEmail') }}</p>
    <UButton
      color="neutral"
      variant="outline"
      icon="i-lucide-send"
      :loading="pending"
      @click="resend"
    >
      {{ t('auth.registerSuccess.resend') }}
    </UButton>
    <p aria-live="polite" class="text-sm text-success">{{ status }}</p>
    <p v-if="error" role="alert" class="text-sm text-error">{{ error }}</p>
  </div>
</template>

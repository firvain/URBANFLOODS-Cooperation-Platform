<script setup lang="ts">
import { computed, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import { useApiErrors } from '@/composables/useApiErrors'
import { VERIFICATION_SENDER } from '@/constants/links'
import { turnstileRequired } from '@/constants/turnstile'
import { useAuthStore } from '@/stores/auth'
import TurnstileWidget from './TurnstileWidget.vue'

/**
 * "Check your email" state after registering, with a resend button. Registering does not sign in,
 * so the resend is anonymous and needs a Turnstile token. Names the sending address so people
 * can find the message in their Spam or Junk folder.
 */
const props = defineProps<{ email: string }>()

const { t } = useI18n()
const auth = useAuthStore()
const { errorMessage } = useApiErrors()

const pending = ref(false)
const status = ref('')
const error = ref('')
// Turnstile tokens are single-use: every request resets the widget for a fresh one, and submit
// waits for a solved challenge while Turnstile is on.
const turnstile = useTemplateRef<InstanceType<typeof TurnstileWidget>>('turnstile')
const turnstileToken = ref<string | null>(null)
const canSubmit = computed(
  () => !pending.value && (!turnstileRequired() || turnstileToken.value !== null),
)

async function resend() {
  if (!canSubmit.value) return
  status.value = ''
  error.value = ''
  pending.value = true
  try {
    await auth.resendVerification(props.email, turnstileToken.value)
    status.value = t('auth.resent')
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    turnstile.value?.reset()
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
    <p class="text-muted">
      {{ t('auth.registerSuccess.noEmail', { sender: VERIFICATION_SENDER }) }}
    </p>
    <TurnstileWidget ref="turnstile" v-model:token="turnstileToken" />
    <UButton
      color="neutral"
      variant="outline"
      icon="i-lucide-send"
      :loading="pending"
      :disabled="!canSubmit"
      @click="resend"
    >
      {{ t('auth.registerSuccess.resend') }}
    </UButton>
    <p aria-live="polite" class="text-sm text-success">{{ status }}</p>
    <p v-if="error" role="alert" class="text-sm text-error">{{ error }}</p>
  </div>
</template>

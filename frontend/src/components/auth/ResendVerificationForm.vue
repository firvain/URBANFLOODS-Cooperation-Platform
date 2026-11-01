<script setup lang="ts">
import { computed, reactive, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import type { FormError, FormSubmitEvent } from '@nuxt/ui'

import { useApiErrors } from '@/composables/useApiErrors'
import { turnstileRequired } from '@/constants/turnstile'
import { useAuthStore } from '@/stores/auth'
import TurnstileWidget from './TurnstileWidget.vue'

/** Email form asking for a new verification link. The answer is the same whether or not the address exists. */
const props = defineProps<{ email?: string }>()

const { t } = useI18n()
const auth = useAuthStore()
const { errorMessage, fieldMessage } = useApiErrors()

const state = reactive({ email: props.email ?? '' })
const status = ref('')
const error = ref('')
const pending = ref(false)
// Turnstile tokens are single-use: every request resets the widget for a fresh one, and submit
// waits for a solved challenge while Turnstile is on.
const turnstile = useTemplateRef<InstanceType<typeof TurnstileWidget>>('turnstile')
const turnstileToken = ref<string | null>(null)
const canSubmit = computed(
  () => !pending.value && (!turnstileRequired() || turnstileToken.value !== null),
)

function validate(s: Partial<typeof state>): FormError[] {
  return s.email?.trim() ? [] : [{ name: 'email', message: fieldMessage('required') }]
}

async function onSubmit(event: FormSubmitEvent<typeof state>) {
  if (!canSubmit.value) return
  status.value = ''
  error.value = ''
  pending.value = true
  try {
    await auth.resendVerification(event.data.email.trim(), turnstileToken.value)
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
  <UForm :state="state" :validate="validate" novalidate class="space-y-4" @submit="onSubmit">
    <p class="text-sm text-muted">{{ t('auth.verify.resendIntro') }}</p>
    <UFormField :label="t('auth.fields.email')" name="email" required>
      <UInput v-model="state.email" type="email" autocomplete="email" class="w-full" />
    </UFormField>
    <TurnstileWidget ref="turnstile" v-model:token="turnstileToken" />
    <UButton type="submit" icon="i-lucide-send" :loading="pending" :disabled="!canSubmit">
      {{ t('auth.verify.resend') }}
    </UButton>
    <p aria-live="polite" class="text-sm text-success">{{ status }}</p>
    <p v-if="error" role="alert" class="text-sm text-error">{{ error }}</p>
  </UForm>
</template>

<script setup lang="ts">
import { computed, reactive, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import type { FormError, FormSubmitEvent } from '@nuxt/ui'

import TurnstileWidget from '@/components/auth/TurnstileWidget.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import { turnstileRequired } from '@/constants/turnstile'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const auth = useAuthStore()
const { errorMessage, fieldMessage } = useApiErrors()

const state = reactive({ email: '' })
const pending = ref(false)
const sent = ref(false)
const formError = ref('')
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
  formError.value = ''
  pending.value = true
  try {
    // The backend answers 202 whether or not the account exists (no user enumeration).
    await auth.forgotPassword(event.data.email.trim(), turnstileToken.value)
    sent.value = true
  } catch (e) {
    formError.value = errorMessage(e)
  } finally {
    turnstile.value?.reset()
    pending.value = false
  }
}
</script>

<template>
  <UContainer class="max-w-md py-12">
    <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none">
      {{ t('auth.forgot.title') }}
    </h1>
    <p class="mt-3 text-muted">{{ t('auth.forgot.intro') }}</p>

    <div aria-live="polite" class="mt-8">
      <UAlert
        v-if="sent"
        color="success"
        variant="subtle"
        icon="i-lucide-mail-check"
        :description="t('auth.forgot.sent')"
      />
    </div>

    <UCard v-if="!sent">
      <UForm :state="state" :validate="validate" novalidate class="space-y-5" @submit="onSubmit">
        <div role="alert">
          <UAlert
            v-if="formError"
            color="error"
            variant="subtle"
            icon="i-lucide-circle-alert"
            :title="formError"
          />
        </div>
        <UFormField :label="t('auth.fields.email')" name="email" required>
          <UInput
            v-model="state.email"
            type="email"
            autocomplete="email"
            autocapitalize="off"
            class="w-full"
          />
        </UFormField>
        <TurnstileWidget ref="turnstile" v-model:token="turnstileToken" />
        <UButton type="submit" block :loading="pending" :disabled="!canSubmit" icon="i-lucide-send">
          {{ t('auth.forgot.submit') }}
        </UButton>
      </UForm>
    </UCard>

    <p class="mt-6 text-sm">
      <ULink to="/login" class="underline">{{ t('auth.forgot.backToLogin') }}</ULink>
    </p>
  </UContainer>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { FormError, FormSubmitEvent } from '@nuxt/ui'

import { useApiErrors } from '@/composables/useApiErrors'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const auth = useAuthStore()
const { errorMessage, fieldMessage } = useApiErrors()

const state = reactive({ email: '' })
const pending = ref(false)
const sent = ref(false)
const formError = ref('')

function validate(s: Partial<typeof state>): FormError[] {
  return s.email?.trim() ? [] : [{ name: 'email', message: fieldMessage('required') }]
}

async function onSubmit(event: FormSubmitEvent<typeof state>) {
  formError.value = ''
  pending.value = true
  try {
    // The backend answers 202 whether or not the account exists (no user enumeration).
    await auth.forgotPassword(event.data.email.trim())
    sent.value = true
  } catch (e) {
    formError.value = errorMessage(e)
  } finally {
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
        <UButton type="submit" block :loading="pending" icon="i-lucide-send">
          {{ t('auth.forgot.submit') }}
        </UButton>
      </UForm>
    </UCard>

    <p class="mt-6 text-sm">
      <ULink to="/login" class="underline">{{ t('auth.forgot.backToLogin') }}</ULink>
    </p>
  </UContainer>
</template>

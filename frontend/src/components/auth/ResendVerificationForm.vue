<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { FormError, FormSubmitEvent } from '@nuxt/ui'

import { useApiErrors } from '@/composables/useApiErrors'
import { useAuthStore } from '@/stores/auth'

/** Email form asking for a new verification link. The answer is the same whether or not the address exists. */
const props = defineProps<{ email?: string }>()

const { t } = useI18n()
const auth = useAuthStore()
const { errorMessage, fieldMessage } = useApiErrors()

const state = reactive({ email: props.email ?? '' })
const status = ref('')
const error = ref('')

function validate(s: Partial<typeof state>): FormError[] {
  return s.email?.trim() ? [] : [{ name: 'email', message: fieldMessage('required') }]
}

async function onSubmit(event: FormSubmitEvent<typeof state>) {
  status.value = ''
  error.value = ''
  try {
    await auth.resendVerification(event.data.email.trim())
    status.value = t('auth.resent')
  } catch (e) {
    error.value = errorMessage(e)
  }
}
</script>

<template>
  <UForm :state="state" :validate="validate" novalidate class="space-y-4" @submit="onSubmit">
    <p class="text-sm text-muted">{{ t('auth.verify.resendIntro') }}</p>
    <UFormField :label="t('auth.fields.email')" name="email" required>
      <UInput v-model="state.email" type="email" autocomplete="email" class="w-full" />
    </UFormField>
    <UButton type="submit" icon="i-lucide-send">{{ t('auth.verify.resend') }}</UButton>
    <p aria-live="polite" class="text-sm text-success">{{ status }}</p>
    <p v-if="error" role="alert" class="text-sm text-error">{{ error }}</p>
  </UForm>
</template>

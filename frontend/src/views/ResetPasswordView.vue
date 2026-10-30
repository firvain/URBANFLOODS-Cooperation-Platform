<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '@nuxt/ui/composables'
import type { FormError, FormSubmitEvent } from '@nuxt/ui'

import PasswordField from '@/components/auth/PasswordField.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from '@/constants/auth'
import { ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const toast = useToast()
const auth = useAuthStore()
const { errorMessage, fieldMessage, fieldErrors } = useApiErrors()

const token = computed(() => (typeof route.query.token === 'string' ? route.query.token : ''))
const state = reactive({ password: '', confirm: '' })
const pending = ref(false)
const formError = ref('')
const tokenRejected = ref(false)
/** No token in the link, or the backend said it is invalid/expired: offer a new link. */
const tokenInvalid = computed(() => !token.value || tokenRejected.value)
const alertText = computed(
  () => formError.value || (token.value ? '' : t('errors.api.auth.token_invalid')),
)
const passwordServerError = ref<string>()

watch(
  () => state.password,
  () => (passwordServerError.value = undefined),
)

function validate(s: Partial<typeof state>): FormError[] {
  const errors: FormError[] = []
  if (!s.password) errors.push({ name: 'password', message: fieldMessage('required') })
  else if (s.password.length < PASSWORD_MIN_LENGTH || !s.password.trim())
    errors.push({ name: 'password', message: fieldMessage('auth.password_too_short') })
  else if (s.password.length > PASSWORD_MAX_LENGTH)
    errors.push({ name: 'password', message: fieldMessage('auth.password_too_long') })
  if (!s.confirm) errors.push({ name: 'confirm', message: fieldMessage('required') })
  else if (s.confirm !== s.password)
    errors.push({ name: 'confirm', message: fieldMessage('password_mismatch') })
  return errors
}

async function onSubmit(event: FormSubmitEvent<typeof state>) {
  formError.value = ''
  pending.value = true
  try {
    await auth.resetPassword(token.value, event.data.password)
  } catch (e) {
    passwordServerError.value = fieldErrors(e).password
    tokenRejected.value = e instanceof ApiError && e.code === 'auth.token_invalid'
    formError.value = passwordServerError.value
      ? t('errors.api.validation.failed')
      : errorMessage(e)
    return
  } finally {
    pending.value = false
  }
  toast.add({ title: t('auth.reset.success'), color: 'success', icon: 'i-lucide-circle-check' })
  await router.push('/')
}
</script>

<template>
  <UContainer class="max-w-md py-12">
    <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none">
      {{ t('auth.reset.title') }}
    </h1>
    <p class="mt-3 text-muted">{{ t('auth.reset.intro') }}</p>

    <div role="alert" class="mt-8">
      <UAlert
        v-if="alertText"
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :title="alertText"
      />
    </div>
    <p v-if="tokenInvalid" class="mt-4 text-sm">
      <ULink to="/forgot-password" class="underline">{{ t('auth.reset.requestNew') }}</ULink>
    </p>

    <UCard v-if="token" class="mt-6">
      <UForm :state="state" :validate="validate" novalidate class="space-y-5" @submit="onSubmit">
        <UFormField
          :label="t('auth.fields.newPassword')"
          name="password"
          required
          :help="t('auth.fields.passwordHint', { min: PASSWORD_MIN_LENGTH })"
          :error="passwordServerError"
        >
          <PasswordField v-model="state.password" autocomplete="new-password" />
        </UFormField>
        <UFormField :label="t('auth.fields.confirmPassword')" name="confirm" required>
          <PasswordField v-model="state.confirm" autocomplete="new-password" />
        </UFormField>
        <UButton type="submit" block :loading="pending" icon="i-lucide-key-round">
          {{ t('auth.reset.submit') }}
        </UButton>
      </UForm>
    </UCard>
  </UContainer>
</template>

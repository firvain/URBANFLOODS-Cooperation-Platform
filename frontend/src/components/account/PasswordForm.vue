<script setup lang="ts">
import { reactive, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from '@nuxt/ui/composables'
import type { FormError, FormSubmitEvent } from '@nuxt/ui'

import PasswordField from '@/components/auth/PasswordField.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from '@/constants/auth'
import { ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const toast = useToast()
const auth = useAuthStore()
const { errorMessage, fieldMessage, fieldErrors } = useApiErrors()

const empty = () => ({ current: '', password: '', confirm: '' })
const state = reactive(empty())
type State = typeof state

const pending = ref(false)
const formError = ref('')
const status = ref('')
const currentError = ref<string>()
const newError = ref<string>()
const form = useTemplateRef<{ clear: () => void }>('form')

watch(
  () => state.current,
  () => (currentError.value = undefined),
)
watch(
  () => state.password,
  () => (newError.value = undefined),
)

function validate(s: Partial<State>): FormError[] {
  const errors: FormError[] = []
  if (!s.current) errors.push({ name: 'current', message: fieldMessage('required') })
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

async function onSubmit(event: FormSubmitEvent<State>) {
  formError.value = ''
  status.value = ''
  pending.value = true
  try {
    await auth.changePassword(event.data.current, event.data.password)
  } catch (e) {
    const fields = fieldErrors(e)
    if (e instanceof ApiError && e.code === 'auth.invalid_credentials')
      currentError.value = t('account.password.wrongCurrent')
    else if (fields.current_password) currentError.value = fields.current_password
    newError.value = fields.new_password
    formError.value =
      currentError.value || newError.value ? t('errors.api.validation.failed') : errorMessage(e)
    return
  } finally {
    pending.value = false
  }
  Object.assign(state, empty())
  form.value?.clear()
  status.value = t('account.password.changed')
  toast.add({ title: status.value, color: 'success', icon: 'i-lucide-circle-check' })
}
</script>

<template>
  <UForm
    ref="form"
    :state="state"
    :validate="validate"
    novalidate
    class="space-y-5"
    @submit="onSubmit"
  >
    <p class="text-sm text-muted">{{ t('account.password.intro') }}</p>

    <div role="alert">
      <UAlert
        v-if="formError"
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :title="formError"
      />
    </div>

    <UFormField
      :label="t('account.password.current')"
      name="current"
      required
      :error="currentError"
    >
      <PasswordField v-model="state.current" autocomplete="current-password" />
    </UFormField>

    <UFormField
      :label="t('auth.fields.newPassword')"
      name="password"
      required
      :help="t('auth.fields.passwordHint', { min: PASSWORD_MIN_LENGTH })"
      :error="newError"
    >
      <PasswordField v-model="state.password" autocomplete="new-password" />
    </UFormField>

    <UFormField :label="t('auth.fields.confirmPassword')" name="confirm" required>
      <PasswordField v-model="state.confirm" autocomplete="new-password" />
    </UFormField>

    <div class="flex flex-wrap items-center gap-4">
      <UButton type="submit" :loading="pending" icon="i-lucide-key-round">
        {{ t('account.password.submit') }}
      </UButton>
      <p aria-live="polite" class="text-sm text-success">{{ status }}</p>
    </div>
  </UForm>
</template>

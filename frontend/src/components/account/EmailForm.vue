<script setup lang="ts">
import { reactive, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from '@nuxt/ui/composables'
import type { FormError, FormSubmitEvent } from '@nuxt/ui'

import PasswordField from '@/components/auth/PasswordField.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import { ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const toast = useToast()
const auth = useAuthStore()
const { errorMessage, fieldMessage, fieldErrors } = useApiErrors()

/** A light shape check only; the server validates the address properly. */
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const empty = () => ({ new_email: '', current_password: '' })
const state = reactive(empty())
type State = typeof state

const pending = ref(false)
const formError = ref('')
const status = ref('')
const emailError = ref<string>()
const passwordError = ref<string>()
const form = useTemplateRef<{ clear: () => void }>('form')

watch(
  () => state.new_email,
  () => (emailError.value = undefined),
)
watch(
  () => state.current_password,
  () => (passwordError.value = undefined),
)

function validate(s: Partial<State>): FormError[] {
  const errors: FormError[] = []
  const address = s.new_email?.trim()
  if (!address) errors.push({ name: 'new_email', message: fieldMessage('required') })
  else if (!EMAIL_SHAPE.test(address))
    errors.push({ name: 'new_email', message: fieldMessage('invalid') })
  if (!s.current_password)
    errors.push({ name: 'current_password', message: fieldMessage('required') })
  return errors
}

async function onSubmit(event: FormSubmitEvent<State>) {
  formError.value = ''
  status.value = ''
  pending.value = true
  const address = event.data.new_email.trim()
  try {
    await auth.requestEmailChange(address, event.data.current_password)
  } catch (e) {
    const fields = fieldErrors(e)
    if (e instanceof ApiError && e.code === 'auth.invalid_credentials')
      passwordError.value = t('account.password.wrongCurrent')
    else if (fields.current_password) passwordError.value = fields.current_password
    if (e instanceof ApiError && e.fields?.new_email === 'auth.email_same')
      emailError.value = t('account.email.same')
    else emailError.value = fields.new_email
    formError.value =
      emailError.value || passwordError.value ? t('errors.api.validation.failed') : errorMessage(e)
    return
  } finally {
    pending.value = false
  }
  Object.assign(state, empty())
  form.value?.clear()
  status.value = t('account.email.sent', { email: address })
  toast.add({ title: status.value, color: 'success', icon: 'i-lucide-mail-check' })
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
    <p class="text-sm text-muted">{{ t('account.email.intro') }}</p>

    <p class="text-sm">
      <span class="text-muted">{{ t('account.email.current') }}</span>
      {{ ' ' }}
      <span class="font-medium text-highlighted">{{ auth.user?.email }}</span>
    </p>

    <div role="alert">
      <UAlert
        v-if="formError"
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :title="formError"
      />
    </div>

    <UFormField :label="t('account.email.newEmail')" name="new_email" required :error="emailError">
      <UInput
        v-model="state.new_email"
        type="email"
        autocomplete="email"
        autocapitalize="off"
        spellcheck="false"
        class="w-full"
      />
    </UFormField>

    <UFormField
      :label="t('account.password.current')"
      name="current_password"
      required
      :error="passwordError"
    >
      <PasswordField v-model="state.current_password" autocomplete="current-password" />
    </UFormField>

    <div class="flex flex-wrap items-center gap-4">
      <UButton type="submit" :loading="pending" icon="i-lucide-mail">
        {{ t('account.email.submit') }}
      </UButton>
      <p aria-live="polite" class="text-sm text-success">{{ status }}</p>
    </div>
  </UForm>
</template>

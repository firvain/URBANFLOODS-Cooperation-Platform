<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import type { FormError, FormSubmitEvent } from '@nuxt/ui'

import PasswordField from './PasswordField.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import { safeRedirect } from '@/router/redirect'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const { errorMessage, fieldMessage } = useApiErrors()

const state = reactive({ email: '', password: '' })
const pending = ref(false)
const formError = ref('')

function validate(s: Partial<typeof state>): FormError[] {
  const errors: FormError[] = []
  if (!s.email?.trim()) errors.push({ name: 'email', message: fieldMessage('required') })
  if (!s.password) errors.push({ name: 'password', message: fieldMessage('required') })
  return errors
}

async function onSubmit(event: FormSubmitEvent<typeof state>) {
  formError.value = ''
  pending.value = true
  try {
    await auth.login(event.data.email.trim(), event.data.password)
  } catch (e) {
    formError.value = errorMessage(e)
    return
  } finally {
    pending.value = false
  }
  await router.push(safeRedirect(route.query.next) ?? '/')
}
</script>

<template>
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

    <UFormField :label="t('auth.fields.password')" name="password" required>
      <PasswordField v-model="state.password" autocomplete="current-password" />
    </UFormField>

    <UButton type="submit" block :loading="pending" icon="i-lucide-log-in">
      {{ t('auth.loginPage.submit') }}
    </UButton>
  </UForm>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import { useApiErrors } from '@/composables/useApiErrors'
import { ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const route = useRoute()
const auth = useAuthStore()
const { errorMessage } = useApiErrors()

const state = ref<'confirming' | 'success' | 'error'>('confirming')
const error = ref('')
const newEmail = ref('')

onMounted(async () => {
  const token = typeof route.query.token === 'string' ? route.query.token : ''
  try {
    if (!token) throw new ApiError(400, 'auth.token_invalid')
    // Updates the store only when this account is the one signed in here.
    newEmail.value = (await auth.confirmEmailChange(token)).email
    state.value = 'success'
  } catch (e) {
    error.value = errorMessage(e)
    state.value = 'error'
  }
})
</script>

<template>
  <UContainer class="max-w-lg py-12">
    <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none">
      {{ t('auth.confirmEmail.title') }}
    </h1>

    <div aria-live="polite" class="mt-8">
      <p v-if="state === 'confirming'" class="flex items-center gap-2 text-muted">
        <UIcon name="i-lucide-loader-circle" class="size-5 animate-spin" aria-hidden="true" />
        {{ t('auth.confirmEmail.confirming') }}
      </p>
      <UAlert
        v-else-if="state === 'success'"
        color="success"
        variant="subtle"
        icon="i-lucide-circle-check"
        :title="t('auth.confirmEmail.success')"
        :description="t('auth.confirmEmail.nowUsing', { email: newEmail })"
      />
    </div>

    <template v-if="state === 'success'">
      <UButton v-if="auth.isAuthenticated" to="/account" class="mt-6" icon="i-lucide-user-round">
        {{ t('auth.confirmEmail.goToAccount') }}
      </UButton>
      <UButton v-else to="/login" class="mt-6" icon="i-lucide-log-in">
        {{ t('auth.confirmEmail.signIn') }}
      </UButton>
    </template>

    <template v-if="state === 'error'">
      <div role="alert">
        <UAlert
          color="error"
          variant="subtle"
          icon="i-lucide-circle-alert"
          :title="t('auth.confirmEmail.failed')"
          :description="error"
        />
      </div>
      <p class="mt-6 text-muted">{{ t('auth.confirmEmail.retryHint') }}</p>
      <UButton
        v-if="auth.isAuthenticated"
        to="/account?tab=password"
        class="mt-4"
        icon="i-lucide-user-round"
      >
        {{ t('auth.confirmEmail.goToAccount') }}
      </UButton>
      <UButton v-else to="/login" class="mt-4" icon="i-lucide-log-in">
        {{ t('auth.confirmEmail.signIn') }}
      </UButton>
    </template>
  </UContainer>
</template>

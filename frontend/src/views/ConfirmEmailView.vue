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

/**
 * The token is sent only when the person presses the button: mail-security scanners open
 * links in a sandboxed browser that runs JavaScript, and would otherwise spend the single-use
 * token before the person clicks.
 */
const state = ref<'ready' | 'confirming' | 'success' | 'error'>('ready')
const error = ref('')
const token = ref('')
const newEmail = ref('')

function fail(e: unknown) {
  error.value = errorMessage(e)
  state.value = 'error'
}

onMounted(() => {
  token.value = typeof route.query.token === 'string' ? route.query.token : ''
  if (!token.value) fail(new ApiError(400, 'auth.token_invalid'))
})

async function confirmChange() {
  if (state.value !== 'ready') return
  state.value = 'confirming'
  try {
    // Updates the store only when this account is the one signed in here.
    newEmail.value = (await auth.confirmEmailChange(token.value)).email
    state.value = 'success'
  } catch (e) {
    fail(e)
  }
}
</script>

<template>
  <UContainer class="max-w-lg py-12">
    <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none">
      {{ t('auth.confirmEmail.title') }}
    </h1>

    <template v-if="state === 'ready' || state === 'confirming'">
      <p class="mt-8 text-muted">{{ t('auth.confirmEmail.prompt') }}</p>
      <UButton
        type="button"
        class="mt-6"
        icon="i-lucide-mail-check"
        :loading="state === 'confirming'"
        :disabled="state === 'confirming'"
        @click="confirmChange"
      >
        {{ t('auth.confirmEmail.button') }}
      </UButton>
    </template>

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

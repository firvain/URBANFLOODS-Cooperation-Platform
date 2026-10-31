<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import CompleteProfileBanner from '@/components/account/CompleteProfileBanner.vue'
import ResendVerificationForm from '@/components/auth/ResendVerificationForm.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import { AUTH_REDIRECT_DELAY_MS } from '@/constants/auth'
import { ApiError } from '@/services/api'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { errorMessage } = useApiErrors()

const state = ref<'verifying' | 'success' | 'error'>('verifying')
const error = ref('')
/** A new member with no expertise yet: the success state points to the profile. */
const needsExpertise = computed(() => auth.user?.expertise.length === 0)
let redirectTimer: ReturnType<typeof setTimeout> | undefined

onMounted(async () => {
  const token = typeof route.query.token === 'string' ? route.query.token : ''
  try {
    if (!token) throw new ApiError(400, 'auth.token_invalid')
    await auth.verifyEmail(token)
    state.value = 'success'
    redirectTimer = setTimeout(() => router.push('/'), AUTH_REDIRECT_DELAY_MS)
  } catch (e) {
    error.value = errorMessage(e)
    state.value = 'error'
  }
})

onBeforeUnmount(() => clearTimeout(redirectTimer))
</script>

<template>
  <UContainer class="max-w-lg py-12">
    <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none">
      {{ t('auth.verify.title') }}
    </h1>

    <div aria-live="polite" class="mt-8">
      <p v-if="state === 'verifying'" class="flex items-center gap-2 text-muted">
        <UIcon name="i-lucide-loader-circle" class="size-5 animate-spin" aria-hidden="true" />
        {{ t('auth.verify.verifying') }}
      </p>
      <UAlert
        v-else-if="state === 'success'"
        color="success"
        variant="subtle"
        icon="i-lucide-circle-check"
        :title="t('auth.verify.success')"
        :description="
          needsExpertise ? t('auth.verify.redirectingProfile') : t('auth.verify.redirecting')
        "
      />
    </div>

    <CompleteProfileBanner v-if="state === 'success'" class="mt-6" />

    <UButton v-if="state === 'success'" to="/" class="mt-6" icon="i-lucide-house">
      {{ t('auth.verify.continue') }}
    </UButton>

    <template v-if="state === 'error'">
      <div role="alert">
        <UAlert
          color="error"
          variant="subtle"
          icon="i-lucide-circle-alert"
          :title="t('auth.verify.failed')"
          :description="error"
        />
      </div>
      <UCard class="mt-8">
        <ResendVerificationForm :email="auth.user?.email" />
      </UCard>
    </template>
  </UContainer>
</template>

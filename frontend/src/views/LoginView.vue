<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import LoginForm from '@/components/auth/LoginForm.vue'

const { t } = useI18n()
</script>

<template>
  <UContainer class="max-w-md py-12">
    <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none">
      {{ t('auth.login') }}
    </h1>
    <p class="mt-3 text-muted">{{ t('auth.loginPage.intro') }}</p>

    <UCard class="mt-8">
      <LoginForm />
    </UCard>

    <ul class="mt-6 space-y-2 text-sm">
      <li>
        <ULink to="/forgot-password" class="underline">{{ t('auth.loginPage.forgot') }}</ULink>
      </li>
      <li class="text-muted">
        {{ t('auth.loginPage.noAccount') }}
        <ULink to="/register" class="underline">{{ t('auth.register') }}</ULink>
      </li>
    </ul>
  </UContainer>
</template>

<script setup lang="ts">
import { nextTick, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import RegisterForm from '@/components/auth/RegisterForm.vue'
import RegisterSuccess from '@/components/auth/RegisterSuccess.vue'

const { t } = useI18n()
const registeredEmail = ref<string | null>(null)
const heading = useTemplateRef<HTMLElement>('heading')

async function onRegistered(email: string) {
  registeredEmail.value = email
  window.scrollTo?.({ top: 0 })
  // The page content changed completely: move focus to the new heading, as on navigation.
  await nextTick()
  heading.value?.focus()
}
</script>

<template>
  <UContainer class="max-w-xl py-12">
    <h1 ref="heading" tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none">
      {{ registeredEmail ? t('auth.registerSuccess.title') : t('auth.registerPage.title') }}
    </h1>

    <template v-if="registeredEmail">
      <div class="mt-8">
        <RegisterSuccess :email="registeredEmail" />
      </div>
    </template>

    <template v-else>
      <p class="mt-3 text-muted">{{ t('auth.registerPage.intro') }}</p>
      <UCard class="mt-8">
        <RegisterForm @registered="onRegistered" />
      </UCard>
      <p class="mt-6 text-sm text-muted">
        {{ t('auth.registerPage.haveAccount') }}
        <ULink to="/login" class="underline">{{ t('auth.login') }}</ULink>
      </p>
    </template>
  </UContainer>
</template>

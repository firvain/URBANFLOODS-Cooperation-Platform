<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <UContainer class="py-16 text-center">
    <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none">
      {{ t('errors.notFound') }}
    </h1>
    <p class="mt-4 text-muted">{{ t('errors.notFoundDescription') }}</p>
    <UButton to="/" icon="i-lucide-house" class="mt-8">{{ t('errors.backHome') }}</UButton>
  </UContainer>
</template>

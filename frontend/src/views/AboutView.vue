<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <UContainer class="py-12">
    <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none">
      {{ t('nav.about') }}
    </h1>
    <p class="mt-4 max-w-3xl text-muted">{{ t('about.intro') }}</p>
  </UContainer>
</template>

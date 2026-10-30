<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <UContainer class="py-12">
    <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none">
      {{ t('nav.account') }}
    </h1>
    <p class="mt-4 text-muted">{{ t('account.intro') }}</p>
  </UContainer>
</template>

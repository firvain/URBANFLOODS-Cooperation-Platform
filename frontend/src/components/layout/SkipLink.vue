<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <a
    href="#main"
    class="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-100 focus:rounded-md focus:bg-primary-700 focus:px-4 focus:py-2 focus:text-white focus-ring"
  >
    {{ t('app.skipToContent') }}
  </a>
</template>

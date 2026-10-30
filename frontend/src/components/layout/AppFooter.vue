<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const year = new Date().getFullYear()
</script>

<template>
  <UFooter :ui="{ root: 'border-t border-default' }">
    <template #left>
      <p class="max-w-3xl text-xs leading-relaxed text-muted">
        {{ t('footer.disclaimer') }}
      </p>
    </template>

    <template #right>
      <p class="text-sm font-semibold text-toned">
        {{ t('footer.copyright', { year }) }}
      </p>
    </template>
  </UFooter>
</template>

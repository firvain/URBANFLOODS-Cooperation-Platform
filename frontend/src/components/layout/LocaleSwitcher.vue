<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { useLocale } from '@/composables/useLocale'

const { t } = useI18n()
const { locale, locales } = useLocale()

const items = computed(() => locales.map((l) => ({ value: l.code, label: l.nativeName })))
</script>

<template>
  <USelect
    v-model="locale"
    :items="items"
    :aria-label="t('app.language')"
    icon="i-lucide-languages"
    size="sm"
    class="w-40"
  />
</template>

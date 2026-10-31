<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { useLocale } from '@/composables/useLocale'

/**
 * The UI language. In the header it is compact below 2xl (globe + "EN"), so the navigation and
 * the search field fit beside the logo at 1280 px; from 2xl, and always in the mobile menu
 * (`full`), it shows the language's own name. The trigger's `aria-label` always names the
 * current language in full; the dropdown lists the full names.
 */
const props = withDefaults(defineProps<{ full?: boolean }>(), { full: false })

const { t } = useI18n()
const { locale, locales } = useLocale()

const items = computed(() => locales.map((l) => ({ value: l.code, label: l.nativeName })))
const current = computed(() => locales.find((l) => l.code === locale.value))
const label = computed(() => `${t('app.language')}: ${current.value?.nativeName ?? locale.value}`)
</script>

<template>
  <USelect
    v-model="locale"
    :items="items"
    :aria-label="label"
    data-testid="locale-switcher"
    icon="i-lucide-globe"
    size="sm"
    :class="props.full ? 'w-40' : 'w-auto 2xl:w-40'"
  >
    <template #default>
      <span v-if="!props.full" data-testid="locale-code" class="2xl:hidden" aria-hidden="true">
        {{ locale.toUpperCase() }}
      </span>
      <span
        data-testid="locale-name"
        :class="props.full ? 'truncate' : 'hidden truncate 2xl:inline'"
        aria-hidden="true"
      >
        {{ current?.nativeName }}
      </span>
    </template>
  </USelect>
</template>

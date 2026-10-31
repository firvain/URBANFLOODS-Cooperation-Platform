<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { SEARCH_MAX_LENGTH } from '@/constants/search'

/**
 * The header's search box: submits to `/search?q=…` (Enter submits). From xl it sits beside the
 * navigation collapsed to its search icon (the header row has no room for a 144 px field beside
 * the logo, eight nav items, the account buttons and the language switcher in the 1280 px page
 * container); focused or filled, it widens leftwards over the navigation. `mobile` is the
 * full-width variant with a submit button for the menu body.
 */
withDefaults(defineProps<{ mobile?: boolean }>(), { mobile: false })

const { t } = useI18n()
const router = useRouter()
const q = ref('')

async function submit() {
  const value = q.value.trim()
  await router.push({ name: 'search', query: value ? { q: value } : {} })
  q.value = ''
}
</script>

<template>
  <form
    role="search"
    :aria-label="t('search.formLabel')"
    :class="mobile ? 'flex w-full gap-2' : 'relative hidden h-8 w-8 shrink-0 items-center xl:flex'"
    @submit.prevent="submit"
  >
    <UInput
      v-if="mobile"
      v-model="q"
      type="search"
      name="q"
      icon="i-lucide-search"
      :aria-label="t('search.inputLabel')"
      :placeholder="t('search.placeholder')"
      :maxlength="SEARCH_MAX_LENGTH"
      class="min-w-0 flex-1"
    />
    <UInput
      v-else
      v-model="q"
      type="search"
      name="q"
      icon="i-lucide-search"
      size="sm"
      :aria-label="t('search.inputLabel')"
      :placeholder="t('search.headerPlaceholder')"
      :maxlength="SEARCH_MAX_LENGTH"
      :class="[
        'absolute end-0 z-10 bg-default transition-[width] duration-200',
        q ? 'w-56' : 'w-8 focus-within:w-56',
      ]"
    />
    <UButton v-if="mobile" type="submit" icon="i-lucide-search" :aria-label="t('search.submit')" />
  </form>
</template>

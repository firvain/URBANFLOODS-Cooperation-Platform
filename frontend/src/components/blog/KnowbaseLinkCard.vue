<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { components } from '@/types/api-schema'

type KnowbaseLinkOut = components['schemas']['KnowbaseLinkOut']

/** A KNOWBASE measure or document linked from a post, pointing to its item page on the platform. */
const props = defineProps<{ link: KnowbaseLinkOut }>()

const { t } = useI18n()

/** Built from the type and id (not the API's `url`), so it always stays inside the app. */
const to = computed(() => `/knowbase/${props.link.kb_type}s/${props.link.kb_id}`)
const localTitle = computed(() => {
  const local = props.link.title_local
  return local && local !== props.link.title_en ? local : null
})
</script>

<template>
  <li
    data-testid="kb-link-card"
    class="flex h-full items-start gap-3 rounded border border-secondary-200 bg-secondary-50 p-3"
  >
    <UIcon
      :name="link.kb_type === 'measure' ? 'i-lucide-shield-check' : 'i-lucide-file-text'"
      class="mt-0.5 size-5 shrink-0 text-primary"
      aria-hidden="true"
    />
    <div class="min-w-0 space-y-1">
      <p class="text-xs font-medium tracking-wide text-gray-700 uppercase">
        {{ t(`post.knowbase.${link.kb_type}`) }}
      </p>
      <ULink
        :to="to"
        raw
        class="block font-medium text-primary-700 underline underline-offset-2 hover:text-primary-800"
      >
        {{ link.title_en }}
      </ULink>
      <p v-if="localTitle" lang="" class="text-sm text-gray-700 italic">{{ localTitle }}</p>
    </div>
  </li>
</template>

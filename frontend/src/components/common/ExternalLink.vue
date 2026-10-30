<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

/**
 * Link to another site, opened in a new tab without giving it `window.opener` or a referrer.
 * Screen readers hear a visually hidden "(opens in a new tab)" after the label.
 * `subtle` is the muted footer style (underline only on hover/focus).
 */
const props = defineProps<{
  href: string
  icon?: string
  trailingIcon?: string
  subtle?: boolean
}>()

const { t } = useI18n()

const linkClass = computed(() =>
  props.subtle
    ? 'text-sm text-muted underline-offset-2 hover:text-highlighted hover:underline focus-visible:underline'
    : 'inline-flex items-center gap-1.5 font-medium text-primary underline underline-offset-2 hover:text-primary-700',
)
</script>

<template>
  <ULink :to="href" target="_blank" rel="noopener noreferrer" raw :class="linkClass">
    <!-- Inline (not flex) in the subtle style so a wrapped label keeps the arrow after its last word. -->
    <UIcon
      v-if="icon"
      :name="icon"
      :data-icon="icon"
      :class="subtle ? 'me-1.5 inline-block size-4 align-[-3px]' : 'size-4 shrink-0'"
      aria-hidden="true"
    />
    <slot />
    <UIcon
      v-if="trailingIcon"
      :name="trailingIcon"
      :data-icon="trailingIcon"
      :class="subtle ? 'ms-0.5 inline-block size-3.5 align-[-2px]' : 'size-3.5 shrink-0'"
      aria-hidden="true"
    />
    <span class="sr-only">{{ ` ${t('a11y.opensInNewTab')}` }}</span>
  </ULink>
</template>

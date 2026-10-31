<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import SafeHtml from '@/components/common/SafeHtml.vue'
import { LEGAL_TITLE_KEYS, type LegalDoc } from '@/constants/legal'
import { LEGAL_DOCUMENTS } from '@/content/legal'
import { renderMarkdown } from '@/utils/markdown'

/** Terms, privacy, accessibility or open data, rendered from `docs/legal/*.md` (English only). */
const props = defineProps<{ doc: LegalDoc }>()

const { t, locale } = useI18n()

const legal = computed(() => {
  const prepared = LEGAL_DOCUMENTS[props.doc]
  const { html, headings } = renderMarkdown(prepared.markdown)
  return {
    ...prepared,
    html,
    sections: headings.filter((heading) => heading.depth === 2),
  }
})
</script>

<template>
  <UContainer class="pt-8 pb-4 lg:pb-24">
    <div class="mx-auto max-w-4xl">
      <div class="mb-8">
        <h1 tabindex="-1" class="mb-4 text-4xl font-bold text-primary-600 focus:outline-none">
          {{ t(LEGAL_TITLE_KEYS[doc]) }}
        </h1>
        <div class="h-1 w-20 rounded bg-secondary-500" />
        <p
          v-if="legal.version && legal.date"
          data-testid="legal-version"
          class="mt-4 text-sm text-muted"
        >
          {{ t('legal.version', { version: legal.version, date: legal.date }) }}
        </p>
        <p v-if="locale !== 'en'" class="mt-2 text-sm text-muted">{{ t('legal.englishOnly') }}</p>
      </div>

      <nav
        :aria-label="t('legal.contents')"
        class="mb-8 rounded-lg border-l-4 border-primary-500 bg-primary-50 p-4"
      >
        <p class="mb-2 text-sm font-semibold text-gray-500 uppercase" aria-hidden="true">
          {{ t('legal.contents') }}
        </p>
        <ul class="grid gap-x-6 gap-y-1.5 sm:grid-cols-2" lang="en">
          <li v-for="section in legal.sections" :key="section.id">
            <a
              :href="`#${section.id}`"
              class="text-sm text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
              >{{ section.text }}</a
            >
          </li>
        </ul>
      </nav>

      <UCard>
        <SafeHtml :html="legal.html" lang="en" class="legal-prose" />
      </UCard>
    </div>
  </UContainer>
</template>

<!--
  Typography for the rendered markdown (Tailwind Typography is not installed). `:deep` because
  v-html content does not carry the scoped attribute.
-->
<style scoped>
.legal-prose {
  color: var(--ui-text);
  line-height: 1.7;
}

.legal-prose :deep(h2) {
  margin: 2.25rem 0 0.75rem;
  font-size: 1.375rem;
  font-weight: 700;
  line-height: 1.3;
  color: var(--color-primary-600);
  scroll-margin-top: calc(var(--ui-header-height) + 1rem);
}

.legal-prose :deep(h2:first-child) {
  margin-top: 0;
}

.legal-prose :deep(h3) {
  margin: 1.75rem 0 0.5rem;
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--color-primary-700);
  scroll-margin-top: calc(var(--ui-header-height) + 1rem);
}

.legal-prose :deep(p) {
  margin: 0.75rem 0;
}

.legal-prose :deep(ul),
.legal-prose :deep(ol) {
  margin: 0.75rem 0;
  padding-inline-start: 1.5rem;
}

.legal-prose :deep(ul) {
  list-style: disc;
}

.legal-prose :deep(ol) {
  list-style: decimal;
}

.legal-prose :deep(li) {
  margin: 0.375rem 0;
}

.legal-prose :deep(a) {
  color: var(--color-primary-600);
  text-decoration: underline;
  text-underline-offset: 2px;
  overflow-wrap: anywhere;
}

.legal-prose :deep(a:hover) {
  color: var(--color-primary-800);
}

.legal-prose :deep(blockquote) {
  margin: 1rem 0;
  padding: 0.25rem 1rem;
  border-inline-start: 4px solid var(--color-secondary-300);
  background-color: var(--color-primary-50);
}

.legal-prose :deep(strong) {
  font-weight: 600;
}

.legal-prose :deep(hr) {
  margin: 2rem 0;
  border: 0;
  border-top: 1px solid var(--color-secondary-200);
}

.legal-prose :deep(.legal-table) {
  margin: 1rem 0;
  border: 1px solid var(--ui-border);
  border-radius: 0.5rem;
}

.legal-prose :deep(.legal-table:focus-visible) {
  outline: 3px solid var(--color-secondary-500);
  outline-offset: 2px;
}

.legal-prose :deep(table) {
  width: 100%;
  min-width: 40rem;
  border-collapse: collapse;
  font-size: 0.875rem;
  line-height: 1.5;
}

.legal-prose :deep(th),
.legal-prose :deep(td) {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--ui-border);
  text-align: start;
  vertical-align: top;
}

.legal-prose :deep(th) {
  background-color: var(--color-primary-50);
  font-weight: 600;
  color: var(--color-primary-700);
}

.legal-prose :deep(tr:last-child td) {
  border-bottom: 0;
}
</style>

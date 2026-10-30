<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

// Placeholders until the blog (M2), forum (M3) and KNOWBASE browser (M2) routes exist.
const sections = [
  { key: 'blog', icon: 'i-lucide-newspaper' },
  { key: 'forum', icon: 'i-lucide-messages-square' },
  { key: 'knowbase', icon: 'i-lucide-library' },
] as const
</script>

<template>
  <UContainer class="py-12">
    <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none sm:text-4xl">
      {{ t('home.title') }}
    </h1>
    <p class="mt-4 max-w-3xl text-lg text-muted">{{ t('home.intro') }}</p>

    <ul class="mt-10 grid gap-6 md:grid-cols-3">
      <li v-for="section in sections" :key="section.key">
        <UCard class="h-full">
          <template #header>
            <div class="flex items-center justify-between gap-2">
              <h2 class="flex items-center gap-2 text-lg font-semibold text-highlighted">
                <UIcon :name="section.icon" class="size-5 text-primary" aria-hidden="true" />
                {{ t(`home.cards.${section.key}.title`) }}
              </h2>
              <UBadge color="neutral" variant="subtle" size="sm">{{ t('home.comingSoon') }}</UBadge>
            </div>
          </template>
          <p class="text-muted">{{ t(`home.cards.${section.key}.description`) }}</p>
        </UCard>
      </li>
    </ul>
  </UContainer>
</template>

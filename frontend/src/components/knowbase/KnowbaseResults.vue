<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { KB_PAGE_SIZE } from '@/constants/knowbase'

/**
 * Result area of a KNOWBASE list: skeletons on the first load, an error with retry, the count,
 * an empty state (with "Clear filters" when filtered), the grid (default slot) and pagination.
 */
defineProps<{
  total: number
  page: number
  count: string
  empty: string
  loadError: string
  paginationLabel: string
  hasItems: boolean
  hasFilters: boolean
  loading: boolean
  initialLoading: boolean
  failed: boolean
}>()

const emit = defineEmits<{ retry: []; clear: []; page: [page: number] }>()

const { t } = useI18n()
</script>

<template>
  <div class="min-w-0 space-y-4">
    <div v-if="initialLoading" data-testid="kb-loading" aria-busy="true">
      <span class="sr-only">{{ t('knowbase.loading') }}</span>
      <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <USkeleton v-for="n in 6" :key="n" class="h-64 w-full" />
      </div>
    </div>

    <div v-else-if="failed" role="alert">
      <UAlert
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :title="loadError"
        :actions="[
          {
            label: t('knowbase.retry'),
            color: 'error',
            variant: 'outline',
            icon: 'i-lucide-rotate-cw',
            onClick: () => emit('retry'),
          },
        ]"
      />
    </div>

    <template v-else>
      <p data-testid="kb-count" role="status" class="text-sm font-medium text-gray-700">
        {{ count }}
      </p>

      <div v-if="!hasItems" class="rounded border border-default p-6 text-center">
        <p class="text-gray-700">{{ empty }}</p>
        <UButton
          v-if="hasFilters"
          color="neutral"
          variant="outline"
          icon="i-lucide-x"
          class="mt-4"
          @click="emit('clear')"
        >
          {{ t('knowbase.clearFilters') }}
        </UButton>
      </div>

      <div v-else :aria-busy="loading">
        <slot />
      </div>

      <div v-if="total > KB_PAGE_SIZE" class="flex justify-center pt-4">
        <UPagination
          :page="page"
          :total="total"
          :items-per-page="KB_PAGE_SIZE"
          :aria-label="paginationLabel"
          @update:page="(next: number) => emit('page', next)"
        />
      </div>
    </template>
  </div>
</template>

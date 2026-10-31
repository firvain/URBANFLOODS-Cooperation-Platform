<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import type { TableColumn } from '@nuxt/ui'

import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import AdminPagination from '@/components/admin/AdminPagination.vue'
import AuditMetadata from '@/components/admin/AuditMetadata.vue'
import ListState from '@/components/admin/ListState.vue'
import { useDebouncedSearch } from '@/composables/useKnowbaseList'
import { useQueryFilters } from '@/composables/useQueryFilters'
import {
  ADMIN_LONG_PAGE_SIZE,
  ADMIN_SEARCH_DEBOUNCE_MS,
  LOG_ACTION_PREFIXES,
  LOG_TARGET_TYPES,
} from '@/constants/admin'
import type { AuditLogEntry } from '@/services/moderation'
import { useModerationStore } from '@/stores/moderation'
import { formatDateTime } from '@/utils/datetime'

/**
 * Audit log, newest first. Filters in the URL: `action` (exact, or a prefix ending in `.`, with
 * quick chips for the common prefixes), `actor_id` and `target_type`.
 */
const { t, locale } = useI18n()
const route = useRoute()
const moderation = useModerationStore()
const log = moderation.log
const { filters, page, hasFilters, setFilters, setPage, clearFilters } = useQueryFilters({
  action: 'string',
  actor_id: 'number',
  target_type: 'string',
})

/** Select value for "no filter" (reka-ui selects cannot hold an empty string). */
const ALL = 'all'

const action = useDebouncedSearch(
  () => filters.value.action,
  (value) => setFilters({ action: value }),
  ADMIN_SEARCH_DEBOUNCE_MS,
)

/** Typed as text (a number input), committed when it is a positive whole number or empty. */
const actorInput = ref(filters.value.actor_id ? String(filters.value.actor_id) : '')
watch(
  () => filters.value.actor_id,
  (id) => {
    if (Number(actorInput.value) !== (id ?? 0)) actorInput.value = id ? String(id) : ''
  },
)
function commitActor() {
  const value = String(actorInput.value ?? '').trim()
  const id = Number(value)
  if (value === '') void setFilters({ actor_id: undefined })
  else if (Number.isInteger(id) && id > 0) void setFilters({ actor_id: id })
}

const targetFilter = computed<string>({
  get: () =>
    (LOG_TARGET_TYPES as readonly string[]).includes(filters.value.target_type)
      ? filters.value.target_type
      : ALL,
  set: (value) => void setFilters({ target_type: value === ALL ? '' : value }),
})
const targetItems = computed(() => [
  { label: t('admin.common.all'), value: ALL },
  ...LOG_TARGET_TYPES.map((type) => ({ label: type, value: type })),
])

/** A chip toggles its prefix: pressing the active chip clears the action filter. */
function toggleChip(prefix: string) {
  const next = filters.value.action === prefix ? '' : prefix
  action.value = next
  void setFilters({ action: next })
}

const params = computed(() => ({
  action: filters.value.action || undefined,
  actor_id: filters.value.actor_id,
  target_type: filters.value.target_type || undefined,
  skip: (page.value - 1) * ADMIN_LONG_PAGE_SIZE,
  limit: ADMIN_LONG_PAGE_SIZE,
}))

watch(
  () => JSON.stringify(params.value),
  () => {
    if (route.name === 'admin-log') void moderation.fetchLog(params.value)
  },
  { immediate: true },
)

const columns = computed<TableColumn<AuditLogEntry>[]>(() => [
  { id: 'when', header: t('admin.log.when') },
  { id: 'action', header: t('admin.log.action') },
  { id: 'actor', header: t('admin.log.actor') },
  { id: 'target', header: t('admin.log.target') },
  { id: 'details', header: t('admin.log.details') },
])
</script>

<template>
  <div>
    <AdminPageHeader :title="t('admin.log.title')" :intro="t('admin.log.intro')" />

    <section aria-labelledby="log-filters" class="mb-6 space-y-4">
      <h2 id="log-filters" class="sr-only">{{ t('admin.log.quick') }}</h2>
      <div role="group" :aria-label="t('admin.log.quick')" class="flex flex-wrap gap-2">
        <UButton
          v-for="prefix in LOG_ACTION_PREFIXES"
          :key="prefix"
          data-testid="action-chip"
          size="sm"
          class="rounded-full font-mono"
          :color="filters.action === prefix ? 'primary' : 'neutral'"
          :variant="filters.action === prefix ? 'solid' : 'outline'"
          :aria-pressed="filters.action === prefix ? 'true' : 'false'"
          @click="toggleChip(prefix)"
        >
          {{ prefix }}
        </UButton>
      </div>
      <div class="grid gap-4 md:grid-cols-[1fr_10rem_12rem]">
        <UFormField :label="t('admin.log.action')" :help="t('admin.log.actionHelp')" name="action">
          <UInput
            v-model="action"
            :placeholder="t('admin.log.actionPlaceholder')"
            class="w-full font-mono"
          />
        </UFormField>
        <UFormField :label="t('admin.log.actor')" name="actor_id">
          <UInput
            v-model="actorInput"
            type="number"
            inputmode="numeric"
            :min="1"
            class="w-full"
            @change="commitActor"
          />
        </UFormField>
        <UFormField :label="t('admin.log.targetType')" name="target_type">
          <USelect v-model="targetFilter" :items="targetItems" class="w-full" />
        </UFormField>
      </div>
      <UButton
        v-if="hasFilters"
        color="neutral"
        variant="link"
        icon="i-lucide-x"
        class="px-0"
        @click="clearFilters()"
      >
        {{ t('admin.log.clear') }}
      </UButton>
    </section>

    <ListState
      :initial="log.initial"
      :loading="log.loading"
      :failed="log.failed"
      @retry="moderation.reloadLog()"
    >
      <p v-if="!log.items.length" class="rounded border border-default p-6 text-center text-muted">
        {{ t('admin.log.empty') }}
      </p>
      <div v-else data-testid="log-table" class="overflow-x-auto">
        <UTable
          :data="log.items"
          :columns="columns"
          :caption="t('admin.log.caption')"
          :loading="log.loading"
          :ui="{ caption: 'sr-only', td: 'align-top' }"
        >
          <template #when-cell="{ row }">
            <time :datetime="row.original.created_at" class="whitespace-nowrap">
              {{ formatDateTime(row.original.created_at, locale) }}
            </time>
          </template>
          <template #action-cell="{ row }">
            <code class="text-xs">{{ row.original.action }}</code>
          </template>
          <template #actor-cell="{ row }">
            <ULink
              v-if="row.original.actor"
              :to="`/u/${row.original.actor.id}`"
              class="hover:underline"
            >
              {{ row.original.actor.display_name }}
            </ULink>
            <span v-else class="text-muted">{{ t('admin.common.system') }}</span>
          </template>
          <template #target-cell="{ row }">
            <span v-if="row.original.target_type" class="font-mono text-xs whitespace-nowrap">
              {{ row.original.target_type
              }}{{ row.original.target_id !== null ? ` #${row.original.target_id}` : '' }}
            </span>
            <span v-else class="text-muted">—</span>
          </template>
          <template #details-cell="{ row }">
            <div class="max-w-md min-w-48 whitespace-normal">
              <AuditMetadata :metadata="row.original.metadata" />
            </div>
          </template>
        </UTable>
      </div>
      <AdminPagination
        :page="page"
        :total="log.total"
        :page-size="ADMIN_LONG_PAGE_SIZE"
        @update:page="setPage"
      />
    </ListState>
  </div>
</template>

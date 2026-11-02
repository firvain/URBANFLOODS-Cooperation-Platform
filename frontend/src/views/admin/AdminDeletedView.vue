<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useToast } from '@nuxt/ui/composables'
import type { TableColumn } from '@nuxt/ui'

import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import AdminPagination from '@/components/admin/AdminPagination.vue'
import ListState from '@/components/admin/ListState.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import RelativeTime from '@/components/common/RelativeTime.vue'
import PurgeDialog from '@/components/moderation/PurgeDialog.vue'
import { useAdminErrors } from '@/composables/useAdminErrors'
import { useQueryFilters } from '@/composables/useQueryFilters'
import { ADMIN_PAGE_SIZE } from '@/constants/admin'
import type { DeletedItem } from '@/services/moderation'
import { useModerationStore } from '@/stores/moderation'
import { contentLink } from '@/utils/contentLink'

/**
 * Deleted content: posts and discussions deleted by their authors or by admins, most recently
 * deleted first (`?type=post|thread`). They are kept for `DELETED_CONTENT_RETENTION_DAYS` days
 * (the days left come from each item's `purge_at`), then the maintenance sweep removes them for
 * good. Restore (confirmed) and Delete permanently (typed confirmation) remove the row at once.
 * An item that was hidden (by an admin, by reports, or rejected) when it was deleted is marked
 * "Was hidden"/"Was rejected": a restore brings it back hidden, and the dialog and toast say so.
 */
const { t } = useI18n()
const route = useRoute()
const toast = useToast()
const moderation = useModerationStore()
const deleted = moderation.deleted
const { adminError } = useAdminErrors()
const { filters, page, setFilters, setPage } = useQueryFilters({ type: 'string' })

const DAY_MS = 24 * 60 * 60 * 1000
/** Select value for "no filter" (reka-ui selects cannot hold an empty string). */
const ALL = 'all'
const TYPES = ['post', 'thread'] as const
type DeletedType = (typeof TYPES)[number]

const isType = (v: string): v is DeletedType => (TYPES as readonly string[]).includes(v)

const typeFilter = computed<string>({
  get: () => (isType(filters.value.type) ? filters.value.type : ALL),
  set: (value) => void setFilters({ type: value === ALL ? '' : value }),
})
const typeItems = computed(() => [
  { label: t('admin.deleted.types.all'), value: ALL },
  ...TYPES.map((type) => ({ label: t(`admin.deleted.types.${type}`), value: type })),
])

const params = computed(() => ({
  type: isType(typeFilter.value) ? typeFilter.value : undefined,
  skip: (page.value - 1) * ADMIN_PAGE_SIZE,
  limit: ADMIN_PAGE_SIZE,
}))

watch(
  () => JSON.stringify(params.value),
  () => {
    if (route.name === 'admin-deleted') void moderation.fetchDeleted(params.value)
  },
  { immediate: true },
)

/** The intro names the retention the server answered with (the same for every item). */
const intro = computed(() => {
  const first = deleted.items[0]
  if (!first) return t('admin.deleted.introUnknown')
  if (!first.purge_at) return t('admin.deleted.introKept')
  const days = Math.round((Date.parse(first.purge_at) - Date.parse(first.deleted_at)) / DAY_MS)
  return t('admin.deleted.introDays', { days })
})

const columns = computed<TableColumn<DeletedItem>[]>(() => [
  { id: 'type', header: t('admin.deleted.type') },
  { id: 'item', header: t('admin.deleted.item') },
  { id: 'author', header: t('admin.deleted.author') },
  { id: 'deleted', header: t('admin.deleted.deleted') },
  { id: 'removal', header: t('admin.deleted.removedIn') },
  { id: 'actions', header: t('admin.common.actions') },
])

const link = (item: DeletedItem) => contentLink(item.content_type, item.id, item.slug) ?? undefined

/** "today" under a day (or overdue: the next sweep takes it), else the whole days left. */
function daysLeft(purgeAt: string): string {
  const left = (Date.parse(purgeAt) - Date.now()) / DAY_MS
  return t('admin.deleted.daysLeft', left < 1 ? 0 : Math.ceil(left))
}

// --- Restore ----------------------------------------------------------------------------------

const restoring = ref<DeletedItem | null>(null)
const restoreOpen = ref(false)
const restoreLoading = ref(false)
const restoreError = ref('')

function askRestore(item: DeletedItem) {
  restoring.value = item
  restoreError.value = ''
  restoreOpen.value = true
}

/** A rejected item was never published (no reports): it goes back to its author. */
const restoreDescription = computed(() => {
  const reason = restoring.value?.hidden_reason
  if (reason === 'rejected') return t('admin.deleted.restoreDescriptionRejected')
  if (reason) return t('admin.deleted.restoreDescriptionHidden')
  return t('admin.deleted.restoreDescription')
})

async function confirmRestore() {
  const item = restoring.value
  if (!item || restoreLoading.value) return
  restoreLoading.value = true
  restoreError.value = ''
  try {
    const result = await moderation.restoreDeleted(item)
    restoreOpen.value = false
    const done =
      result.status === 'hidden' ? 'admin.deleted.restoredHidden' : 'admin.deleted.restored'
    toast.add({
      title: t(done, { title: item.title }),
      color: 'success',
      icon: 'i-lucide-undo-2',
    })
  } catch (error) {
    restoreError.value = adminError(error)
  } finally {
    restoreLoading.value = false
  }
}

// --- Delete permanently -----------------------------------------------------------------------

const purging = ref<DeletedItem | null>(null)
const purgeOpen = ref(false)
const purgeLoading = ref(false)
const purgeError = ref('')

function askPurge(item: DeletedItem) {
  purging.value = item
  purgeError.value = ''
  purgeOpen.value = true
}

async function confirmPurge() {
  const item = purging.value
  if (!item || purgeLoading.value) return
  purgeLoading.value = true
  purgeError.value = ''
  try {
    await moderation.purgeDeleted(item)
    purgeOpen.value = false
    toast.add({
      title: t('admin.deleted.purged', { title: item.title }),
      color: 'neutral',
      icon: 'i-lucide-trash-2',
    })
  } catch (error) {
    purgeError.value = adminError(error)
  } finally {
    purgeLoading.value = false
  }
}
</script>

<template>
  <div>
    <AdminPageHeader :title="t('admin.deleted.title')" :intro="intro" />

    <section aria-labelledby="deleted-filters" class="mb-6 max-w-xs">
      <h2 id="deleted-filters" class="sr-only">{{ t('admin.deleted.type') }}</h2>
      <UFormField :label="t('admin.deleted.type')" name="type">
        <USelect v-model="typeFilter" :items="typeItems" class="w-full" />
      </UFormField>
    </section>

    <ListState
      :initial="deleted.initial"
      :loading="deleted.loading"
      :failed="deleted.failed"
      @retry="moderation.reloadDeleted()"
    >
      <p
        v-if="!deleted.items.length"
        class="rounded border border-default p-6 text-center text-muted"
      >
        {{ t('admin.deleted.empty') }}
      </p>
      <div v-else data-testid="deleted-table" class="overflow-x-auto">
        <UTable
          :data="deleted.items"
          :columns="columns"
          :caption="t('admin.deleted.caption')"
          :loading="deleted.loading"
          :ui="{ caption: 'sr-only', td: 'align-top' }"
        >
          <template #type-cell="{ row }">
            <UBadge color="neutral" variant="subtle" size="sm">
              {{ t(`admin.contentType.${row.original.content_type}`) }}
            </UBadge>
          </template>
          <template #item-cell="{ row }">
            <div class="max-w-md min-w-48 space-y-1 whitespace-normal">
              <ULink :to="link(row.original)" class="font-medium text-primary-700 hover:underline">
                {{ row.original.title }}
              </ULink>
              <p class="text-sm text-muted">{{ row.original.category.name }}</p>
              <UBadge
                v-if="row.original.hidden_reason"
                data-testid="was-hidden"
                color="error"
                variant="subtle"
                size="sm"
                icon="i-lucide-eye-off"
                :title="t(`admin.deleted.reason.${row.original.hidden_reason}`)"
              >
                {{
                  t(
                    row.original.hidden_reason === 'rejected'
                      ? 'admin.deleted.wasRejected'
                      : 'admin.deleted.wasHidden',
                  )
                }}
              </UBadge>
            </div>
          </template>
          <template #author-cell="{ row }">
            <ULink
              v-if="row.original.author"
              :to="`/u/${row.original.author.id}`"
              class="hover:underline"
            >
              {{ row.original.author.display_name }}
            </ULink>
            <span v-else class="text-muted">—</span>
          </template>
          <template #deleted-cell="{ row }">
            <div class="min-w-32 whitespace-normal">
              <RelativeTime :datetime="row.original.deleted_at" />
              <p v-if="row.original.deleted_by" class="text-sm text-muted">
                {{ t('admin.deleted.by') }}
                <ULink :to="`/u/${row.original.deleted_by.id}`" class="hover:underline">
                  {{ row.original.deleted_by.display_name }}
                </ULink>
              </p>
            </div>
          </template>
          <template #removal-cell="{ row }">
            <time
              v-if="row.original.purge_at"
              :datetime="row.original.purge_at"
              class="whitespace-nowrap"
            >
              {{ daysLeft(row.original.purge_at) }}
            </time>
            <span v-else class="text-muted">{{ t('admin.deleted.never') }}</span>
          </template>
          <template #actions-cell="{ row }">
            <div class="flex gap-2">
              <UButton
                size="sm"
                color="neutral"
                variant="outline"
                icon="i-lucide-undo-2"
                :aria-label="t('admin.deleted.restoreLabel', { title: row.original.title })"
                @click="askRestore(row.original)"
              >
                {{ t('admin.deleted.restore') }}
              </UButton>
              <UButton
                size="sm"
                color="error"
                variant="outline"
                icon="i-lucide-trash-2"
                :aria-label="t('admin.deleted.purgeLabel', { title: row.original.title })"
                @click="askPurge(row.original)"
              >
                {{ t('admin.deleted.purge') }}
              </UButton>
            </div>
          </template>
        </UTable>
      </div>
      <AdminPagination
        :page="page"
        :total="deleted.total"
        :page-size="ADMIN_PAGE_SIZE"
        @update:page="setPage"
      />
    </ListState>

    <ConfirmDialog
      v-model:open="restoreOpen"
      :title="t('admin.deleted.restoreTitle', { title: restoring?.title ?? '' })"
      :description="restoreDescription"
      :confirm-label="t('admin.deleted.restore')"
      :loading="restoreLoading"
      :error="restoreError"
      @confirm="confirmRestore"
    />

    <PurgeDialog
      v-model:open="purgeOpen"
      :kind="purging?.content_type === 'thread' ? 'thread' : 'post'"
      :loading="purgeLoading"
      :error="purgeError"
      @confirm="confirmPurge"
    />
  </div>
</template>

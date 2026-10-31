<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useToast } from '@nuxt/ui/composables'
import type { TableColumn } from '@nuxt/ui'

import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import AdminPagination from '@/components/admin/AdminPagination.vue'
import ListState from '@/components/admin/ListState.vue'
import ReasonDialog from '@/components/admin/ReasonDialog.vue'
import RelativeTime from '@/components/common/RelativeTime.vue'
import { useAdminErrors } from '@/composables/useAdminErrors'
import { useQueryFilters } from '@/composables/useQueryFilters'
import { ADMIN_PAGE_SIZE } from '@/constants/admin'
import type { QueueItem } from '@/services/moderation'
import { useModerationStore } from '@/stores/moderation'
import { contentLink } from '@/utils/contentLink'

/**
 * Approval queue: first posts and threads of untrusted members, oldest first. Approve publishes
 * (and trusts the author); Reject hides with an optional audited reason. Rows leave at once.
 */
const { t } = useI18n()
const route = useRoute()
const toast = useToast()
const moderation = useModerationStore()
const queue = moderation.queue
const { adminError } = useAdminErrors()
const { page, setPage } = useQueryFilters({})

watch(
  page,
  (current) => {
    if (route.name !== 'admin-queue') return
    void moderation.fetchQueue({ skip: (current - 1) * ADMIN_PAGE_SIZE, limit: ADMIN_PAGE_SIZE })
  },
  { immediate: true },
)

const columns = computed<TableColumn<QueueItem>[]>(() => [
  { id: 'type', header: t('admin.queue.type') },
  { id: 'item', header: t('admin.queue.item') },
  { id: 'author', header: t('admin.queue.author') },
  { id: 'category', header: t('admin.queue.category') },
  { id: 'created', header: t('admin.common.created') },
  { id: 'actions', header: t('admin.common.actions') },
])

const link = (item: QueueItem) => contentLink(item.content_type, item.id, item.slug) ?? undefined

async function approve(item: QueueItem) {
  try {
    await moderation.approve(item)
    toast.add({
      title: t('admin.queue.approved', { title: item.title }),
      color: 'success',
      icon: 'i-lucide-check',
    })
  } catch (error) {
    toast.add({ title: adminError(error), color: 'error', icon: 'i-lucide-circle-alert' })
  }
}

// --- Reject -----------------------------------------------------------------------------------

const rejecting = ref<QueueItem | null>(null)
const rejectOpen = ref(false)
const rejectLoading = ref(false)
const rejectError = ref('')

function askReject(item: QueueItem) {
  rejecting.value = item
  rejectError.value = ''
  rejectOpen.value = true
}

async function confirmReject(reason: string) {
  const item = rejecting.value
  if (!item || rejectLoading.value) return
  rejectLoading.value = true
  rejectError.value = ''
  try {
    await moderation.reject(item, reason)
    rejectOpen.value = false
    toast.add({
      title: t('admin.queue.rejected', { title: item.title }),
      color: 'neutral',
      icon: 'i-lucide-eye-off',
    })
  } catch (error) {
    rejectError.value = adminError(error)
  } finally {
    rejectLoading.value = false
  }
}
</script>

<template>
  <div>
    <AdminPageHeader :title="t('admin.queue.title')" :intro="t('admin.queue.intro')" />

    <ListState
      :initial="queue.initial"
      :loading="queue.loading"
      :failed="queue.failed"
      @retry="moderation.reloadQueue()"
    >
      <p
        v-if="!queue.items.length"
        class="rounded border border-default p-6 text-center text-muted"
      >
        {{ t('admin.queue.empty') }}
      </p>
      <div v-else data-testid="queue-table" class="overflow-x-auto">
        <UTable
          :data="queue.items"
          :columns="columns"
          :caption="t('admin.queue.caption')"
          :loading="queue.loading"
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
              <p class="line-clamp-2 text-sm text-muted">{{ row.original.excerpt }}</p>
            </div>
          </template>
          <template #author-cell="{ row }">
            <div v-if="row.original.author" class="flex flex-wrap items-center gap-1.5">
              <ULink :to="`/u/${row.original.author.id}`" class="hover:underline">
                {{ row.original.author.display_name }}
              </ULink>
              <UBadge
                v-if="row.original.author.trusted"
                color="success"
                variant="subtle"
                size="sm"
                icon="i-lucide-badge-check"
              >
                {{ t('admin.queue.trusted') }}
              </UBadge>
            </div>
            <span v-else class="text-muted">—</span>
          </template>
          <template #category-cell="{ row }">{{ row.original.category.name }}</template>
          <template #created-cell="{ row }">
            <RelativeTime :datetime="row.original.created_at" />
          </template>
          <template #actions-cell="{ row }">
            <div class="flex gap-2">
              <UButton
                size="sm"
                color="success"
                icon="i-lucide-check"
                :aria-label="t('admin.queue.approveLabel', { title: row.original.title })"
                @click="approve(row.original)"
              >
                {{ t('admin.queue.approve') }}
              </UButton>
              <UButton
                size="sm"
                color="error"
                variant="outline"
                icon="i-lucide-x"
                :aria-label="t('admin.queue.rejectLabel', { title: row.original.title })"
                @click="askReject(row.original)"
              >
                {{ t('admin.queue.reject') }}
              </UButton>
            </div>
          </template>
        </UTable>
      </div>
      <AdminPagination
        :page="page"
        :total="queue.total"
        :page-size="ADMIN_PAGE_SIZE"
        @update:page="setPage"
      />
    </ListState>

    <ReasonDialog
      v-model:open="rejectOpen"
      :title="t('admin.queue.rejectTitle', { title: rejecting?.title ?? '' })"
      :description="t('admin.queue.rejectDescription')"
      :confirm-label="t('admin.queue.reject')"
      :loading="rejectLoading"
      :error="rejectError"
      @confirm="confirmReject"
    />
  </div>
</template>

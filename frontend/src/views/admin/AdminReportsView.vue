<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useToast } from '@nuxt/ui/composables'
import type { DropdownMenuItem, TableColumn } from '@nuxt/ui'

import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import AdminPagination from '@/components/admin/AdminPagination.vue'
import ContentStatusBadge from '@/components/admin/ContentStatusBadge.vue'
import ListState from '@/components/admin/ListState.vue'
import ReasonDialog from '@/components/admin/ReasonDialog.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import RelativeTime from '@/components/common/RelativeTime.vue'
import { useAdminErrors } from '@/composables/useAdminErrors'
import { useQueryFilters } from '@/composables/useQueryFilters'
import { ADMIN_PAGE_SIZE } from '@/constants/admin'
import type { ContentType, ReportDetail, ReportStatus } from '@/services/moderation'
import { useModerationStore, type ContentAction } from '@/stores/moderation'
import { contentLink } from '@/utils/contentLink'

/**
 * Reports: open ones by default (`?status=resolved|dismissed|all`, `?content_type=`). Each row
 * shows the reported content's summary and offers Resolve / Dismiss for the report and Hide /
 * Unhide / Delete for the content (each confirmed).
 */
const { t } = useI18n()
const route = useRoute()
const toast = useToast()
const moderation = useModerationStore()
const reports = moderation.reports
const { adminError } = useAdminErrors()
const { filters, page, setFilters, setPage } = useQueryFilters({
  status: 'string',
  content_type: 'string',
})

/** Select value for "no filter" (reka-ui selects cannot hold an empty string). */
const ALL = 'all'
const STATUSES: ReportStatus[] = ['open', 'resolved', 'dismissed']
const TYPES: ContentType[] = ['post', 'thread', 'reply', 'comment']

const isStatus = (v: string): v is ReportStatus => (STATUSES as string[]).includes(v)
const isType = (v: string): v is ContentType => (TYPES as string[]).includes(v)

/** `open` when the URL has no status; `all` (no filter) when it says so. */
const statusFilter = computed<string>({
  get: () =>
    filters.value.status === ALL || isStatus(filters.value.status) ? filters.value.status : 'open',
  set: (value) => void setFilters({ status: value === 'open' ? '' : value }),
})
const typeFilter = computed<string>({
  get: () => (isType(filters.value.content_type) ? filters.value.content_type : ALL),
  set: (value) => void setFilters({ content_type: value === ALL ? '' : value }),
})

const statusItems = computed(() => [
  ...STATUSES.map((s) => ({ label: t(`admin.reports.statuses.${s}`), value: s })),
  { label: t('admin.common.all'), value: ALL },
])
const typeItems = computed(() => [
  { label: t('admin.common.all'), value: ALL },
  ...TYPES.map((type) => ({ label: t(`admin.contentType.${type}`), value: type })),
])

const params = computed(() => ({
  status: isStatus(statusFilter.value) ? statusFilter.value : undefined,
  content_type: isType(typeFilter.value) ? typeFilter.value : undefined,
  skip: (page.value - 1) * ADMIN_PAGE_SIZE,
  limit: ADMIN_PAGE_SIZE,
}))

watch(
  () => JSON.stringify(params.value),
  () => {
    if (route.name === 'admin-reports') void moderation.fetchReports(params.value)
  },
  { immediate: true },
)

const columns = computed<TableColumn<ReportDetail>[]>(() => [
  { id: 'reason', header: t('admin.reports.reason') },
  { id: 'content', header: t('admin.reports.content') },
  { id: 'reporter', header: t('admin.reports.reporter') },
  { id: 'status', header: t('admin.reports.status') },
  { id: 'created', header: t('admin.common.created') },
  { id: 'actions', header: t('admin.common.actions') },
])

const link = (report: ReportDetail) =>
  report.content
    ? (contentLink(report.content.type, report.content.id, report.content.url_slug) ?? undefined)
    : undefined

const STATUS_COLOR = { open: 'warning', resolved: 'success', dismissed: 'neutral' } as const

// --- Report actions ---------------------------------------------------------------------------

async function closeReport(report: ReportDetail, action: 'resolve' | 'dismiss') {
  try {
    if (action === 'resolve') await moderation.resolveReport(report.id)
    else await moderation.dismissReport(report.id)
    toast.add({
      title: t(action === 'resolve' ? 'admin.reports.resolved' : 'admin.reports.dismissed'),
      color: 'success',
      icon: 'i-lucide-check',
    })
  } catch (error) {
    toast.add({ title: adminError(error), color: 'error', icon: 'i-lucide-circle-alert' })
  }
}

// --- Content actions --------------------------------------------------------------------------

const pending = ref<{ report: ReportDetail; action: ContentAction } | null>(null)
const hideOpen = ref(false)
const confirmOpen = ref(false)
const acting = ref(false)
const actionError = ref('')

const DONE: Record<ContentAction, string> = {
  hide: 'admin.reports.hidden',
  unhide: 'admin.reports.unhidden',
  delete: 'admin.reports.deleted',
  restore: 'admin.reports.unhidden',
}

function askContent(report: ReportDetail, action: ContentAction) {
  pending.value = { report, action }
  actionError.value = ''
  if (action === 'hide') hideOpen.value = true
  else confirmOpen.value = true
}

async function runContent(reason?: string) {
  const current = pending.value
  if (!current?.report.content || acting.value) return
  acting.value = true
  actionError.value = ''
  try {
    const { type, id } = current.report.content
    await moderation.contentAction(type, id, current.action, reason)
    hideOpen.value = false
    confirmOpen.value = false
    toast.add({ title: t(DONE[current.action]), color: 'success', icon: 'i-lucide-check' })
  } catch (error) {
    actionError.value = adminError(error)
  } finally {
    acting.value = false
  }
}

const confirmTexts = computed(() =>
  pending.value?.action === 'delete'
    ? {
        title: t('admin.reports.deleteTitle'),
        description: t('admin.reports.deleteDescription'),
        label: t('admin.reports.delete'),
        color: 'error' as const,
      }
    : {
        title: t('admin.reports.unhideTitle'),
        description: t('admin.reports.unhideDescription'),
        label: t('admin.reports.unhide'),
        color: 'primary' as const,
      },
)

function menuItems(report: ReportDetail): DropdownMenuItem[][] {
  const groups: DropdownMenuItem[][] = []
  if (report.status === 'open') {
    groups.push([
      {
        label: t('admin.reports.resolve'),
        icon: 'i-lucide-circle-check',
        onSelect: () => void closeReport(report, 'resolve'),
      },
      {
        label: t('admin.reports.dismiss'),
        icon: 'i-lucide-circle-slash',
        onSelect: () => void closeReport(report, 'dismiss'),
      },
    ])
  }
  const status = report.content?.status
  const content: DropdownMenuItem[] = []
  if (status === 'published')
    content.push({
      label: t('admin.reports.hide'),
      icon: 'i-lucide-eye-off',
      onSelect: () => askContent(report, 'hide'),
    })
  if (status === 'hidden')
    content.push({
      label: t('admin.reports.unhide'),
      icon: 'i-lucide-eye',
      onSelect: () => askContent(report, 'unhide'),
    })
  if (status && status !== 'deleted')
    content.push({
      label: t('admin.reports.delete'),
      icon: 'i-lucide-trash-2',
      color: 'error',
      onSelect: () => askContent(report, 'delete'),
    })
  if (content.length) groups.push(content)
  return groups
}
</script>

<template>
  <div>
    <AdminPageHeader :title="t('admin.reports.title')" :intro="t('admin.reports.intro')" />

    <section aria-labelledby="reports-filters" class="mb-6 grid gap-4 sm:grid-cols-2 lg:max-w-xl">
      <h2 id="reports-filters" class="sr-only">{{ t('admin.reports.status') }}</h2>
      <UFormField :label="t('admin.reports.status')" name="status">
        <USelect v-model="statusFilter" :items="statusItems" class="w-full" />
      </UFormField>
      <UFormField :label="t('admin.reports.type')" name="content_type">
        <USelect v-model="typeFilter" :items="typeItems" class="w-full" />
      </UFormField>
    </section>

    <ListState
      :initial="reports.initial"
      :loading="reports.loading"
      :failed="reports.failed"
      @retry="moderation.reloadReports()"
    >
      <p
        v-if="!reports.items.length"
        class="rounded border border-default p-6 text-center text-muted"
      >
        {{ t('admin.reports.empty') }}
      </p>
      <div v-else data-testid="reports-table" class="overflow-x-auto">
        <UTable
          :data="reports.items"
          :columns="columns"
          :caption="t('admin.reports.caption')"
          :loading="reports.loading"
          :ui="{ caption: 'sr-only', td: 'align-top' }"
        >
          <template #reason-cell="{ row }">
            <div class="max-w-xs min-w-40 space-y-1 whitespace-normal">
              <UBadge color="warning" variant="subtle" size="sm">
                {{ t(`admin.reports.reasons.${row.original.reason}`) }}
              </UBadge>
              <p v-if="row.original.details" class="text-sm">{{ row.original.details }}</p>
            </div>
          </template>
          <template #content-cell="{ row }">
            <div v-if="row.original.content" class="max-w-md min-w-48 space-y-1 whitespace-normal">
              <div class="flex flex-wrap items-center gap-1.5">
                <UBadge color="neutral" variant="subtle" size="sm">
                  {{ t(`admin.contentType.${row.original.content.type}`) }}
                </UBadge>
                <ContentStatusBadge :status="row.original.content.status" />
              </div>
              <ULink
                v-if="link(row.original)"
                :to="link(row.original)"
                class="font-medium text-primary-700 hover:underline"
              >
                {{
                  row.original.content.title ||
                  row.original.content.excerpt ||
                  t('admin.common.untitled')
                }}
              </ULink>
              <p
                v-if="row.original.content.title && row.original.content.excerpt"
                class="line-clamp-2 text-sm text-muted"
              >
                {{ row.original.content.excerpt }}
              </p>
              <ULink
                :to="{ name: 'admin-log', query: { target_type: row.original.content_type } }"
                class="inline-flex items-center gap-1 text-xs text-muted hover:underline"
              >
                <UIcon name="i-lucide-scroll-text" aria-hidden="true" />
                {{ t('admin.reports.viewLog') }}
              </ULink>
            </div>
            <span v-else class="text-muted">{{ t('admin.reports.contentGone') }}</span>
          </template>
          <template #reporter-cell="{ row }">
            <ULink
              v-if="row.original.reporter"
              :to="`/u/${row.original.reporter.id}`"
              class="hover:underline"
            >
              {{ row.original.reporter.display_name }}
            </ULink>
            <span v-else class="text-muted">{{ t('admin.reports.deletedAccount') }}</span>
          </template>
          <template #status-cell="{ row }">
            <UBadge :color="STATUS_COLOR[row.original.status]" variant="subtle" size="sm">
              {{ t(`admin.reports.statuses.${row.original.status}`) }}
            </UBadge>
          </template>
          <template #created-cell="{ row }">
            <RelativeTime :datetime="row.original.created_at" />
          </template>
          <template #actions-cell="{ row }">
            <UDropdownMenu
              v-if="menuItems(row.original).length"
              :items="menuItems(row.original)"
              :content="{ align: 'end' }"
            >
              <UButton
                color="neutral"
                variant="ghost"
                icon="i-lucide-ellipsis-vertical"
                :aria-label="t('admin.reports.actionsFor', { id: row.original.id })"
              />
            </UDropdownMenu>
          </template>
        </UTable>
      </div>
      <AdminPagination
        :page="page"
        :total="reports.total"
        :page-size="ADMIN_PAGE_SIZE"
        @update:page="setPage"
      />
    </ListState>

    <ReasonDialog
      v-model:open="hideOpen"
      :title="t('admin.reports.hideTitle')"
      :description="t('admin.reports.hideDescription')"
      :confirm-label="t('admin.reports.hide')"
      :loading="acting"
      :error="actionError"
      @confirm="runContent"
    />
    <ConfirmDialog
      v-model:open="confirmOpen"
      :title="confirmTexts.title"
      :description="confirmTexts.description"
      :confirm-label="confirmTexts.label"
      :color="confirmTexts.color"
      :loading="acting"
      :error="actionError"
      @confirm="runContent()"
    />
  </div>
</template>

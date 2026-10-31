<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import { useToast } from '@nuxt/ui/composables'

import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { useAdminErrors } from '@/composables/useAdminErrors'
import { adminService } from '@/services/admin'
import { useAdminStore } from '@/stores/admin'
import { formatDateTime, localDateInput } from '@/utils/datetime'
import { saveFile } from '@/utils/download'

/**
 * Admin dashboard: counts of users, content and open reports, the KNOWBASE proxy state with a
 * "clear cache" action, a "send the moderation digest now" action, and the reporting CSV for a
 * date range.
 */
const { t, locale } = useI18n()
const toast = useToast()
const admin = useAdminStore()
const { stats, statsLoading, statsFailed } = storeToRefs(admin)
const { adminError } = useAdminErrors()

/** The project started on 1 September 2024 (the export's default first day). */
const PROJECT_START = '2024-09-01'

onMounted(() => void admin.fetchStats())

const number = (value: number) => new Intl.NumberFormat([locale.value, 'en']).format(value)
const when = (iso: string | null) =>
  iso ? formatDateTime(iso, locale.value) : t('admin.dashboard.knowbase.never')

interface Stat {
  key: string
  label: string
  value: number
}

const groups = computed<{ id: string; heading: string; stats: Stat[] }[]>(() => {
  const s = stats.value
  if (!s) return []
  const d = 'admin.dashboard'
  return [
    {
      id: 'users',
      heading: t(`${d}.users.heading`),
      stats: [
        { key: 'users-total', label: t(`${d}.users.total`), value: s.users.total },
        { key: 'users-verified', label: t(`${d}.users.verified`), value: s.users.verified },
        { key: 'users-trusted', label: t(`${d}.users.trusted`), value: s.users.trusted },
        { key: 'users-admins', label: t(`${d}.users.admins`), value: s.users.admins },
        { key: 'users-new30d', label: t(`${d}.users.new30d`), value: s.users.new_30d },
      ],
    },
    {
      id: 'content',
      heading: t(`${d}.content.heading`),
      stats: [
        { key: 'content-posts', label: t(`${d}.content.posts`), value: s.content.posts_published },
        {
          key: 'content-threads',
          label: t(`${d}.content.threads`),
          value: s.content.threads_published,
        },
        { key: 'content-replies', label: t(`${d}.content.replies`), value: s.content.replies },
        { key: 'content-comments', label: t(`${d}.content.comments`), value: s.content.comments },
        { key: 'content-pending', label: t(`${d}.content.pending`), value: s.content.pending },
      ],
    },
    {
      id: 'reports',
      heading: t(`${d}.reports.heading`),
      stats: [{ key: 'reports-open', label: t(`${d}.reports.open`), value: s.reports_open }],
    },
  ]
})

const cacheStats = computed<Stat[]>(() => {
  const cache = stats.value?.knowbase.cache
  if (!cache) return []
  const k = 'admin.dashboard.knowbase'
  return [
    { key: 'cache-lists', label: t(`${k}.lists`), value: cache.lists },
    { key: 'cache-details', label: t(`${k}.details`), value: cache.details },
    { key: 'cache-lookups', label: t(`${k}.lookups`), value: cache.lookups },
    { key: 'cache-stale', label: t(`${k}.stale`), value: cache.stale },
  ]
})

// --- Clear the KNOWBASE cache -----------------------------------------------------------------

const clearOpen = ref(false)
const clearing = ref(false)
const clearError = ref('')

function askClear() {
  clearError.value = ''
  clearOpen.value = true
}

async function confirmClear() {
  if (clearing.value) return
  clearing.value = true
  clearError.value = ''
  try {
    const cleared = await admin.clearKnowbaseCache()
    clearOpen.value = false
    toast.add({
      title: t('admin.dashboard.knowbase.cleared', { count: cleared }, cleared),
      color: 'success',
      icon: 'i-lucide-check',
    })
  } catch (error) {
    clearError.value = adminError(error)
  } finally {
    clearing.value = false
  }
}

// --- Send the admin digest now ---------------------------------------------------------------

const digestOpen = ref(false)
const sendingDigest = ref(false)
const digestError = ref('')

function askDigest() {
  digestError.value = ''
  digestOpen.value = true
}

async function confirmDigest() {
  if (sendingDigest.value) return
  sendingDigest.value = true
  digestError.value = ''
  try {
    const { recipients, items, sent } = await adminService.sendDigest()
    digestOpen.value = false
    toast.add(
      sent
        ? {
            title: t('admin.dashboard.digest.sent', { recipients, items }, recipients),
            color: 'success',
            icon: 'i-lucide-check',
          }
        : {
            title: t('admin.dashboard.digest.failed'),
            color: 'warning',
            icon: 'i-lucide-triangle-alert',
          },
    )
  } catch (error) {
    digestError.value = adminError(error)
  } finally {
    sendingDigest.value = false
  }
}

// --- Reporting export -------------------------------------------------------------------------

const from = ref(PROJECT_START)
const to = ref(localDateInput())
const rangeError = ref('')
const exportError = ref('')
const exporting = ref(false)

async function downloadCsv() {
  rangeError.value = ''
  exportError.value = ''
  // `YYYY-MM-DD` strings compare in date order.
  if (from.value && to.value && from.value > to.value) {
    rangeError.value = t('admin.dashboard.export.invalidRange')
    return
  }
  exporting.value = true
  try {
    const { blob, filename } = await adminService.exportStats({
      from: from.value || PROJECT_START,
      to: to.value || localDateInput(),
    })
    saveFile(blob, filename)
  } catch {
    exportError.value = t('admin.dashboard.export.failed')
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div class="space-y-10">
    <AdminPageHeader :title="t('admin.dashboard.title')" :intro="t('admin.dashboard.intro')" />

    <div v-if="statsLoading && !stats" aria-busy="true" class="grid gap-4 sm:grid-cols-3">
      <span class="sr-only">{{ t('admin.common.loading') }}</span>
      <USkeleton v-for="n in 6" :key="n" class="h-24" />
    </div>

    <div v-else-if="statsFailed && !stats" role="alert">
      <UAlert
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :title="t('admin.dashboard.loadError')"
        :actions="[
          {
            label: t('admin.common.retry'),
            color: 'error',
            variant: 'outline',
            icon: 'i-lucide-rotate-cw',
            onClick: () => admin.fetchStats(),
          },
        ]"
      />
    </div>

    <template v-else-if="stats">
      <section
        v-for="group in groups"
        :key="group.id"
        :aria-labelledby="`dashboard-${group.id}`"
        class="space-y-3"
      >
        <h2 :id="`dashboard-${group.id}`" class="text-lg font-semibold text-highlighted">
          {{ group.heading }}
        </h2>
        <dl class="grid gap-3 sm:grid-cols-3 xl:grid-cols-5">
          <div
            v-for="stat in group.stats"
            :key="stat.key"
            :data-testid="`stat-${stat.key}`"
            class="flex flex-col-reverse rounded-md border border-default bg-default p-4"
          >
            <dt class="text-sm text-muted">{{ stat.label }}</dt>
            <dd class="text-2xl font-semibold text-highlighted tabular-nums">
              {{ number(stat.value) }}
            </dd>
          </div>
        </dl>
      </section>

      <section
        aria-labelledby="dashboard-knowbase"
        data-testid="knowbase-status"
        class="space-y-4 rounded-md border border-default p-4"
      >
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h2 id="dashboard-knowbase" class="text-lg font-semibold text-highlighted">
            {{ t('admin.dashboard.knowbase.heading') }}
          </h2>
          <UBadge
            :color="stats.knowbase.reachable ? 'success' : 'error'"
            :icon="stats.knowbase.reachable ? 'i-lucide-plug-zap' : 'i-lucide-unplug'"
            variant="subtle"
          >
            {{
              stats.knowbase.reachable
                ? t('admin.dashboard.knowbase.reachable')
                : t('admin.dashboard.knowbase.unreachable')
            }}
          </UBadge>
        </div>
        <dl class="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
          <dt class="text-muted">{{ t('admin.dashboard.knowbase.lastSuccess') }}</dt>
          <dd>{{ when(stats.knowbase.last_success_at) }}</dd>
          <template v-if="stats.knowbase.last_error_at || stats.knowbase.last_error">
            <dt class="text-muted">{{ t('admin.dashboard.knowbase.lastErrorAt') }}</dt>
            <dd>{{ when(stats.knowbase.last_error_at) }}</dd>
            <dt class="text-muted">{{ t('admin.dashboard.knowbase.lastError') }}</dt>
            <dd>
              <code class="text-xs break-all">{{ stats.knowbase.last_error ?? '—' }}</code>
            </dd>
          </template>
        </dl>
        <div>
          <h3 class="mb-2 text-sm font-semibold text-highlighted">
            {{ t('admin.dashboard.knowbase.cache') }}
          </h3>
          <dl class="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div
              v-for="stat in cacheStats"
              :key="stat.key"
              :data-testid="`stat-${stat.key}`"
              class="flex flex-col-reverse rounded border border-default p-3"
            >
              <dt class="text-xs text-muted">{{ stat.label }}</dt>
              <dd class="text-lg font-semibold tabular-nums">{{ number(stat.value) }}</dd>
            </div>
          </dl>
        </div>
        <UButton color="warning" variant="outline" icon="i-lucide-eraser" @click="askClear">
          {{ t('admin.dashboard.knowbase.clear') }}
        </UButton>
      </section>
    </template>

    <section
      aria-labelledby="dashboard-digest"
      data-testid="digest-send"
      class="space-y-4 rounded-md border border-default p-4"
    >
      <h2 id="dashboard-digest" class="text-lg font-semibold text-highlighted">
        {{ t('admin.dashboard.digest.heading') }}
      </h2>
      <p class="text-sm text-muted">{{ t('admin.dashboard.digest.intro') }}</p>
      <UButton color="neutral" variant="outline" icon="i-lucide-send" @click="askDigest">
        {{ t('admin.dashboard.digest.button') }}
      </UButton>
    </section>

    <section
      aria-labelledby="dashboard-export"
      class="space-y-4 rounded-md border border-default p-4"
    >
      <h2 id="dashboard-export" class="text-lg font-semibold text-highlighted">
        {{ t('admin.dashboard.export.heading') }}
      </h2>
      <p class="text-sm text-muted">{{ t('admin.dashboard.export.description') }}</p>
      <form novalidate class="flex flex-wrap items-start gap-4" @submit.prevent="downloadCsv">
        <UFormField :label="t('admin.dashboard.export.from')" name="from">
          <UInput v-model="from" type="date" :max="to || undefined" />
        </UFormField>
        <UFormField
          :label="t('admin.dashboard.export.to')"
          name="to"
          :error="rangeError || undefined"
        >
          <UInput v-model="to" type="date" :min="from || undefined" />
        </UFormField>
        <UButton type="submit" icon="i-lucide-download" :loading="exporting" class="mt-6">
          {{ t('admin.dashboard.export.download') }}
        </UButton>
      </form>
      <div role="alert">
        <UAlert
          v-if="exportError"
          color="error"
          variant="subtle"
          icon="i-lucide-circle-alert"
          :title="exportError"
        />
      </div>
    </section>

    <ConfirmDialog
      v-model:open="clearOpen"
      :title="t('admin.dashboard.knowbase.clearTitle')"
      :description="t('admin.dashboard.knowbase.clearDescription')"
      :confirm-label="t('admin.dashboard.knowbase.clearConfirm')"
      color="warning"
      :loading="clearing"
      :error="clearError"
      @confirm="confirmClear"
    />

    <ConfirmDialog
      v-model:open="digestOpen"
      :title="t('admin.dashboard.digest.title')"
      :description="t('admin.dashboard.digest.description')"
      :confirm-label="t('admin.dashboard.digest.confirm')"
      :loading="sendingDigest"
      :error="digestError"
      @confirm="confirmDigest"
    />
  </div>
</template>

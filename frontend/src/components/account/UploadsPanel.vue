<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from '@nuxt/ui/composables'

import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import { uploadsService, type MyUpload, type UploadUsage } from '@/services/uploads'
import { contentLink } from '@/utils/contentLink'
import { formatDate } from '@/utils/datetime'

/**
 * The member's own uploads (`GET /uploads/mine/`): thumbnail, alt text, size, date and the content
 * that uses each image. An image still used by content that is not deleted cannot be deleted (the
 * button is disabled, with the reason as visible text next to it; the server answers 409
 * `uploads.in_use` anyway); the others are deleted after confirming.
 */
const PAGE_SIZE = 50

const { t, locale } = useI18n()
const toast = useToast()
const { errorMessage } = useApiErrors()

const uploads = ref<MyUpload[]>([])
const total = ref(0)
const loading = ref(true)
const loadingMore = ref(false)
const loadFailed = ref(false)

async function load() {
  loading.value = true
  loadFailed.value = false
  try {
    const page = await uploadsService.listMine({ skip: 0, limit: PAGE_SIZE })
    uploads.value = page.items
    total.value = page.total
  } catch {
    loadFailed.value = true
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  loadingMore.value = true
  try {
    const page = await uploadsService.listMine({ skip: uploads.value.length, limit: PAGE_SIZE })
    const known = new Set(uploads.value.map((u) => u.id))
    uploads.value.push(...page.items.filter((u) => !known.has(u.id)))
    total.value = page.total
  } catch (error) {
    toast.add({ title: errorMessage(error), color: 'error', icon: 'i-lucide-circle-alert' })
  } finally {
    loadingMore.value = false
  }
}

onMounted(load)

/** "240 kB", "1.2 MB" in the UI locale (binary multiples, as the upload limit). */
function formatSize(bytes: number): string {
  const mb = bytes >= 1024 * 1024
  const value = mb ? bytes / (1024 * 1024) : Math.max(1, Math.round(bytes / 1024))
  return new Intl.NumberFormat([locale.value, 'en'], {
    style: 'unit',
    unit: mb ? 'megabyte' : 'kilobyte',
    unitDisplay: 'short',
    maximumFractionDigits: mb ? 1 : 0,
  }).format(value)
}

const usageLink = (usage: UploadUsage) =>
  contentLink(usage.content_type, usage.id, usage.slug) ?? undefined
/** Live content still uses it. Content in status `deleted` does not block the owner's delete
 * (the server agrees); the hint then says a restore would show it without the image. */
const blocked = (upload: MyUpload) => upload.used_in.some((usage) => usage.status !== 'deleted')
const usageTitle = (usage: UploadUsage) =>
  usage.title || t(`account.uploads.types.${usage.content_type}`)

// --- Delete -----------------------------------------------------------------------------------

const target = ref<MyUpload | null>(null)
const deleteOpen = ref(false)
const deleting = ref(false)
const deleteError = ref('')

function askDelete(upload: MyUpload) {
  target.value = upload
  deleteError.value = ''
  deleteOpen.value = true
}

async function confirmDelete() {
  const upload = target.value
  if (!upload || deleting.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    await uploadsService.deleteUpload(upload.id)
    uploads.value = uploads.value.filter((u) => u.id !== upload.id)
    total.value = Math.max(0, total.value - 1)
    deleteOpen.value = false
    toast.add({ title: t('account.uploads.deleted'), color: 'success', icon: 'i-lucide-check' })
  } catch (error) {
    deleteError.value = errorMessage(error)
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <div class="space-y-5">
    <p class="text-sm text-muted">{{ t('account.uploads.intro') }}</p>

    <div v-if="loading" aria-busy="true" class="space-y-3">
      <span class="sr-only">{{ t('account.uploads.loading') }}</span>
      <USkeleton v-for="n in 3" :key="n" class="h-24 w-full" />
    </div>

    <div v-else-if="loadFailed" role="alert">
      <UAlert
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :title="t('account.uploads.loadError')"
        :actions="[
          {
            label: t('account.uploads.retry'),
            color: 'error',
            variant: 'outline',
            icon: 'i-lucide-rotate-cw',
            onClick: load,
          },
        ]"
      />
    </div>

    <template v-else>
      <p v-if="!uploads.length" class="text-sm text-muted">{{ t('account.uploads.empty') }}</p>
      <ul v-else class="divide-y divide-default rounded-md border border-default">
        <li
          v-for="upload in uploads"
          :key="upload.id"
          data-testid="upload-row"
          :data-alt="upload.alt_text"
          class="flex flex-wrap items-start gap-4 p-4"
        >
          <img
            :src="upload.thumb_url ?? upload.url"
            :alt="upload.alt_text"
            :width="96"
            :height="Math.round((96 * upload.height) / Math.max(1, upload.width))"
            loading="lazy"
            class="h-auto w-24 shrink-0 rounded border border-default object-cover"
          />
          <div class="min-w-0 flex-1 space-y-1">
            <p class="font-medium break-words text-highlighted">{{ upload.alt_text }}</p>
            <p class="text-xs text-muted">
              {{ formatSize(upload.size_bytes) }} · {{ upload.width }}×{{ upload.height }} ·
              <time :datetime="upload.created_at">{{ formatDate(upload.created_at, locale) }}</time>
            </p>
            <div v-if="upload.used_in.length" class="text-sm">
              <span class="text-muted">{{ t('account.uploads.usedIn') }}</span>
              <ul class="mt-1 space-y-0.5">
                <li
                  v-for="usage in upload.used_in"
                  :key="`${usage.content_type}-${usage.id}`"
                  class="flex flex-wrap items-center gap-1.5"
                >
                  <ULink
                    v-if="usageLink(usage)"
                    :to="usageLink(usage)"
                    raw
                    class="text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
                  >
                    {{ usageTitle(usage) }}
                  </ULink>
                  <span v-else>{{ usageTitle(usage) }}</span>
                  <UBadge
                    v-if="usage.status !== 'published'"
                    color="neutral"
                    variant="subtle"
                    size="sm"
                  >
                    {{ t(`post.status.${usage.status}`) }}
                  </UBadge>
                </li>
              </ul>
            </div>
            <p v-else class="text-sm text-muted">{{ t('account.uploads.notUsed') }}</p>
          </div>
          <div class="flex max-w-56 flex-col items-end gap-1 text-end">
            <UButton
              color="error"
              variant="outline"
              size="sm"
              icon="i-lucide-trash-2"
              :disabled="blocked(upload)"
              :aria-label="t('account.uploads.deleteLabel', { alt: upload.alt_text })"
              :aria-describedby="upload.used_in.length ? `upload-hint-${upload.id}` : undefined"
              @click="askDelete(upload)"
            >
              {{ t('account.uploads.delete') }}
            </UButton>
            <p
              v-if="upload.used_in.length"
              :id="`upload-hint-${upload.id}`"
              data-testid="upload-hint"
              class="text-xs text-muted"
            >
              {{ blocked(upload) ? t('account.uploads.inUse') : t('account.uploads.onlyDeleted') }}
            </p>
          </div>
        </li>
      </ul>
      <div v-if="uploads.length < total" class="flex justify-center">
        <UButton color="neutral" variant="outline" :loading="loadingMore" @click="loadMore">
          {{ t('account.uploads.loadMore') }}
        </UButton>
      </div>
    </template>

    <ConfirmDialog
      v-model:open="deleteOpen"
      :title="t('account.uploads.deleteTitle')"
      :description="t('account.uploads.deleteDescription')"
      :confirm-label="t('account.uploads.deleteConfirm')"
      color="error"
      :loading="deleting"
      :error="deleteError"
      @confirm="confirmDelete"
    />
  </div>
</template>

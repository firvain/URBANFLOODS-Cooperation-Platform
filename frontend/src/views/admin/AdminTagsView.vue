<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useToast } from '@nuxt/ui/composables'
import type { TableColumn } from '@nuxt/ui'

import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import AdminPagination from '@/components/admin/AdminPagination.vue'
import ListState from '@/components/admin/ListState.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { useAdminErrors } from '@/composables/useAdminErrors'
import { useDebouncedSearch } from '@/composables/useKnowbaseList'
import { useQueryFilters } from '@/composables/useQueryFilters'
import { ADMIN_LONG_PAGE_SIZE, ADMIN_SEARCH_DEBOUNCE_MS } from '@/constants/admin'
import { tagsService, type TagOut } from '@/services/tags'
import { useAdminStore } from '@/stores/admin'

/**
 * Tags by name (search in the URL): merge a tag into another (its uses move, it is deleted) or
 * delete a tag nobody uses. The API has no rename; merging into a new spelling replaces it.
 */
const { t } = useI18n()
const route = useRoute()
const toast = useToast()
const admin = useAdminStore()
const tags = admin.tags
const { adminError } = useAdminErrors()
const { filters, page, setFilters, setPage } = useQueryFilters({ q: 'string' })

const search = useDebouncedSearch(
  () => filters.value.q,
  (q) => setFilters({ q }),
  ADMIN_SEARCH_DEBOUNCE_MS,
)

const params = computed(() => ({
  q: filters.value.q || undefined,
  skip: (page.value - 1) * ADMIN_LONG_PAGE_SIZE,
  limit: ADMIN_LONG_PAGE_SIZE,
}))

watch(
  () => JSON.stringify(params.value),
  () => {
    if (route.name === 'admin-tags') void admin.fetchTags(params.value)
  },
  { immediate: true },
)

const columns = computed<TableColumn<TagOut>[]>(() => [
  { id: 'name', header: t('admin.tags.name') },
  { id: 'slug', header: t('admin.tags.slug') },
  { id: 'usage', header: t('admin.tags.usage') },
  { id: 'actions', header: t('admin.common.actions') },
])

// --- Merge ------------------------------------------------------------------------------------

/** Merge targets offered in the picker (the API's page size cap). */
const TARGETS_LIMIT = 100

const merging = ref<TagOut | null>(null)
const mergeOpen = ref(false)
const mergeLoading = ref(false)
const mergeError = ref('')
const targetId = ref<number | undefined>()
const candidates = ref<TagOut[]>([])
const targetSearch = ref('')
const formId = useId()

const targetItems = computed(() =>
  candidates.value
    .filter((tag) => tag.id !== merging.value?.id)
    .map((tag) => ({ label: tag.name, value: tag.id })),
)
const target = computed(() => candidates.value.find((tag) => tag.id === targetId.value))

/** The picker searches the server as the admin types (the current page is the first answer). */
let latestSearch = 0
async function loadCandidates(q: string) {
  const request = ++latestSearch
  try {
    const { items } = await tagsService.list({
      q: q || undefined,
      sort: 'name',
      limit: TARGETS_LIMIT,
    })
    if (request !== latestSearch) return
    const chosen = target.value
    candidates.value = chosen && !items.some((i) => i.id === chosen.id) ? [chosen, ...items] : items
  } catch {
    // Keep the current candidates.
  }
}
watch(targetSearch, (q) => {
  if (mergeOpen.value) void loadCandidates(q.trim())
})

function askMerge(tag: TagOut) {
  merging.value = tag
  targetId.value = undefined
  targetSearch.value = ''
  candidates.value = [...tags.items]
  mergeError.value = ''
  mergeOpen.value = true
  void loadCandidates('')
}

async function confirmMerge() {
  const source = merging.value
  if (!source || mergeLoading.value) return
  const chosen = target.value
  if (!chosen) {
    mergeError.value = t('admin.tags.mergeTargetPlaceholder')
    return
  }
  mergeLoading.value = true
  mergeError.value = ''
  try {
    await admin.mergeTag(source.id, chosen.id)
    mergeOpen.value = false
    toast.add({
      title: t('admin.tags.merged', { source: source.name, target: chosen.name }),
      color: 'success',
      icon: 'i-lucide-check',
    })
  } catch (error) {
    mergeError.value = adminError(error)
  } finally {
    mergeLoading.value = false
  }
}

// --- Delete -----------------------------------------------------------------------------------

const deleting = ref<TagOut | null>(null)
const deleteOpen = ref(false)
const deleteLoading = ref(false)
const deleteError = ref('')

function askDelete(tag: TagOut) {
  deleting.value = tag
  deleteError.value = ''
  deleteOpen.value = true
}

async function confirmDelete() {
  const tag = deleting.value
  if (!tag || deleteLoading.value) return
  deleteLoading.value = true
  deleteError.value = ''
  try {
    await admin.deleteTag(tag.id)
    deleteOpen.value = false
    toast.add({
      title: t('admin.tags.deleted', { name: tag.name }),
      color: 'neutral',
      icon: 'i-lucide-trash-2',
    })
  } catch (error) {
    deleteError.value = adminError(error)
  } finally {
    deleteLoading.value = false
  }
}
</script>

<template>
  <div>
    <AdminPageHeader :title="t('admin.tags.title')" :intro="t('admin.tags.intro')" />

    <div class="mb-6 max-w-sm">
      <UFormField :label="t('admin.tags.search')" name="q">
        <UInput v-model="search" type="search" icon="i-lucide-search" class="w-full" />
      </UFormField>
    </div>

    <ListState
      :initial="tags.initial"
      :loading="tags.loading"
      :failed="tags.failed"
      @retry="admin.reloadTags()"
    >
      <p v-if="!tags.items.length" class="rounded border border-default p-6 text-center text-muted">
        {{ t('admin.tags.empty') }}
      </p>
      <div v-else data-testid="tags-table" class="overflow-x-auto">
        <UTable
          :data="tags.items"
          :columns="columns"
          :caption="t('admin.tags.caption')"
          :loading="tags.loading"
          :ui="{ caption: 'sr-only' }"
        >
          <template #name-cell="{ row }">
            <span class="font-medium text-highlighted">{{ row.original.name }}</span>
          </template>
          <template #slug-cell="{ row }">
            <span class="font-mono text-xs text-muted">{{ row.original.slug }}</span>
          </template>
          <template #usage-cell="{ row }">
            <span class="tabular-nums">{{ row.original.usage_count }}</span>
          </template>
          <template #actions-cell="{ row }">
            <div class="flex gap-1">
              <UButton
                size="sm"
                color="neutral"
                variant="outline"
                icon="i-lucide-merge"
                :aria-label="t('admin.tags.mergeLabel', { name: row.original.name })"
                @click="askMerge(row.original)"
              >
                {{ t('admin.tags.merge') }}
              </UButton>
              <UButton
                v-if="row.original.usage_count === 0"
                size="sm"
                color="error"
                variant="ghost"
                icon="i-lucide-trash-2"
                :aria-label="t('admin.tags.deleteLabel', { name: row.original.name })"
                @click="askDelete(row.original)"
              />
            </div>
          </template>
        </UTable>
      </div>
      <AdminPagination
        :page="page"
        :total="tags.total"
        :page-size="ADMIN_LONG_PAGE_SIZE"
        @update:page="setPage"
      />
    </ListState>

    <UModal
      v-model:open="mergeOpen"
      :title="t('admin.tags.mergeTitle', { name: merging?.name ?? '' })"
      :dismissible="!mergeLoading"
    >
      <template #body>
        <form :id="formId" novalidate class="space-y-4" @submit.prevent="confirmMerge">
          <div role="alert">
            <UAlert
              v-if="mergeError"
              color="error"
              variant="subtle"
              icon="i-lucide-circle-alert"
              :title="mergeError"
            />
          </div>
          <UFormField :label="t('admin.tags.mergeTarget')" name="target_id" required>
            <USelectMenu
              v-model="targetId"
              v-model:search-term="targetSearch"
              :items="targetItems"
              value-key="value"
              :placeholder="t('admin.tags.mergeTargetPlaceholder')"
              class="w-full"
            />
          </UFormField>
          <p v-if="merging && target" role="status" class="text-sm text-warning-700">
            {{
              t('admin.tags.mergeWarning', {
                source: merging.name,
                target: target.name,
                count: merging.usage_count,
              })
            }}
          </p>
        </form>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton
            color="neutral"
            variant="outline"
            :disabled="mergeLoading"
            @click="mergeOpen = false"
          >
            {{ t('common.cancel') }}
          </UButton>
          <UButton type="submit" :form="formId" color="warning" :loading="mergeLoading">
            {{ t('admin.tags.mergeConfirm') }}
          </UButton>
        </div>
      </template>
    </UModal>

    <ConfirmDialog
      v-model:open="deleteOpen"
      :title="t('admin.tags.deleteTitle', { name: deleting?.name ?? '' })"
      :description="t('admin.tags.deleteDescription')"
      :confirm-label="t('admin.tags.delete')"
      color="error"
      :loading="deleteLoading"
      :error="deleteError"
      @confirm="confirmDelete"
    />
  </div>
</template>

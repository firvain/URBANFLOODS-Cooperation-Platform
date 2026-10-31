<script setup lang="ts">
import { computed, onMounted, reactive, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from '@nuxt/ui/composables'
import type { TableColumn } from '@nuxt/ui'

import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import ListState from '@/components/admin/ListState.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { useAdminErrors } from '@/composables/useAdminErrors'
import {
  CATEGORY_DESCRIPTION_MAX_LENGTH,
  CATEGORY_NAME_MAX_LENGTH,
  CATEGORY_NAME_MIN_LENGTH,
  CATEGORY_SLUG_MAX_LENGTH,
  CATEGORY_SLUG_PATTERN,
  CATEGORY_SORT_ORDER_MAX,
} from '@/constants/admin'
import type {
  CategoryCreate,
  CategoryKind,
  CategoryOut,
  CategoryUpdate,
} from '@/services/categories'
import { useAdminStore } from '@/stores/admin'

/**
 * Categories (blog and forum, archived ones included): create, edit, archive and restore.
 * Validation mirrors the backend; server conflicts (`categories.*`) show in the dialog.
 */
const { t } = useI18n()
const toast = useToast()
const admin = useAdminStore()
const { adminError } = useAdminErrors()

onMounted(() => void admin.fetchCategories())

const KINDS: CategoryKind[] = ['blog', 'forum']
const kindItems = computed(() =>
  KINDS.map((k) => ({ label: t(`admin.categories.kinds.${k}`), value: k })),
)

const columns = computed<TableColumn<CategoryOut>[]>(() => [
  { id: 'name', header: t('admin.categories.name') },
  { id: 'kind', header: t('admin.categories.kind') },
  { id: 'order', header: t('admin.categories.sortOrder') },
  { id: 'posts', header: t('admin.categories.posts') },
  { id: 'adminOnly', header: t('admin.categories.adminOnly') },
  { id: 'actions', header: t('admin.common.actions') },
])

// --- Create / edit ----------------------------------------------------------------------------

const editing = ref<CategoryOut | null>(null)
const formOpen = ref(false)
const saving = ref(false)
const formError = ref('')
const formId = useId()
const form = reactive({
  kind: 'blog' as CategoryKind,
  name: '',
  slug: '',
  description: '',
  // Text (a number input); read with `String()` as the input may hand back a number.
  sortOrder: '0',
  adminOnly: false,
})
const errors = reactive<Record<'name' | 'slug' | 'description' | 'sortOrder', string | undefined>>({
  name: undefined,
  slug: undefined,
  description: undefined,
  sortOrder: undefined,
})

function openForm(category: CategoryOut | null) {
  editing.value = category
  Object.assign(form, {
    kind: category?.kind ?? 'blog',
    name: category?.name ?? '',
    slug: category?.slug ?? '',
    description: category?.description ?? '',
    sortOrder: String(category?.sort_order ?? 0),
    adminOnly: category?.admin_only ?? false,
  })
  Object.assign(errors, {
    name: undefined,
    slug: undefined,
    description: undefined,
    sortOrder: undefined,
  })
  formError.value = ''
  formOpen.value = true
}

function validate(): boolean {
  const name = form.name.trim()
  const slug = form.slug.trim()
  const orderText = String(form.sortOrder ?? '').trim()
  const order = Number(orderText)
  errors.name =
    name.length < CATEGORY_NAME_MIN_LENGTH
      ? t('admin.categories.validation.nameRequired', { min: CATEGORY_NAME_MIN_LENGTH })
      : name.length > CATEGORY_NAME_MAX_LENGTH
        ? t('admin.categories.validation.nameTooLong', { max: CATEGORY_NAME_MAX_LENGTH })
        : undefined
  errors.slug =
    slug && (slug.length > CATEGORY_SLUG_MAX_LENGTH || !CATEGORY_SLUG_PATTERN.test(slug))
      ? t('admin.categories.validation.slugInvalid')
      : undefined
  errors.description =
    form.description.trim().length > CATEGORY_DESCRIPTION_MAX_LENGTH
      ? t('admin.categories.validation.descriptionTooLong', {
          max: CATEGORY_DESCRIPTION_MAX_LENGTH,
        })
      : undefined
  errors.sortOrder =
    orderText === '' || !Number.isInteger(order) || order < 0 || order > CATEGORY_SORT_ORDER_MAX
      ? t('admin.categories.validation.sortOrderInvalid', { max: CATEGORY_SORT_ORDER_MAX })
      : undefined
  return !Object.values(errors).some(Boolean)
}

/** The edit as a partial update: only the fields that changed (a blank slug keeps the old one). */
function changesFrom(category: CategoryOut): CategoryUpdate {
  const changes: CategoryUpdate = {}
  const name = form.name.trim()
  const slug = form.slug.trim()
  const description = form.description.trim() || null
  const sortOrder = Number(form.sortOrder)
  if (name !== category.name) changes.name = name
  if (slug && slug !== category.slug) changes.slug = slug
  if (description !== category.description) changes.description = description
  if (sortOrder !== category.sort_order) changes.sort_order = sortOrder
  if (form.adminOnly !== category.admin_only) changes.admin_only = form.adminOnly
  return changes
}

async function save() {
  if (saving.value || !validate()) return
  saving.value = true
  formError.value = ''
  try {
    const category = editing.value
    let saved: CategoryOut
    if (category) {
      const changes = changesFrom(category)
      saved = Object.keys(changes).length
        ? await admin.updateCategory(category.id, changes)
        : category
    } else {
      const payload: CategoryCreate = {
        kind: form.kind,
        name: form.name.trim(),
        slug: form.slug.trim() || null,
        description: form.description.trim() || null,
        sort_order: Number(form.sortOrder),
        admin_only: form.adminOnly,
      }
      saved = await admin.createCategory(payload)
    }
    formOpen.value = false
    toast.add({
      title: t(category ? 'admin.categories.updated' : 'admin.categories.created', {
        name: saved.name,
      }),
      color: 'success',
      icon: 'i-lucide-check',
    })
  } catch (error) {
    formError.value = adminError(error)
  } finally {
    saving.value = false
  }
}

// --- Archive / restore ------------------------------------------------------------------------

const archiving = ref<CategoryOut | null>(null)
const archiveOpen = ref(false)
const archiveLoading = ref(false)
const archiveError = ref('')

function askArchive(category: CategoryOut) {
  archiving.value = category
  archiveError.value = ''
  archiveOpen.value = true
}

async function confirmArchive() {
  const category = archiving.value
  if (!category || archiveLoading.value) return
  archiveLoading.value = true
  archiveError.value = ''
  try {
    await admin.archiveCategory(category.id)
    archiveOpen.value = false
    toast.add({
      title: t('admin.categories.archivedDone', { name: category.name }),
      color: 'neutral',
      icon: 'i-lucide-archive',
    })
  } catch (error) {
    archiveError.value = adminError(error)
  } finally {
    archiveLoading.value = false
  }
}

async function restore(category: CategoryOut) {
  try {
    await admin.updateCategory(category.id, { is_archived: false })
    toast.add({
      title: t('admin.categories.restored', { name: category.name }),
      color: 'success',
      icon: 'i-lucide-check',
    })
  } catch (error) {
    toast.add({ title: adminError(error), color: 'error', icon: 'i-lucide-circle-alert' })
  }
}
</script>

<template>
  <div>
    <AdminPageHeader :title="t('admin.categories.title')" :intro="t('admin.categories.intro')">
      <template #actions>
        <UButton icon="i-lucide-plus" class="shrink-0 self-start" @click="openForm(null)">
          {{ t('admin.categories.create') }}
        </UButton>
      </template>
    </AdminPageHeader>

    <ListState
      :initial="admin.categoriesLoading && !admin.categories.length"
      :loading="admin.categoriesLoading"
      :failed="admin.categoriesFailed"
      @retry="admin.fetchCategories()"
    >
      <p
        v-if="!admin.categories.length"
        class="rounded border border-default p-6 text-center text-muted"
      >
        {{ t('admin.categories.empty') }}
      </p>
      <div v-else data-testid="categories-table" class="overflow-x-auto">
        <UTable
          :data="admin.categories"
          :columns="columns"
          :caption="t('admin.categories.caption')"
          :ui="{ caption: 'sr-only', td: 'align-top' }"
        >
          <template #name-cell="{ row }">
            <div class="max-w-sm min-w-48 space-y-0.5 whitespace-normal">
              <div class="flex flex-wrap items-center gap-1.5">
                <span class="font-medium text-highlighted">{{ row.original.name }}</span>
                <UBadge v-if="row.original.is_archived" color="neutral" variant="subtle" size="sm">
                  {{ t('admin.categories.archived') }}
                </UBadge>
              </div>
              <p class="font-mono text-xs text-muted">{{ row.original.slug }}</p>
              <p v-if="row.original.description" class="line-clamp-2 text-sm text-muted">
                {{ row.original.description }}
              </p>
            </div>
          </template>
          <template #kind-cell="{ row }">
            {{ t(`admin.categories.kinds.${row.original.kind}`) }}
          </template>
          <template #order-cell="{ row }">
            <span class="tabular-nums">{{ row.original.sort_order }}</span>
          </template>
          <template #posts-cell="{ row }">
            <span class="tabular-nums">{{ row.original.post_count }}</span>
          </template>
          <template #adminOnly-cell="{ row }">
            {{ row.original.admin_only ? t('admin.common.yes') : t('admin.common.no') }}
          </template>
          <template #actions-cell="{ row }">
            <div class="flex gap-1">
              <UButton
                size="sm"
                color="neutral"
                variant="ghost"
                icon="i-lucide-pencil"
                :aria-label="t('admin.categories.editLabel', { name: row.original.name })"
                @click="openForm(row.original)"
              />
              <UButton
                v-if="row.original.is_archived"
                size="sm"
                color="neutral"
                variant="ghost"
                icon="i-lucide-archive-restore"
                :aria-label="t('admin.categories.unarchiveLabel', { name: row.original.name })"
                @click="restore(row.original)"
              />
              <UButton
                v-else
                size="sm"
                color="error"
                variant="ghost"
                icon="i-lucide-archive"
                :aria-label="t('admin.categories.archiveLabel', { name: row.original.name })"
                @click="askArchive(row.original)"
              />
            </div>
          </template>
        </UTable>
      </div>
    </ListState>

    <UModal
      v-model:open="formOpen"
      :title="
        editing
          ? t('admin.categories.editTitle', { name: editing.name })
          : t('admin.categories.createTitle')
      "
      :dismissible="!saving"
    >
      <template #body>
        <form :id="formId" novalidate class="space-y-4" @submit.prevent="save">
          <div role="alert">
            <UAlert
              v-if="formError"
              color="error"
              variant="subtle"
              icon="i-lucide-circle-alert"
              :title="formError"
            />
          </div>
          <UFormField :label="t('admin.categories.kind')" name="kind" required>
            <USelect v-model="form.kind" :items="kindItems" :disabled="!!editing" class="w-full" />
          </UFormField>
          <UFormField :label="t('admin.categories.name')" name="name" required :error="errors.name">
            <UInput v-model="form.name" :maxlength="CATEGORY_NAME_MAX_LENGTH" class="w-full" />
          </UFormField>
          <UFormField
            :label="t('admin.categories.slug')"
            name="slug"
            :help="t('admin.categories.slugHelp')"
            :error="errors.slug"
          >
            <UInput
              v-model="form.slug"
              :maxlength="CATEGORY_SLUG_MAX_LENGTH"
              class="w-full font-mono"
            />
          </UFormField>
          <UFormField
            :label="t('admin.categories.description')"
            name="description"
            :error="errors.description"
          >
            <UTextarea
              v-model="form.description"
              :rows="3"
              :maxlength="CATEGORY_DESCRIPTION_MAX_LENGTH"
              class="w-full"
            />
          </UFormField>
          <UFormField
            :label="t('admin.categories.sortOrder')"
            name="sort_order"
            required
            :error="errors.sortOrder"
          >
            <UInput
              v-model="form.sortOrder"
              type="number"
              inputmode="numeric"
              :min="0"
              :max="CATEGORY_SORT_ORDER_MAX"
              class="w-32"
            />
          </UFormField>
          <UCheckbox
            v-model="form.adminOnly"
            name="admin_only"
            :label="t('admin.categories.adminOnly')"
            :description="t('admin.categories.adminOnlyHelp')"
          />
        </form>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton color="neutral" variant="outline" :disabled="saving" @click="formOpen = false">
            {{ t('common.cancel') }}
          </UButton>
          <UButton type="submit" :form="formId" :loading="saving">
            {{ t('admin.categories.save') }}
          </UButton>
        </div>
      </template>
    </UModal>

    <ConfirmDialog
      v-model:open="archiveOpen"
      :title="t('admin.categories.archiveTitle', { name: archiving?.name ?? '' })"
      :description="t('admin.categories.archiveDescription')"
      :confirm-label="t('admin.categories.archive')"
      color="error"
      :loading="archiveLoading"
      :error="archiveError"
      @confirm="confirmArchive"
    />
  </div>
</template>

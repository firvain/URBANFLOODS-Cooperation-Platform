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
  EXPERTISE_LABEL_MAX_LENGTH,
  EXPERTISE_LABEL_MIN_LENGTH,
  EXPERTISE_SLUG_MAX_LENGTH,
  EXPERTISE_SLUG_PATTERN,
  EXPERTISE_SORT_ORDER_MAX,
} from '@/constants/admin'
import type { ExpertiseTag, ExpertiseTagCreate, ExpertiseTagUpdate } from '@/services/expertise'
import { useAdminStore } from '@/stores/admin'

/**
 * Expertise areas (deactivated ones included): create, edit, deactivate and reactivate. There is
 * no delete: a deactivated area stays on the members who have it but cannot be picked any more.
 * Validation mirrors the backend; server conflicts (`expertise.*`) show in the dialog.
 */
const { t } = useI18n()
const toast = useToast()
const admin = useAdminStore()
const { adminError } = useAdminErrors()

onMounted(() => void admin.fetchExpertise())

const columns = computed<TableColumn<ExpertiseTag>[]>(() => [
  { id: 'label', header: t('admin.expertise.label') },
  { id: 'slug', header: t('admin.expertise.slug') },
  { id: 'order', header: t('admin.expertise.sortOrder') },
  { id: 'status', header: t('admin.expertise.status') },
  { id: 'actions', header: t('admin.common.actions') },
])

// --- Create / edit ----------------------------------------------------------------------------

const editing = ref<ExpertiseTag | null>(null)
const formOpen = ref(false)
const saving = ref(false)
const formError = ref('')
const formId = useId()
const form = reactive({
  label: '',
  slug: '',
  // Text (a number input); read with `String()` as the input may hand back a number.
  sortOrder: '0',
})
const errors = reactive<Record<'label' | 'slug' | 'sortOrder', string | undefined>>({
  label: undefined,
  slug: undefined,
  sortOrder: undefined,
})

function openForm(tag: ExpertiseTag | null) {
  editing.value = tag
  Object.assign(form, {
    label: tag?.label ?? '',
    slug: tag?.slug ?? '',
    sortOrder: String(tag?.sort_order ?? 0),
  })
  Object.assign(errors, { label: undefined, slug: undefined, sortOrder: undefined })
  formError.value = ''
  formOpen.value = true
}

function validate(): boolean {
  const label = form.label.trim()
  const slug = form.slug.trim()
  const orderText = String(form.sortOrder ?? '').trim()
  const order = Number(orderText)
  errors.label =
    label.length < EXPERTISE_LABEL_MIN_LENGTH
      ? t('admin.expertise.validation.labelRequired', { min: EXPERTISE_LABEL_MIN_LENGTH })
      : label.length > EXPERTISE_LABEL_MAX_LENGTH
        ? t('admin.expertise.validation.labelTooLong', { max: EXPERTISE_LABEL_MAX_LENGTH })
        : undefined
  errors.slug =
    slug && (slug.length > EXPERTISE_SLUG_MAX_LENGTH || !EXPERTISE_SLUG_PATTERN.test(slug))
      ? t('admin.expertise.validation.slugInvalid')
      : undefined
  errors.sortOrder =
    orderText === '' || !Number.isInteger(order) || order < 0 || order > EXPERTISE_SORT_ORDER_MAX
      ? t('admin.expertise.validation.sortOrderInvalid', { max: EXPERTISE_SORT_ORDER_MAX })
      : undefined
  return !Object.values(errors).some(Boolean)
}

/** The edit as a partial update: only the fields that changed (a blank slug keeps the old one). */
function changesFrom(tag: ExpertiseTag): ExpertiseTagUpdate {
  const changes: ExpertiseTagUpdate = {}
  const label = form.label.trim()
  const slug = form.slug.trim()
  const sortOrder = Number(form.sortOrder)
  if (label !== tag.label) changes.label = label
  if (slug && slug !== tag.slug) changes.slug = slug
  if (sortOrder !== tag.sort_order) changes.sort_order = sortOrder
  return changes
}

async function save() {
  if (saving.value || !validate()) return
  saving.value = true
  formError.value = ''
  try {
    const tag = editing.value
    let saved: ExpertiseTag
    if (tag) {
      const changes = changesFrom(tag)
      saved = Object.keys(changes).length ? await admin.updateExpertise(tag.id, changes) : tag
    } else {
      const payload: ExpertiseTagCreate = {
        label: form.label.trim(),
        slug: form.slug.trim() || null,
        sort_order: Number(form.sortOrder),
      }
      saved = await admin.createExpertise(payload)
    }
    formOpen.value = false
    toast.add({
      title: t(tag ? 'admin.expertise.updated' : 'admin.expertise.created', {
        name: saved.label,
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

// --- Deactivate / reactivate ------------------------------------------------------------------

const deactivating = ref<ExpertiseTag | null>(null)
const deactivateOpen = ref(false)
const deactivateLoading = ref(false)
const deactivateError = ref('')

function askDeactivate(tag: ExpertiseTag) {
  deactivating.value = tag
  deactivateError.value = ''
  deactivateOpen.value = true
}

async function confirmDeactivate() {
  const tag = deactivating.value
  if (!tag || deactivateLoading.value) return
  deactivateLoading.value = true
  deactivateError.value = ''
  try {
    await admin.updateExpertise(tag.id, { is_active: false })
    deactivateOpen.value = false
    toast.add({
      title: t('admin.expertise.deactivated', { name: tag.label }),
      color: 'neutral',
      icon: 'i-lucide-circle-pause',
    })
  } catch (error) {
    deactivateError.value = adminError(error)
  } finally {
    deactivateLoading.value = false
  }
}

async function reactivate(tag: ExpertiseTag) {
  try {
    await admin.updateExpertise(tag.id, { is_active: true })
    toast.add({
      title: t('admin.expertise.reactivated', { name: tag.label }),
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
    <AdminPageHeader :title="t('admin.expertise.title')" :intro="t('admin.expertise.intro')">
      <template #actions>
        <UButton icon="i-lucide-plus" class="shrink-0 self-start" @click="openForm(null)">
          {{ t('admin.expertise.create') }}
        </UButton>
      </template>
    </AdminPageHeader>

    <ListState
      :initial="admin.expertiseLoading && !admin.expertise.length"
      :loading="admin.expertiseLoading"
      :failed="admin.expertiseFailed"
      @retry="admin.fetchExpertise()"
    >
      <p
        v-if="!admin.expertise.length"
        class="rounded border border-default p-6 text-center text-muted"
      >
        {{ t('admin.expertise.empty') }}
      </p>
      <div v-else data-testid="expertise-table" class="overflow-x-auto">
        <UTable
          :data="admin.expertise"
          :columns="columns"
          :caption="t('admin.expertise.caption')"
          :ui="{ caption: 'sr-only', td: 'align-top' }"
        >
          <template #label-cell="{ row }">
            <span class="font-medium whitespace-normal text-highlighted">
              {{ row.original.label }}
            </span>
          </template>
          <template #slug-cell="{ row }">
            <span class="font-mono text-xs text-muted">{{ row.original.slug }}</span>
          </template>
          <template #order-cell="{ row }">
            <span class="tabular-nums">{{ row.original.sort_order }}</span>
          </template>
          <template #status-cell="{ row }">
            <UBadge
              :color="row.original.is_active ? 'success' : 'neutral'"
              variant="subtle"
              size="sm"
            >
              {{
                row.original.is_active ? t('admin.expertise.active') : t('admin.expertise.inactive')
              }}
            </UBadge>
          </template>
          <template #actions-cell="{ row }">
            <div class="flex gap-1">
              <UButton
                size="sm"
                color="neutral"
                variant="ghost"
                icon="i-lucide-pencil"
                :aria-label="t('admin.expertise.editLabel', { name: row.original.label })"
                @click="openForm(row.original)"
              />
              <UButton
                v-if="row.original.is_active"
                size="sm"
                color="error"
                variant="ghost"
                icon="i-lucide-circle-pause"
                :aria-label="t('admin.expertise.deactivateLabel', { name: row.original.label })"
                @click="askDeactivate(row.original)"
              />
              <UButton
                v-else
                size="sm"
                color="neutral"
                variant="ghost"
                icon="i-lucide-circle-play"
                :aria-label="t('admin.expertise.reactivateLabel', { name: row.original.label })"
                @click="reactivate(row.original)"
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
          ? t('admin.expertise.editTitle', { name: editing.label })
          : t('admin.expertise.createTitle')
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
          <UFormField
            :label="t('admin.expertise.label')"
            name="label"
            required
            :error="errors.label"
          >
            <UInput v-model="form.label" :maxlength="EXPERTISE_LABEL_MAX_LENGTH" class="w-full" />
          </UFormField>
          <UFormField
            :label="t('admin.expertise.slug')"
            name="slug"
            :help="t('admin.expertise.slugHelp')"
            :error="errors.slug"
          >
            <UInput
              v-model="form.slug"
              :maxlength="EXPERTISE_SLUG_MAX_LENGTH"
              class="w-full font-mono"
            />
          </UFormField>
          <UFormField
            :label="t('admin.expertise.sortOrder')"
            name="sort_order"
            required
            :error="errors.sortOrder"
          >
            <UInput
              v-model="form.sortOrder"
              type="number"
              inputmode="numeric"
              :min="0"
              :max="EXPERTISE_SORT_ORDER_MAX"
              class="w-32"
            />
          </UFormField>
        </form>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton color="neutral" variant="outline" :disabled="saving" @click="formOpen = false">
            {{ t('common.cancel') }}
          </UButton>
          <UButton type="submit" :form="formId" :loading="saving">
            {{ t('admin.expertise.save') }}
          </UButton>
        </div>
      </template>
    </UModal>

    <ConfirmDialog
      v-model:open="deactivateOpen"
      :title="t('admin.expertise.deactivateTitle', { name: deactivating?.label ?? '' })"
      :description="t('admin.expertise.deactivateDescription')"
      :confirm-label="t('admin.expertise.deactivate')"
      color="error"
      :loading="deactivateLoading"
      :error="deactivateError"
      @confirm="confirmDeactivate"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from '@nuxt/ui/composables'
import type { TableColumn } from '@nuxt/ui'

import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import ListState from '@/components/admin/ListState.vue'
import { useAdminErrors } from '@/composables/useAdminErrors'
import { OTHER_COUNTRY, useCountries } from '@/composables/useCountries'
import {
  ORGANISATION_NAME_MAX_LENGTH,
  ORGANISATION_NAME_MIN_LENGTH,
  ORGANISATION_SHORT_NAME_MAX_LENGTH,
  ORGANISATION_SORT_ORDER_MAX,
  ORGANISATION_TYPES,
  ORGANISATION_WEBSITE_MAX_LENGTH,
} from '@/constants/admin'
import type {
  Organisation,
  OrganisationCreate,
  OrganisationType,
  OrganisationUpdate,
} from '@/services/organisations'
import { useAdminStore } from '@/stores/admin'

/**
 * Organisations (partners and the rest): create and edit. There is no delete (members belong to
 * organisations). Validation mirrors the backend; server conflicts (`organisations.*`) show in the
 * dialog.
 */
const { t } = useI18n()
const toast = useToast()
const admin = useAdminStore()
const { adminError } = useAdminErrors()
const { countryName, countryItems: buildCountryItems } = useCountries()

onMounted(() => void admin.fetchOrganisations())

const typeItems = computed(() =>
  ORGANISATION_TYPES.map((type) => ({
    label: t(`admin.organisations.types.${type}`),
    value: type,
  })),
)

const columns = computed<TableColumn<Organisation>[]>(() => [
  { id: 'name', header: t('admin.organisations.name') },
  { id: 'shortName', header: t('admin.organisations.shortName') },
  { id: 'country', header: t('admin.organisations.country') },
  { id: 'type', header: t('admin.organisations.type') },
  { id: 'partner', header: t('admin.organisations.partner') },
  { id: 'members', header: t('admin.organisations.members') },
  { id: 'order', header: t('admin.organisations.sortOrder') },
  { id: 'actions', header: t('admin.common.actions') },
])

// --- Create / edit ----------------------------------------------------------------------------

const editing = ref<Organisation | null>(null)
const formOpen = ref(false)
const saving = ref(false)
const formError = ref('')
const formId = useId()
const form = reactive({
  name: '',
  shortName: '',
  country: undefined as string | undefined,
  type: 'other' as OrganisationType,
  website: '',
  isPartner: false,
  // Text (a number input); read with `String()` as the input may hand back a number.
  sortOrder: '0',
})
type Field = 'name' | 'shortName' | 'country' | 'website' | 'sortOrder'
const errors = reactive<Record<Field, string | undefined>>({
  name: undefined,
  shortName: undefined,
  country: undefined,
  website: undefined,
  sortOrder: undefined,
})

/** The partner countries plus the edited organisation's own; an organisation always has one. */
const countryItems = computed(() =>
  buildCountryItems(editing.value?.country).filter((item) => item.value !== OTHER_COUNTRY),
)

function openForm(organisation: Organisation | null) {
  editing.value = organisation
  Object.assign(form, {
    name: organisation?.name ?? '',
    shortName: organisation?.short_name ?? '',
    country: organisation?.country,
    type: organisation?.type ?? 'other',
    website: organisation?.website ?? '',
    isPartner: organisation?.is_partner ?? false,
    sortOrder: String(organisation?.sort_order ?? 0),
  })
  for (const key of Object.keys(errors) as Field[]) errors[key] = undefined
  formError.value = ''
  formOpen.value = true
}

/** An absolute http(s) URL with a host and no spaces, as the backend accepts. */
function isWebsite(value: string): boolean {
  if (/\s/.test(value) || value.length > ORGANISATION_WEBSITE_MAX_LENGTH) return false
  try {
    const url = new URL(value)
    return (url.protocol === 'http:' || url.protocol === 'https:') && url.hostname !== ''
  } catch {
    return false
  }
}

function validate(): boolean {
  const name = form.name.trim()
  const shortName = form.shortName.trim()
  const website = form.website.trim()
  const orderText = String(form.sortOrder ?? '').trim()
  const order = Number(orderText)
  errors.name =
    name.length < ORGANISATION_NAME_MIN_LENGTH
      ? t('admin.organisations.validation.nameRequired', { min: ORGANISATION_NAME_MIN_LENGTH })
      : name.length > ORGANISATION_NAME_MAX_LENGTH
        ? t('admin.organisations.validation.nameTooLong', { max: ORGANISATION_NAME_MAX_LENGTH })
        : undefined
  errors.shortName = !shortName
    ? t('admin.organisations.validation.shortNameRequired')
    : shortName.length > ORGANISATION_SHORT_NAME_MAX_LENGTH
      ? t('admin.organisations.validation.shortNameTooLong', {
          max: ORGANISATION_SHORT_NAME_MAX_LENGTH,
        })
      : undefined
  errors.country = form.country ? undefined : t('admin.organisations.validation.countryRequired')
  errors.website =
    website && !isWebsite(website) ? t('admin.organisations.validation.websiteInvalid') : undefined
  errors.sortOrder =
    orderText === '' || !Number.isInteger(order) || order < 0 || order > ORGANISATION_SORT_ORDER_MAX
      ? t('admin.organisations.validation.sortOrderInvalid', { max: ORGANISATION_SORT_ORDER_MAX })
      : undefined
  return !Object.values(errors).some(Boolean)
}

/** The edit as a partial update: only the fields that changed (an empty website clears it). */
function changesFrom(organisation: Organisation): OrganisationUpdate {
  const changes: OrganisationUpdate = {}
  const name = form.name.trim()
  const shortName = form.shortName.trim()
  const website = form.website.trim() || null
  const sortOrder = Number(form.sortOrder)
  if (name !== organisation.name) changes.name = name
  if (shortName !== organisation.short_name) changes.short_name = shortName
  if (form.country && form.country !== organisation.country) changes.country = form.country
  if (form.type !== organisation.type) changes.type = form.type
  if (website !== organisation.website) changes.website = website
  if (form.isPartner !== organisation.is_partner) changes.is_partner = form.isPartner
  if (sortOrder !== organisation.sort_order) changes.sort_order = sortOrder
  return changes
}

async function save() {
  if (saving.value || !validate()) return
  saving.value = true
  formError.value = ''
  try {
    const organisation = editing.value
    let saved: Organisation
    if (organisation) {
      const changes = changesFrom(organisation)
      saved = Object.keys(changes).length
        ? await admin.updateOrganisation(organisation.id, changes)
        : organisation
    } else {
      const payload: OrganisationCreate = {
        name: form.name.trim(),
        short_name: form.shortName.trim(),
        country: form.country!,
        type: form.type,
        website: form.website.trim() || null,
        is_partner: form.isPartner,
        sort_order: Number(form.sortOrder),
      }
      saved = await admin.createOrganisation(payload)
    }
    formOpen.value = false
    toast.add({
      title: t(organisation ? 'admin.organisations.updated' : 'admin.organisations.created', {
        name: saved.short_name,
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
</script>

<template>
  <div>
    <AdminPageHeader
      :title="t('admin.organisations.title')"
      :intro="t('admin.organisations.intro')"
    >
      <template #actions>
        <UButton icon="i-lucide-plus" class="shrink-0 self-start" @click="openForm(null)">
          {{ t('admin.organisations.create') }}
        </UButton>
      </template>
    </AdminPageHeader>

    <ListState
      :initial="admin.organisationsLoading && !admin.organisations.length"
      :loading="admin.organisationsLoading"
      :failed="admin.organisationsFailed"
      @retry="admin.fetchOrganisations()"
    >
      <p
        v-if="!admin.organisations.length"
        class="rounded border border-default p-6 text-center text-muted"
      >
        {{ t('admin.organisations.empty') }}
      </p>
      <div v-else data-testid="organisations-table" class="overflow-x-auto">
        <UTable
          :data="admin.organisations"
          :columns="columns"
          :caption="t('admin.organisations.caption')"
          :ui="{ caption: 'sr-only', td: 'align-top' }"
        >
          <template #name-cell="{ row }">
            <div class="max-w-sm min-w-48 space-y-0.5 whitespace-normal">
              <span class="font-medium text-highlighted">{{ row.original.name }}</span>
              <p v-if="row.original.website" class="truncate text-xs text-muted">
                {{ row.original.website }}
              </p>
            </div>
          </template>
          <template #shortName-cell="{ row }">
            {{ row.original.short_name }}
          </template>
          <template #country-cell="{ row }">
            {{ countryName(row.original.country) }}
          </template>
          <template #type-cell="{ row }">
            {{ t(`admin.organisations.types.${row.original.type}`) }}
          </template>
          <template #partner-cell="{ row }">
            {{ row.original.is_partner ? t('admin.common.yes') : t('admin.common.no') }}
          </template>
          <template #members-cell="{ row }">
            <span class="tabular-nums">{{ row.original.member_count }}</span>
          </template>
          <template #order-cell="{ row }">
            <span class="tabular-nums">{{ row.original.sort_order }}</span>
          </template>
          <template #actions-cell="{ row }">
            <UButton
              size="sm"
              color="neutral"
              variant="ghost"
              icon="i-lucide-pencil"
              :aria-label="t('admin.organisations.editLabel', { name: row.original.short_name })"
              @click="openForm(row.original)"
            />
          </template>
        </UTable>
      </div>
    </ListState>

    <UModal
      v-model:open="formOpen"
      :title="
        editing
          ? t('admin.organisations.editTitle', { name: editing.short_name })
          : t('admin.organisations.createTitle')
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
            :label="t('admin.organisations.name')"
            name="name"
            required
            :error="errors.name"
          >
            <UInput v-model="form.name" :maxlength="ORGANISATION_NAME_MAX_LENGTH" class="w-full" />
          </UFormField>
          <UFormField
            :label="t('admin.organisations.shortName')"
            name="short_name"
            required
            :error="errors.shortName"
          >
            <UInput
              v-model="form.shortName"
              :maxlength="ORGANISATION_SHORT_NAME_MAX_LENGTH"
              class="w-full"
            />
          </UFormField>
          <div class="grid gap-4 sm:grid-cols-2">
            <UFormField
              :label="t('admin.organisations.country')"
              name="country"
              required
              :error="errors.country"
            >
              <USelect
                v-model="form.country"
                :items="countryItems"
                :placeholder="t('admin.organisations.countryPlaceholder')"
                class="w-full"
              />
            </UFormField>
            <UFormField :label="t('admin.organisations.type')" name="type" required>
              <USelect v-model="form.type" :items="typeItems" class="w-full" />
            </UFormField>
          </div>
          <UFormField
            :label="t('admin.organisations.website')"
            name="website"
            :help="t('admin.organisations.websiteHelp')"
            :error="errors.website"
          >
            <UInput
              v-model="form.website"
              type="url"
              inputmode="url"
              :maxlength="ORGANISATION_WEBSITE_MAX_LENGTH"
              class="w-full"
            />
          </UFormField>
          <UFormField
            :label="t('admin.organisations.sortOrder')"
            name="sort_order"
            required
            :error="errors.sortOrder"
          >
            <UInput
              v-model="form.sortOrder"
              type="number"
              inputmode="numeric"
              :min="0"
              :max="ORGANISATION_SORT_ORDER_MAX"
              class="w-32"
            />
          </UFormField>
          <UCheckbox
            v-model="form.isPartner"
            name="is_partner"
            :label="t('admin.organisations.isPartner')"
            :description="t('admin.organisations.isPartnerHelp')"
          />
        </form>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton color="neutral" variant="outline" :disabled="saving" @click="formOpen = false">
            {{ t('common.cancel') }}
          </UButton>
          <UButton type="submit" :form="formId" :loading="saving">
            {{ t('admin.organisations.save') }}
          </UButton>
        </div>
      </template>
    </UModal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'

import type { OrganisationChoice } from '@/services/organisations'
import { useOrganisationsStore } from '@/stores/organisations'

/**
 * Organisation field of the register and profile forms: a listed organisation or "Other…" with a
 * free-text name. Emits `{organisation_id, organisation_other}` with at most one of them set
 * (`organisation_other: ''` while "Other…" is chosen but not yet typed). Renders two
 * `UFormField`s named `organisation_id` and `organisation_other`, so a parent `UForm` can attach
 * validation errors to them; server errors come in through the `*Error` props.
 */
defineProps<{ organisationError?: string; otherError?: string }>()

const model = defineModel<OrganisationChoice>({ required: true })

/** Sentinel select value for "Other…". */
const OTHER = 'other'

const { t } = useI18n()
const store = useOrganisationsStore()
const { all } = storeToRefs(store)

onMounted(async () => {
  try {
    await store.fetchAll()
  } catch {
    // The picker still offers "Other…"; the field is optional.
  }
})

const items = computed(() => [
  ...all.value.map((o) => ({ label: o.name, value: o.id })),
  { label: t('auth.fields.organisationOtherOption'), value: OTHER },
])

const selected = computed<number | typeof OTHER | undefined>({
  get: () =>
    model.value.organisation_other !== null ? OTHER : (model.value.organisation_id ?? undefined),
  set: (value) => {
    if (value === OTHER) {
      model.value = {
        organisation_id: null,
        organisation_other: model.value.organisation_other ?? '',
      }
    } else {
      model.value = {
        organisation_id: typeof value === 'number' ? value : null,
        organisation_other: null,
      }
    }
  },
})

const other = computed({
  get: () => model.value.organisation_other ?? '',
  set: (value: string) => {
    model.value = { organisation_id: null, organisation_other: value }
  },
})
</script>

<template>
  <div class="space-y-5">
    <UFormField
      :label="t('auth.fields.organisation')"
      name="organisation_id"
      :error="organisationError"
    >
      <USelectMenu
        v-model="selected"
        :items="items"
        value-key="value"
        :placeholder="t('auth.fields.organisationPlaceholder')"
        class="w-full"
      />
    </UFormField>

    <UFormField
      v-if="selected === OTHER"
      :label="t('auth.fields.organisationOther')"
      name="organisation_other"
      required
      :error="otherError"
    >
      <UInput
        v-model="other"
        name="organisation_other"
        autocomplete="organization"
        maxlength="200"
        class="w-full"
      />
    </UFormField>
  </div>
</template>

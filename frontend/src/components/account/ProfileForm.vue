<script setup lang="ts">
import { computed, nextTick, reactive, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from '@nuxt/ui/composables'
import type { FormError, FormSubmitEvent } from '@nuxt/ui'

import ExpertisePicker from '@/components/common/ExpertisePicker.vue'
import OrganisationPicker from '@/components/common/OrganisationPicker.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import { OTHER_COUNTRY, useCountries } from '@/composables/useCountries'
import { EXPERTISE_MAX } from '@/constants/auth'
import { SUPPORTED_LOCALES, isSupportedLocale, type LocaleCode } from '@/i18n'
import type { UpdateMePayload, UserMe } from '@/services/auth'
import type { OrganisationChoice } from '@/services/organisations'
import { useAuthStore } from '@/stores/auth'

/** Mirrors the backend `Bio` constraint. */
const BIO_MAX_LENGTH = 2000

const { t } = useI18n()
const toast = useToast()
const auth = useAuthStore()
const { errorMessage, fieldMessage, fieldErrors } = useApiErrors()
const { countryItems: buildCountryItems } = useCountries()

const sortedIds = (ids: number[]) => [...ids].sort((a, b) => a - b)

function stateFrom(user: UserMe) {
  return {
    display_name: user.display_name,
    organisation: {
      organisation_id: user.organisation?.id ?? null,
      organisation_other: user.organisation_other,
    } as OrganisationChoice,
    country: (user.country ?? undefined) as string | undefined,
    locale: (isSupportedLocale(user.locale) ? user.locale : 'en') as LocaleCode,
    bio: user.bio ?? '',
    expertise_ids: user.expertise.map((tag) => tag.id),
    show_email: user.show_email,
    show_in_directory: user.show_in_directory,
  }
}
type State = ReturnType<typeof stateFrom>

// The route requires a session, so the user is known when this form mounts.
const state = reactive(stateFrom(auth.user!))
const pending = ref(false)
const formError = ref('')
const status = ref('')
/** Server-side errors per backend field name; cleared as soon as the user edits that field. */
const serverErrors = reactive<Record<string, string>>({})
const form = useTemplateRef<{ clear: () => void }>('form')

const countryItems = computed(() => buildCountryItems(auth.user?.country))
const localeItems = SUPPORTED_LOCALES.map((l) => ({ label: l.nativeName, value: l.code }))

watch(
  () => ({ ...state }),
  (next, prev) => {
    status.value = ''
    for (const key of Object.keys(next) as (keyof State)[]) {
      if (next[key] === prev[key]) continue
      if (key === 'organisation') {
        delete serverErrors.organisation_id
        delete serverErrors.organisation_other
      } else delete serverErrors[key]
    }
  },
)

function validate(s: Partial<State>): FormError[] {
  const errors: FormError[] = []
  if (!s.display_name?.trim())
    errors.push({ name: 'display_name', message: fieldMessage('required') })
  const other = s.organisation?.organisation_other
  if (other !== null && other !== undefined && !other.trim())
    errors.push({ name: 'organisation_other', message: fieldMessage('required') })
  if ((s.expertise_ids?.length ?? 0) > EXPERTISE_MAX)
    errors.push({
      name: 'expertise_ids',
      message: t('account.profile.expertiseMax', { max: EXPERTISE_MAX }),
    })
  return errors
}

/** Only what differs from the saved profile; the organisation pair travels together. */
function changedFields(data: State, user: UserMe): UpdateMePayload {
  const changes: UpdateMePayload = {}
  const displayName = data.display_name.trim()
  if (displayName !== user.display_name) changes.display_name = displayName

  const organisationId = data.organisation.organisation_id
  const organisationOther = data.organisation.organisation_other?.trim() || null
  if (
    organisationId !== (user.organisation?.id ?? null) ||
    organisationOther !== user.organisation_other
  ) {
    changes.organisation_id = organisationId
    changes.organisation_other = organisationOther
  }

  const country = data.country && data.country !== OTHER_COUNTRY ? data.country : null
  if (country !== user.country) changes.country = country
  if (data.locale !== user.locale) changes.locale = data.locale
  const bio = data.bio.trim() || null
  if (bio !== user.bio) changes.bio = bio

  const expertiseIds = sortedIds(data.expertise_ids)
  const currentIds = sortedIds(user.expertise.map((tag) => tag.id))
  if (expertiseIds.join() !== currentIds.join()) changes.expertise_ids = expertiseIds
  if (data.show_email !== user.show_email) changes.show_email = data.show_email
  if (data.show_in_directory !== user.show_in_directory)
    changes.show_in_directory = data.show_in_directory
  return changes
}

async function onSubmit(event: FormSubmitEvent<State>) {
  formError.value = ''
  status.value = ''
  const changes = changedFields(event.data, auth.user!)
  if (!Object.keys(changes).length) {
    status.value = t('account.profile.noChanges')
    return
  }

  pending.value = true
  try {
    const user = await auth.updateProfile(changes)
    Object.assign(state, stateFrom(user))
    form.value?.clear()
    // Let the state watcher (which clears the status) run before the status is set.
    await nextTick()
  } catch (e) {
    const fields = fieldErrors(e)
    for (const [field, message] of Object.entries(fields)) serverErrors[field] = message
    formError.value = Object.keys(fields).length
      ? t('errors.api.validation.failed')
      : errorMessage(e)
    return
  } finally {
    pending.value = false
  }
  status.value = t('account.profile.saved')
  toast.add({ title: status.value, color: 'success', icon: 'i-lucide-circle-check' })
}
</script>

<template>
  <UForm
    ref="form"
    :state="state"
    :validate="validate"
    novalidate
    class="space-y-5"
    @submit="onSubmit"
  >
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
      :label="t('auth.fields.displayName')"
      name="display_name"
      required
      :help="t('auth.fields.displayNameHint')"
      :error="serverErrors.display_name"
    >
      <UInput v-model="state.display_name" autocomplete="nickname" maxlength="120" class="w-full" />
    </UFormField>

    <OrganisationPicker
      v-model="state.organisation"
      :organisation-error="serverErrors.organisation_id"
      :other-error="serverErrors.organisation_other"
    />

    <div class="grid gap-5 sm:grid-cols-2">
      <UFormField :label="t('auth.fields.country')" name="country" :error="serverErrors.country">
        <USelect
          v-model="state.country"
          :items="countryItems"
          :placeholder="t('auth.fields.countryPlaceholder')"
          class="w-full"
        />
      </UFormField>

      <UFormField
        :label="t('auth.fields.locale')"
        name="locale"
        :help="t('auth.fields.localeHint')"
        :error="serverErrors.locale"
      >
        <USelect v-model="state.locale" :items="localeItems" class="w-full" />
      </UFormField>
    </div>

    <UFormField
      :label="t('account.profile.bio')"
      name="bio"
      :help="t('account.profile.bioHint')"
      :error="serverErrors.bio"
    >
      <template #hint>
        <span class="text-xs tabular-nums">
          {{ t('account.profile.bioCount', { count: state.bio.length, max: BIO_MAX_LENGTH }) }}
        </span>
      </template>
      <UTextarea
        v-model="state.bio"
        :maxlength="BIO_MAX_LENGTH"
        :rows="4"
        autoresize
        :maxrows="12"
        class="w-full"
      />
    </UFormField>

    <ExpertisePicker
      v-model="state.expertise_ids"
      :label="t('account.profile.expertise')"
      :help="t('account.profile.expertiseHint', { max: EXPERTISE_MAX })"
      :placeholder="t('account.profile.expertisePlaceholder')"
      :error="serverErrors.expertise_ids"
      :known="auth.user?.expertise"
    />

    <fieldset class="space-y-4 rounded border border-default p-4">
      <legend class="px-1 text-sm font-semibold text-highlighted">
        {{ t('account.profile.networkTitle') }}
      </legend>
      <USwitch
        v-model="state.show_in_directory"
        name="show_in_directory"
        :label="t('account.profile.showInDirectory')"
        :description="t('account.profile.showInDirectoryHint')"
      />
      <USwitch
        v-model="state.show_email"
        name="show_email"
        :label="t('account.profile.showEmail')"
        :description="t('account.profile.showEmailHint')"
      />
    </fieldset>

    <div class="flex flex-wrap items-center gap-4">
      <UButton type="submit" :loading="pending" icon="i-lucide-save">
        {{ t('account.profile.submit') }}
      </UButton>
      <p aria-live="polite" class="text-sm text-success">{{ status }}</p>
    </div>
  </UForm>
</template>

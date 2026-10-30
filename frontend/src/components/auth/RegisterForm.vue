<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { FormError, FormSubmitEvent } from '@nuxt/ui'

import PasswordField from './PasswordField.vue'
import TurnstileWidget from './TurnstileWidget.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, PROJECT_COUNTRIES } from '@/constants/auth'
import { SUPPORTED_LOCALES, isSupportedLocale, type LocaleCode } from '@/i18n'
import { ApiError } from '@/services/api'
import type { RegisterPayload } from '@/services/auth'
import { listOrganisations, type Organisation } from '@/services/organisations'
import { useAuthStore } from '@/stores/auth'

const emit = defineEmits<{ registered: [email: string] }>()

/** Sentinel option value: "my organisation / country is not in the list". */
const OTHER = 'other'

const { t, locale } = useI18n()
const auth = useAuthStore()
const { errorMessage, fieldMessage, fieldErrors } = useApiErrors()

const state = reactive({
  email: '',
  password: '',
  display_name: '',
  organisation: undefined as number | typeof OTHER | undefined,
  organisation_other: '',
  country: undefined as string | undefined,
  locale: (isSupportedLocale(locale.value) ? locale.value : 'en') as LocaleCode,
  accept_terms: false,
})
type State = typeof state

const turnstileToken = ref<string | null>(null)
const pending = ref(false)
const formError = ref('')
/** Server-side errors per form field; cleared as soon as the user edits that field. */
const serverErrors = reactive<Partial<Record<keyof State, string>>>({})

const organisations = ref<Organisation[]>([])
onMounted(async () => {
  try {
    organisations.value = (await listOrganisations()).items
  } catch {
    // The picker still offers "Other…"; the field is optional.
  }
})

const organisationItems = computed(() => [
  ...organisations.value.map((o) => ({ label: `${o.short_name} – ${o.name}`, value: o.id })),
  { label: t('auth.fields.organisationOtherOption'), value: OTHER },
])

const countryItems = computed(() => {
  let names: Intl.DisplayNames | null = null
  try {
    names = new Intl.DisplayNames([locale.value, 'en'], { type: 'region' })
  } catch {
    // Very old browsers: show the ISO codes.
  }
  const countries = PROJECT_COUNTRIES.map((code) => ({
    label: names?.of(code) ?? code,
    value: code,
  }))
  countries.sort((a, b) => a.label.localeCompare(b.label, locale.value))
  return [...countries, { label: t('auth.fields.countryOther'), value: OTHER }]
})

const localeItems = SUPPORTED_LOCALES.map((l) => ({ label: l.nativeName, value: l.code }))

const showOrganisationOther = computed(() => state.organisation === OTHER)

watch(
  () => ({ ...state }),
  (next, prev) => {
    for (const key of Object.keys(next) as (keyof State)[]) {
      if (next[key] !== prev[key]) delete serverErrors[key]
    }
  },
)

function validate(s: Partial<State>): FormError[] {
  const errors: FormError[] = []
  const required = (name: keyof State) => errors.push({ name, message: fieldMessage('required') })

  if (!s.email?.trim()) required('email')
  if (!s.password) required('password')
  else if (s.password.length < PASSWORD_MIN_LENGTH || !s.password.trim())
    errors.push({ name: 'password', message: fieldMessage('auth.password_too_short') })
  else if (s.password.length > PASSWORD_MAX_LENGTH)
    errors.push({ name: 'password', message: fieldMessage('auth.password_too_long') })
  if (!s.display_name?.trim()) required('display_name')
  if (s.organisation === OTHER && !s.organisation_other?.trim()) required('organisation_other')
  if (s.accept_terms !== true)
    errors.push({ name: 'accept_terms', message: fieldMessage('must_accept') })
  return errors
}

/** Backend field names → form field names. */
const FIELD_ALIASES: Record<string, keyof State> = { organisation_id: 'organisation' }

async function onSubmit(event: FormSubmitEvent<State>) {
  const data = event.data
  const payload: RegisterPayload = {
    email: data.email.trim(),
    password: data.password,
    display_name: data.display_name.trim(),
    organisation_id: typeof data.organisation === 'number' ? data.organisation : null,
    organisation_other: data.organisation === OTHER ? data.organisation_other.trim() : null,
    country: data.country && data.country !== OTHER ? data.country : null,
    locale: data.locale,
    accept_terms: true,
    turnstile_token: turnstileToken.value,
  }

  formError.value = ''
  pending.value = true
  try {
    await auth.register(payload)
    emit('registered', payload.email)
  } catch (e) {
    const fields = fieldErrors(e)
    if (e instanceof ApiError && e.code === 'auth.email_taken') fields.email = errorMessage(e)
    for (const [field, message] of Object.entries(fields)) {
      serverErrors[FIELD_ALIASES[field] ?? (field as keyof State)] = message
    }
    formError.value = Object.keys(fields).length
      ? t('errors.api.validation.failed')
      : errorMessage(e)
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <UForm :state="state" :validate="validate" novalidate class="space-y-5" @submit="onSubmit">
    <div role="alert">
      <UAlert
        v-if="formError"
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :title="formError"
      />
    </div>

    <UFormField :label="t('auth.fields.email')" name="email" required :error="serverErrors.email">
      <UInput
        v-model="state.email"
        type="email"
        autocomplete="email"
        autocapitalize="off"
        class="w-full"
      />
    </UFormField>

    <UFormField
      :label="t('auth.fields.password')"
      name="password"
      required
      :help="t('auth.fields.passwordHint', { min: PASSWORD_MIN_LENGTH })"
      :error="serverErrors.password"
    >
      <PasswordField v-model="state.password" autocomplete="new-password" />
    </UFormField>

    <UFormField
      :label="t('auth.fields.displayName')"
      name="display_name"
      required
      :help="t('auth.fields.displayNameHint')"
      :error="serverErrors.display_name"
    >
      <UInput v-model="state.display_name" autocomplete="nickname" maxlength="120" class="w-full" />
    </UFormField>

    <UFormField
      :label="t('auth.fields.organisation')"
      name="organisation"
      :error="serverErrors.organisation"
    >
      <USelectMenu
        v-model="state.organisation"
        :items="organisationItems"
        value-key="value"
        :placeholder="t('auth.fields.organisationPlaceholder')"
        class="w-full"
      />
    </UFormField>

    <UFormField
      v-if="showOrganisationOther"
      :label="t('auth.fields.organisationOther')"
      name="organisation_other"
      required
      :error="serverErrors.organisation_other"
    >
      <UInput
        v-model="state.organisation_other"
        name="organisation_other"
        autocomplete="organization"
        maxlength="200"
        class="w-full"
      />
    </UFormField>

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

    <UFormField name="accept_terms" :error="serverErrors.accept_terms">
      <UCheckbox v-model="state.accept_terms" required>
        <template #label>
          <i18n-t keypath="auth.fields.acceptTerms" tag="span" scope="global">
            <template #terms>
              <ULink to="/terms" class="underline">{{ t('auth.fields.terms') }}</ULink>
            </template>
            <template #privacy>
              <ULink to="/privacy" class="underline">{{ t('auth.fields.privacy') }}</ULink>
            </template>
          </i18n-t>
        </template>
      </UCheckbox>
    </UFormField>

    <TurnstileWidget v-model:token="turnstileToken" />

    <UButton type="submit" block :loading="pending" icon="i-lucide-user-plus">
      {{ t('auth.registerPage.submit') }}
    </UButton>
  </UForm>
</template>

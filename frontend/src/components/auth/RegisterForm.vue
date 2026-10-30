<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { FormError, FormSubmitEvent } from '@nuxt/ui'

import PasswordField from './PasswordField.vue'
import TurnstileWidget from './TurnstileWidget.vue'
import OrganisationPicker from '@/components/common/OrganisationPicker.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import { OTHER_COUNTRY, useCountries } from '@/composables/useCountries'
import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from '@/constants/auth'
import { SUPPORTED_LOCALES, isSupportedLocale, type LocaleCode } from '@/i18n'
import { ApiError } from '@/services/api'
import type { RegisterPayload } from '@/services/auth'
import type { OrganisationChoice } from '@/services/organisations'
import { useAuthStore } from '@/stores/auth'

const emit = defineEmits<{ registered: [email: string] }>()

const { t, locale } = useI18n()
const auth = useAuthStore()
const { errorMessage, fieldMessage, fieldErrors } = useApiErrors()
const { countryItems: buildCountryItems } = useCountries()

const state = reactive({
  email: '',
  password: '',
  display_name: '',
  organisation: { organisation_id: null, organisation_other: null } as OrganisationChoice,
  country: undefined as string | undefined,
  locale: (isSupportedLocale(locale.value) ? locale.value : 'en') as LocaleCode,
  accept_terms: false,
})
type State = typeof state

const turnstileToken = ref<string | null>(null)
const pending = ref(false)
const formError = ref('')
/**
 * Server-side errors per backend field name (the organisation picker's fields are
 * `organisation_id` / `organisation_other`); cleared as soon as the user edits that field.
 */
const serverErrors = reactive<Record<string, string>>({})

const countryItems = computed(() => buildCountryItems())

const localeItems = SUPPORTED_LOCALES.map((l) => ({ label: l.nativeName, value: l.code }))

watch(
  () => ({ ...state }),
  (next, prev) => {
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
  const required = (name: keyof State) => errors.push({ name, message: fieldMessage('required') })

  if (!s.email?.trim()) required('email')
  if (!s.password) required('password')
  else if (s.password.length < PASSWORD_MIN_LENGTH || !s.password.trim())
    errors.push({ name: 'password', message: fieldMessage('auth.password_too_short') })
  else if (s.password.length > PASSWORD_MAX_LENGTH)
    errors.push({ name: 'password', message: fieldMessage('auth.password_too_long') })
  if (!s.display_name?.trim()) required('display_name')
  if (
    s.organisation &&
    s.organisation.organisation_other !== null &&
    !s.organisation.organisation_other.trim()
  )
    errors.push({ name: 'organisation_other', message: fieldMessage('required') })
  if (s.accept_terms !== true)
    errors.push({ name: 'accept_terms', message: fieldMessage('must_accept') })
  return errors
}

async function onSubmit(event: FormSubmitEvent<State>) {
  const data = event.data
  const payload: RegisterPayload = {
    email: data.email.trim(),
    password: data.password,
    display_name: data.display_name.trim(),
    organisation_id: data.organisation.organisation_id,
    organisation_other: data.organisation.organisation_other?.trim() || null,
    country: data.country && data.country !== OTHER_COUNTRY ? data.country : null,
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
      serverErrors[field] = message
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

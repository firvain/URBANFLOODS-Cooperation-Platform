<script setup lang="ts">
import { ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useToast } from '@nuxt/ui/composables'

import PasswordField from '@/components/auth/PasswordField.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import { ApiError } from '@/services/api'
import { authService } from '@/services/auth'
import { useAuthStore } from '@/stores/auth'
import { saveFile } from '@/utils/download'

/**
 * The member's data (GDPR): download everything stored about them as a JSON file, or delete
 * the account after confirming with the current password in a modal.
 */
const { t } = useI18n()
const router = useRouter()
const toast = useToast()
const auth = useAuthStore()
const { errorMessage, fieldMessage } = useApiErrors()

// --- Export -----------------------------------------------------------------------------------

const exporting = ref(false)
const exportError = ref('')

async function download() {
  exporting.value = true
  exportError.value = ''
  try {
    const { blob, filename } = await authService.exportData()
    saveFile(blob, filename)
  } catch {
    exportError.value = t('account.data.export.failed')
  } finally {
    exporting.value = false
  }
}

// --- Delete -----------------------------------------------------------------------------------

const deleteOpen = ref(false)
const deleting = ref(false)
const password = ref('')
const passwordError = ref<string>()
const deleteError = ref('')
const formId = useId()

watch(password, () => (passwordError.value = undefined))

function askDelete() {
  password.value = ''
  passwordError.value = undefined
  deleteError.value = ''
  deleteOpen.value = true
}

async function confirmDelete() {
  if (deleting.value) return
  deleteError.value = ''
  if (!password.value) {
    passwordError.value = fieldMessage('required')
    return
  }
  deleting.value = true
  try {
    await auth.deleteAccount(password.value)
  } catch (e) {
    if (e instanceof ApiError && e.code === 'auth.invalid_credentials')
      passwordError.value = t('account.data.delete.wrongPassword')
    else if (e instanceof ApiError && e.code === 'admin.last_superadmin')
      deleteError.value = t('account.data.delete.lastSuperadmin')
    else deleteError.value = errorMessage(e)
    return
  } finally {
    deleting.value = false
  }
  deleteOpen.value = false
  toast.add({ title: t('account.data.delete.done'), color: 'success', icon: 'i-lucide-check' })
  await router.push('/')
}
</script>

<template>
  <div class="space-y-8">
    <p class="text-sm text-muted">{{ t('account.data.intro') }}</p>

    <section aria-labelledby="data-export-heading" class="space-y-3">
      <h2 id="data-export-heading" class="text-lg font-semibold text-highlighted">
        {{ t('account.data.export.title') }}
      </h2>
      <p class="text-sm text-muted">{{ t('account.data.export.description') }}</p>
      <div role="alert">
        <UAlert
          v-if="exportError"
          data-testid="export-error"
          color="error"
          variant="subtle"
          icon="i-lucide-circle-alert"
          :title="exportError"
        />
      </div>
      <UButton
        color="neutral"
        variant="outline"
        icon="i-lucide-download"
        :loading="exporting"
        @click="download"
      >
        {{ t('account.data.export.button') }}
      </UButton>
    </section>

    <section
      aria-labelledby="data-delete-heading"
      class="space-y-3 rounded border border-error/40 p-4"
    >
      <h2 id="data-delete-heading" class="text-lg font-semibold text-error">
        {{ t('account.data.delete.title') }}
      </h2>
      <p class="text-sm text-muted">{{ t('account.data.delete.description') }}</p>
      <UButton color="error" variant="outline" icon="i-lucide-user-x" @click="askDelete">
        {{ t('account.data.delete.button') }}
      </UButton>
    </section>

    <UModal
      v-model:open="deleteOpen"
      :title="t('account.data.delete.dialogTitle')"
      :description="t('account.data.delete.dialogDescription')"
      :dismissible="!deleting"
    >
      <template #body>
        <form :id="formId" novalidate class="space-y-4" @submit.prevent="confirmDelete">
          <div role="alert">
            <UAlert
              v-if="deleteError"
              color="error"
              variant="subtle"
              icon="i-lucide-circle-alert"
              :title="deleteError"
            />
          </div>
          <UFormField
            :label="t('account.data.delete.password')"
            name="current_password"
            required
            :error="passwordError"
          >
            <PasswordField v-model="password" autocomplete="current-password" />
          </UFormField>
        </form>
      </template>
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton
            color="neutral"
            variant="outline"
            :disabled="deleting"
            @click="deleteOpen = false"
          >
            {{ t('account.data.delete.cancel') }}
          </UButton>
          <UButton type="submit" :form="formId" color="error" :loading="deleting">
            {{ t('account.data.delete.confirm') }}
          </UButton>
        </div>
      </template>
    </UModal>
  </div>
</template>

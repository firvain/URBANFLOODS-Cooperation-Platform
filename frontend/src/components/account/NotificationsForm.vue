<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from '@nuxt/ui/composables'
import type { RadioGroupItem } from '@nuxt/ui'

import { useApiErrors } from '@/composables/useApiErrors'
import { authService, type NotificationPreferences } from '@/services/auth'
import { useAuthStore } from '@/stores/auth'

/**
 * Email notification preferences: four switches for activity on the member's own content
 * (replies, comments, and an admin's decision on their posts and discussions) and, for admins
 * only, the moderation digest and its frequency. Saving sends the whole object (the API replaces
 * it), so a member's hidden admin fields go back unchanged.
 */
const { t } = useI18n()
const toast = useToast()
const auth = useAuthStore()
const { errorMessage } = useApiErrors()

const CONTENT_FIELDS = [
  { key: 'reply_to_my_thread', label: 'replyToMyThread' },
  { key: 'comment_on_my_post', label: 'commentOnMyPost' },
  { key: 'reply_to_my_reply', label: 'replyToMyReply' },
  { key: 'moderation_decisions', label: 'moderationDecisions' },
] as const

const state = ref<NotificationPreferences | null>(null)
const loading = ref(true)
const loadFailed = ref(false)
const pending = ref(false)
const formError = ref('')
const status = ref('')

const frequencies = computed<RadioGroupItem[]>(() => [
  { label: t('account.notifications.daily'), value: 'daily' },
  { label: t('account.notifications.weekly'), value: 'weekly' },
])

async function load() {
  loading.value = true
  loadFailed.value = false
  try {
    state.value = await authService.getNotifications()
  } catch {
    loadFailed.value = true
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function save() {
  if (!state.value || pending.value) return
  formError.value = ''
  status.value = ''
  pending.value = true
  try {
    state.value = await authService.updateNotifications({ ...state.value })
  } catch (e) {
    formError.value = errorMessage(e)
    return
  } finally {
    pending.value = false
  }
  status.value = t('account.notifications.saved')
  toast.add({ title: status.value, color: 'success', icon: 'i-lucide-circle-check' })
}
</script>

<template>
  <div class="space-y-5">
    <p class="text-sm text-muted">{{ t('account.notifications.intro') }}</p>

    <div v-if="loading" aria-busy="true" class="space-y-3">
      <span class="sr-only">{{ t('account.notifications.loading') }}</span>
      <!-- One placeholder per switch every member sees. -->
      <USkeleton v-for="field in CONTENT_FIELDS" :key="field.key" class="h-12 w-full" />
    </div>

    <div v-else-if="loadFailed || !state" role="alert">
      <UAlert
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :title="t('account.notifications.loadError')"
        :actions="[
          {
            label: t('account.notifications.retry'),
            color: 'error',
            variant: 'outline',
            icon: 'i-lucide-rotate-cw',
            onClick: load,
          },
        ]"
      />
    </div>

    <form
      v-else
      data-testid="notifications-form"
      novalidate
      class="space-y-5"
      @submit.prevent="save"
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

      <fieldset class="space-y-4 rounded border border-default p-4">
        <legend class="px-1 text-sm font-semibold text-highlighted">
          {{ t('account.notifications.contentTitle') }}
        </legend>
        <USwitch
          v-for="field in CONTENT_FIELDS"
          :key="field.key"
          v-model="state[field.key]"
          :name="field.key"
          :label="t(`account.notifications.${field.label}`)"
          :description="t(`account.notifications.${field.label}Hint`)"
        />
      </fieldset>

      <fieldset v-if="auth.isAdmin" class="space-y-4 rounded border border-default p-4">
        <legend class="px-1 text-sm font-semibold text-highlighted">
          {{ t('account.notifications.adminTitle') }}
        </legend>
        <USwitch
          v-model="state.admin_digest"
          name="admin_digest"
          :label="t('account.notifications.adminDigest')"
          :description="t('account.notifications.adminDigestHint')"
        />
        <URadioGroup
          v-model="state.digest_frequency"
          name="digest_frequency"
          :legend="t('account.notifications.frequency')"
          :items="frequencies"
          orientation="horizontal"
        />
      </fieldset>

      <div class="flex flex-wrap items-center gap-4">
        <UButton type="submit" :loading="pending" icon="i-lucide-save">
          {{ t('account.notifications.submit') }}
        </UButton>
        <p aria-live="polite" class="text-sm text-success">{{ status }}</p>
      </div>
    </form>
  </div>
</template>

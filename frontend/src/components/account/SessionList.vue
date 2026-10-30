<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from '@nuxt/ui/composables'

import { useApiErrors } from '@/composables/useApiErrors'
import { authService, type SessionInfo } from '@/services/auth'
import { describeUserAgent } from '@/utils/userAgent'

const { t, locale } = useI18n()
const toast = useToast()
const { errorMessage } = useApiErrors()

const sessions = ref<SessionInfo[]>([])
const loading = ref(true)
const loadFailed = ref(false)
const actionError = ref('')
const status = ref('')
/** Id of the session being signed out. */
const revoking = ref<string | null>(null)

async function load() {
  loading.value = true
  loadFailed.value = false
  try {
    sessions.value = (await authService.listSessions()).items
  } catch {
    loadFailed.value = true
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function revoke(session: SessionInfo) {
  actionError.value = ''
  status.value = ''
  revoking.value = session.id
  try {
    await authService.revokeSession(session.id)
  } catch (e) {
    actionError.value = errorMessage(e)
    return
  } finally {
    revoking.value = null
  }
  sessions.value = sessions.value.filter((s) => s.id !== session.id)
  status.value = t('account.sessions.signedOut')
  toast.add({ title: status.value, color: 'success', icon: 'i-lucide-log-out' })
}

function device(session: SessionInfo): string {
  const { browser, os } = describeUserAgent(session.user_agent)
  if (browser && os) return t('account.sessions.device', { browser, os })
  return browser ?? os ?? t('account.sessions.unknownDevice')
}

function formatDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat([locale.value, 'en'], {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(iso))
  } catch {
    return iso
  }
}
</script>

<template>
  <div class="space-y-5">
    <p class="text-sm text-muted">{{ t('account.sessions.intro') }}</p>

    <div v-if="loading" aria-busy="true" class="space-y-3">
      <span class="sr-only">{{ t('account.sessions.loading') }}</span>
      <USkeleton v-for="n in 3" :key="n" class="h-20 w-full" />
    </div>

    <div v-else-if="loadFailed" role="alert">
      <UAlert
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :title="t('account.sessions.loadError')"
        :actions="[
          {
            label: t('account.sessions.retry'),
            color: 'error',
            variant: 'outline',
            icon: 'i-lucide-rotate-cw',
            onClick: load,
          },
        ]"
      />
    </div>

    <template v-else>
      <div role="alert">
        <UAlert
          v-if="actionError"
          color="error"
          variant="subtle"
          icon="i-lucide-circle-alert"
          :title="actionError"
        />
      </div>

      <p v-if="!sessions.length" class="text-sm text-muted">{{ t('account.sessions.empty') }}</p>
      <ul v-else class="divide-y divide-default rounded-md border border-default">
        <li
          v-for="session in sessions"
          :key="session.id"
          data-testid="session-row"
          :aria-current="session.is_current ? 'true' : undefined"
          class="flex flex-wrap items-center justify-between gap-3 p-4"
        >
          <div class="min-w-0 space-y-1">
            <p class="flex flex-wrap items-center gap-2 font-medium text-highlighted">
              <UIcon
                name="i-lucide-monitor-smartphone"
                class="size-4 shrink-0"
                aria-hidden="true"
              />
              <span :id="`session-${session.id}`">{{ device(session) }}</span>
              <UBadge v-if="session.is_current" color="primary" variant="subtle" size="sm">
                {{ t('account.sessions.current') }}
              </UBadge>
            </p>
            <p class="text-xs text-muted">
              {{ t('account.sessions.signedIn', { date: formatDate(session.created_at) }) }}
              ·
              {{ t('account.sessions.lastSeen', { date: formatDate(session.last_seen_at) }) }}
            </p>
            <p class="text-xs text-muted">
              {{ t('account.sessions.expires', { date: formatDate(session.expires_at) }) }}
            </p>
          </div>
          <UButton
            v-if="!session.is_current"
            color="neutral"
            variant="outline"
            size="sm"
            icon="i-lucide-log-out"
            :loading="revoking === session.id"
            :aria-describedby="`session-${session.id}`"
            @click="revoke(session)"
          >
            {{ t('account.sessions.signOut') }}
          </UButton>
        </li>
      </ul>
    </template>

    <p aria-live="polite" class="text-sm text-success">{{ status }}</p>
  </div>
</template>

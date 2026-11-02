<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useToast } from '@nuxt/ui/composables'
import type { DropdownMenuItem } from '@nuxt/ui'

import ReasonDialog from '@/components/admin/ReasonDialog.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import PurgeDialog from '@/components/moderation/PurgeDialog.vue'
import { useAdminErrors } from '@/composables/useAdminErrors'
import {
  moderationService,
  type ContentStatus,
  type ModerationAction,
  type ModerationResult,
} from '@/services/moderation'
import { useAuthStore } from '@/stores/auth'

/**
 * "Moderate" menu for admins on a post or thread page: the state-machine actions valid for the
 * current status (approve, hide with an optional reason, unhide, delete, restore) and "Delete
 * permanently". State changes are reported with `changed` so the page updates in place; a
 * permanent delete goes to the blog or forum list. Renders nothing for anyone but admins.
 */
const props = defineProps<{
  contentType: 'post' | 'thread'
  contentId: number
  status: ContentStatus
}>()
const emit = defineEmits<{ changed: [result: ModerationResult] }>()

type MenuAction = Exclude<ModerationAction, 'reject'>

const { t } = useI18n()
const auth = useAuthStore()
const router = useRouter()
const toast = useToast()
const { adminError } = useAdminErrors()

const LIST_PATH = { post: '/blog', thread: '/forum' } as const

const busy = ref(false)
const hideOpen = ref(false)
const deleteOpen = ref(false)
const purgeOpen = ref(false)
const dialogError = ref('')

async function run(action: MenuAction, reason?: string) {
  if (busy.value) return
  busy.value = true
  dialogError.value = ''
  try {
    const result = await moderationService.act(props.contentType, props.contentId, action, reason)
    hideOpen.value = false
    deleteOpen.value = false
    emit('changed', result)
    // Content hidden when it was deleted comes back hidden: the toast must not suggest otherwise.
    const done = action === 'restore' && result.status === 'hidden' ? 'restoreHidden' : action
    toast.add({ title: t(`moderation.done.${done}`), color: 'success', icon: 'i-lucide-check' })
  } catch (error) {
    const message = adminError(error)
    // In a dialog the error stays next to the button; otherwise a toast.
    if (hideOpen.value || deleteOpen.value) dialogError.value = message
    else toast.add({ title: message, color: 'error', icon: 'i-lucide-circle-alert' })
  } finally {
    busy.value = false
  }
}

function openDialog(which: 'hide' | 'delete' | 'purge') {
  dialogError.value = ''
  if (which === 'hide') hideOpen.value = true
  else if (which === 'delete') deleteOpen.value = true
  else purgeOpen.value = true
}

async function purge() {
  if (busy.value) return
  busy.value = true
  dialogError.value = ''
  try {
    await moderationService.purge(props.contentType, props.contentId)
    purgeOpen.value = false
    toast.add({ title: t('moderation.done.purge'), color: 'success', icon: 'i-lucide-check' })
    await router.push(LIST_PATH[props.contentType])
  } catch (error) {
    dialogError.value = adminError(error)
  } finally {
    busy.value = false
  }
}

const items = computed<DropdownMenuItem[][]>(() => {
  const status = props.status
  const changes: DropdownMenuItem[] = []
  if (status === 'pending')
    changes.push({
      label: t('moderation.approve'),
      icon: 'i-lucide-circle-check',
      onSelect: () => void run('approve'),
    })
  if (status === 'published')
    changes.push({
      label: t('moderation.hide'),
      icon: 'i-lucide-eye-off',
      onSelect: () => openDialog('hide'),
    })
  if (status === 'hidden')
    changes.push({
      label: t('moderation.unhide'),
      icon: 'i-lucide-eye',
      onSelect: () => void run('unhide'),
    })
  if (status === 'deleted')
    changes.push({
      label: t('moderation.restore'),
      icon: 'i-lucide-undo-2',
      onSelect: () => void run('restore'),
    })
  else
    changes.push({
      label: t('moderation.delete'),
      icon: 'i-lucide-trash',
      onSelect: () => openDialog('delete'),
    })
  return [
    changes,
    [
      {
        label: t('moderation.purge'),
        icon: 'i-lucide-trash-2',
        color: 'error',
        onSelect: () => openDialog('purge'),
      },
    ],
  ]
})
</script>

<template>
  <template v-if="auth.isAdmin">
    <UDropdownMenu :items="items" :content="{ align: 'end' }">
      <UButton
        icon="i-lucide-shield"
        trailing-icon="i-lucide-chevron-down"
        color="neutral"
        variant="outline"
        :loading="busy && !hideOpen && !deleteOpen && !purgeOpen"
      >
        {{ t('moderation.menu') }}
      </UButton>
    </UDropdownMenu>

    <ReasonDialog
      v-model:open="hideOpen"
      :title="t('moderation.hideTitle')"
      :description="t('moderation.hideDescription')"
      :confirm-label="t('moderation.hide')"
      :loading="busy"
      :error="dialogError"
      @confirm="(reason) => run('hide', reason)"
    />
    <ConfirmDialog
      v-model:open="deleteOpen"
      :title="t('moderation.deleteTitle')"
      :description="t('moderation.deleteDescription')"
      :confirm-label="t('moderation.delete')"
      color="error"
      :loading="busy"
      :error="dialogError"
      @confirm="run('delete')"
    />
    <PurgeDialog
      v-model:open="purgeOpen"
      :kind="contentType"
      :loading="busy"
      :error="dialogError"
      @confirm="purge"
    />
  </template>
</template>

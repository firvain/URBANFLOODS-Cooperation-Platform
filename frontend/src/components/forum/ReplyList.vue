<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from '@nuxt/ui/composables'

import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import type { ReplyOut } from '@/services/replies'
import { useRepliesStore } from '@/stores/replies'
import ReplyItem from './ReplyItem.vue'

/**
 * The replies of a thread, oldest first, children one level in, with "Load more replies".
 * Shown from the session cache at once and refreshed from the server on every visit. Deleting
 * asks in a modal.
 */
const props = withDefaults(defineProps<{ threadId: number; locked?: boolean }>(), {
  locked: false,
})

const { t } = useI18n()
const toast = useToast()
const { errorMessage } = useApiErrors()
const replies = useRepliesStore()

watch(
  () => props.threadId,
  (id) => void replies.load(id),
  { immediate: true },
)

// `load` (above) creates the thread's entry before the first render.
const state = computed(() => replies.threads[props.threadId] ?? replies.of(props.threadId))
const items = computed(() => replies.list(props.threadId))
const hasMore = computed(() => replies.hasMore(props.threadId))

// --- Delete -----------------------------------------------------------------------------------

const target = ref<ReplyOut | null>(null)
const deleteOpen = ref(false)
const deleting = ref(false)
const deleteError = ref('')

function askDelete(reply: ReplyOut) {
  target.value = reply
  deleteError.value = ''
  deleteOpen.value = true
}

async function confirmDelete() {
  if (!target.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    await replies.remove(props.threadId, target.value.id)
    deleteOpen.value = false
    target.value = null
    toast.add({ title: t('reply.removed'), color: 'success', icon: 'i-lucide-check' })
  } catch (error) {
    deleteError.value = errorMessage(error)
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="state.loading && !state.loaded" aria-busy="true" class="space-y-3">
      <span class="sr-only">{{ t('reply.loading') }}</span>
      <USkeleton v-for="n in 3" :key="n" class="h-20 w-full" />
    </div>

    <div v-else-if="state.failed && !items.length" role="alert">
      <UAlert
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :title="t('reply.loadError')"
        :actions="[
          {
            label: t('forum.retry'),
            color: 'error',
            variant: 'outline',
            icon: 'i-lucide-rotate-cw',
            onClick: () => replies.load(threadId),
          },
        ]"
      />
    </div>

    <p v-else-if="!items.length" class="text-sm text-gray-700">{{ t('reply.empty') }}</p>

    <ol v-else data-testid="reply-list" class="space-y-4">
      <ReplyItem
        v-for="reply in items"
        :key="reply.id"
        :reply="reply"
        :thread-id="threadId"
        :locked="locked"
        @delete="askDelete"
      />
    </ol>

    <div v-if="hasMore && state.loaded" class="flex justify-center">
      <UButton
        color="neutral"
        variant="outline"
        icon="i-lucide-chevrons-down"
        :loading="state.loading"
        @click="replies.loadMore(threadId)"
      >
        {{ t('reply.loadMore') }}
      </UButton>
    </div>

    <ConfirmDialog
      v-model:open="deleteOpen"
      :title="t('reply.deleteConfirm.title')"
      :description="t('reply.deleteConfirm.description')"
      :confirm-label="t('reply.deleteConfirm.confirm')"
      :cancel-label="t('reply.deleteConfirm.cancel')"
      color="error"
      :loading="deleting"
      :error="deleteError"
      @confirm="confirmDelete"
    />
  </div>
</template>

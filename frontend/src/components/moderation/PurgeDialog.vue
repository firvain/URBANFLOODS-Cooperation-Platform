<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

/**
 * Confirm a permanent delete: says what goes (the item, its comments or replies, images used
 * only there) and enables the button only once the admin has typed {@link CONFIRM_WORD}. The
 * word is the same in every language. The parent closes the dialog, so it can stay open to show
 * an `error`.
 */
withDefaults(defineProps<{ kind: 'post' | 'thread'; loading?: boolean; error?: string }>(), {
  loading: false,
  error: '',
})
const open = defineModel<boolean>('open', { required: true })
const emit = defineEmits<{ confirm: [] }>()

const CONFIRM_WORD = 'DELETE'

const { t } = useI18n()
const typed = ref('')
const formId = useId()
const confirmed = computed(() => typed.value.trim() === CONFIRM_WORD)

// Empty every time the dialog opens.
watch(open, (isOpen) => {
  if (isOpen) typed.value = ''
})

function submit() {
  if (confirmed.value) emit('confirm')
}
</script>

<template>
  <UModal
    v-model:open="open"
    :title="t('moderation.purgeDialog.title')"
    :description="t('moderation.purgeDialog.intro')"
    :dismissible="!loading"
  >
    <template #body>
      <form :id="formId" novalidate class="space-y-4" @submit.prevent="submit">
        <div role="alert">
          <UAlert
            v-if="error"
            color="error"
            variant="subtle"
            icon="i-lucide-circle-alert"
            :title="error"
          />
        </div>
        <ul data-testid="purge-list" class="list-disc space-y-1 ps-5 text-sm">
          <li>{{ t(`moderation.purgeDialog.content.${kind}`) }}</li>
          <li>{{ t(`moderation.purgeDialog.children.${kind}`) }}</li>
          <li>{{ t('moderation.purgeDialog.images') }}</li>
          <li>{{ t('moderation.purgeDialog.reports') }}</li>
        </ul>
        <UFormField
          :label="t('moderation.purgeDialog.typeLabel', { word: CONFIRM_WORD })"
          name="confirm"
        >
          <UInput v-model="typed" autocomplete="off" spellcheck="false" class="w-full" />
        </UFormField>
      </form>
    </template>
    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <UButton color="neutral" variant="outline" :disabled="loading" @click="open = false">
          {{ t('common.cancel') }}
        </UButton>
        <UButton
          type="submit"
          :form="formId"
          color="error"
          icon="i-lucide-trash-2"
          :disabled="!confirmed"
          :loading="loading"
        >
          {{ t('moderation.purgeDialog.confirm') }}
        </UButton>
      </div>
    </template>
  </UModal>
</template>

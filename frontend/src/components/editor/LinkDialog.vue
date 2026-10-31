<script setup lang="ts">
import { ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { validLinkUrl, type LinkInput } from './useRichEditor'

/**
 * Asks for a link address (http, https or mailto only; anything else gets an inline error) and
 * whether it opens in a new tab. `initial` is the link at the cursor (offers "Remove link").
 */
const props = defineProps<{ initial: LinkInput | null }>()
const open = defineModel<boolean>('open', { required: true })
const emit = defineEmits<{ apply: [link: LinkInput]; remove: [] }>()

const { t } = useI18n()
const formId = useId()

const url = ref('')
const newTab = ref(false)
const error = ref('')

watch(
  open,
  (isOpen) => {
    if (!isOpen) return
    url.value = props.initial?.href ?? ''
    newTab.value = props.initial?.newTab ?? false
    error.value = ''
  },
  { immediate: true },
)

function apply() {
  const href = validLinkUrl(url.value)
  if (!href) {
    error.value = t('editor.link.invalid')
    return
  }
  emit('apply', { href, newTab: newTab.value })
  open.value = false
}

function remove() {
  emit('remove')
  open.value = false
}
</script>

<template>
  <UModal
    v-model:open="open"
    :title="t('editor.link.title')"
    :description="t('editor.link.description')"
  >
    <template #body>
      <form :id="formId" novalidate class="space-y-4" @submit.prevent="apply">
        <UFormField
          :label="t('editor.link.url')"
          name="url"
          :help="t('editor.link.urlHint')"
          :error="error || undefined"
          required
        >
          <UInput
            v-model="url"
            type="url"
            inputmode="url"
            autocomplete="url"
            placeholder="https://"
            class="w-full"
            @update:model-value="error = ''"
          />
        </UFormField>
        <UCheckbox v-model="newTab" :label="t('editor.link.newTab')" />
      </form>
    </template>
    <template #footer>
      <div class="flex w-full flex-wrap justify-end gap-2">
        <UButton
          v-if="initial"
          color="error"
          variant="ghost"
          icon="i-lucide-unlink"
          class="me-auto"
          @click="remove"
        >
          {{ t('editor.link.remove') }}
        </UButton>
        <UButton color="neutral" variant="outline" @click="open = false">
          {{ t('editor.link.cancel') }}
        </UButton>
        <UButton type="submit" :form="formId" @click.prevent="apply">{{
          t('editor.link.apply')
        }}</UButton>
      </div>
    </template>
  </UModal>
</template>

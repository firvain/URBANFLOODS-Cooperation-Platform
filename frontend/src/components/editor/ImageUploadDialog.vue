<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { useApiErrors } from '@/composables/useApiErrors'
import {
  UPLOAD_ACCEPTED_TYPES,
  uploadsService,
  type Upload,
  type UploadKind,
} from '@/services/uploads'
import type { ImageInput } from './useRichEditor'

/**
 * Upload an image with its (required) alternative text, then emit it for insertion. `file`
 * pre-fills the dialog (an image pasted or dropped into the editor); the alt text is always asked
 * for. Server errors are shown through `errors.api.*` / `errors.fields.*`.
 */
const props = withDefaults(defineProps<{ kind?: UploadKind; file?: File | null }>(), {
  kind: 'image',
  file: null,
})
const open = defineModel<boolean>('open', { required: true })
const emit = defineEmits<{ uploaded: [image: ImageInput & { upload: Upload }] }>()

const ALT_MAX = 300
const ACCEPT = UPLOAD_ACCEPTED_TYPES.join(',')

const { t } = useI18n()
const { errorMessage, fieldErrors } = useApiErrors()
const formId = useId()
const fileId = useId()

const chosen = ref<File | null>(null)
const alt = ref('')
const previewUrl = ref('')
const pending = ref(false)
const formError = ref('')
const altError = ref('')

const fileError = computed(() =>
  chosen.value && !(UPLOAD_ACCEPTED_TYPES as readonly string[]).includes(chosen.value.type)
    ? t('editor.image.unsupported')
    : '',
)
const canSubmit = computed(
  () => !!chosen.value && !fileError.value && !!alt.value.trim() && !pending.value,
)

function setFile(next: File | null) {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  chosen.value = next
  previewUrl.value = next && !fileError.value ? URL.createObjectURL(next) : ''
  formError.value = ''
}

watch(
  open,
  (isOpen) => {
    if (!isOpen) return
    alt.value = ''
    formError.value = ''
    altError.value = ''
    pending.value = false
    setFile(props.file)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})

function onFileChange(event: Event) {
  setFile((event.target as HTMLInputElement).files?.[0] ?? null)
}

async function submit() {
  if (!canSubmit.value || !chosen.value) return
  pending.value = true
  formError.value = ''
  altError.value = ''
  try {
    const upload = await uploadsService.uploadImage(chosen.value, alt.value.trim(), props.kind)
    emit('uploaded', {
      src: upload.url,
      alt: upload.alt_text,
      width: upload.width,
      height: upload.height,
      upload,
    })
    open.value = false
  } catch (e) {
    altError.value = fieldErrors(e).alt_text ?? ''
    formError.value = errorMessage(e)
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <UModal
    v-model:open="open"
    :title="t('editor.image.title')"
    :description="t('editor.image.description')"
    :dismissible="!pending"
  >
    <template #body>
      <form :id="formId" novalidate class="space-y-4" @submit.prevent="submit">
        <div role="alert">
          <UAlert
            v-if="formError"
            color="error"
            variant="subtle"
            icon="i-lucide-circle-alert"
            :title="formError"
          />
        </div>

        <div class="space-y-1">
          <label :for="fileId" class="block space-y-1">
            <span class="block text-sm font-medium text-default">
              {{ t('editor.image.file') }}
              <span aria-hidden="true" class="text-error">*</span>
            </span>
            <input
              :id="fileId"
              type="file"
              :accept="ACCEPT"
              required
              :aria-invalid="fileError ? 'true' : undefined"
              :aria-describedby="`${fileId}-hint${fileError ? ` ${fileId}-error` : ''}`"
              :disabled="pending"
              class="block w-full text-sm text-muted file:me-3 file:rounded-md file:border-0 file:bg-primary-50 file:px-3 file:py-1.5 file:font-medium file:text-primary-800 hover:file:bg-primary-100 focus-visible:focus-ring"
              @change="onFileChange"
            />
          </label>
          <p :id="`${fileId}-hint`" class="text-sm text-muted">{{ t('editor.image.fileHint') }}</p>
          <p v-if="fileError" :id="`${fileId}-error`" class="text-sm text-error">{{ fileError }}</p>
        </div>

        <figure v-if="chosen" class="space-y-2">
          <img
            v-if="previewUrl"
            :src="previewUrl"
            :alt="alt.trim()"
            class="max-h-48 rounded-md border border-default object-contain"
          />
          <figcaption class="text-sm text-muted">{{ chosen.name }}</figcaption>
        </figure>

        <UFormField
          :label="t('editor.image.alt')"
          name="alt_text"
          :help="t('editor.image.altHint')"
          :error="altError || undefined"
          required
        >
          <UInput
            v-model="alt"
            required
            :maxlength="ALT_MAX"
            :disabled="pending"
            class="w-full"
            @update:model-value="altError = ''"
          />
        </UFormField>

        <p aria-live="polite" class="text-sm text-muted">
          {{ pending ? t('editor.image.uploading') : '' }}
        </p>
      </form>
    </template>
    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <UButton color="neutral" variant="outline" :disabled="pending" @click="open = false">
          {{ t('editor.image.cancel') }}
        </UButton>
        <UButton
          type="submit"
          :form="formId"
          icon="i-lucide-upload"
          :loading="pending"
          :disabled="!canSubmit"
          @click.prevent="submit"
        >
          {{ t('editor.image.upload') }}
        </UButton>
      </div>
    </template>
  </UModal>
</template>

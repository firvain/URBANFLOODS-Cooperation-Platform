<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

/**
 * Password input with a show/hide toggle. Use inside a `UFormField`, which supplies the id,
 * label and `aria-describedby`. The toggle is a real button with `aria-pressed`; its label stays
 * constant ("Show password") as the pressed state carries the on/off meaning.
 */
defineProps<{
  autocomplete: 'current-password' | 'new-password'
  name?: string
}>()

const model = defineModel<string>({ default: '' })
const visible = ref(false)
const { t } = useI18n()
</script>

<template>
  <UInput
    v-model="model"
    :type="visible ? 'text' : 'password'"
    :autocomplete="autocomplete"
    :name="name"
    autocapitalize="off"
    spellcheck="false"
    class="w-full"
    :ui="{ trailing: 'pe-1' }"
  >
    <template #trailing>
      <UButton
        color="neutral"
        variant="link"
        size="sm"
        :icon="visible ? 'i-lucide-eye-off' : 'i-lucide-eye'"
        :aria-label="t('auth.fields.showPassword')"
        :aria-pressed="visible"
        @click="visible = !visible"
      />
    </template>
  </UInput>
</template>

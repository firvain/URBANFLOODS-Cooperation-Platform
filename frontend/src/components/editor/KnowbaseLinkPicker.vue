<script lang="ts">
import type { components } from '@/types/api-schema'

type KbType = components['schemas']['KbType']

/**
 * One linked KNOWBASE item: the `knowbase_links` entry posts and threads send
 * (`{kb_type, kb_id}`), plus the title shown on its chip.
 */
export type KnowbaseLinkValue = components['schemas']['KnowbaseLinkIn'] & { title: string }

/** Most links a post or thread may have (backend limit). */
export const KNOWBASE_LINKS_MAX = 10
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'

import { knowbaseService } from '@/services/knowbase'

/**
 * Link KNOWBASE measures or documents to a post or thread: debounced search through the proxy,
 * "Add" on a result, chips with remove buttons for the chosen items (at most 10).
 */
const props = withDefaults(defineProps<{ label?: string; max?: number }>(), {
  label: undefined,
  max: KNOWBASE_LINKS_MAX,
})
const model = defineModel<KnowbaseLinkValue[]>({ required: true })

interface Result extends KnowbaseLinkValue {
  /** Measure code or document country, shown next to the title. */
  detail: string | null
}

const DEBOUNCE_MS = 300
const SEARCH_LIMIT = 10

const { t } = useI18n()
const hintId = useId()

const kbType = ref<KbType>('measure')
const query = ref('')
const results = ref<Result[]>([])
const searching = ref(false)
const searched = ref(false)
const searchError = ref(false)
const refused = ref(false)

let timer: ReturnType<typeof setTimeout> | undefined
let sequence = 0

const atLimit = computed(() => model.value.length >= props.max)
const types = computed(() => [
  { value: 'measure' as const, label: t('editor.kb.measures') },
  { value: 'document' as const, label: t('editor.kb.documents') },
])

const isSelected = (item: KnowbaseLinkValue) =>
  model.value.some((v) => v.kb_type === item.kb_type && v.kb_id === item.kb_id)

async function runSearch() {
  const q = query.value.trim()
  const seq = ++sequence
  if (!q) {
    results.value = []
    searched.value = false
    searching.value = false
    return
  }
  searching.value = true
  searchError.value = false
  try {
    const items: Result[] =
      kbType.value === 'measure'
        ? (await knowbaseService.listMeasures({ q, limit: SEARCH_LIMIT })).data.items.map((m) => ({
            kb_type: 'measure' as const,
            kb_id: m.id,
            title: m.title_en || m.measure_code || `#${m.id}`,
            detail: m.measure_code,
          }))
        : (await knowbaseService.listDocuments({ q, limit: SEARCH_LIMIT })).data.items.map((d) => ({
            kb_type: 'document' as const,
            kb_id: d.id,
            title: d.name_of_document_en || `#${d.id}`,
            detail: d.country,
          }))
    if (seq !== sequence) return
    results.value = items
  } catch {
    if (seq !== sequence) return
    results.value = []
    searchError.value = true
  } finally {
    if (seq === sequence) {
      searching.value = false
      searched.value = true
    }
  }
}

function onInput() {
  clearTimeout(timer)
  timer = setTimeout(runSearch, DEBOUNCE_MS)
}

function setType(value: KbType) {
  if (kbType.value === value) return
  kbType.value = value
  results.value = []
  clearTimeout(timer)
  void runSearch()
}

function add(item: Result) {
  if (isSelected(item)) return
  if (atLimit.value) {
    refused.value = true
    return
  }
  model.value = [...model.value, { kb_type: item.kb_type, kb_id: item.kb_id, title: item.title }]
}

function remove(item: KnowbaseLinkValue) {
  refused.value = false
  model.value = model.value.filter((v) => !(v.kb_type === item.kb_type && v.kb_id === item.kb_id))
}

onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <fieldset class="space-y-3" :aria-describedby="hintId">
    <legend class="text-sm font-medium text-default">{{ label ?? t('editor.kb.label') }}</legend>
    <p :id="hintId" class="text-sm text-muted">{{ t('editor.kb.hint') }}</p>

    <div v-if="model.length" class="space-y-1">
      <ul class="flex flex-wrap gap-2" :aria-label="t('editor.kb.selected')">
        <li
          v-for="item in model"
          :key="`${item.kb_type}-${item.kb_id}`"
          class="inline-flex items-center gap-1 rounded-full border border-accented bg-elevated py-0.5 ps-3 pe-1 text-sm"
        >
          <span class="sr-only">{{ t(`editor.kb.${item.kb_type}`) }}:</span>
          <UIcon
            :name="item.kb_type === 'measure' ? 'i-lucide-shield-check' : 'i-lucide-file-text'"
            class="size-4 shrink-0 text-muted"
            aria-hidden="true"
          />
          <span>{{ item.title }}</span>
          <UButton
            icon="i-lucide-x"
            color="neutral"
            variant="ghost"
            size="xs"
            :aria-label="t('editor.kb.remove', { title: item.title })"
            @click="remove(item)"
          />
        </li>
      </ul>
    </div>
    <p v-else class="text-sm text-muted">{{ t('editor.kb.none') }}</p>

    <p role="status" class="text-sm" :class="refused ? 'text-error' : 'text-muted'">
      {{ atLimit ? t('editor.kb.limit', { max }) : '' }}
    </p>

    <div role="group" :aria-label="t('editor.kb.type')" class="inline-flex gap-1">
      <UButton
        v-for="type in types"
        :key="type.value"
        size="sm"
        :color="kbType === type.value ? 'primary' : 'neutral'"
        :variant="kbType === type.value ? 'solid' : 'outline'"
        :aria-pressed="kbType === type.value ? 'true' : 'false'"
        @click="setType(type.value)"
      >
        {{ type.label }}
      </UButton>
    </div>

    <UFormField :label="t('editor.kb.search')" name="kb_search">
      <UInput
        v-model="query"
        type="search"
        icon="i-lucide-search"
        :placeholder="t('editor.kb.searchPlaceholder')"
        :loading="searching"
        class="w-full"
        @update:model-value="onInput"
      />
    </UFormField>

    <p aria-live="polite" class="text-sm text-muted">
      <template v-if="searching">{{ t('editor.kb.searching') }}</template>
      <template v-else-if="searchError">{{ t('editor.kb.searchError') }}</template>
      <template v-else-if="searched && !results.length">{{ t('editor.kb.noResults') }}</template>
    </p>

    <ul
      v-if="results.length"
      :aria-label="t('editor.kb.results')"
      class="divide-y divide-default rounded-md border border-default"
    >
      <li
        v-for="result in results"
        :key="`${result.kb_type}-${result.kb_id}`"
        class="flex items-center justify-between gap-3 px-3 py-2"
      >
        <span class="min-w-0">
          <span class="block text-sm text-default">{{ result.title }}</span>
          <span v-if="result.detail" class="block text-xs text-muted">{{ result.detail }}</span>
        </span>
        <UButton
          size="xs"
          :variant="isSelected(result) ? 'ghost' : 'outline'"
          :icon="isSelected(result) ? 'i-lucide-check' : 'i-lucide-plus'"
          :disabled="isSelected(result)"
          :aria-label="t('editor.kb.addItem', { title: result.title })"
          @click="add(result)"
        >
          {{ isSelected(result) ? t('editor.kb.added') : t('editor.kb.add') }}
        </UButton>
      </li>
    </ul>
  </fieldset>
</template>

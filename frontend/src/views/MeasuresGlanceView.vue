<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import MeasureGlanceCard from '@/components/knowbase/MeasureGlanceCard.vue'
import { useQueryFilters } from '@/composables/useQueryFilters'
import { knowbaseService, type Measure, type MeasureRef } from '@/services/knowbase'

/**
 * "Measures at a glance" (7c): the KNOWBASE's succinct list of measures, grouped by type and
 * filterable by phase and scale. Deliberately small and read-only: one request for all measures,
 * filtered and grouped in the browser; no search, no paging (browsing stays on the KNOWBASE).
 */
const { t, te } = useI18n()

/** All measures in one request (the KNOWBASE has about 40; the proxy allows up to 200). */
const LIMIT = 200

type Kind = 'types' | 'phases' | 'scales'

/** Display order of the known codes; unknown codes follow, by label. */
const ORDER: Record<Kind, readonly string[]> = {
  types: ['NBS', 'STR', 'NS', 'HYB'],
  phases: ['PRO', 'PRE', 'REC', 'MIT'],
  scales: ['PROP', 'LOC', 'REG', 'NAT'],
}

/** The label of a reference value, translated by code; the KNOWBASE label for an unknown code. */
function label(kind: Kind, value: MeasureRef): string {
  const key = `knowbase.${kind}.${value.code}`
  return te(key, 'en') ? t(key) : value.label_en || value.code
}

function byOrder(kind: Kind) {
  const rank = (code: string) => {
    const index = ORDER[kind].indexOf(code)
    return index === -1 ? ORDER[kind].length : index
  }
  return (a: MeasureRef, b: MeasureRef) =>
    rank(a.code) - rank(b.code) || label(kind, a).localeCompare(label(kind, b))
}

// --- Data -------------------------------------------------------------------------------------

const measures = ref<Measure[]>([])
const state = ref<'loading' | 'ready' | 'failed'>('loading')

async function load() {
  state.value = 'loading'
  try {
    measures.value = (await knowbaseService.listMeasures({ limit: LIMIT })).data.items
    state.value = 'ready'
  } catch {
    state.value = 'failed'
  }
}

onMounted(load)

// --- Filters (codes in the URL: ?phase=PRE&scale=LOC) ------------------------------------------

const { filters, hasFilters, setFilter, clearFilters } = useQueryFilters({
  phase: 'string',
  scale: 'string',
})

type FilterKey = 'phase' | 'scale'

const FILTERS: { key: FilterKey; kind: Kind; refs: (m: Measure) => MeasureRef[] }[] = [
  { key: 'phase', kind: 'phases', refs: (m) => m.levels_of_application },
  { key: 'scale', kind: 'scales', refs: (m) => m.scales },
]

const hasCode = (refs: MeasureRef[], code: string) => !code || refs.some((r) => r.code === code)

/** Whether a measure passes every filter except `skip` (for the counts of that filter's chips). */
function passes(measure: Measure, skip?: FilterKey) {
  return FILTERS.every(
    ({ key, refs }) => key === skip || hasCode(refs(measure), filters.value[key]),
  )
}

/** One chip group per filter: All, then the codes found in the data, each with its count. */
const chipGroups = computed(() =>
  FILTERS.map(({ key, kind, refs }) => {
    const found = new Map<string, MeasureRef>()
    for (const measure of measures.value) {
      for (const value of refs(measure)) if (!found.has(value.code)) found.set(value.code, value)
    }
    const base = measures.value.filter((m) => passes(m, key))
    const options = [...found.values()].sort(byOrder(kind)).map((value) => ({
      code: value.code,
      label: label(kind, value),
      count: base.filter((m) => hasCode(refs(m), value.code)).length,
    }))
    return {
      key,
      label: t(`knowbase.glance.${key}`),
      chips: [{ code: '', label: t('knowbase.glance.all'), count: base.length }, ...options],
    }
  }),
)

const visible = computed(() => measures.value.filter((m) => passes(m)))

// --- Groups by type ---------------------------------------------------------------------------

interface Group {
  id: string
  label: string
  category: MeasureRef | null
  items: Measure[]
}

/** The visible measures by type (NBS, STR, NS, HYB, unknown types), then "Other". */
const groups = computed<Group[]>(() => {
  const byCode = new Map<string, Group>()
  let other: Group | null = null
  for (const measure of visible.value) {
    const category = measure.category
    if (!category) {
      other ??= { id: 'glance-type-other', label: t('knowbase.types.other'), category, items: [] }
      other.items.push(measure)
      continue
    }
    let group = byCode.get(category.code)
    if (!group) {
      const slug = category.code.toLowerCase().replace(/[^a-z0-9]+/g, '-')
      group = { id: `glance-type-${slug}`, label: label('types', category), category, items: [] }
      byCode.set(category.code, group)
    }
    group.items.push(measure)
  }
  const sort = byOrder('types')
  const known = [...byCode.values()].sort((a, b) => sort(a.category!, b.category!))
  return other ? [...known, other] : known
})

const phaseLabels = (m: Measure) =>
  [...m.levels_of_application].sort(byOrder('phases')).map((v) => label('phases', v))
const scaleLabels = (m: Measure) =>
  [...m.scales].sort(byOrder('scales')).map((v) => label('scales', v))
</script>

<template>
  <UContainer class="pt-8 pb-16 lg:pb-24">
    <div class="mb-6">
      <h1 tabindex="-1" class="mb-4 text-4xl font-bold text-primary-600 focus:outline-none">
        {{ t('knowbase.glance.title') }}
      </h1>
      <div class="h-1 w-20 rounded bg-secondary-500" />
    </div>
    <p class="mb-8 max-w-3xl text-lg text-gray-700">{{ t('knowbase.glance.intro') }}</p>

    <div v-if="state === 'loading'" data-testid="glance-loading" aria-busy="true">
      <span class="sr-only">{{ t('knowbase.loading') }}</span>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        <USkeleton v-for="n in 8" :key="n" class="h-64 w-full" />
      </div>
    </div>

    <div v-else-if="state === 'failed'" role="alert">
      <UAlert
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :title="t('knowbase.glance.loadError')"
        :actions="[
          {
            label: t('knowbase.retry'),
            color: 'error',
            variant: 'outline',
            icon: 'i-lucide-rotate-cw',
            onClick: () => load(),
          },
        ]"
      />
    </div>

    <template v-else>
      <section aria-labelledby="glance-filters-heading" class="mb-8 space-y-3">
        <h2 id="glance-filters-heading" class="sr-only">{{ t('knowbase.glance.filters') }}</h2>
        <div
          v-for="group in chipGroups"
          :key="group.key"
          class="flex flex-col gap-2 sm:flex-row sm:items-center"
        >
          <!-- The group's aria-label names it for screen readers; this is the visible name. -->
          <span aria-hidden="true" class="w-16 shrink-0 text-sm font-semibold text-gray-700">
            {{ group.label }}
          </span>
          <div role="group" :aria-label="group.label" class="flex flex-wrap gap-2">
            <UButton
              v-for="chip in group.chips"
              :key="chip.code || 'all'"
              :data-testid="`${group.key}-chip`"
              size="sm"
              :color="filters[group.key] === chip.code ? 'primary' : 'neutral'"
              :variant="filters[group.key] === chip.code ? 'solid' : 'outline'"
              :aria-pressed="filters[group.key] === chip.code ? 'true' : 'false'"
              class="rounded-full"
              @click="setFilter(group.key, chip.code)"
            >
              {{ chip.label }} ({{ chip.count }})
            </UButton>
          </div>
        </div>
        <div class="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <p data-testid="glance-count" role="status" class="font-medium text-gray-700">
            {{ t('knowbase.glance.shown', { count: visible.length }) }}
          </p>
          <UButton
            v-if="hasFilters"
            color="neutral"
            variant="link"
            icon="i-lucide-x"
            class="px-0"
            @click="clearFilters()"
          >
            {{ t('knowbase.glance.clearFilters') }}
          </UButton>
        </div>
      </section>

      <div v-if="!groups.length" class="rounded border border-default p-6 text-center">
        <p class="text-gray-700">{{ t('knowbase.glance.empty') }}</p>
        <UButton
          v-if="hasFilters"
          color="neutral"
          variant="outline"
          icon="i-lucide-x"
          class="mt-4"
          @click="clearFilters()"
        >
          {{ t('knowbase.glance.clearFilters') }}
        </UButton>
      </div>

      <div v-else class="space-y-10">
        <section
          v-for="group in groups"
          :key="group.id"
          data-testid="measure-group"
          :aria-labelledby="group.id"
        >
          <h2 :id="group.id" class="mb-4 text-2xl font-semibold text-primary-800">
            {{ group.label }} ({{ group.items.length }})
          </h2>
          <ul class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            <MeasureGlanceCard
              v-for="measure in group.items"
              :key="measure.id"
              :measure="measure"
              :phases="phaseLabels(measure)"
              :scales="scaleLabels(measure)"
            />
          </ul>
        </section>
      </div>
    </template>
  </UContainer>
</template>

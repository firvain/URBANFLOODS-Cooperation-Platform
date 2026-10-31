<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import ExternalLink from '@/components/common/ExternalLink.vue'
import KnowbaseField from '@/components/knowbase/KnowbaseField.vue'
import KnowbaseMentions from '@/components/knowbase/KnowbaseMentions.vue'
import { EXTERNAL_LINKS } from '@/constants/links'
import { ApiError } from '@/services/api'
import { knowbaseService, type Measure } from '@/services/knowbase'

/** One KNOWBASE flood management measure, with the platform posts that mention it. */
const { t } = useI18n()
const route = useRoute()

const id = computed(() => Number(route.params.id))
const measure = ref<Measure | null>(null)
const state = ref<'loading' | 'ready' | 'not-found' | 'failed'>('loading')

async function load() {
  measure.value = null
  if (!Number.isInteger(id.value) || id.value < 1) {
    state.value = 'not-found'
    return
  }
  state.value = 'loading'
  try {
    measure.value = (await knowbaseService.getMeasure(id.value)).data
    state.value = 'ready'
  } catch (error) {
    state.value = error instanceof ApiError && error.status === 404 ? 'not-found' : 'failed'
  }
}

// Leaving the page also changes the params; only this route's id matters.
watch(
  id,
  () => {
    if (route.name === 'knowbase-measure') void load()
  },
  { immediate: true },
)

const title = computed(() => measure.value?.title_en || t('knowbase.measures.untitled'))
/** The original-language title, when it differs from the English one. */
const localTitle = computed(() => {
  const local = measure.value?.title_local
  return local && local !== measure.value?.title_en ? local : null
})
const localDescription = computed(() => {
  const local = measure.value?.description_local
  return local && local !== measure.value?.description_en ? local : null
})
</script>

<template>
  <UContainer class="pt-8 pb-16 lg:pb-24">
    <ULink
      to="/knowbase/measures"
      raw
      class="mb-6 inline-flex items-center gap-1 text-sm text-primary-700 underline-offset-2 hover:underline"
    >
      <UIcon name="i-lucide-arrow-left" class="size-4" aria-hidden="true" />
      {{ t('knowbase.measures.back') }}
    </ULink>

    <div v-if="state === 'loading'" aria-busy="true" class="space-y-4">
      <span class="sr-only">{{ t('knowbase.loading') }}</span>
      <USkeleton class="h-10 w-2/3" />
      <USkeleton class="h-72 w-full" />
      <USkeleton class="h-24 w-full" />
    </div>

    <template v-else-if="state === 'not-found'">
      <h1 tabindex="-1" class="text-3xl font-bold text-primary-600 focus:outline-none">
        {{ t('knowbase.measures.notFound') }}
      </h1>
      <p class="mt-4 text-muted">{{ t('knowbase.notFoundHint') }}</p>
    </template>

    <div v-else-if="state === 'failed'" role="alert">
      <UAlert
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :title="t('knowbase.measures.detailError')"
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

    <article v-else-if="measure" class="max-w-4xl space-y-8">
      <header class="space-y-3">
        <h1
          tabindex="-1"
          class="text-3xl font-bold text-primary-600 focus:outline-none sm:text-4xl"
        >
          {{ title }}
        </h1>
        <!-- The KNOWBASE does not say which language the local title is in. -->
        <p v-if="localTitle" data-testid="title-local" lang="" class="text-lg text-gray-700 italic">
          {{ localTitle }}
        </p>
        <div class="flex flex-wrap gap-2">
          <UBadge v-if="measure.category" color="secondary" variant="subtle" icon="i-lucide-layers">
            <span class="sr-only">{{ `${t('knowbase.measures.fields.category')}: ` }}</span>
            {{ measure.category.label_en }}
          </UBadge>
          <UBadge
            v-for="level in measure.levels_of_application"
            :key="`level-${level.id}`"
            color="primary"
            variant="subtle"
            icon="i-lucide-shield-check"
          >
            <span class="sr-only">{{ `${t('knowbase.measures.fields.level')}: ` }}</span>
            {{ level.label_en }}
          </UBadge>
          <UBadge
            v-for="scale in measure.scales"
            :key="`scale-${scale.id}`"
            color="neutral"
            variant="subtle"
            icon="i-lucide-map"
          >
            <span class="sr-only">{{ `${t('knowbase.measures.fields.scale')}: ` }}</span>
            {{ scale.label_en }}
          </UBadge>
        </div>
      </header>

      <figure v-if="measure.photo_url" class="overflow-hidden rounded border border-default">
        <img :src="measure.photo_url" :alt="title" class="max-h-[28rem] w-full object-cover" />
        <figcaption v-if="measure.photo_source" class="px-3 py-2 text-xs text-gray-700">
          {{ t('knowbase.measures.photoCredit', { source: measure.photo_source }) }}
        </figcaption>
      </figure>

      <KnowbaseField :label="t('knowbase.fields.description')" :text="measure.description_en" />
      <KnowbaseField
        :label="t('knowbase.fields.descriptionLocal')"
        :text="localDescription"
        lang=""
      />
      <KnowbaseField
        :label="t('knowbase.measures.fields.resources')"
        :text="measure.resources_required_en"
      />
      <KnowbaseField :label="t('knowbase.measures.fields.benefits')" :text="measure.benefits_en" />
      <KnowbaseField
        :label="t('knowbase.measures.fields.constraints')"
        :text="measure.constraints_en"
      />
      <KnowbaseField v-if="measure.all_keywords.length" :label="t('knowbase.fields.keywords')">
        <ul class="flex flex-wrap gap-1.5">
          <li v-for="keyword in measure.all_keywords" :key="keyword">
            <UBadge data-testid="kb-keyword" color="neutral" variant="outline">{{
              keyword
            }}</UBadge>
          </li>
        </ul>
      </KnowbaseField>

      <KnowbaseMentions :key="measure.id" kb-type="measure" :kb-id="measure.id" />

      <p>
        <ExternalLink
          :href="`${EXTERNAL_LINKS.knowbase}/measures`"
          trailing-icon="i-lucide-arrow-up-right"
        >
          {{ t('knowbase.openInKnowbase') }}
        </ExternalLink>
      </p>
    </article>
  </UContainer>
</template>

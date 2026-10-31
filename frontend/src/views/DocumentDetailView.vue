<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import ExternalLink from '@/components/common/ExternalLink.vue'
import KnowbaseField from '@/components/knowbase/KnowbaseField.vue'
import KnowbaseMentions from '@/components/knowbase/KnowbaseMentions.vue'
import PartnerCountry from '@/components/partners/PartnerCountry.vue'
import { EXTERNAL_LINKS } from '@/constants/links'
import { ApiError } from '@/services/api'
import { knowbaseService, parseWebLinks, type KbDocument } from '@/services/knowbase'

/** One KNOWBASE legislation or policy document, with the platform posts that mention it. */
const { t } = useI18n()
const route = useRoute()

const id = computed(() => Number(route.params.id))
const doc = ref<KbDocument | null>(null)
const state = ref<'loading' | 'ready' | 'not-found' | 'failed'>('loading')

async function load() {
  doc.value = null
  if (!Number.isInteger(id.value) || id.value < 1) {
    state.value = 'not-found'
    return
  }
  state.value = 'loading'
  try {
    doc.value = (await knowbaseService.getDocument(id.value)).data
    state.value = 'ready'
  } catch (error) {
    state.value = error instanceof ApiError && error.status === 404 ? 'not-found' : 'failed'
  }
}

// Leaving the page also changes the params; only this route's id matters.
watch(
  id,
  () => {
    if (route.name === 'knowbase-document') void load()
  },
  { immediate: true },
)

const title = computed(() => doc.value?.name_of_document_en || t('knowbase.documents.untitled'))
const localTitle = computed(() => {
  const local = doc.value?.name_of_document_local
  return local && local !== doc.value?.name_of_document_en ? local : null
})
const localDescription = computed(() => {
  const local = doc.value?.extended_description_local
  return local && local !== doc.value?.extended_description_en ? local : null
})
const webLinks = computed(() => parseWebLinks(doc.value?.web_links))

/** Host name for the link label (the full URL is the href). */
function linkLabel(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}
</script>

<template>
  <UContainer class="pt-8 pb-16 lg:pb-24">
    <ULink
      to="/knowbase/documents"
      raw
      class="mb-6 inline-flex items-center gap-1 text-sm text-primary-700 underline-offset-2 hover:underline"
    >
      <UIcon name="i-lucide-arrow-left" class="size-4" aria-hidden="true" />
      {{ t('knowbase.documents.back') }}
    </ULink>

    <div v-if="state === 'loading'" aria-busy="true" class="space-y-4">
      <span class="sr-only">{{ t('knowbase.loading') }}</span>
      <USkeleton class="h-10 w-2/3" />
      <USkeleton class="h-24 w-full" />
      <USkeleton class="h-24 w-full" />
    </div>

    <template v-else-if="state === 'not-found'">
      <h1 tabindex="-1" class="text-3xl font-bold text-primary-600 focus:outline-none">
        {{ t('knowbase.documents.notFound') }}
      </h1>
      <p class="mt-4 text-muted">{{ t('knowbase.notFoundHint') }}</p>
    </template>

    <div v-else-if="state === 'failed'" role="alert">
      <UAlert
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :title="t('knowbase.documents.detailError')"
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

    <article v-else-if="doc" class="max-w-4xl space-y-8">
      <header class="space-y-3">
        <h1
          tabindex="-1"
          class="text-3xl font-bold text-primary-600 focus:outline-none sm:text-4xl"
        >
          {{ title }}
        </h1>
        <!-- The KNOWBASE does not say which language the local name is in. -->
        <p v-if="localTitle" data-testid="title-local" lang="" class="text-lg text-gray-700 italic">
          {{ localTitle }}
        </p>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-gray-700">
          <PartnerCountry v-if="doc.country" :code="doc.country" />
          <UBadge v-if="doc.level" color="primary" variant="subtle" icon="i-lucide-landmark">
            <span class="sr-only">{{ `${t('knowbase.documents.fields.level')}: ` }}</span>
            {{ doc.level.label }}
          </UBadge>
          <UBadge v-if="doc.subject" color="secondary" variant="subtle" icon="i-lucide-file-text">
            <span class="sr-only">{{ `${t('knowbase.documents.fields.subject')}: ` }}</span>
            {{ doc.subject.label }}
          </UBadge>
        </div>
      </header>

      <KnowbaseField :label="t('knowbase.documents.fields.number')" :text="doc.no" />
      <KnowbaseField
        :label="t('knowbase.documents.fields.gazette')"
        :text="doc.official_gazzette_ref"
      />
      <KnowbaseField
        :label="t('knowbase.fields.description')"
        :text="doc.extended_description_en"
      />
      <KnowbaseField
        :label="t('knowbase.fields.descriptionLocal')"
        :text="localDescription"
        lang=""
      />
      <KnowbaseField v-if="webLinks.length" :label="t('knowbase.documents.fields.webLinks')">
        <ul data-testid="web-links" class="space-y-1">
          <li v-for="link in webLinks" :key="link">
            <ExternalLink :href="link" trailing-icon="i-lucide-arrow-up-right">
              {{ linkLabel(link) }}
            </ExternalLink>
          </li>
        </ul>
      </KnowbaseField>
      <KnowbaseField :label="t('knowbase.documents.fields.comments')" :text="doc.comments" />
      <KnowbaseField v-if="doc.all_keywords.length" :label="t('knowbase.fields.keywords')">
        <ul class="flex flex-wrap gap-1.5">
          <li v-for="keyword in doc.all_keywords" :key="keyword">
            <UBadge data-testid="kb-keyword" color="neutral" variant="outline">{{
              keyword
            }}</UBadge>
          </li>
        </ul>
      </KnowbaseField>

      <KnowbaseMentions :key="doc.id" kb-type="document" :kb-id="doc.id" />

      <p>
        <ExternalLink
          :href="`${EXTERNAL_LINKS.knowbase}/legislation`"
          trailing-icon="i-lucide-arrow-up-right"
        >
          {{ t('knowbase.openInKnowbase') }}
        </ExternalLink>
      </p>
    </article>
  </UContainer>
</template>

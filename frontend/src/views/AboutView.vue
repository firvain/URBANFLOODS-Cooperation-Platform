<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import logoStacked from '@/assets/logos/interreg-urbanfloods-stacked.png'
import priorityIcon from '@/assets/logos/priority-2-greener.png'
import ExternalLink from '@/components/common/ExternalLink.vue'
import LeadPartnerCard from '@/components/partners/LeadPartnerCard.vue'
import { EXTERNAL_LINKS } from '@/constants/links'

const { t, tm } = useI18n()

/** Fact rows below the full title, grouped as on the KNOWBASE About page. */
const FACT_ROWS = [
  { cols: 'md:grid-cols-2', keys: ['programme', 'priority'] },
  { cols: 'md:grid-cols-2', keys: ['call', 'specificObjective'] },
  { cols: 'md:grid-cols-3', keys: ['dates', 'totalBudget', 'interregFunds'] },
] as const

/**
 * The scientific coordinator's address is assembled at runtime so it never appears as one string
 * in the source, the translations or the built bundle (light protection against harvesters).
 */
const COORDINATOR_EMAIL_PARTS = ['louta', 'uowm.gr'] as const
const coordinatorEmail = COORDINATOR_EMAIL_PARTS.join('@')
const coordinatorMailto = `mailto:${coordinatorEmail}`

/** Array messages read by index through `t`, so other locales fall back to English per entry. */
const paragraphs = computed(() =>
  (tm('about.summary.paragraphs') as unknown[]).map((_, i) => t(`about.summary.paragraphs.${i}`)),
)
const outputs = computed(() =>
  (tm('about.summary.outputs') as unknown[]).map((_, i) => ({
    title: t(`about.summary.outputs.${i}.title`),
    text: t(`about.summary.outputs.${i}.text`),
  })),
)
</script>

<!-- Project web presence content (docs/branding.md §2.2, docs/about-partners-style.md). -->
<template>
  <UContainer class="pt-8 pb-4 lg:pb-24">
    <div class="mx-auto max-w-4xl">
      <div class="mb-12">
        <h1 tabindex="-1" class="mb-4 text-4xl font-bold text-primary-600 focus:outline-none">
          {{ t('about.title') }}
        </h1>
        <div class="h-1 w-20 rounded bg-secondary-500" />
      </div>

      <UCard class="mt-8">
        <div class="space-y-6">
          <!-- Wide enough that the Interreg logotype + EU emblem part reaches 300 px on desktop. -->
          <div class="mb-8 flex justify-center">
            <img
              :src="logoStacked"
              :alt="t('app.logoAlt')"
              width="1599"
              height="833"
              class="h-auto w-full max-w-[448px] min-w-[240px] lg:max-w-[560px]"
            />
          </div>

          <section aria-labelledby="information-heading" class="border-b border-secondary-200 pb-6">
            <h2 id="information-heading" class="mb-6 text-2xl font-bold text-secondary">
              {{ t('about.informationTitle') }}
            </h2>

            <div class="mb-6">
              <h3 class="mb-2 text-sm font-semibold text-muted uppercase">
                {{ t('about.facts.acronym') }}
              </h3>
              <p class="text-3xl font-bold text-primary-600">{{ t('about.values.acronym') }}</p>
            </div>

            <div
              data-testid="full-title"
              class="mb-8 rounded-lg border-l-4 border-primary-500 bg-primary-50 p-4"
            >
              <h3 class="mb-2 text-sm font-semibold text-muted uppercase">
                {{ t('about.facts.fullTitle') }}
              </h3>
              <p class="text-lg leading-relaxed font-semibold text-gray-900">
                {{ t('about.values.fullTitle') }}
              </p>
            </div>

            <div
              v-for="(row, index) in FACT_ROWS"
              :key="index"
              :class="['grid grid-cols-1 gap-6', row.cols, index > 0 && 'mt-6']"
            >
              <div v-for="key in row.keys" :key="key">
                <h3 class="mb-2 text-sm font-semibold text-muted uppercase">
                  {{ t(`about.facts.${key}`) }}
                </h3>
                <div v-if="key === 'priority'" class="flex items-center gap-3">
                  <img
                    :src="priorityIcon"
                    :alt="t('about.priorityIconAlt')"
                    width="48"
                    height="48"
                    class="h-12 w-12 shrink-0"
                  />
                  <p class="text-base text-gray-900">{{ t('about.values.priority') }}</p>
                </div>
                <p
                  v-else
                  :class="[
                    'text-gray-900',
                    key === 'programme'
                      ? 'text-xl font-bold'
                      : key === 'totalBudget' || key === 'interregFunds'
                        ? 'text-base font-semibold'
                        : 'text-base',
                  ]"
                >
                  {{ t(`about.values.${key}`) }}
                </p>
              </div>
            </div>
          </section>

          <section aria-labelledby="partners-heading">
            <h3 id="partners-heading" class="mb-3 text-lg font-semibold text-secondary">
              {{ t('about.partnersTitle') }}
            </h3>
            <LeadPartnerCard
              :name="t('about.leadPartner.name')"
              short-name="UOWM"
              country="GR"
              :address="t('about.leadPartner.address')"
            >
              <p class="font-semibold text-gray-800">
                {{ t('about.leadPartner.coordinatorName') }}
              </p>
              <p class="text-xs text-gray-600">{{ t('about.leadPartner.coordinatorRole') }}</p>
              <a
                :href="coordinatorMailto"
                class="mt-1 inline-block text-primary-600 underline underline-offset-2 hover:text-primary-700"
              >
                {{ coordinatorEmail }}
              </a>
            </LeadPartnerCard>
            <p class="mt-4">
              <ULink
                to="/partners"
                class="font-medium text-primary underline underline-offset-2 hover:text-primary-700"
              >
                {{ t('about.partnersLink') }}
              </ULink>
            </p>
          </section>

          <section aria-labelledby="summary-heading">
            <h3 id="summary-heading" class="mb-3 text-lg font-semibold text-secondary">
              {{ t('about.summary.title') }}
            </h3>
            <div class="space-y-4 text-sm leading-relaxed text-gray-600">
              <p v-for="(paragraph, i) in paragraphs" :key="i">{{ paragraph }}</p>
              <div class="mt-4">
                <p class="mb-2 font-semibold text-gray-700">
                  {{ t('about.summary.outputsIntro') }}
                </p>
                <ul class="ml-2 list-inside list-disc space-y-2">
                  <li v-for="(output, i) in outputs" :key="i">
                    <strong>{{ output.title }}</strong> {{ output.text }}
                  </li>
                </ul>
              </div>
              <p>{{ t('about.summary.closing') }}</p>
            </div>
          </section>

          <section aria-labelledby="links-heading">
            <h3 id="links-heading" class="mb-3 text-lg font-semibold text-secondary">
              {{ t('about.links.title') }}
            </h3>
            <ul class="flex flex-col gap-2">
              <li>
                <ExternalLink :href="EXTERNAL_LINKS.project">
                  {{ t('about.links.project') }}
                </ExternalLink>
              </li>
            </ul>
          </section>
        </div>
      </UCard>
    </div>
  </UContainer>
</template>

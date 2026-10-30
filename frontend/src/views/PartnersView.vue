<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'

import logoStacked from '@/assets/logos/interreg-urbanfloods-stacked.png'
import LeadPartnerCard from '@/components/partners/LeadPartnerCard.vue'
import PartnerTile from '@/components/partners/PartnerTile.vue'
import { useOrganisationsStore } from '@/stores/organisations'

/** The partnership in the KNOWBASE About-page style (docs/about-partners-style.md). */
const { t } = useI18n()
const store = useOrganisationsStore()
const { leadPartner, projectPartners, associatedPartners, partnerCountryCount, partnersLoaded } =
  storeToRefs(store)

const loading = ref(false)
const failed = ref(false)

async function load(force = false) {
  loading.value = !partnersLoaded.value || force
  failed.value = false
  try {
    await store.fetchPartners({ force })
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

onMounted(() => load())

/** The lead partner counts as a project partner. */
const counts = computed(() =>
  t('partners.counts', {
    projectPartners: projectPartners.value.length + (leadPartner.value ? 1 : 0),
    associatedPartners: associatedPartners.value.length,
    countries: partnerCountryCount.value,
  }),
)
const isEmpty = computed(
  () => !leadPartner.value && !projectPartners.value.length && !associatedPartners.value.length,
)
</script>

<template>
  <UContainer class="pt-8 pb-4 lg:pb-24">
    <div class="mx-auto max-w-4xl">
      <div class="mb-12">
        <h1 tabindex="-1" class="mb-4 text-4xl font-bold text-primary-600 focus:outline-none">
          {{ t('partners.title') }}
        </h1>
        <div class="h-1 w-20 rounded bg-secondary-500" />
        <p v-if="partnersLoaded && !isEmpty" class="mt-4 text-base text-gray-600">{{ counts }}</p>
      </div>

      <UCard class="mt-8">
        <div class="space-y-6">
          <!-- Stacked project logo at the size that keeps the measured part ≥ 300/240 px. -->
          <div class="mb-8 flex justify-center">
            <img
              :src="logoStacked"
              :alt="t('app.logoAlt')"
              width="1599"
              height="833"
              class="h-auto w-full max-w-[448px] min-w-[240px] lg:max-w-[560px]"
            />
          </div>

          <div v-if="loading" data-testid="partners-loading" aria-busy="true" class="space-y-4">
            <span class="sr-only">{{ t('partners.loading') }}</span>
            <USkeleton class="h-6 w-48" />
            <USkeleton class="h-28 w-full" />
            <div class="grid grid-cols-1 gap-2 md:grid-cols-2">
              <USkeleton v-for="n in 6" :key="n" class="h-24 w-full" />
            </div>
          </div>

          <div v-else-if="failed" role="alert">
            <UAlert
              color="error"
              variant="subtle"
              icon="i-lucide-circle-alert"
              :title="t('partners.loadError')"
              :actions="[
                {
                  label: t('partners.retry'),
                  color: 'error',
                  variant: 'outline',
                  icon: 'i-lucide-rotate-cw',
                  onClick: () => load(true),
                },
              ]"
            />
          </div>

          <p v-else-if="isEmpty" class="text-gray-600">{{ t('partners.empty') }}</p>

          <section v-else aria-labelledby="partnership-heading" class="space-y-6">
            <h2 id="partnership-heading" class="text-2xl font-bold text-secondary-600">
              {{ t('partners.partnershipTitle') }}
            </h2>

            <div v-if="leadPartner">
              <h3 class="mb-3 text-lg font-semibold text-secondary-600">
                {{ t('partners.leadPartner') }}
              </h3>
              <LeadPartnerCard
                :name="leadPartner.name"
                :short-name="leadPartner.short_name"
                :country="leadPartner.country"
                :website="leadPartner.website"
                :address="t('about.leadPartner.address')"
              />
            </div>

            <div v-if="projectPartners.length">
              <h3 class="mb-3 text-lg font-semibold text-secondary-600">
                {{ t('partners.projectPartners') }}
              </h3>
              <ul data-testid="project-partners" class="grid grid-cols-1 gap-2 md:grid-cols-2">
                <PartnerTile v-for="o in projectPartners" :key="o.id" :organisation="o" />
              </ul>
            </div>

            <div v-if="associatedPartners.length">
              <h3 class="mb-3 text-lg font-semibold text-secondary-600">
                {{ t('partners.associatedPartners') }}
              </h3>
              <ul data-testid="associated-partners" class="grid grid-cols-1 gap-2 md:grid-cols-2">
                <PartnerTile v-for="o in associatedPartners" :key="o.id" :organisation="o" />
              </ul>
            </div>
          </section>
        </div>
      </UCard>
    </div>
  </UContainer>
</template>

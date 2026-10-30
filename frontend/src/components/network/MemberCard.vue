<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import ExternalLink from '@/components/common/ExternalLink.vue'
import PartnerCountry from '@/components/partners/PartnerCountry.vue'
import { memberOrganisation, type Member } from '@/services/members'
import MemberExpertise from './MemberExpertise.vue'

/** One member in the Collaboration Network directory (the partner-tile style). */
const props = defineProps<{ member: Member }>()

const { t } = useI18n()
const organisation = computed(() => memberOrganisation(props.member))
</script>

<template>
  <li
    data-testid="member-card"
    class="flex h-full flex-col gap-2 rounded border border-secondary-200 bg-secondary-50 p-3"
  >
    <h2 class="text-base leading-snug font-semibold">
      <ULink
        :to="`/u/${member.id}`"
        raw
        class="text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
      >
        {{ member.display_name }}
      </ULink>
    </h2>
    <div class="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-gray-700">
      <span v-if="organisation">{{ organisation }}</span>
      <PartnerCountry v-if="member.country" :code="member.country" />
    </div>
    <MemberExpertise :expertise="member.expertise" />
    <p v-if="member.bio_excerpt" class="line-clamp-3 text-sm text-gray-700">
      {{ member.bio_excerpt }}
    </p>
    <p v-if="member.email" class="mt-auto text-sm">
      <ExternalLink :href="`mailto:${member.email}`" icon="i-lucide-mail">
        {{ t('network.card.email') }}<span class="sr-only">{{ ` ${member.display_name}` }}</span>
      </ExternalLink>
    </p>
  </li>
</template>

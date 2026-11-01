<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { PROFILE_TAB_LINK } from '@/components/account/CompleteProfileBanner.vue'
import ExternalLink from '@/components/common/ExternalLink.vue'
import PartnerCountry from '@/components/partners/PartnerCountry.vue'
import { memberOrganisation, type Member } from '@/services/members'
import { useAuthStore } from '@/stores/auth'
import MemberExpertise from './MemberExpertise.vue'

/** One member in the Collaboration Network directory (the partner-tile style). */
const props = defineProps<{ member: Member }>()

const { t } = useI18n()
const auth = useAuthStore()
const organisation = computed(() => memberOrganisation(props.member))
/** The signed-in member's own card, still without expertise: invite them to add some. */
const addOwnExpertise = computed(
  () =>
    auth.user?.id === props.member.id &&
    !props.member.expertise.length &&
    !props.member.expertise_other,
)
</script>

<template>
  <li
    data-testid="member-card"
    class="flex h-full flex-col gap-2 rounded border border-secondary-200 bg-secondary-50 p-3"
  >
    <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
      <h2 class="text-base leading-snug font-semibold">
        <ULink
          :to="`/u/${member.id}`"
          raw
          class="text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
        >
          {{ member.display_name }}
        </ULink>
      </h2>
      <UBadge
        v-if="member.is_admin"
        data-testid="member-admin-badge"
        color="primary"
        variant="subtle"
        size="sm"
        icon="i-lucide-shield-check"
      >
        {{ t('profile.adminBadge') }}
      </UBadge>
    </div>
    <div class="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-gray-700">
      <span v-if="organisation">{{ organisation }}</span>
      <PartnerCountry v-if="member.country" :code="member.country" />
    </div>
    <ULink
      v-if="addOwnExpertise"
      data-testid="add-own-expertise"
      :to="PROFILE_TAB_LINK"
      raw
      class="inline-flex items-center gap-1 self-start text-sm font-medium text-primary underline underline-offset-2 hover:text-primary-700"
    >
      <UIcon name="i-lucide-plus" class="size-4" aria-hidden="true" />
      {{ t('account.nudge.ownCard') }}
    </ULink>
    <MemberExpertise v-else :expertise="member.expertise" :other="member.expertise_other" />
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

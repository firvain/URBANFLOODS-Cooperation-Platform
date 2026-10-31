<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { memberOrganisation, membersService, type SuggestedMember } from '@/services/members'
import { useAuthStore } from '@/stores/auth'

/**
 * Matchmaking on the home page: members who share the user's expertise areas. Verified users
 * only; the parent decides whether to render it (so nothing is requested for anyone else).
 * Without expertise areas there is nothing to match on, so it asks for them instead of fetching.
 */
const MAX_SHOWN = 6

const { t } = useI18n()
const auth = useAuthStore()

/** Fixed at mount: the profile is edited on another page. */
const needsExpertise = !auth.user?.expertise.length

const suggestions = ref<SuggestedMember[]>([])
const loading = ref(!needsExpertise)
const failed = ref(false)

onMounted(async () => {
  if (needsExpertise) return
  try {
    suggestions.value = (await membersService.suggested()).items
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
})

const shown = computed(() => suggestions.value.slice(0, MAX_SHOWN))
</script>

<template>
  <!-- Members without expertise get the CompleteProfileBanner instead; one nudge per page. -->
  <section
    v-if="!needsExpertise"
    data-testid="suggested-collaborators"
    aria-labelledby="suggested-heading"
    :aria-busy="loading"
  >
    <div class="flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 id="suggested-heading" class="text-2xl font-bold text-secondary-600">
          {{ t('network.suggested.title') }}
        </h2>
        <p class="mt-1 text-muted">{{ t('network.suggested.intro') }}</p>
      </div>
      <ULink
        to="/network"
        raw
        class="inline-flex items-center gap-1 text-sm font-medium text-primary underline underline-offset-2 hover:text-primary-700"
      >
        {{ t('network.suggested.seeAll') }}
        <UIcon name="i-lucide-arrow-right" class="size-4" aria-hidden="true" />
      </ULink>
    </div>

    <div v-if="loading" class="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <USkeleton v-for="n in 3" :key="n" class="h-20 w-full" />
    </div>

    <p v-else-if="failed" class="mt-4 text-sm text-muted">{{ t('network.suggested.loadError') }}</p>

    <p v-else-if="!shown.length" class="mt-4 text-gray-700">
      {{ t('network.suggested.empty') }}
      <ULink
        to="/account"
        raw
        class="font-medium text-primary underline underline-offset-2 hover:text-primary-700"
      >
        {{ t('network.suggested.editProfile') }}
      </ULink>
    </p>

    <ul v-else class="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <li
        v-for="member in shown"
        :key="member.id"
        data-testid="suggested-card"
        class="rounded border border-secondary-200 bg-secondary-50 px-3 py-2.5"
      >
        <ULink
          :to="`/u/${member.id}`"
          raw
          class="font-semibold text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
        >
          {{ member.display_name }}
        </ULink>
        <p v-if="memberOrganisation(member)" class="truncate text-xs text-gray-700">
          {{ memberOrganisation(member) }}
        </p>
        <p v-if="member.shared_expertise > 0" class="mt-1 text-xs font-medium text-secondary-700">
          {{
            t(
              'network.suggested.shared',
              { count: member.shared_expertise },
              member.shared_expertise,
            )
          }}
        </p>
      </li>
    </ul>
  </section>
</template>

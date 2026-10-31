<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'

import { useAuthStore } from '@/stores/auth'

/**
 * Shown in place of member data (the directory, a profile) to visitors who may not see it: a
 * sign-in link (back to this page) for anonymous visitors, a verify-your-email notice for
 * unverified users. `partners` adds a link to the public partner organisations.
 */
defineProps<{ partners?: boolean }>()

const { t } = useI18n()
const route = useRoute()
const { isAuthenticated } = storeToRefs(useAuthStore())

const loginTo = computed(() => ({ name: 'login', query: { next: route.fullPath } }))
</script>

<template>
  <div class="space-y-3 rounded border border-default p-6 text-center">
    <p v-if="!isAuthenticated">
      <ULink
        :to="loginTo"
        raw
        class="inline-flex items-center gap-1 font-medium text-primary-700 underline underline-offset-2 hover:text-primary-800"
      >
        <UIcon name="i-lucide-log-in" class="size-4" aria-hidden="true" />
        {{ t('network.restricted.signIn') }}
      </ULink>
    </p>
    <UAlert
      v-else
      color="warning"
      variant="subtle"
      icon="i-lucide-mail-warning"
      :title="t('network.restricted.verify')"
      class="text-start"
    />
    <p v-if="partners" class="text-sm">
      <ULink
        to="/partners"
        raw
        class="text-primary-700 underline underline-offset-2 hover:text-primary-800"
      >
        {{ t('network.restricted.partners') }}
      </ULink>
    </p>
  </div>
</template>

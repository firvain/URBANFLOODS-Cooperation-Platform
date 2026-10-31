<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ContentStatus, HiddenReason } from '@/services/reports'

/**
 * Why a post or thread is visible to its author (and admins) but not to others: waiting for
 * approval, not approved, hidden by an admin or after reports, or deleted. The author also reads
 * what happens after a first approval and, for hidden content, whom to contact.
 */
const props = withDefaults(
  defineProps<{
    kind: 'post' | 'thread'
    status: ContentStatus
    hiddenReason?: HiddenReason | null
    /** The viewer wrote it (otherwise an admin is looking). */
    forAuthor?: boolean
  }>(),
  { hiddenReason: null, forAuthor: false },
)

const { t } = useI18n()

/** Assembled at runtime so it never appears as one string in the source or bundle (as on About). */
const CONTACT_EMAIL_PARTS = ['louta', 'uowm.gr'] as const
const contactEmail = CONTACT_EMAIL_PARTS.join('@')

const title = computed(() => {
  switch (props.status) {
    case 'published':
      return null
    case 'hidden':
      return props.hiddenReason === 'rejected'
        ? t(`${props.kind}.statusHint.rejected`)
        : t(`${props.kind}.statusHint.hidden`)
    default:
      return t(`${props.kind}.statusHint.${props.status}`)
  }
})

const reasonText = computed(() =>
  props.status === 'hidden' && props.hiddenReason && props.hiddenReason !== 'rejected'
    ? t(`status.reason.${props.hiddenReason}`)
    : null,
)
const showFirstApproval = computed(() => props.forAuthor && props.status === 'pending')
const showContact = computed(() => props.forAuthor && props.status === 'hidden')
const color = computed(() =>
  props.status === 'pending' ? 'warning' : props.status === 'hidden' ? 'error' : 'neutral',
)
const hasDescription = computed(
  () => !!reasonText.value || showFirstApproval.value || showContact.value,
)
</script>

<template>
  <UAlert
    v-if="title"
    data-testid="status-hint"
    :color="color"
    variant="subtle"
    icon="i-lucide-info"
    :title="title"
  >
    <template v-if="hasDescription" #description>
      <p v-if="reasonText">{{ reasonText }}</p>
      <p v-if="showFirstApproval">{{ t('status.banner.firstApproval') }}</p>
      <i18n-t v-if="showContact" keypath="status.banner.contact" tag="p" scope="global">
        <template #email>
          <ULink
            :href="`mailto:${contactEmail}`"
            raw
            class="font-medium underline underline-offset-2"
          >
            {{ contactEmail }}
          </ULink>
        </template>
      </i18n-t>
    </template>
  </UAlert>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ContentStatus, HiddenReason } from '@/services/reports'

/**
 * Why a post or thread is visible to its author (and admins) but not to others: waiting for
 * approval, not approved, hidden by an admin or after reports, or deleted. The author also reads
 * what happens after a first approval and, for hidden content, whom to contact.
 *
 * A rejected item shows the admin's note (plain text, never HTML) and, to its author, a Resubmit
 * button (emits `resubmit`); once resubmitted and pending again, the note stays until a decision.
 */
const props = withDefaults(
  defineProps<{
    kind: 'post' | 'thread'
    status: ContentStatus
    hiddenReason?: HiddenReason | null
    /** The viewer wrote it (otherwise an admin is looking). */
    forAuthor?: boolean
    /** The admin's note on the last rejection. */
    moderationNote?: string | null
    /** The resubmission is being sent. */
    resubmitting?: boolean
  }>(),
  { hiddenReason: null, forAuthor: false, moderationNote: null, resubmitting: false },
)

const emit = defineEmits<{ resubmit: [] }>()

const { t } = useI18n()

/** Assembled at runtime so it never appears as one string in the source or bundle (as on About). */
const CONTACT_EMAIL_PARTS = ['louta', 'uowm.gr'] as const
const contactEmail = CONTACT_EMAIL_PARTS.join('@')

const rejected = computed(() => props.status === 'hidden' && props.hiddenReason === 'rejected')

const title = computed(() => {
  switch (props.status) {
    case 'published':
      return null
    case 'hidden':
      return rejected.value
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
/** The note belongs to a rejection: shown while rejected or resubmitted and pending again. */
const note = computed(() =>
  (rejected.value || props.status === 'pending') && props.moderationNote
    ? props.moderationNote
    : null,
)
const showResubmit = computed(() => props.forAuthor && rejected.value)
const showFirstApproval = computed(() => props.forAuthor && props.status === 'pending')
const showContact = computed(() => props.forAuthor && props.status === 'hidden')
const color = computed(() =>
  props.status === 'pending' ? 'warning' : props.status === 'hidden' ? 'error' : 'neutral',
)
const hasDescription = computed(
  () =>
    !!reasonText.value ||
    !!note.value ||
    showResubmit.value ||
    showFirstApproval.value ||
    showContact.value,
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
      <p v-if="note" class="mt-1">
        <span class="font-semibold">{{ t('status.banner.reason') }}</span>
        {{ ' ' }}
        <span data-testid="moderation-note" class="whitespace-pre-line">{{ note }}</span>
      </p>
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
      <UButton
        v-if="showResubmit"
        data-testid="resubmit"
        class="mt-3"
        color="neutral"
        variant="outline"
        icon="i-lucide-send"
        :loading="resubmitting"
        :disabled="resubmitting"
        @click="emit('resubmit')"
      >
        {{ t('status.banner.resubmit') }}
      </UButton>
    </template>
  </UAlert>
</template>

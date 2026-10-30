<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import ExternalLink from '@/components/common/ExternalLink.vue'
import PartnerCountry from '@/components/partners/PartnerCountry.vue'
import { ApiError } from '@/services/api'
import { memberOrganisation, membersService, type MemberDetail } from '@/services/members'
import NotFoundView from './NotFoundView.vue'

/** A member's public profile (`/u/:id`). An unknown or unlisted member shows the 404 content. */
const { t, locale } = useI18n()
const route = useRoute()

const member = ref<MemberDetail | null>(null)
const loading = ref(true)
const failed = ref(false)
const notFound = ref(false)

/** The id from the URL, or null when it is not a positive integer. */
const memberId = computed(() => {
  const raw = route.params.id
  const id = Number(Array.isArray(raw) ? raw[0] : raw)
  return Number.isInteger(id) && id > 0 ? id : null
})

let latest = 0

async function load() {
  const request = ++latest
  const id = memberId.value
  failed.value = false
  notFound.value = false
  if (id === null) {
    member.value = null
    notFound.value = true
    loading.value = false
    return
  }
  loading.value = true
  try {
    const result = await membersService.get(id)
    if (request === latest) member.value = result
  } catch (e) {
    if (request !== latest) return
    member.value = null
    if (e instanceof ApiError && e.status === 404) notFound.value = true
    else failed.value = true
  } finally {
    if (request === latest) loading.value = false
  }
}

watch(
  () => route.params.id,
  () => {
    if (route.name === 'profile') void load()
  },
  { immediate: true },
)

const organisation = computed(() => (member.value ? memberOrganisation(member.value) : null))

const memberSince = computed(() => {
  if (!member.value) return ''
  const date = new Intl.DateTimeFormat([locale.value, 'en'], {
    month: 'long',
    year: 'numeric',
  }).format(new Date(member.value.created_at))
  return t('profile.memberSince', { date })
})
</script>

<template>
  <NotFoundView v-if="notFound" />

  <UContainer v-else class="pt-8 pb-16 lg:pb-24">
    <div class="mx-auto max-w-3xl">
      <div
        v-if="loading && !member"
        data-testid="profile-loading"
        aria-busy="true"
        class="space-y-4"
      >
        <span class="sr-only">{{ t('profile.loading') }}</span>
        <USkeleton class="h-10 w-64" />
        <USkeleton class="h-40 w-full" />
      </div>

      <div v-else-if="failed" class="space-y-4">
        <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none">
          {{ t('profile.title') }}
        </h1>
        <div role="alert">
          <UAlert
            color="error"
            variant="subtle"
            icon="i-lucide-circle-alert"
            :title="t('profile.loadError')"
            :actions="[
              {
                label: t('profile.retry'),
                color: 'error',
                variant: 'outline',
                icon: 'i-lucide-rotate-cw',
                onClick: () => load(),
              },
            ]"
          />
        </div>
      </div>

      <article v-else-if="member">
        <div class="mb-8">
          <h1 tabindex="-1" class="mb-4 text-4xl font-bold text-primary-600 focus:outline-none">
            {{ member.display_name }}
          </h1>
          <div class="h-1 w-20 rounded bg-secondary-500" />
          <p class="mt-4 text-sm text-muted">{{ memberSince }}</p>
        </div>

        <UCard>
          <dl class="grid gap-x-6 gap-y-4 sm:grid-cols-[10rem_1fr]">
            <template v-if="organisation">
              <dt class="font-semibold text-secondary-600">{{ t('profile.organisation') }}</dt>
              <dd class="text-gray-800">{{ organisation }}</dd>
            </template>
            <template v-if="member.country">
              <dt class="font-semibold text-secondary-600">{{ t('profile.country') }}</dt>
              <dd class="text-gray-800"><PartnerCountry :code="member.country" /></dd>
            </template>
            <template v-if="member.expertise.length">
              <dt class="font-semibold text-secondary-600">{{ t('profile.expertise') }}</dt>
              <dd>
                <ul data-testid="profile-expertise" class="flex flex-wrap gap-1.5">
                  <li v-for="tag in member.expertise" :key="tag.id">
                    <UBadge color="secondary" variant="subtle">{{ tag.label }}</UBadge>
                  </li>
                </ul>
              </dd>
            </template>
            <template v-if="member.email">
              <dt class="font-semibold text-secondary-600">{{ t('profile.email') }}</dt>
              <dd>
                <ExternalLink
                  :href="`mailto:${member.email}`"
                  icon="i-lucide-mail"
                  class="break-all"
                >
                  {{ member.email }}
                </ExternalLink>
              </dd>
            </template>
          </dl>

          <section v-if="member.bio" aria-labelledby="profile-bio-heading" class="mt-6">
            <h2 id="profile-bio-heading" class="mb-2 text-lg font-semibold text-secondary-600">
              {{ t('profile.bio') }}
            </h2>
            <!-- Plain text from the member; line breaks kept, never rendered as HTML. -->
            <p data-testid="profile-bio" class="whitespace-pre-line text-gray-800">
              {{ member.bio }}
            </p>
          </section>
        </UCard>

        <UButton to="/network" variant="link" icon="i-lucide-arrow-left" class="mt-6 px-0">
          {{ t('profile.backToNetwork') }}
        </UButton>
      </article>
    </div>
  </UContainer>
</template>

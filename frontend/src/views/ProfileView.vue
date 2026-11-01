<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'

import ExternalLink from '@/components/common/ExternalLink.vue'
import MembersRestricted from '@/components/network/MembersRestricted.vue'
import PartnerCountry from '@/components/partners/PartnerCountry.vue'
import { ApiError } from '@/services/api'
import { memberOrganisation, membersService, type MemberDetail } from '@/services/members'
import { postsService, type PaginatedPosts } from '@/services/posts'
import { threadsService, type PaginatedThreads } from '@/services/threads'
import { useAuthStore } from '@/stores/auth'
import { formatDate } from '@/utils/datetime'
import NotFoundView from './NotFoundView.vue'

/**
 * A member's profile (`/u/:id`). An unknown or unlisted member shows the 404 content. Below the
 * details: their published posts and discussions (10 newest of each, with "See all" links to the
 * blog and forum filtered by `author_id`). An admin or superadmin gets an "Admin" badge next to
 * the name (`is_admin`; the API never exposes the exact role).
 * Profiles are for verified users (route meta `auth: 'verified'`); an unverified user, or a
 * 401/403 from the API, gets the sign-in/verify notice instead of an error.
 */
const { t, locale } = useI18n()
const route = useRoute()

const member = ref<MemberDetail | null>(null)
const loading = ref(true)
const failed = ref(false)
const notFound = ref(false)
/** The viewer may not see member profiles (not verified, or the API said 401/403). */
const restricted = ref(false)
const { isVerified } = storeToRefs(useAuthStore())

/** The id from the URL, or null when it is not a positive integer. */
const memberId = computed(() => {
  const raw = route.params.id
  const id = Number(Array.isArray(raw) ? raw[0] : raw)
  return Number.isInteger(id) && id > 0 ? id : null
})

/** How many of each kind of contribution the profile lists. */
const CONTRIBUTIONS_LIMIT = 10

const posts = ref<PaginatedPosts | null>(null)
const threads = ref<PaginatedThreads | null>(null)
const contributionsLoading = ref(false)
const contributionsFailed = ref(false)

let latest = 0

/** Published only: admins (and the member themselves) would otherwise also get pending ones. */
async function loadContributions(id: number, request: number) {
  posts.value = null
  threads.value = null
  contributionsFailed.value = false
  contributionsLoading.value = true
  const params = {
    author_id: id,
    status: 'published' as const,
    sort: 'newest' as const,
    limit: CONTRIBUTIONS_LIMIT,
  }
  try {
    const [postPage, threadPage] = await Promise.all([
      postsService.list(params),
      threadsService.list(params),
    ])
    if (request !== latest) return
    posts.value = postPage
    threads.value = threadPage
  } catch {
    if (request === latest) contributionsFailed.value = true
  } finally {
    if (request === latest) contributionsLoading.value = false
  }
}

async function load() {
  const request = ++latest
  const id = memberId.value
  failed.value = false
  notFound.value = false
  restricted.value = false
  if (id === null) {
    member.value = null
    notFound.value = true
    loading.value = false
    return
  }
  if (!isVerified.value) {
    member.value = null
    restricted.value = true
    loading.value = false
    return
  }
  loading.value = true
  void loadContributions(id, request)
  try {
    const result = await membersService.get(id)
    if (request === latest) member.value = result
  } catch (e) {
    if (request !== latest) return
    member.value = null
    if (e instanceof ApiError && e.status === 404) notFound.value = true
    else if (e instanceof ApiError && (e.status === 401 || e.status === 403))
      restricted.value = true
    else failed.value = true
  } finally {
    if (request === latest) loading.value = false
  }
}

watch(
  () => [route.params.id, isVerified.value],
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

const postTotal = computed(() => posts.value?.total ?? 0)
const threadTotal = computed(() => threads.value?.total ?? 0)
const hasContributions = computed(() => postTotal.value + threadTotal.value > 0)
const contributionCounts = computed(
  () =>
    `${t('blog.count', { count: postTotal.value }, postTotal.value)} · ` +
    t('forum.count', { count: threadTotal.value }, threadTotal.value),
)

const dateOf = (item: { published_at: string | null; created_at: string }) =>
  item.published_at ?? item.created_at
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

      <div v-else-if="restricted" class="space-y-4">
        <h1 tabindex="-1" class="text-3xl font-bold text-highlighted focus:outline-none">
          {{ t('profile.title') }}
        </h1>
        <MembersRestricted data-testid="profile-restricted" />
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
          <div class="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
            <h1 tabindex="-1" class="text-4xl font-bold text-primary-600 focus:outline-none">
              {{ member.display_name }}
            </h1>
            <UBadge
              v-if="member.is_admin"
              data-testid="profile-admin-badge"
              color="primary"
              variant="subtle"
              icon="i-lucide-shield-check"
            >
              {{ t('profile.adminBadge') }}
            </UBadge>
          </div>
          <div class="h-1 w-20 rounded bg-secondary-500" />
          <p class="mt-4 text-sm text-muted">{{ memberSince }}</p>
        </div>

        <UCard>
          <dl class="grid gap-x-6 gap-y-4 sm:grid-cols-[10rem_1fr]">
            <template v-if="organisation">
              <dt class="font-semibold text-secondary">{{ t('profile.organisation') }}</dt>
              <dd class="text-gray-800">{{ organisation }}</dd>
            </template>
            <template v-if="member.country">
              <dt class="font-semibold text-secondary">{{ t('profile.country') }}</dt>
              <dd class="text-gray-800"><PartnerCountry :code="member.country" /></dd>
            </template>
            <template v-if="member.expertise.length || member.expertise_other">
              <dt class="font-semibold text-secondary">{{ t('profile.expertise') }}</dt>
              <dd>
                <ul data-testid="profile-expertise" class="flex flex-wrap gap-1.5">
                  <li v-for="tag in member.expertise" :key="tag.id">
                    <UBadge color="secondary" variant="subtle">{{ tag.label }}</UBadge>
                  </li>
                  <li v-if="member.expertise_other">
                    <UBadge color="secondary" variant="subtle">{{ member.expertise_other }}</UBadge>
                  </li>
                </ul>
              </dd>
            </template>
            <template v-if="member.email">
              <dt class="font-semibold text-secondary">{{ t('profile.email') }}</dt>
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
            <h2 id="profile-bio-heading" class="mb-2 text-lg font-semibold text-secondary">
              {{ t('profile.bio') }}
            </h2>
            <!-- Plain text from the member; line breaks kept, never rendered as HTML. -->
            <p data-testid="profile-bio" class="whitespace-pre-line text-gray-800">
              {{ member.bio }}
            </p>
          </section>
        </UCard>

        <section
          data-testid="profile-contributions"
          aria-labelledby="profile-contributions-heading"
          class="mt-8"
        >
          <div class="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 id="profile-contributions-heading" class="text-2xl font-semibold text-secondary">
              {{ t('profile.contributions.title') }}
            </h2>
            <p
              v-if="hasContributions"
              data-testid="contributions-counts"
              class="text-sm font-medium text-gray-700"
            >
              {{ contributionCounts }}
            </p>
          </div>

          <div v-if="contributionsLoading" aria-busy="true">
            <span class="sr-only">{{ t('profile.contributions.loading') }}</span>
            <USkeleton class="h-24 w-full" />
          </div>
          <p v-else-if="contributionsFailed" class="text-gray-700">
            {{ t('profile.contributions.loadError') }}
          </p>
          <p v-else-if="!hasContributions" class="text-gray-700">
            {{ t('profile.contributions.empty', { name: member.display_name }) }}
          </p>
          <div v-else class="grid gap-6 md:grid-cols-2">
            <section v-if="posts && postTotal" aria-labelledby="contributions-posts-heading">
              <h3
                id="contributions-posts-heading"
                class="mb-2 text-lg font-semibold text-secondary"
              >
                {{ t('profile.contributions.posts') }}
              </h3>
              <ul data-testid="contributions-posts" class="divide-y divide-default">
                <li v-for="post in posts.items" :key="post.id" class="py-2">
                  <ULink
                    :to="`/blog/${post.slug}`"
                    raw
                    :lang="post.locale"
                    class="font-medium text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
                  >
                    {{ post.title }}
                  </ULink>
                  <time :datetime="dateOf(post)" class="block text-sm text-muted">
                    {{ formatDate(dateOf(post), locale) }}
                  </time>
                </li>
              </ul>
              <UButton
                :to="`/blog?author_id=${member.id}`"
                variant="link"
                trailing-icon="i-lucide-arrow-right"
                class="mt-2 px-0"
              >
                {{ t('profile.contributions.seeAllPosts') }}
              </UButton>
            </section>

            <section v-if="threads && threadTotal" aria-labelledby="contributions-threads-heading">
              <h3
                id="contributions-threads-heading"
                class="mb-2 text-lg font-semibold text-secondary"
              >
                {{ t('profile.contributions.threads') }}
              </h3>
              <ul data-testid="contributions-threads" class="divide-y divide-default">
                <li v-for="thread in threads.items" :key="thread.id" class="py-2">
                  <ULink
                    :to="`/forum/t/${thread.slug}`"
                    raw
                    :lang="thread.locale"
                    class="font-medium text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
                  >
                    {{ thread.title }}
                  </ULink>
                  <time :datetime="dateOf(thread)" class="block text-sm text-muted">
                    {{ formatDate(dateOf(thread), locale) }}
                  </time>
                </li>
              </ul>
              <UButton
                :to="`/forum?author_id=${member.id}`"
                variant="link"
                trailing-icon="i-lucide-arrow-right"
                class="mt-2 px-0"
              >
                {{ t('profile.contributions.seeAllThreads') }}
              </UButton>
            </section>
          </div>
        </section>

        <UButton to="/network" variant="link" icon="i-lucide-arrow-left" class="mt-6 px-0">
          {{ t('profile.backToNetwork') }}
        </UButton>
      </article>
    </div>
  </UContainer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '@nuxt/ui/composables'

import KnowbaseLinkCard from '@/components/blog/KnowbaseLinkCard.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import RelativeTime from '@/components/common/RelativeTime.vue'
import SafeHtml from '@/components/common/SafeHtml.vue'
import ReplyForm from '@/components/forum/ReplyForm.vue'
import ReplyList from '@/components/forum/ReplyList.vue'
import ThreadFlags from '@/components/forum/ThreadFlags.vue'
import ModerationMenu from '@/components/moderation/ModerationMenu.vue'
import PendingBanner from '@/components/moderation/PendingBanner.vue'
import ReportButton from '@/components/moderation/ReportButton.vue'
import StatusBadge from '@/components/moderation/StatusBadge.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import { absoluteUrl, usePageHead } from '@/composables/usePageHead'
import { CONTENT_LICENCE_URL } from '@/constants/links'
import { ApiError } from '@/services/api'
import type { ModerationResult } from '@/services/moderation'
import { threadsService, type ThreadAdminAction, type ThreadDetail } from '@/services/threads'
import { useAuthStore } from '@/stores/auth'
import { useRepliesStore } from '@/stores/replies'
import { formatDate } from '@/utils/datetime'

/**
 * One forum thread: meta, body (sanitised), tags, KNOWBASE links and the replies with the reply
 * form. Its author and admins may edit or delete it; admins pin/unpin and lock/unlock it. A locked
 * thread takes no replies; visitors are invited to log in, unverified members to verify.
 */
const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const replies = useRepliesStore()
const toast = useToast()
const { errorMessage } = useApiErrors()

const slug = computed(() => String(route.params.slug ?? ''))
const thread = ref<ThreadDetail | null>(null)
const state = ref<'loading' | 'ready' | 'not-found' | 'failed'>('loading')
/** When an admin deleted it from the menu (the detail response has no such field). */
const deletedAt = ref<string | null>(null)

async function load() {
  thread.value = null
  deletedAt.value = null
  state.value = 'loading'
  try {
    thread.value = await threadsService.get(slug.value)
    state.value = 'ready'
  } catch (error) {
    state.value = error instanceof ApiError && error.status === 404 ? 'not-found' : 'failed'
  }
}

// Leaving the page also changes the params; only this route's slug matters.
watch(
  slug,
  () => {
    if (route.name === 'thread') void load()
  },
  { immediate: true },
)

const isAuthor = computed(
  () => !!thread.value && auth.user !== null && auth.user.id === thread.value.author?.id,
)
const canManage = computed(() => !!thread.value && (auth.isAdmin || isAuthor.value))

const startedAt = computed(() => thread.value?.published_at ?? thread.value?.created_at ?? '')

const published = computed(() => thread.value?.status === 'published')
const replyCount = computed(() =>
  thread.value
    ? Math.max(0, thread.value.reply_count + (replies.threads[thread.value.id]?.delta ?? 0))
    : 0,
)
const loginTo = computed(() => ({ name: 'login', query: { next: route.fullPath } }))

// Title, Open Graph and schema.org DiscussionForumPosting data (only for a published thread).
usePageHead(() => {
  const value = thread.value
  if (!value) return null
  const url = absoluteUrl(`/forum/t/${encodeURIComponent(value.slug)}`)
  return {
    title: value.title,
    description: value.excerpt,
    type: 'article',
    canonical: url,
    jsonLd: published.value
      ? {
          '@context': 'https://schema.org',
          '@type': 'DiscussionForumPosting',
          headline: value.title,
          text: value.excerpt || undefined,
          datePublished: value.published_at ?? value.created_at,
          dateModified: value.updated_at,
          author: value.author ? { '@type': 'Person', name: value.author.display_name } : undefined,
          inLanguage: value.locale,
          license: CONTENT_LICENCE_URL,
          url,
          interactionStatistic: {
            '@type': 'InteractionCounter',
            interactionType: 'https://schema.org/CommentAction',
            userInteractionCount: replyCount.value,
          },
        }
      : null,
  }
})

// --- Admin: pin and lock ----------------------------------------------------------------------

const moderating = ref<ThreadAdminAction | null>(null)

const MODERATED: Record<ThreadAdminAction, string> = {
  pin: 'thread.admin.pinned',
  unpin: 'thread.admin.unpinned',
  lock: 'thread.admin.locked',
  unlock: 'thread.admin.unlocked',
}

async function moderate(action: ThreadAdminAction) {
  if (!thread.value || moderating.value) return
  moderating.value = action
  try {
    thread.value = await threadsService.moderate(thread.value.id, action)
    toast.add({ title: t(MODERATED[action]), color: 'success', icon: 'i-lucide-check' })
  } catch (error) {
    toast.add({ title: errorMessage(error), color: 'error', icon: 'i-lucide-circle-alert' })
  } finally {
    moderating.value = null
  }
}

// --- Admin: moderation menu -------------------------------------------------------------------

/** A moderation action from the menu: the page shows the result as returned (badge, banner,
 * dates; a restore of never-approved content has no publication date). */
function applyModeration(result: ModerationResult) {
  const value = thread.value
  if (!value) return
  thread.value = {
    ...value,
    status: result.status,
    hidden_reason: result.hidden_reason,
    published_at: result.published_at,
  }
  deletedAt.value = result.deleted_at
}

// --- Delete -----------------------------------------------------------------------------------

const deleteOpen = ref(false)
const deleting = ref(false)
const deleteError = ref('')

function askDelete() {
  deleteError.value = ''
  deleteOpen.value = true
}

async function confirmDelete() {
  if (!thread.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    await threadsService.remove(thread.value.id)
    deleteOpen.value = false
    toast.add({ title: t('thread.deleted'), color: 'success', icon: 'i-lucide-check' })
    await router.push('/forum')
  } catch (error) {
    deleteError.value = errorMessage(error)
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <UContainer class="pt-8 pb-16 lg:pb-24">
    <ULink
      to="/forum"
      raw
      class="mb-6 inline-flex items-center gap-1 text-sm text-primary-700 underline-offset-2 hover:underline"
    >
      <UIcon name="i-lucide-arrow-left" class="size-4" aria-hidden="true" />
      {{ t('thread.back') }}
    </ULink>

    <div v-if="state === 'loading'" aria-busy="true" class="space-y-4">
      <span class="sr-only">{{ t('forum.loading') }}</span>
      <USkeleton class="h-10 w-2/3" />
      <USkeleton class="h-40 w-full" />
    </div>

    <template v-else-if="state === 'not-found'">
      <h1 tabindex="-1" class="text-3xl font-bold text-primary-600 focus:outline-none">
        {{ t('thread.notFound') }}
      </h1>
      <p class="mt-4 text-muted">{{ t('thread.notFoundHint') }}</p>
    </template>

    <div v-else-if="state === 'failed'" role="alert">
      <UAlert
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :title="t('thread.loadError')"
        :actions="[
          {
            label: t('forum.retry'),
            color: 'error',
            variant: 'outline',
            icon: 'i-lucide-rotate-cw',
            onClick: () => load(),
          },
        ]"
      />
    </div>

    <div v-else-if="thread" class="mx-auto max-w-4xl space-y-8">
      <article class="space-y-8">
        <header class="space-y-4">
          <div class="flex flex-wrap items-center gap-2">
            <ThreadFlags :pinned="thread.is_pinned" :locked="thread.is_locked" size="md" />
            <ULink
              :to="`/forum/c/${thread.category.slug}`"
              raw
              class="rounded-md bg-secondary-100 px-2 py-0.5 text-sm font-medium text-secondary-900 underline-offset-2 hover:underline focus-visible:underline"
            >
              {{ thread.category.name }}
            </ULink>
            <StatusBadge :status="thread.status" :hidden-reason="thread.hidden_reason" />
            <time
              v-if="thread.status === 'deleted' && deletedAt"
              data-testid="deleted-at"
              :datetime="deletedAt"
              class="text-sm text-gray-700"
            >
              {{ formatDate(deletedAt, locale) }}
            </time>
          </div>

          <h1
            tabindex="-1"
            :lang="thread.locale"
            class="text-3xl font-bold text-primary-600 focus:outline-none sm:text-4xl"
          >
            {{ thread.title }}
          </h1>

          <PendingBanner
            kind="thread"
            :status="thread.status"
            :hidden-reason="thread.hidden_reason"
            :for-author="isAuthor"
          />

          <div class="flex flex-wrap items-center justify-between gap-4">
            <div data-testid="thread-author" class="flex items-center gap-3">
              <UAvatar
                :src="thread.author?.avatar_url ?? undefined"
                :alt="thread.author?.display_name ?? t('post.formerMember')"
                size="md"
              />
              <div class="text-sm">
                <ULink
                  v-if="thread.author"
                  :to="`/u/${thread.author.id}`"
                  raw
                  class="font-medium text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
                >
                  {{ thread.author.display_name }}
                </ULink>
                <span v-else class="font-medium">{{ t('post.formerMember') }}</span>
                <span v-if="thread.author?.organisation" class="block text-gray-700">
                  {{ thread.author.organisation.name }}
                </span>
                <span class="block text-gray-700">
                  {{ t('thread.started') }}
                  <time :datetime="startedAt">{{ formatDate(startedAt, locale) }}</time>
                  ·
                  {{ t('thread.lastActivity') }}
                  <RelativeTime :datetime="thread.last_activity_at" />
                </span>
              </div>
            </div>

            <div class="flex flex-wrap gap-2">
              <template v-if="auth.isAdmin">
                <div role="group" :aria-label="t('thread.admin.label')" class="flex gap-2">
                  <UButton
                    :icon="thread.is_pinned ? 'i-lucide-pin-off' : 'i-lucide-pin'"
                    color="neutral"
                    variant="outline"
                    :loading="moderating === 'pin' || moderating === 'unpin'"
                    @click="moderate(thread.is_pinned ? 'unpin' : 'pin')"
                  >
                    {{ thread.is_pinned ? t('thread.admin.unpin') : t('thread.admin.pin') }}
                  </UButton>
                  <UButton
                    :icon="thread.is_locked ? 'i-lucide-lock-open' : 'i-lucide-lock'"
                    color="neutral"
                    variant="outline"
                    :loading="moderating === 'lock' || moderating === 'unlock'"
                    @click="moderate(thread.is_locked ? 'unlock' : 'lock')"
                  >
                    {{ thread.is_locked ? t('thread.admin.unlock') : t('thread.admin.lock') }}
                  </UButton>
                </div>
              </template>
              <template v-if="canManage">
                <UButton
                  :to="`/forum/t/${thread.slug}/edit`"
                  icon="i-lucide-pencil"
                  color="neutral"
                  variant="outline"
                >
                  {{ t('thread.edit') }}
                </UButton>
                <UButton icon="i-lucide-trash-2" color="error" variant="outline" @click="askDelete">
                  {{ t('thread.delete') }}
                </UButton>
              </template>
              <ModerationMenu
                content-type="thread"
                :content-id="thread.id"
                :status="thread.status"
                @changed="applyModeration"
              />
              <ReportButton
                content-type="thread"
                :content-id="thread.id"
                :author-id="thread.author?.id ?? null"
                :status="thread.status"
                size="sm"
              />
            </div>
          </div>
        </header>

        <SafeHtml
          data-testid="thread-body"
          :html="thread.body_html"
          :lang="thread.locale"
          class="content-prose"
        />

        <section
          v-if="thread.knowbase_links?.length"
          aria-labelledby="thread-kb-heading"
          class="space-y-3"
        >
          <h2 id="thread-kb-heading" class="text-lg font-semibold text-secondary">
            {{ t('post.knowbase.title') }}
          </h2>
          <ul class="grid gap-3 sm:grid-cols-2">
            <KnowbaseLinkCard
              v-for="link in thread.knowbase_links"
              :key="`${link.kb_type}-${link.kb_id}`"
              :link="link"
            />
          </ul>
        </section>

        <ul
          v-if="thread.tags.length"
          class="flex flex-wrap gap-1.5 border-t border-default pt-6"
          :aria-label="t('thread.tags')"
        >
          <li v-for="tag in thread.tags" :key="tag.id">
            <ULink
              :to="`/forum?tag=${tag.slug}`"
              raw
              class="inline-flex rounded-md border border-accented px-2 py-0.5 text-sm text-gray-700 underline-offset-2 hover:underline focus-visible:underline"
            >
              #{{ tag.name }}
            </ULink>
          </li>
        </ul>
      </article>

      <section
        v-if="published"
        aria-labelledby="replies-heading"
        class="space-y-6 border-t border-default pt-8"
      >
        <h2 id="replies-heading" class="text-2xl font-semibold text-primary-600">
          {{ t('thread.replies', replyCount) }}
        </h2>

        <ReplyList :thread-id="thread.id" :locked="thread.is_locked" />

        <UAlert
          v-if="thread.is_locked"
          data-testid="locked-notice"
          color="neutral"
          variant="subtle"
          icon="i-lucide-lock"
          :title="t('reply.lockedNotice')"
        />
        <p
          v-else-if="!auth.isAuthenticated"
          data-testid="login-to-reply"
          class="rounded border border-default p-4 text-center"
        >
          <ULink
            :to="loginTo"
            raw
            class="inline-flex items-center gap-1 font-medium text-primary-700 underline underline-offset-2 hover:text-primary-800"
          >
            <UIcon name="i-lucide-log-in" class="size-4" aria-hidden="true" />
            {{ t('reply.loginToReply') }}
          </ULink>
        </p>
        <UAlert
          v-else-if="!auth.isVerified"
          data-testid="unverified-notice"
          color="warning"
          variant="subtle"
          icon="i-lucide-mail-warning"
          :title="t('reply.unverified')"
        />
        <ReplyForm v-else :thread-id="thread.id" />
      </section>
      <p v-else class="border-t border-default pt-6 text-sm text-gray-700">
        {{ t('reply.notPublished') }}
      </p>
    </div>

    <ConfirmDialog
      v-model:open="deleteOpen"
      :title="t('thread.deleteConfirm.title')"
      :description="t('thread.deleteConfirm.description')"
      :confirm-label="t('thread.deleteConfirm.confirm')"
      :cancel-label="t('thread.deleteConfirm.cancel')"
      color="error"
      :loading="deleting"
      :error="deleteError"
      @confirm="confirmDelete"
    />
  </UContainer>
</template>

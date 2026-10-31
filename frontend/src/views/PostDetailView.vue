<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '@nuxt/ui/composables'

import KnowbaseLinkCard from '@/components/blog/KnowbaseLinkCard.vue'
import CommentList from '@/components/comments/CommentList.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import ExternalLink from '@/components/common/ExternalLink.vue'
import SafeHtml from '@/components/common/SafeHtml.vue'
import ModerationMenu from '@/components/moderation/ModerationMenu.vue'
import PendingBanner from '@/components/moderation/PendingBanner.vue'
import ReportButton from '@/components/moderation/ReportButton.vue'
import StatusBadge from '@/components/moderation/StatusBadge.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import { absoluteUrl, usePageHead } from '@/composables/usePageHead'
import { CONTENT_LICENCE_URL } from '@/constants/links'
import { ApiError } from '@/services/api'
import { moderationService, type ModerationResult } from '@/services/moderation'
import { postsService, type PostDetail } from '@/services/posts'
import { useAuthStore } from '@/stores/auth'
import { formatDate, formatDateTime } from '@/utils/datetime'

/**
 * One blog post: cover, meta, body (sanitised), event, KNOWBASE links and the comments;
 * edit/delete for its author.
 */
const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const toast = useToast()
const { errorMessage } = useApiErrors()

const slug = computed(() => String(route.params.slug ?? ''))
const post = ref<PostDetail | null>(null)
const state = ref<'loading' | 'ready' | 'not-found' | 'failed'>('loading')
/** When it was deleted (only admins can load a deleted post); updated by the moderation menu. */
const deletedAt = ref<string | null>(null)

async function load() {
  post.value = null
  deletedAt.value = null
  state.value = 'loading'
  try {
    post.value = await postsService.get(slug.value)
    deletedAt.value = post.value.deleted_at ?? null
    state.value = 'ready'
  } catch (error) {
    state.value = error instanceof ApiError && error.status === 404 ? 'not-found' : 'failed'
  }
}

// Leaving the page also changes the params; only this route's slug matters.
watch(
  slug,
  () => {
    if (route.name === 'post') void load()
  },
  { immediate: true },
)

// Title, Open Graph and schema.org Article data (only for a published post: nobody else can
// share or index the others).
usePageHead(() => {
  const value = post.value
  if (!value) return null
  const url = absoluteUrl(`/blog/${encodeURIComponent(value.slug)}`)
  const image = value.cover?.url ? absoluteUrl(value.cover.url) : null
  return {
    title: value.title,
    description: value.excerpt,
    image,
    type: 'article',
    canonical: url,
    jsonLd:
      value.status === 'published'
        ? {
            '@context': 'https://schema.org',
            '@type': 'Article',
            headline: value.title,
            description: value.excerpt || undefined,
            datePublished: value.published_at ?? value.created_at,
            dateModified: value.updated_at,
            author: value.author
              ? { '@type': 'Person', name: value.author.display_name }
              : undefined,
            inLanguage: value.locale,
            license: CONTENT_LICENCE_URL,
            url,
            image: image ?? undefined,
          }
        : null,
  }
})

const isAuthor = computed(
  () => !!post.value && auth.user !== null && auth.user.id === post.value.author?.id,
)
/** Edit and delete for its author or an admin; a deleted post cannot be edited (admins restore
 * or purge it from the moderation menu instead). */
const canManage = computed(
  () =>
    !!post.value && post.value.status !== 'deleted' && (auth.isAdmin || isAuthor.value),
)

const publishedAt = computed(() => post.value?.published_at ?? post.value?.created_at ?? '')
/** "Updated" only for a real edit, not the seconds between creation and publication. */
const updatedAt = computed(() => {
  const value = post.value
  if (!value || !publishedAt.value) return null
  const edited = new Date(value.updated_at).getTime() - new Date(publishedAt.value).getTime()
  return edited > 60_000 ? value.updated_at : null
})

// --- Admin: moderation menu -------------------------------------------------------------------

/** A moderation action from the menu: the page shows the result as returned (badge, banner,
 * dates; a restore of never-approved content has no publication date). */
function applyModeration(result: ModerationResult) {
  const value = post.value
  if (!value) return
  post.value = {
    ...value,
    status: result.status,
    hidden_reason: result.hidden_reason,
    published_at: result.published_at,
  }
  deletedAt.value = result.deleted_at
}

// --- Author: resubmit a rejected post -------------------------------------------------------

const resubmitting = ref(false)

/** Back to the approval queue after editing; the admin's note stays until the next decision. */
async function resubmit() {
  const value = post.value
  if (!value || resubmitting.value) return
  resubmitting.value = true
  try {
    applyModeration(await moderationService.resubmit('post', value.id))
    toast.add({ title: t('status.banner.resubmitted'), color: 'success', icon: 'i-lucide-check' })
  } catch (error) {
    toast.add({ title: errorMessage(error), color: 'error', icon: 'i-lucide-circle-alert' })
  } finally {
    resubmitting.value = false
  }
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
  if (!post.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    await postsService.remove(post.value.id)
    deleteOpen.value = false
    toast.add({ title: t('post.deleted'), color: 'success', icon: 'i-lucide-check' })
    await router.push('/blog')
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
      to="/blog"
      raw
      class="mb-6 inline-flex items-center gap-1 text-sm text-primary-700 underline-offset-2 hover:underline"
    >
      <UIcon name="i-lucide-arrow-left" class="size-4" aria-hidden="true" />
      {{ t('post.back') }}
    </ULink>

    <div v-if="state === 'loading'" aria-busy="true" class="space-y-4">
      <span class="sr-only">{{ t('blog.loading') }}</span>
      <USkeleton class="h-72 w-full" />
      <USkeleton class="h-10 w-2/3" />
      <USkeleton class="h-40 w-full" />
    </div>

    <template v-else-if="state === 'not-found'">
      <h1 tabindex="-1" class="text-3xl font-bold text-primary-600 focus:outline-none">
        {{ t('post.notFound') }}
      </h1>
      <p class="mt-4 text-muted">{{ t('post.notFoundHint') }}</p>
    </template>

    <div v-else-if="state === 'failed'" role="alert">
      <UAlert
        color="error"
        variant="subtle"
        icon="i-lucide-circle-alert"
        :title="t('post.loadError')"
        :actions="[
          {
            label: t('blog.retry'),
            color: 'error',
            variant: 'outline',
            icon: 'i-lucide-rotate-cw',
            onClick: () => load(),
          },
        ]"
      />
    </div>

    <article v-else-if="post" class="mx-auto max-w-4xl space-y-8">
      <img
        v-if="post.cover"
        data-testid="post-cover"
        :src="post.cover.url"
        :alt="post.cover.alt_text"
        :width="post.cover.width"
        :height="post.cover.height"
        class="max-h-[28rem] w-full rounded border border-default object-cover"
      />

      <header class="space-y-4">
        <div class="flex flex-wrap items-center gap-2">
          <ULink
            :to="`/blog/category/${post.category.slug}`"
            raw
            class="rounded-md bg-secondary-100 px-2 py-0.5 text-sm font-medium text-secondary-900 underline-offset-2 hover:underline focus-visible:underline"
          >
            {{ post.category.name }}
          </ULink>
          <StatusBadge :status="post.status" :hidden-reason="post.hidden_reason" />
          <time
            v-if="post.status === 'deleted' && deletedAt"
            data-testid="deleted-at"
            :datetime="deletedAt"
            class="text-sm text-gray-700"
          >
            {{ formatDate(deletedAt, locale) }}
          </time>
        </div>

        <h1
          tabindex="-1"
          :lang="post.locale"
          class="text-3xl font-bold text-primary-600 focus:outline-none sm:text-4xl"
        >
          {{ post.title }}
        </h1>

        <PendingBanner
          kind="post"
          :status="post.status"
          :hidden-reason="post.hidden_reason"
          :for-author="isAuthor"
          :moderation-note="post.moderation_note"
          :resubmitting="resubmitting"
          @resubmit="resubmit"
        />

        <div class="flex flex-wrap items-center justify-between gap-4">
          <div data-testid="post-author" class="flex items-center gap-3">
            <UAvatar
              :src="post.author?.avatar_url ?? undefined"
              :alt="post.author?.display_name ?? t('post.formerMember')"
              size="md"
            />
            <div class="text-sm">
              <ULink
                v-if="post.author?.has_profile"
                :to="`/u/${post.author.id}`"
                raw
                class="font-medium text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
              >
                {{ post.author.display_name }}
              </ULink>
              <span v-else-if="post.author" class="font-medium">
                {{ post.author.display_name }}
              </span>
              <span v-else class="font-medium">{{ t('post.formerMember') }}</span>
              <span v-if="post.author?.organisation" class="block text-gray-700">
                {{ post.author.organisation.name }}
              </span>
              <span class="block text-gray-700">
                <time :datetime="publishedAt">{{ formatDate(publishedAt, locale) }}</time>
                <template v-if="updatedAt">
                  ·
                  {{ t('post.updated') }}
                  <time :datetime="updatedAt">{{ formatDate(updatedAt, locale) }}</time>
                </template>
              </span>
            </div>
          </div>

          <div class="flex flex-wrap items-center gap-2">
            <template v-if="canManage">
              <UButton
                :to="`/blog/${post.slug}/edit`"
                icon="i-lucide-pencil"
                color="neutral"
                variant="outline"
              >
                {{ t('post.edit') }}
              </UButton>
              <UButton icon="i-lucide-trash-2" color="error" variant="outline" @click="askDelete">
                {{ t('post.delete') }}
              </UButton>
            </template>
            <ModerationMenu
              content-type="post"
              :content-id="post.id"
              :status="post.status"
              @changed="applyModeration"
            />
            <ReportButton
              content-type="post"
              :content-id="post.id"
              :author-id="post.author?.id ?? null"
              :status="post.status"
              size="sm"
            />
          </div>
        </div>
      </header>

      <section
        v-if="post.event_at"
        data-testid="post-event"
        aria-labelledby="post-event-heading"
        class="flex flex-wrap items-center gap-x-6 gap-y-2 rounded border-l-4 border-primary-500 bg-primary-50 p-4"
      >
        <h2 id="post-event-heading" class="flex items-center gap-2 font-semibold text-primary-700">
          <UIcon name="i-lucide-calendar" class="size-5" aria-hidden="true" />
          {{ t('post.event.label') }}
        </h2>
        <time :datetime="post.event_at" class="font-medium">
          {{ formatDateTime(post.event_at, locale) }}
        </time>
        <ExternalLink
          v-if="post.event_url"
          :href="post.event_url"
          trailing-icon="i-lucide-arrow-up-right"
        >
          {{ t('post.event.link') }}
        </ExternalLink>
      </section>

      <SafeHtml
        data-testid="post-body"
        :html="post.body_html"
        :lang="post.locale"
        class="content-prose"
      />

      <section
        v-if="post.knowbase_links?.length"
        aria-labelledby="post-kb-heading"
        class="space-y-3"
      >
        <h2 id="post-kb-heading" class="text-lg font-semibold text-secondary">
          {{ t('post.knowbase.title') }}
        </h2>
        <ul class="grid gap-3 sm:grid-cols-2">
          <KnowbaseLinkCard
            v-for="link in post.knowbase_links"
            :key="`${link.kb_type}-${link.kb_id}`"
            :link="link"
          />
        </ul>
      </section>

      <footer v-if="post.tags.length" class="border-t border-default pt-6">
        <ul class="flex flex-wrap gap-1.5" :aria-label="t('post.tags')">
          <li v-for="tag in post.tags" :key="tag.id">
            <ULink
              :to="`/blog/tag/${tag.slug}`"
              raw
              class="inline-flex rounded-md border border-accented px-2 py-0.5 text-sm text-gray-700 underline-offset-2 hover:underline focus-visible:underline"
            >
              #{{ tag.name }}
            </ULink>
          </li>
        </ul>
      </footer>

      <CommentList
        :post-id="post.id"
        :count="post.comment_count"
        :status="post.status"
        class="border-t border-default pt-8"
      />
    </article>

    <ConfirmDialog
      v-model:open="deleteOpen"
      :title="t('post.deleteConfirm.title')"
      :description="t('post.deleteConfirm.description')"
      :confirm-label="t('post.deleteConfirm.confirm')"
      :cancel-label="t('post.deleteConfirm.cancel')"
      color="error"
      :loading="deleting"
      :error="deleteError"
      @confirm="confirmDelete"
    />
  </UContainer>
</template>

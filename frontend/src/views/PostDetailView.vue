<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '@nuxt/ui/composables'

import KnowbaseLinkCard from '@/components/blog/KnowbaseLinkCard.vue'
import PostStatusBadge from '@/components/blog/PostStatusBadge.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import ExternalLink from '@/components/common/ExternalLink.vue'
import SafeHtml from '@/components/common/SafeHtml.vue'
import { useApiErrors } from '@/composables/useApiErrors'
import { usePageHead } from '@/composables/usePageHead'
import { ApiError } from '@/services/api'
import { postsService, type PostDetail } from '@/services/posts'
import { useAuthStore } from '@/stores/auth'
import { formatDate, formatDateTime } from '@/utils/datetime'

/** One blog post: cover, meta, body (sanitised), event, KNOWBASE links; edit/delete for its author. */
const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const toast = useToast()
const { errorMessage } = useApiErrors()

const slug = computed(() => String(route.params.slug ?? ''))
const post = ref<PostDetail | null>(null)
const state = ref<'loading' | 'ready' | 'not-found' | 'failed'>('loading')

async function load() {
  post.value = null
  state.value = 'loading'
  try {
    post.value = await postsService.get(slug.value)
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

usePageHead(() =>
  post.value
    ? {
        title: post.value.title,
        description: post.value.excerpt,
        image: post.value.cover?.url ?? null,
        type: 'article',
      }
    : null,
)

const canManage = computed(
  () =>
    !!post.value &&
    (auth.isAdmin || (auth.user !== null && auth.user.id === post.value.author?.id)),
)

const publishedAt = computed(() => post.value?.published_at ?? post.value?.created_at ?? '')
/** "Updated" only for a real edit, not the seconds between creation and publication. */
const updatedAt = computed(() => {
  const value = post.value
  if (!value || !publishedAt.value) return null
  const edited = new Date(value.updated_at).getTime() - new Date(publishedAt.value).getTime()
  return edited > 60_000 ? value.updated_at : null
})

/** Why the author sees a post that others do not. */
const statusHint = computed(() => {
  const value = post.value
  if (!value || value.status === 'published') return null
  if (value.status === 'hidden') {
    return value.hidden_reason === 'rejected'
      ? t('post.statusHint.rejected')
      : t('post.statusHint.hidden')
  }
  return t(`post.statusHint.${value.status}`)
})

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
          <PostStatusBadge :status="post.status" />
        </div>

        <h1
          tabindex="-1"
          :lang="post.locale"
          class="text-3xl font-bold text-primary-600 focus:outline-none sm:text-4xl"
        >
          {{ post.title }}
        </h1>

        <UAlert
          v-if="statusHint"
          data-testid="status-hint"
          color="warning"
          variant="subtle"
          icon="i-lucide-info"
          :title="statusHint"
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
                v-if="post.author"
                :to="`/u/${post.author.id}`"
                raw
                class="font-medium text-primary-700 underline-offset-2 hover:underline focus-visible:underline"
              >
                {{ post.author.display_name }}
              </ULink>
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

          <div v-if="canManage" class="flex gap-2">
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
        class="post-prose"
      />

      <section
        v-if="post.knowbase_links?.length"
        aria-labelledby="post-kb-heading"
        class="space-y-3"
      >
        <h2 id="post-kb-heading" class="text-lg font-semibold text-secondary-700">
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

      <footer class="space-y-4 border-t border-default pt-6">
        <ul v-if="post.tags.length" class="flex flex-wrap gap-1.5" :aria-label="t('post.tags')">
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
        <!-- Comments (list and form) arrive in M3; until then only the count is shown. -->
        <p data-testid="post-comments" class="flex items-center gap-1.5 text-sm text-gray-700">
          <UIcon name="i-lucide-message-circle" class="size-4" aria-hidden="true" />
          {{ t('post.comments', post.comment_count) }}
        </p>
      </footer>
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

<!--
  Typography for the post body (Tailwind Typography is not installed). `:deep` because the
  sanitised HTML does not carry the scoped attribute. Tags: the editor allow-list.
-->
<style scoped>
.post-prose {
  color: var(--ui-text);
  line-height: 1.7;
  overflow-wrap: break-word;
}
.post-prose :deep(* + *) {
  margin-top: 0.875em;
}
.post-prose :deep(h2) {
  margin-top: 1.75em;
  font-size: 1.5rem;
  font-weight: 700;
  line-height: 1.3;
  color: var(--color-primary-600);
}
.post-prose :deep(h3) {
  margin-top: 1.5em;
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--color-primary-700);
}
.post-prose :deep(h4) {
  font-weight: 600;
}
.post-prose :deep(ul) {
  list-style: disc;
  padding-inline-start: 1.5rem;
}
.post-prose :deep(ol) {
  list-style: decimal;
  padding-inline-start: 1.5rem;
}
.post-prose :deep(li + li) {
  margin-top: 0.375em;
}
.post-prose :deep(a) {
  color: var(--color-primary-600);
  text-decoration: underline;
  text-underline-offset: 2px;
  overflow-wrap: anywhere;
}
.post-prose :deep(a:hover) {
  color: var(--color-primary-800);
}
.post-prose :deep(strong) {
  font-weight: 600;
}
.post-prose :deep(blockquote) {
  border-inline-start: 3px solid var(--color-secondary-500);
  padding-inline-start: 1rem;
  color: var(--ui-text-muted);
}
.post-prose :deep(pre) {
  overflow-x: auto;
  border-radius: 0.375rem;
  background: var(--ui-bg-elevated);
  padding: 0.75rem 1rem;
  font-family: var(--font-mono, ui-monospace, monospace);
}
.post-prose :deep(code) {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.9em;
}
.post-prose :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 0.375rem;
}
.post-prose :deep(hr) {
  border: 0;
  border-top: 1px solid var(--color-secondary-200);
}
</style>

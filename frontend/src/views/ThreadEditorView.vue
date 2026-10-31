<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  useId,
  useTemplateRef,
  watch,
} from 'vue'
import { useI18n } from 'vue-i18n'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useToast } from '@nuxt/ui/composables'

import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import KnowbaseLinkPicker, {
  type KnowbaseLinkValue,
} from '@/components/editor/KnowbaseLinkPicker.vue'
import RichTextEditor from '@/components/editor/RichTextEditor.vue'
import { DRAFT_SAVE_DELAY_MS } from '@/constants/blog'
import {
  THREAD_BODY_MAX_LENGTH,
  THREAD_DRAFT_KEY_PREFIX,
  THREAD_TAGS_MAX,
  THREAD_TAG_MAX_LENGTH,
  THREAD_TITLE_MAX_LENGTH,
  THREAD_TITLE_MIN_LENGTH,
} from '@/constants/forum'
import { useApiErrors } from '@/composables/useApiErrors'
import { SUPPORTED_LOCALES, isSupportedLocale } from '@/i18n'
import { ApiError } from '@/services/api'
import { categoryName } from '@/services/categories'
import {
  threadsService,
  type ThreadCreate,
  type ThreadDetail,
  type ThreadLocale,
  type ThreadUpdate,
} from '@/services/threads'
import { useAuthStore } from '@/stores/auth'
import { useCategoriesStore } from '@/stores/categories'

/**
 * Start a thread (`/forum/new`) or edit one (`/forum/t/:slug/edit`, its author or an admin), the
 * forum counterpart of `PostEditorView` (kept separate: the post form has a cover, excerpt and
 * event the thread form does not). Edits send only the changed fields. Unsaved changes are
 * guarded (a modal on leaving, the browser prompt on closing the tab) and kept as a draft in
 * `sessionStorage`, offered back when the page reopens.
 */
const { t, locale: uiLocale } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const categories = useCategoriesStore()
const toast = useToast()
const { errorMessage, fieldMessage } = useApiErrors()

const bodyLabelId = useId()
const editorRef = useTemplateRef<InstanceType<typeof RichTextEditor>>('editor')

const isEdit = computed(() => route.name === 'thread-edit')
const slug = computed(() => String(route.params.slug ?? ''))

// --- Form state -------------------------------------------------------------------------------

interface ThreadForm {
  title: string
  category_id: number | undefined
  locale: ThreadLocale
  body: string
  tags: string[]
  links: KnowbaseLinkValue[]
}

function defaultLocale(): ThreadLocale {
  const preferred = auth.user?.locale
  return isSupportedLocale(preferred) ? preferred : (uiLocale.value as ThreadLocale)
}

function emptyForm(): ThreadForm {
  return {
    title: '',
    category_id: undefined,
    locale: defaultLocale(),
    body: '',
    tags: [],
    links: [],
  }
}

function formFromThread(thread: ThreadDetail): ThreadForm {
  return {
    title: thread.title,
    category_id: thread.category.id,
    locale: isSupportedLocale(thread.locale) ? thread.locale : 'en',
    body: thread.body_html,
    tags: thread.tags.map((tag) => tag.name),
    links: (thread.knowbase_links ?? []).map((link) => ({
      kb_type: link.kb_type,
      kb_id: link.kb_id,
      title: link.title_en,
    })),
  }
}

const clone = (form: ThreadForm): ThreadForm => JSON.parse(JSON.stringify(form)) as ThreadForm
const snapshot = (form: ThreadForm) => JSON.stringify(form)

const form = ref<ThreadForm>(emptyForm())
const initial = ref<ThreadForm>(emptyForm())
const dirty = computed(() => snapshot(form.value) !== snapshot(initial.value))

function setInitial(value: ThreadForm) {
  initial.value = clone(value)
  form.value = clone(value)
}

/** The API fields of a form. */
function apiValues(value: ThreadForm) {
  return {
    title: value.title.trim(),
    category_id: value.category_id ?? null,
    locale: value.locale,
    body_html: value.body,
    tags: value.tags,
    knowbase_links: value.links.map(({ kb_type, kb_id }) => ({ kb_type, kb_id })),
  }
}

type ApiField = keyof ReturnType<typeof apiValues>

/** Only what differs from the loaded thread. */
function changedValues(): ThreadUpdate {
  const now = apiValues(form.value)
  const before = apiValues(initial.value)
  const changes: Record<string, unknown> = {}
  for (const key of Object.keys(now) as ApiField[]) {
    if (JSON.stringify(now[key]) !== JSON.stringify(before[key])) changes[key] = now[key]
  }
  return changes as ThreadUpdate
}

// --- Loading ----------------------------------------------------------------------------------

type State = 'loading' | 'ready' | 'unverified' | 'forbidden' | 'not-found' | 'failed'
const state = ref<State>('loading')
const thread = ref<ThreadDetail | null>(null)

async function init() {
  done = false
  draft.value = null
  draftKey = THREAD_DRAFT_KEY_PREFIX + route.path
  clearErrors()
  categories.loadForum().catch(() => {})
  if (!auth.isVerified) {
    state.value = 'unverified'
    return
  }
  if (!isEdit.value) {
    setInitial(emptyForm())
    state.value = 'ready'
    checkDraft()
    return
  }
  state.value = 'loading'
  try {
    const loaded = await threadsService.get(slug.value)
    if (!auth.isAdmin && auth.user?.id !== loaded.author?.id) {
      state.value = 'forbidden'
      return
    }
    thread.value = loaded
    setInitial(formFromThread(loaded))
    state.value = 'ready'
    checkDraft()
  } catch (error) {
    state.value = error instanceof ApiError && error.status === 404 ? 'not-found' : 'failed'
  }
}

onMounted(init)

// `/forum/new` and `/forum/t/:slug/edit` share this view: Vue Router reuses it between them.
watch(
  () => route.fullPath,
  () => {
    if (route.name === 'thread-new' || route.name === 'thread-edit') void init()
  },
)

// --- Options ----------------------------------------------------------------------------------

/** Admin-only categories are for admins (an edited thread keeps its current category). */
const categoryItems = computed(() =>
  categories.forum
    .filter((c) => !c.admin_only || auth.isAdmin || c.id === initial.value.category_id)
    .map((c) => ({ label: categoryName(c, uiLocale.value), value: c.id })),
)

const localeItems = SUPPORTED_LOCALES.map((l) => ({ label: l.nativeName, value: l.code }))

/** Authors who are not trusted yet: their thread waits for an admin. */
const needsReview = computed(() => !isEdit.value && !auth.isTrusted && !auth.isAdmin)

// --- Validation and submit --------------------------------------------------------------------

const errors = reactive<Partial<Record<ApiField, string>>>({})
const formError = ref('')
const pending = ref(false)
/** Saved or deliberately abandoned: no leave guard, no draft. */
let done = false

const FIELD_KEYS: ApiField[] = [
  'title',
  'category_id',
  'locale',
  'body_html',
  'tags',
  'knowbase_links',
]

function clearErrors() {
  for (const key of FIELD_KEYS) delete errors[key]
  formError.value = ''
}

function validate(): boolean {
  clearErrors()
  const value = form.value
  const title = value.title.trim()
  if (!title) errors.title = t('editor.form.errors.titleRequired')
  else if (title.length < THREAD_TITLE_MIN_LENGTH)
    errors.title = t('editor.form.errors.titleTooShort', { min: THREAD_TITLE_MIN_LENGTH })
  if (value.category_id === undefined) errors.category_id = t('editor.form.errors.categoryRequired')
  if (!value.body) errors.body_html = t('thread.form.errors.bodyRequired')
  else if (editorRef.value?.isOverLimit) errors.body_html = t('editor.form.errors.bodyTooLong')
  const valid = !FIELD_KEYS.some((key) => errors[key])
  if (!valid) formError.value = t('errors.api.validation.failed')
  return valid
}

/** Messages that say more than the generic field codes for this form. */
const SPECIFIC_FIELD_ERRORS: Record<string, string> = {
  'knowbase_links:not_found': 'editor.form.errors.knowbaseNotFound',
  'body_html:empty': 'thread.form.errors.bodyRequired',
}

/** Server field errors on our fields (`tags.3` → `tags`); the request error goes to the form. */
function applyServerErrors(error: unknown) {
  const codes = error instanceof ApiError ? (error.fields ?? {}) : {}
  for (const [path, code] of Object.entries(codes)) {
    const key = path.split('.')[0] as ApiField
    if (!FIELD_KEYS.includes(key) || errors[key]) continue
    const specific = SPECIFIC_FIELD_ERRORS[`${key}:${code}`]
    errors[key] = specific ? t(specific) : fieldMessage(code)
  }
  formError.value = errorMessage(error)
}

async function submit() {
  if (pending.value || !validate()) return
  pending.value = true
  try {
    let saved: ThreadDetail
    if (isEdit.value && thread.value) {
      const changes = changedValues()
      saved = Object.keys(changes).length
        ? await threadsService.update(thread.value.id, changes)
        : thread.value
      toast.add({ title: t('thread.form.saved'), color: 'success', icon: 'i-lucide-check' })
    } else {
      saved = await threadsService.create(apiValues(form.value) as ThreadCreate)
      toast.add({
        title:
          saved.status === 'pending' ? t('thread.form.createdPending') : t('thread.form.created'),
        color: 'success',
        icon: 'i-lucide-check',
      })
    }
    done = true
    removeDraft()
    await router.push(`/forum/t/${saved.slug}`)
  } catch (error) {
    applyServerErrors(error)
  } finally {
    pending.value = false
  }
}

const cancelTo = computed(() => (isEdit.value ? `/forum/t/${slug.value}` : '/forum'))

// --- Leave guard ------------------------------------------------------------------------------

const leaveOpen = ref(false)
let leaveTarget: string | null = null

onBeforeRouteLeave((to) => {
  if (done || state.value !== 'ready' || !dirty.value) return true
  leaveTarget = to.fullPath
  leaveOpen.value = true
  return false
})

function confirmLeave() {
  done = true
  removeDraft()
  leaveOpen.value = false
  if (leaveTarget) void router.push(leaveTarget)
}

function onBeforeUnload(event: BeforeUnloadEvent) {
  if (done || state.value !== 'ready' || !dirty.value) return
  saveDraft()
  event.preventDefault()
  event.returnValue = ''
}

onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))

// --- Draft autosave ---------------------------------------------------------------------------

interface Draft {
  savedAt: string
  form: ThreadForm
}

/** Set when the page (re)initialises, so it never follows the route away from the editor. */
let draftKey = ''
const draft = ref<Draft | null>(null)
let draftTimer: ReturnType<typeof setTimeout> | undefined

function readDraft(): Draft | null {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(draftKey) ?? 'null') as Draft | null
    if (!parsed?.form || typeof parsed.form.title !== 'string' || !Array.isArray(parsed.form.tags))
      return null
    return { savedAt: String(parsed.savedAt ?? ''), form: { ...emptyForm(), ...parsed.form } }
  } catch {
    return null
  }
}

function saveDraft() {
  clearTimeout(draftTimer)
  draftTimer = undefined
  try {
    if (dirty.value) {
      const value: Draft = { savedAt: new Date().toISOString(), form: form.value }
      sessionStorage.setItem(draftKey, JSON.stringify(value))
    } else {
      sessionStorage.removeItem(draftKey)
    }
  } catch {
    // Storage full or unavailable: the leave guard still protects the text.
  }
}

function removeDraft() {
  clearTimeout(draftTimer)
  draftTimer = undefined
  try {
    sessionStorage.removeItem(draftKey)
  } catch {
    // Unavailable storage holds no draft.
  }
}

/** Offer a saved draft that differs from what the page starts with. */
function checkDraft() {
  const saved = readDraft()
  if (saved && snapshot(saved.form) !== snapshot(initial.value)) draft.value = saved
  else if (saved) removeDraft()
}

function restoreDraft() {
  if (draft.value) form.value = clone(draft.value.form)
  draft.value = null
}

function discardDraft() {
  removeDraft()
  draft.value = null
}

watch(
  () => snapshot(form.value),
  () => {
    // While the restore prompt is open the stored draft is kept as it is.
    if (state.value !== 'ready' || draft.value || done) return
    clearTimeout(draftTimer)
    draftTimer = setTimeout(saveDraft, DRAFT_SAVE_DELAY_MS)
  },
)

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
  if (draftTimer !== undefined && !done) saveDraft()
  clearTimeout(draftTimer)
})

const draftSavedAt = computed(() => {
  const at = draft.value?.savedAt
  if (!at || Number.isNaN(new Date(at).getTime())) return ''
  return new Intl.DateTimeFormat([uiLocale.value, 'en'], { timeStyle: 'short' }).format(
    new Date(at),
  )
})
</script>

<template>
  <UContainer class="pt-8 pb-16 lg:pb-24">
    <ULink
      :to="cancelTo"
      raw
      class="mb-6 inline-flex items-center gap-1 text-sm text-primary-700 underline-offset-2 hover:underline"
    >
      <UIcon name="i-lucide-arrow-left" class="size-4" aria-hidden="true" />
      {{ isEdit ? t('thread.form.backToThread') : t('thread.back') }}
    </ULink>

    <div v-if="state === 'loading'" aria-busy="true" class="space-y-4">
      <span class="sr-only">{{ t('forum.loading') }}</span>
      <USkeleton class="h-10 w-2/3" />
      <USkeleton class="h-96 w-full" />
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
            onClick: () => init(),
          },
        ]"
      />
    </div>

    <div v-else class="mx-auto max-w-4xl">
      <h1 tabindex="-1" class="mb-4 text-4xl font-bold text-primary-600 focus:outline-none">
        {{ isEdit ? t('thread.form.titleEdit') : t('thread.form.titleNew') }}
      </h1>
      <div class="mb-8 h-1 w-20 rounded bg-secondary-500" />

      <UAlert
        v-if="state === 'unverified'"
        color="warning"
        variant="subtle"
        icon="i-lucide-mail-warning"
        :title="t('thread.form.unverified')"
      />

      <UAlert
        v-else-if="state === 'forbidden'"
        color="error"
        variant="subtle"
        icon="i-lucide-lock"
        :title="t('thread.form.forbidden')"
      />

      <template v-else>
        <UAlert
          v-if="draft"
          data-testid="draft-prompt"
          color="info"
          variant="subtle"
          icon="i-lucide-history"
          class="mb-6"
          :title="t('thread.form.draft.found')"
          :description="
            draftSavedAt ? t('editor.form.draft.savedAt', { time: draftSavedAt }) : undefined
          "
          :actions="[
            { label: t('editor.form.draft.restore'), color: 'info', onClick: restoreDraft },
            {
              label: t('editor.form.draft.discard'),
              color: 'neutral',
              variant: 'outline',
              onClick: discardDraft,
            },
          ]"
        />

        <form data-testid="thread-form" novalidate class="space-y-6" @submit.prevent="submit">
          <div v-if="formError" data-testid="form-error" role="alert">
            <UAlert
              color="error"
              variant="subtle"
              icon="i-lucide-circle-alert"
              :title="formError"
            />
          </div>

          <UFormField
            :label="t('thread.form.title')"
            name="title"
            required
            :help="t('thread.form.titleHint')"
            :error="errors.title || undefined"
          >
            <UInput
              v-model="form.title"
              required
              :maxlength="THREAD_TITLE_MAX_LENGTH"
              size="lg"
              class="w-full"
            />
          </UFormField>

          <div class="grid gap-6 sm:grid-cols-2">
            <UFormField
              :label="t('thread.form.category')"
              name="category_id"
              required
              :error="errors.category_id || undefined"
            >
              <USelect
                v-model="form.category_id"
                :items="categoryItems"
                :placeholder="t('thread.form.categoryPlaceholder')"
                class="w-full"
              />
            </UFormField>
            <UFormField
              :label="t('thread.form.locale')"
              name="locale"
              :help="t('thread.form.localeHint')"
              :error="errors.locale || undefined"
            >
              <USelect v-model="form.locale" :items="localeItems" class="w-full" />
            </UFormField>
          </div>

          <div class="space-y-2">
            <span :id="bodyLabelId" class="block text-sm font-medium text-default">
              {{ t('thread.form.body') }}
              <span aria-hidden="true" class="text-error">*</span>
            </span>
            <RichTextEditor
              ref="editor"
              v-model="form.body"
              :label-id="bodyLabelId"
              :max-length="THREAD_BODY_MAX_LENGTH"
              :disabled="pending"
            />
            <p v-if="errors.body_html" role="alert" class="text-sm text-error">
              {{ errors.body_html }}
            </p>
          </div>

          <UFormField
            :label="t('thread.form.tags')"
            name="tags"
            :help="t('editor.form.tagsHint', { max: THREAD_TAGS_MAX })"
            :error="errors.tags || undefined"
          >
            <UInputTags
              v-model="form.tags"
              :aria-label="t('thread.form.tags')"
              :placeholder="t('thread.form.tagsPlaceholder')"
              :max="THREAD_TAGS_MAX"
              :max-length="THREAD_TAG_MAX_LENGTH"
              add-on-blur
              add-on-paste
              delimiter=","
              class="w-full"
            />
          </UFormField>

          <div class="space-y-1">
            <KnowbaseLinkPicker v-model="form.links" />
            <p v-if="errors.knowbase_links" class="text-sm text-error">
              {{ errors.knowbase_links }}
            </p>
          </div>

          <UAlert
            v-if="needsReview"
            data-testid="untrusted-note"
            color="info"
            variant="subtle"
            icon="i-lucide-shield-check"
            :title="t('thread.form.untrustedNote')"
          />

          <div class="flex flex-wrap justify-end gap-2 border-t border-default pt-6">
            <UButton :to="cancelTo" color="neutral" variant="outline" :disabled="pending">
              {{ t('thread.form.cancel') }}
            </UButton>
            <UButton type="submit" icon="i-lucide-send" :loading="pending">
              {{
                isEdit
                  ? t('thread.form.submitEdit')
                  : needsReview
                    ? t('thread.form.submitReview')
                    : t('thread.form.submitCreate')
              }}
            </UButton>
          </div>
        </form>
      </template>
    </div>

    <ConfirmDialog
      v-model:open="leaveOpen"
      :title="t('thread.form.leave.title')"
      :description="t('thread.form.leave.description')"
      :confirm-label="t('thread.form.leave.confirm')"
      :cancel-label="t('thread.form.leave.stay')"
      color="warning"
      @confirm="confirmLeave"
    />
  </UContainer>
</template>

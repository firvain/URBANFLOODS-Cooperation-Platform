import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import type { Editor } from '@tiptap/vue-3'

import RichTextEditor from '@/components/editor/RichTextEditor.vue'
import { DRAFT_SAVE_DELAY_MS } from '@/constants/blog'
import i18n from '@/i18n'
import type { UserMe } from '@/services/auth'
import { callsTo, makeUser, mockApi, reply, replyError, type Handler } from './helpers/api'
import {
  BLOG_CATEGORIES,
  CATEGORY_LIST,
  CREATE_POST,
  TAGS,
  TAG_LIST,
  makePostDetail,
} from './helpers/blog'
import { buttonIn, chooseFile, dialog, field, pngFile } from './helpers/editor'
import { MEASURES, kbReply, measurePage } from './helpers/knowbase'
import { mountApp, unmountAll } from './helpers/mount'
import { enterOption, openSelect } from './helpers/select'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'
const SLUG = 'rain-gardens-in-kozani'
const GET_POST = `GET /api/v1/posts/${SLUG}`
const PATCH_POST = 'PATCH /api/v1/posts/42'
const UPLOAD = 'POST /api/v1/uploads/images/'

const CREATED = makePostDetail({ id: 77, slug: 'my-new-post', title: 'My new post' })

afterEach(() => {
  unmountAll()
  sessionStorage.clear()
})

function routes(user: UserMe | null = makeUser(), extra: Record<string, Handler> = {}) {
  return {
    ...(user ? { [ME]: reply(200, user) } : {}),
    [BLOG_CATEGORIES]: reply(200, CATEGORY_LIST),
    [TAGS]: reply(200, TAG_LIST),
    [CREATE_POST]: reply(201, CREATED),
    [`GET /api/v1/posts/${CREATED.slug}`]: reply(200, CREATED),
    [GET_POST]: reply(200, makePostDetail()),
    ...extra,
  }
}

const body = () => document.body
const form = (wrapper: VueWrapper) => wrapper.find('form[data-testid="post-form"]')
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function editorOf(wrapper: VueWrapper): Editor {
  return (wrapper.findComponent(RichTextEditor).vm as unknown as { editor: Editor }).editor
}

async function typeBody(wrapper: VueWrapper, text: string) {
  editorOf(wrapper).chain().focus().insertContent(text).run()
  await flushPromises()
}

async function addTag(wrapper: VueWrapper, name: string) {
  const input = wrapper.find<HTMLInputElement>(`input[aria-label="${t('editor.form.tags')}"]`)
  await input.setValue(name)
  await input.trigger('keydown', { key: 'Enter' })
  await flushPromises()
}

/** Title, category (News) and body: the minimum for a valid post. */
async function fillRequired(wrapper: VueWrapper, title = 'My new post') {
  await field(body(), t('editor.form.title')).setValue(title)
  await openSelect(wrapper, t('editor.form.category'))
  await enterOption('News')
  await typeBody(wrapper, 'Kozani tests rain gardens.')
}

async function submit(wrapper: VueWrapper) {
  await form(wrapper).trigger('submit')
  await flushPromises()
}

describe('PostEditorView access', () => {
  it('sends anonymous visitors to the login page', async () => {
    mockApi(routes(null))
    const { router } = await mountApp('/blog/new')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.next).toBe('/blog/new')
  })

  it('shows unverified users the banner and no form', async () => {
    mockApi(routes(makeUser({ is_verified: false })))
    const { wrapper } = await mountApp('/blog/new')
    expect(wrapper.text()).toContain(t('auth.unverified.title'))
    expect(wrapper.text()).toContain(t('editor.form.unverified'))
    expect(form(wrapper).exists()).toBe(false)
  })

  it('refuses to edit somebody else’s post', async () => {
    mockApi(routes(makeUser({ id: 99 })))
    const { wrapper } = await mountApp(`/blog/${SLUG}/edit`)
    expect(wrapper.text()).toContain(t('editor.form.forbidden'))
    expect(form(wrapper).exists()).toBe(false)
  })
})

describe('PostEditorView create', () => {
  it('has a focusable h1 and the labelled fields', async () => {
    mockApi(routes())
    const { wrapper } = await mountApp('/blog/new')
    const h1 = wrapper.find('main h1')
    expect(h1.text()).toBe(t('editor.form.titleNew'))
    expect(h1.attributes('tabindex')).toBe('-1')
    expect(field(body(), t('editor.form.title')).exists()).toBe(true)
    expect(field(body(), t('editor.form.excerpt')).element.getAttribute('maxlength')).toBe('500')
    expect(document.querySelector('[role="textbox"][aria-labelledby]')).not.toBeNull()
  })

  it('submits the payload and goes to the new post', async () => {
    const fetchMock = mockApi(routes(makeUser(), { [MEASURES]: kbReply(measurePage(3, 0, 10)) }))
    const { wrapper, router } = await mountApp('/blog/new')
    await fillRequired(wrapper)
    await field(body(), t('editor.form.excerpt')).setValue('  A short summary.  ')
    await addTag(wrapper, 'NBS')
    await addTag(wrapper, 'rain gardens')

    // Event
    const toggle = document.querySelector<HTMLButtonElement>('button[role="switch"]')!
    toggle.click()
    await flushPromises()
    await field(body(), t('editor.form.event.at')).setValue('2026-11-20T18:00')
    await field(body(), t('editor.form.event.url')).setValue('https://example.org/webinar')

    // KNOWBASE link
    await field(body(), t('editor.kb.search')).setValue('rain')
    await wait(400)
    await flushPromises()
    buttonIn(body(), t('editor.kb.addItem', { title: 'Measure 2' })).click()
    await flushPromises()

    await submit(wrapper)
    const [call] = callsTo(fetchMock, CREATE_POST)
    expect(call).toBeDefined()
    const sent = call!.body as Record<string, unknown>
    expect(sent).toMatchObject({
      title: 'My new post',
      category_id: 1,
      locale: 'en',
      excerpt: 'A short summary.',
      body_html: '<p>Kozani tests rain gardens.</p>',
      tags: ['NBS', 'rain gardens'],
      knowbase_links: [{ kb_type: 'measure', kb_id: 2 }],
      event_url: 'https://example.org/webinar',
      cover_attachment_id: null,
    })
    expect((sent.knowbase_links as object[])[0]).not.toHaveProperty('title')
    const eventAt = sent.event_at as string
    expect(eventAt).toMatch(/^2026-11-20T\d\d:00:00(Z|[+-]\d\d:\d\d)$/)
    expect(new Date(eventAt).getTime()).toBe(new Date(2026, 10, 20, 18, 0).getTime())
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/blog/my-new-post'))
  })

  it('validates the required fields before sending', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountApp('/blog/new')
    await submit(wrapper)
    expect(callsTo(fetchMock, CREATE_POST)).toHaveLength(0)
    expect(wrapper.text()).toContain(t('editor.form.errors.titleRequired'))
    expect(wrapper.text()).toContain(t('editor.form.errors.categoryRequired'))
    expect(wrapper.text()).toContain(t('editor.form.errors.bodyRequired'))
  })

  it('shows the review note to untrusted authors only', async () => {
    mockApi(routes())
    let { wrapper } = await mountApp('/blog/new')
    const note = wrapper.find('[data-testid="untrusted-note"]')
    expect(note.text()).toContain(t('editor.form.untrustedNote'))
    expect(t('editor.form.untrustedNote')).toBe(
      'Your first post will be reviewed by an admin before it is published.',
    )
    unmountAll()

    mockApi(routes(makeUser({ is_trusted: true })))
    ;({ wrapper } = await mountApp('/blog/new'))
    expect(wrapper.find('[data-testid="untrusted-note"]').exists()).toBe(false)
  })

  it('maps a server 422 on title to the title field', async () => {
    mockApi(
      routes(makeUser(), {
        [CREATE_POST]: replyError(422, 'validation.failed', { title: 'string_too_long' }),
      }),
    )
    const { wrapper, router } = await mountApp('/blog/new')
    await fillRequired(wrapper)
    await submit(wrapper)
    expect(router.currentRoute.value.path).toBe('/blog/new')
    expect(wrapper.text()).toContain(t('errors.fields.string_too_long'))
    expect(field(body(), t('editor.form.title')).attributes('aria-invalid')).toBe('true')
  })

  it('shows a request-level error such as an admin-only category', async () => {
    mockApi(routes(makeUser(), { [CREATE_POST]: replyError(403, 'posts.category_admin_only') }))
    const { wrapper } = await mountApp('/blog/new')
    await fillRequired(wrapper)
    await submit(wrapper)
    expect(wrapper.find('[data-testid="form-error"]').text()).toContain(
      t('errors.api.posts.category_admin_only'),
    )
  })

  it('hides admin-only categories from members and offers them to admins', async () => {
    mockApi(routes())
    let { wrapper } = await mountApp('/blog/new')
    await openSelect(wrapper, t('editor.form.category'))
    let options = Array.from(document.querySelectorAll('[role="option"]'), (o) =>
      o.textContent?.trim(),
    )
    expect(options).toEqual(['News', 'Best practices', 'Events'])
    unmountAll()

    mockApi(routes(makeUser({ role: 'admin' })))
    ;({ wrapper } = await mountApp('/blog/new'))
    await openSelect(wrapper, t('editor.form.category'))
    options = Array.from(document.querySelectorAll('[role="option"]'), (o) => o.textContent?.trim())
    expect(options).toContain('Project updates')
  })

  it('uploads a cover with kind=cover, shows its thumbnail and can remove it', async () => {
    const fetchMock = mockApi(
      routes(makeUser(), {
        [UPLOAD]: reply(201, {
          id: 9,
          url: '/static/uploads/2026/10/c.webp',
          thumb_url: '/static/uploads/2026/10/c_thumb.webp',
          width: 1600,
          height: 900,
          size_bytes: 1000,
          mime: 'image/webp',
          alt_text: 'Flooded square',
          created_at: '2026-10-31T10:00:00Z',
        }),
      }),
    )
    const { wrapper } = await mountApp('/blog/new')
    buttonIn(body(), t('editor.form.coverAdd')).click()
    await flushPromises()
    const box = dialog()
    await chooseFile(box.querySelector<HTMLInputElement>('input[type="file"]')!, pngFile())
    await field(box, t('editor.image.alt')).setValue('Flooded square')
    buttonIn(box, t('editor.image.upload')).click()
    await flushPromises()
    const [upload] = callsTo(fetchMock, UPLOAD)
    expect((upload!.body as FormData).get('kind')).toBe('cover')
    const thumb = wrapper.find('[data-testid="cover-preview"] img')
    expect(thumb.attributes('src')).toBe('/static/uploads/2026/10/c_thumb.webp')
    expect(thumb.attributes('alt')).toBe('Flooded square')

    await fillRequired(wrapper)
    buttonIn(body(), t('editor.form.coverRemove')).click()
    await flushPromises()
    expect(wrapper.find('[data-testid="cover-preview"]').exists()).toBe(false)
  })

  it('asks before leaving with unsaved changes (a modal, not confirm())', async () => {
    mockApi(routes())
    const { wrapper, router } = await mountApp('/blog/new')
    await field(body(), t('editor.form.title')).setValue('Half-written')
    await router.push('/about')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/blog/new')
    const box = dialog()
    expect(box.textContent).toContain(t('editor.form.leave.title'))

    buttonIn(box, t('editor.form.leave.stay')).click()
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/blog/new')

    await router.push('/about')
    await flushPromises()
    buttonIn(dialog(), t('editor.form.leave.confirm')).click()
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/about'))
    await flushPromises()
    expect(wrapper.find('form[data-testid="post-form"]').exists()).toBe(false)
  })

  it('leaves without asking when nothing changed', async () => {
    mockApi(routes())
    const { router } = await mountApp('/blog/new')
    await router.push('/about')
    expect(router.currentRoute.value.path).toBe('/about')
  })

  it('autosaves a draft and offers to restore it', async () => {
    mockApi(routes())
    let { wrapper } = await mountApp('/blog/new')
    expect(wrapper.find('[data-testid="draft-prompt"]').exists()).toBe(false)
    await field(body(), t('editor.form.title')).setValue('Draft title')
    await wait(DRAFT_SAVE_DELAY_MS + 50)
    unmountAll()

    mockApi(routes())
    ;({ wrapper } = await mountApp('/blog/new'))
    const prompt = wrapper.find('[data-testid="draft-prompt"]')
    expect(prompt.text()).toContain(t('editor.form.draft.found'))
    expect(field(body(), t('editor.form.title')).element.value).toBe('')
    buttonIn(prompt.element as HTMLElement, t('editor.form.draft.restore')).click()
    await flushPromises()
    expect(field(body(), t('editor.form.title')).element.value).toBe('Draft title')
    expect(wrapper.find('[data-testid="draft-prompt"]').exists()).toBe(false)
  })

  it('discarding the draft forgets it', async () => {
    mockApi(routes())
    let { wrapper } = await mountApp('/blog/new')
    await field(body(), t('editor.form.title')).setValue('Draft title')
    await wait(DRAFT_SAVE_DELAY_MS + 50)
    unmountAll()

    mockApi(routes())
    ;({ wrapper } = await mountApp('/blog/new'))
    const prompt = wrapper.find('[data-testid="draft-prompt"]')
    buttonIn(prompt.element as HTMLElement, t('editor.form.draft.discard')).click()
    await flushPromises()
    expect(wrapper.find('[data-testid="draft-prompt"]').exists()).toBe(false)
    unmountAll()

    mockApi(routes())
    ;({ wrapper } = await mountApp('/blog/new'))
    expect(wrapper.find('[data-testid="draft-prompt"]').exists()).toBe(false)
  })
})

describe('PostEditorView edit', () => {
  const author = () => makeUser({ id: 11 })

  it('prefills the form from GET /posts/{slug}', async () => {
    mockApi(routes(author()))
    const { wrapper } = await mountApp(`/blog/${SLUG}/edit`)
    expect(wrapper.find('main h1').text()).toBe(t('editor.form.titleEdit'))
    expect(field(body(), t('editor.form.title')).element.value).toBe('Rain gardens in Kozani')
    expect(field(body(), t('editor.form.excerpt')).element.value).toBe(
      'How Kozani reduces surface runoff with rain gardens.',
    )
    expect(editorOf(wrapper).getHTML()).toContain('nature-based solutions')
    expect(wrapper.find('[data-testid="cover-preview"] img').attributes('alt')).toBe(
      'Rain garden in a school yard',
    )
    expect(wrapper.text()).toContain('Rain Gardens')
    expect(wrapper.text()).toContain('urban drainage')
    expect(wrapper.find('[data-testid="untrusted-note"]').exists()).toBe(false)
  })

  it('sends only the changed fields and returns to the post', async () => {
    const updated = makePostDetail({ title: 'Rain gardens in Kozani, one year on' })
    const fetchMock = mockApi(routes(author(), { [PATCH_POST]: reply(200, updated) }))
    const { wrapper, router } = await mountApp(`/blog/${SLUG}/edit`)
    await field(body(), t('editor.form.title')).setValue('Rain gardens in Kozani, one year on')
    await submit(wrapper)
    const [call] = callsTo(fetchMock, PATCH_POST)
    expect(call!.body).toEqual({ title: 'Rain gardens in Kozani, one year on' })
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe(`/blog/${SLUG}`))
  })

  it('clears a removed event with null', async () => {
    const fetchMock = mockApi(
      routes(author(), {
        [GET_POST]: reply(
          200,
          makePostDetail({ event_at: '2026-11-20T16:00:00Z', event_url: 'https://example.org/e' }),
        ),
        [PATCH_POST]: reply(200, makePostDetail()),
      }),
    )
    const { wrapper } = await mountApp(`/blog/${SLUG}/edit`)
    const toggle = document.querySelector<HTMLButtonElement>('button[role="switch"]')!
    expect(toggle.getAttribute('aria-checked')).toBe('true')
    toggle.click()
    await flushPromises()
    await submit(wrapper)
    expect(callsTo(fetchMock, PATCH_POST)[0]!.body).toEqual({ event_at: null, event_url: null })
  })

  it('an admin may edit any post', async () => {
    mockApi(routes(makeUser({ id: 99, role: 'admin' })))
    const { wrapper } = await mountApp(`/blog/${SLUG}/edit`)
    expect(form(wrapper).exists()).toBe(true)
  })

  it('shows not-found content for an unknown post', async () => {
    mockApi(routes(author(), { [GET_POST]: replyError(404, 'posts.not_found') }))
    const { wrapper } = await mountApp(`/blog/${SLUG}/edit`)
    expect(wrapper.find('main h1').text()).toBe(t('post.notFound'))
  })
})

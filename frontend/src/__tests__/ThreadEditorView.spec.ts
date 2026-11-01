import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import type { Editor } from '@tiptap/vue-3'

import RichTextEditor from '@/components/editor/RichTextEditor.vue'
import { DRAFT_SAVE_DELAY_MS } from '@/constants/blog'
import i18n from '@/i18n'
import type { UserMe } from '@/services/auth'
import { callsTo, makeUser, mockApi, reply, replyError, type Handler } from './helpers/api'
import { buttonIn, dialog, field } from './helpers/editor'
import {
  CREATE_THREAD,
  FORUM_CATEGORIES,
  FORUM_CATEGORY_LIST,
  makeThreadDetail,
  repliesOf,
} from './helpers/forum'
import { MEASURES, kbReply, measurePage } from './helpers/knowbase'
import { mountApp, unmountAll } from './helpers/mount'
import { enterOption, openSelect } from './helpers/select'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'
const SLUG = 'sirens-or-sms'
const GET_THREAD = `GET /api/v1/threads/${SLUG}`
const PATCH_THREAD = 'PATCH /api/v1/threads/42'

const CREATED = makeThreadDetail({ id: 77, slug: 'my-question', title: 'My question' })

afterEach(() => {
  unmountAll()
  sessionStorage.clear()
})

function routes(user: UserMe | null = makeUser(), extra: Record<string, Handler> = {}) {
  return {
    ...(user ? { [ME]: reply(200, user) } : {}),
    [FORUM_CATEGORIES]: reply(200, FORUM_CATEGORY_LIST),
    [CREATE_THREAD]: reply(201, CREATED),
    [`GET /api/v1/threads/${CREATED.slug}`]: reply(200, CREATED),
    [`GET ${repliesOf(77)}`]: reply(200, { total: 0, items: [] }),
    [`GET ${repliesOf(42)}`]: reply(200, { total: 0, items: [] }),
    [GET_THREAD]: reply(200, makeThreadDetail()),
    ...extra,
  }
}

const body = () => document.body
const form = (wrapper: VueWrapper) => wrapper.find('form[data-testid="thread-form"]')
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function editorOf(wrapper: VueWrapper): Editor {
  return (wrapper.findComponent(RichTextEditor).vm as unknown as { editor: Editor }).editor
}

async function typeBody(wrapper: VueWrapper, text: string) {
  editorOf(wrapper).chain().focus('end').insertContent(text).run()
  await flushPromises()
}

async function addTag(wrapper: VueWrapper, name: string) {
  const input = wrapper.find<HTMLInputElement>(`input[aria-label="${t('thread.form.tags')}"]`)
  await input.setValue(name)
  await input.trigger('keydown', { key: 'Enter' })
  await flushPromises()
}

async function fillRequired(wrapper: VueWrapper, title = 'My question') {
  await field(body(), t('thread.form.title')).setValue(title)
  await openSelect(wrapper, t('thread.form.category'))
  await enterOption('Early warning')
  await typeBody(wrapper, 'Which channel reaches residents faster?')
}

async function submit(wrapper: VueWrapper) {
  await form(wrapper).trigger('submit')
  await flushPromises()
}

describe('ThreadEditorView access', () => {
  it('sends anonymous visitors to the login page', async () => {
    mockApi(routes(null))
    const { router } = await mountApp('/forum/new')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.next).toBe('/forum/new')
  })

  it('shows unverified users the banner and no form', async () => {
    mockApi(routes(makeUser({ is_verified: false })))
    const { wrapper } = await mountApp('/forum/new')
    expect(wrapper.text()).toContain(t('auth.unverified.title'))
    expect(wrapper.text()).toContain(t('thread.form.unverified'))
    expect(form(wrapper).exists()).toBe(false)
  })

  it('refuses to edit somebody else’s thread', async () => {
    mockApi(routes(makeUser({ id: 99 })))
    const { wrapper } = await mountApp(`/forum/t/${SLUG}/edit`)
    expect(wrapper.text()).toContain(t('thread.form.forbidden'))
    expect(form(wrapper).exists()).toBe(false)
  })
})

describe('ThreadEditorView create', () => {
  it('has a focusable h1 and the labelled fields', async () => {
    mockApi(routes())
    const { wrapper } = await mountApp('/forum/new')
    const h1 = wrapper.find('main h1')
    expect(h1.text()).toBe(t('thread.form.titleNew'))
    expect(h1.attributes('tabindex')).toBe('-1')
    expect(field(body(), t('thread.form.title')).exists()).toBe(true)
    expect(document.querySelector('[role="textbox"][aria-labelledby]')).not.toBeNull()
    expect(wrapper.text()).toContain(t('editor.counter', { count: 0, max: 50000 }))
  })

  it('submits the payload and goes to the new thread', async () => {
    const fetchMock = mockApi(routes(makeUser(), { [MEASURES]: kbReply(measurePage(3, 0, 10)) }))
    const { wrapper, router } = await mountApp('/forum/new')
    await fillRequired(wrapper)
    await addTag(wrapper, 'sirens')
    await field(body(), t('editor.kb.search')).setValue('warning')
    await wait(400)
    await flushPromises()
    buttonIn(body(), t('editor.kb.addItem', { title: 'Measure 2' })).click()
    await flushPromises()

    await submit(wrapper)
    const [call] = callsTo(fetchMock, CREATE_THREAD)
    expect(call!.body).toEqual({
      title: 'My question',
      category_id: 22,
      locale: 'en',
      body_html: '<p>Which channel reaches residents faster?</p>',
      tags: ['sirens'],
      knowbase_links: [{ kb_type: 'measure', kb_id: 2 }],
    })
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/forum/t/my-question'))
  })

  it('validates the required fields before sending', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountApp('/forum/new')
    await submit(wrapper)
    expect(callsTo(fetchMock, CREATE_THREAD)).toHaveLength(0)
    expect(wrapper.text()).toContain(t('editor.form.errors.titleRequired'))
    expect(wrapper.text()).toContain(t('editor.form.errors.categoryRequired'))
    expect(wrapper.text()).toContain(t('thread.form.errors.bodyRequired'))
  })

  it('shows the review note to untrusted authors only', async () => {
    mockApi(routes())
    let { wrapper } = await mountApp('/forum/new')
    expect(wrapper.find('[data-testid="untrusted-note"]').text()).toContain(
      t('thread.form.untrustedNote'),
    )
    expect(t('thread.form.untrustedNote')).toBe(
      'Your first discussion will be reviewed by an admin before it is published.',
    )
    unmountAll()

    mockApi(routes(makeUser({ is_trusted: true })))
    ;({ wrapper } = await mountApp('/forum/new'))
    expect(wrapper.find('[data-testid="untrusted-note"]').exists()).toBe(false)
  })

  it('maps a server 422 on title to the title field', async () => {
    mockApi(
      routes(makeUser(), {
        [CREATE_THREAD]: replyError(422, 'validation.failed', { title: 'string_too_long' }),
      }),
    )
    const { wrapper, router } = await mountApp('/forum/new')
    await fillRequired(wrapper)
    await submit(wrapper)
    expect(router.currentRoute.value.path).toBe('/forum/new')
    expect(wrapper.text()).toContain(t('errors.fields.string_too_long'))
    expect(field(body(), t('thread.form.title')).attributes('aria-invalid')).toBe('true')
  })

  it('shows a request-level error such as an admin-only category', async () => {
    mockApi(routes(makeUser(), { [CREATE_THREAD]: replyError(403, 'threads.category_admin_only') }))
    const { wrapper } = await mountApp('/forum/new')
    await fillRequired(wrapper)
    await submit(wrapper)
    expect(wrapper.find('[data-testid="form-error"]').text()).toContain(
      t('errors.api.threads.category_admin_only'),
    )
  })

  it('hides admin-only forum categories from members and offers them to admins', async () => {
    mockApi(routes())
    let { wrapper } = await mountApp('/forum/new')
    await openSelect(wrapper, t('thread.form.category'))
    let options = Array.from(document.querySelectorAll('[role="option"]'), (o) =>
      o.textContent?.trim(),
    )
    expect(options).toEqual(['General discussion', 'Early warning', 'Nature-based solutions'])
    unmountAll()

    mockApi(routes(makeUser({ role: 'admin' })))
    ;({ wrapper } = await mountApp('/forum/new'))
    await openSelect(wrapper, t('thread.form.category'))
    options = Array.from(document.querySelectorAll('[role="option"]'), (o) => o.textContent?.trim())
    expect(options).toContain('Announcements')
  })

  it('asks before leaving with unsaved changes', async () => {
    mockApi(routes())
    const { router } = await mountApp('/forum/new')
    await field(body(), t('thread.form.title')).setValue('Half-written')
    await router.push('/about')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/forum/new')
    const box = dialog()
    expect(box.textContent).toContain(t('thread.form.leave.title'))
    buttonIn(box, t('thread.form.leave.stay')).click()
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/forum/new')

    await router.push('/about')
    await flushPromises()
    buttonIn(dialog(), t('thread.form.leave.confirm')).click()
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/about'))
  })

  it('leaves without asking when nothing changed', async () => {
    mockApi(routes())
    const { router } = await mountApp('/forum/new')
    await router.push('/about')
    expect(router.currentRoute.value.path).toBe('/about')
  })

  it('autosaves a draft and offers to restore or discard it', async () => {
    mockApi(routes())
    let { wrapper } = await mountApp('/forum/new')
    await field(body(), t('thread.form.title')).setValue('Draft question')
    await wait(DRAFT_SAVE_DELAY_MS + 50)
    unmountAll()

    mockApi(routes())
    ;({ wrapper } = await mountApp('/forum/new'))
    let prompt = wrapper.find('[data-testid="draft-prompt"]')
    expect(prompt.text()).toContain(t('thread.form.draft.found'))
    buttonIn(prompt.element as HTMLElement, t('editor.form.draft.restore')).click()
    await flushPromises()
    expect(field(body(), t('thread.form.title')).element.value).toBe('Draft question')
    await wait(DRAFT_SAVE_DELAY_MS + 50)
    unmountAll()

    mockApi(routes())
    ;({ wrapper } = await mountApp('/forum/new'))
    prompt = wrapper.find('[data-testid="draft-prompt"]')
    buttonIn(prompt.element as HTMLElement, t('editor.form.draft.discard')).click()
    await flushPromises()
    unmountAll()

    mockApi(routes())
    ;({ wrapper } = await mountApp('/forum/new'))
    expect(wrapper.find('[data-testid="draft-prompt"]').exists()).toBe(false)
  })

  it('does not share drafts with the post editor', async () => {
    mockApi(routes())
    await mountApp('/forum/new')
    await field(body(), t('thread.form.title')).setValue('Forum draft')
    await wait(DRAFT_SAVE_DELAY_MS + 50)
    const keys = Object.keys(sessionStorage)
    expect(keys).toEqual(['thread-draft:/forum/new'])
  })
})

describe('ThreadEditorView edit', () => {
  const author = () => makeUser({ id: 11 })

  it('prefills the form from GET /threads/{slug}', async () => {
    mockApi(routes(author()))
    const { wrapper } = await mountApp(`/forum/t/${SLUG}/edit`)
    expect(wrapper.find('main h1').text()).toBe(t('thread.form.titleEdit'))
    expect(field(body(), t('thread.form.title')).element.value).toBe(
      'Sirens or SMS for flood warnings?',
    )
    expect(editorOf(wrapper).getHTML()).toContain('faster')
    expect(wrapper.text()).toContain('Early Warning Systems')
    expect(wrapper.find('[data-testid="untrusted-note"]').exists()).toBe(false)
  })

  it('sends only the changed fields and returns to the thread', async () => {
    const updated = makeThreadDetail({ title: 'Sirens, SMS or cell broadcast?' })
    const fetchMock = mockApi(routes(author(), { [PATCH_THREAD]: reply(200, updated) }))
    const { wrapper, router } = await mountApp(`/forum/t/${SLUG}/edit`)
    await field(body(), t('thread.form.title')).setValue('Sirens, SMS or cell broadcast?')
    await submit(wrapper)
    expect(callsTo(fetchMock, PATCH_THREAD)[0]!.body).toEqual({
      title: 'Sirens, SMS or cell broadcast?',
    })
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe(`/forum/t/${SLUG}`))
  })

  it('an admin may edit any thread', async () => {
    mockApi(routes(makeUser({ id: 99, role: 'admin' })))
    const { wrapper } = await mountApp(`/forum/t/${SLUG}/edit`)
    expect(form(wrapper).exists()).toBe(true)
  })

  it('shows not-found content for an unknown thread', async () => {
    mockApi(routes(author(), { [GET_THREAD]: replyError(404, 'threads.not_found') }))
    const { wrapper } = await mountApp(`/forum/t/${SLUG}/edit`)
    expect(wrapper.find('main h1').text()).toBe(t('thread.notFound'))
  })
})

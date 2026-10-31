import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import type { Editor } from '@tiptap/vue-3'

import RichTextEditor from '@/components/editor/RichTextEditor.vue'
import ThreadDetailView from '@/views/ThreadDetailView.vue'
import i18n from '@/i18n'
import type { UserMe } from '@/services/auth'
import type { ThreadDetail } from '@/services/threads'
import { callsTo, makeUser, mockApi, reply, replyError, type Handler } from './helpers/api'
import { buttonIn, dialog } from './helpers/editor'
import { AUTHOR } from './helpers/blog'
import { OTHER, makeReply, makeThreadDetail, repliesOf, replyUrl } from './helpers/forum'
import { mountApp, mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'
const SLUG = 'sirens-or-sms'
const GET_THREAD = `GET /api/v1/threads/${SLUG}`
const LIST_REPLIES = `GET ${repliesOf(42)}`
const POST_REPLY = `POST ${repliesOf(42)}`
const DELETE_THREAD = 'DELETE /api/v1/threads/42'

const REPLIES = {
  total: 2,
  items: [
    makeReply(1, {
      children: [makeReply(3, { parent_reply_id: 1, body_html: '<p>A child reply</p>' })],
    }),
    makeReply(2),
  ],
}

afterEach(() => {
  vi.useRealTimers()
  unmountAll()
})

function routes(
  thread: Partial<ThreadDetail> | Handler = {},
  user: UserMe | null = null,
  extra: Record<string, Handler> = {},
) {
  return {
    [GET_THREAD]: typeof thread === 'function' ? thread : reply(200, makeThreadDetail(thread)),
    [LIST_REPLIES]: reply(200, REPLIES),
    ...(user ? { [ME]: reply(200, user) } : {}),
    ...extra,
  }
}

const mountThread = () => mountWithApp(ThreadDetailView, { path: `/forum/t/${SLUG}` })
const button = (text: string) =>
  Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === text)
const topLevel = (wrapper: VueWrapper) =>
  wrapper.findAll('[data-testid="reply-list"] > [data-testid="reply"]')

function editors(wrapper: VueWrapper): Editor[] {
  return wrapper
    .findAllComponents(RichTextEditor)
    .map((c) => (c.vm as unknown as { editor: Editor }).editor)
}

async function typeInto(editor: Editor, text: string) {
  editor.chain().focus('end').insertContent(text).run()
  await flushPromises()
}

describe('ThreadDetailView', () => {
  it('renders title, category, author, body, tags and KNOWBASE links', async () => {
    mockApi(routes())
    const { wrapper } = await mountThread()
    expect(wrapper.find('h1').text()).toBe('Sirens or SMS for flood warnings?')
    expect(wrapper.find('h1').attributes('tabindex')).toBe('-1')
    expect(wrapper.find('a[href="/forum/c/early-warning"]').text()).toBe('Early warning')
    const author = wrapper.find('[data-testid="thread-author"]')
    expect(author.find('a').attributes('href')).toBe('/u/11')
    expect(author.text()).toContain('University of Western Macedonia')
    const body = wrapper.find('[data-testid="thread-body"]')
    expect(body.html()).toContain('<strong>faster</strong>')
    expect(wrapper.find('a[href="/forum?tag=nbs"]').exists()).toBe(true)
    const kb = wrapper.findAll('[data-testid="kb-link-card"]')
    expect(kb).toHaveLength(1)
    expect(kb[0]!.find('a').attributes('href')).toBe('/knowbase/measures/2')
    expect(wrapper.find('[data-testid="post-status"]').exists()).toBe(false)
    expect(wrapper.find('a[href="/forum"]').exists()).toBe(true)
  })

  it.each([true, false])(
    'links the author name to the profile only when it exists (has_profile %s)',
    async (hasProfile) => {
      mockApi(routes({ author: { ...AUTHOR, has_profile: hasProfile } }))
      const { wrapper } = await mountThread()
      const author = wrapper.find('[data-testid="thread-author"]')
      expect(author.text()).toContain(AUTHOR.display_name)
      expect(author.find('a[href="/u/11"]').exists()).toBe(hasProfile)
      expect(author.text()).toContain(AUTHOR.organisation.name)
    },
  )

  it('shows pinned and locked badges', async () => {
    mockApi(routes({ is_pinned: true, is_locked: true }))
    const { wrapper } = await mountThread()
    expect(wrapper.find('[data-testid="thread-pinned"]').text()).toBe(t('thread.pinned'))
    expect(wrapper.find('[data-testid="thread-locked"]').text()).toContain(t('thread.locked'))
  })

  it('explains a pending thread to its author and loads no replies', async () => {
    const fetchMock = mockApi(
      routes({ status: 'pending', published_at: null }, makeUser({ id: 11 })),
    )
    const { wrapper } = await mountThread()
    expect(wrapper.find('[data-testid="post-status"]').text()).toBe(t('post.status.pending'))
    expect(wrapper.find('[data-testid="status-hint"]').text()).toContain(
      t('thread.statusHint.pending'),
    )
    expect(t('thread.statusHint.pending')).toContain('Waiting for approval')
    expect(callsTo(fetchMock, LIST_REPLIES)).toHaveLength(0)
  })

  it('lets the author of a rejected thread read the note and resubmit it', async () => {
    const fetchMock = mockApi(
      routes(
        { status: 'hidden', hidden_reason: 'rejected', published_at: null, moderation_note: 'Too vague' },
        makeUser({ id: 11 }),
        {
          'POST /api/v1/moderation/thread/42/resubmit': reply(200, {
            content_type: 'thread',
            id: 42,
            status: 'pending',
            hidden_reason: null,
            published_at: null,
            deleted_at: null,
            author_trusted: false,
          }),
        },
      ),
    )
    // The whole app, for the toast.
    const { wrapper } = await mountApp(`/forum/t/${SLUG}`)
    const hint = () => wrapper.find('[data-testid="status-hint"]')
    expect(hint().find('[data-testid="moderation-note"]').text()).toContain('Too vague')
    expect(wrapper.find(`a[href="/forum/t/${SLUG}/edit"]`).exists()).toBe(true)

    await hint().find('[data-testid="resubmit"]').trigger('click')
    await flushPromises()

    expect(callsTo(fetchMock, 'POST /api/v1/moderation/thread/42/resubmit')).toHaveLength(1)
    expect(hint().text()).toContain(t('thread.statusHint.pending'))
    expect(hint().find('[data-testid="resubmit"]').exists()).toBe(false)
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain(t('status.banner.resubmitted')),
    )
  })

  it('offers report buttons on the thread and on replies by others, not on own replies', async () => {
    const replies = {
      total: 2,
      items: [makeReply(1, { author: { ...OTHER, id: 99 } }), makeReply(2)],
    }
    mockApi(routes({}, makeUser({ id: 99 }), { [LIST_REPLIES]: reply(200, replies) }))
    const { wrapper } = await mountThread()
    expect(
      wrapper.find('article header [data-testid="report-button"]').attributes('aria-label'),
    ).toBe(t('report.title.thread'))
    const [own, other] = topLevel(wrapper)
    expect(own!.find('[data-testid="report-button"]').exists()).toBe(false)
    expect(
      other!
        .find('[data-testid="reply-actions"] [data-testid="report-button"]')
        .attributes('aria-label'),
    ).toBe(t('report.title.reply'))
  })

  it('offers no report button on the thread to its author', async () => {
    mockApi(routes({}, makeUser({ id: 11 })))
    const { wrapper } = await mountThread()
    expect(wrapper.find('article header [data-testid="report-button"]').exists()).toBe(false)
  })

  it('lists the replies as a tree, children one level in', async () => {
    mockApi(routes())
    const { wrapper } = await mountThread()
    expect(topLevel(wrapper)).toHaveLength(2)
    const children = topLevel(wrapper)[0]!.find('[data-testid="reply-children"]')
    expect(children.text()).toContain('A child reply')
  })

  it('a verified member posts a reply and sees it in the list', async () => {
    const created = makeReply(10, {
      author: { ...OTHER, id: 1, display_name: 'Maria' },
      body_html: '<p>SMS, in our pilot.</p>',
    })
    const fetchMock = mockApi(routes({}, makeUser(), { [POST_REPLY]: reply(201, created) }))
    const { wrapper } = await mountThread()
    const form = wrapper.find('[data-testid="reply-form"]')
    expect(form.exists()).toBe(true)
    const [bottom] = editors(wrapper)
    await typeInto(bottom!, 'SMS, in our pilot.')
    await form.find('form').trigger('submit')
    await flushPromises()
    const [call] = callsTo(fetchMock, POST_REPLY)
    expect(call!.body).toEqual({ body_html: '<p>SMS, in our pilot.</p>' })
    expect(topLevel(wrapper)).toHaveLength(3)
    expect(topLevel(wrapper)[2]!.text()).toContain('SMS, in our pilot.')
    // The form is emptied for the next reply.
    expect(bottom!.getHTML()).toBe('<p></p>')
  })

  it('a nested reply posts parent_reply_id and appears under its parent', async () => {
    const created = makeReply(11, {
      parent_reply_id: 1,
      author: { ...OTHER, id: 1, display_name: 'Maria' },
      body_html: '<p>Agreed.</p>',
    })
    const fetchMock = mockApi(routes({}, makeUser(), { [POST_REPLY]: reply(201, created) }))
    const { wrapper } = await mountThread()
    const first = topLevel(wrapper)[0]!
    await first
      .findAll('button')
      .find((b) => b.text() === t('reply.reply'))!
      .trigger('click')
    await flushPromises()
    const inline = first.find('[data-testid="reply-form"]')
    expect(inline.exists()).toBe(true)
    const editor = editors(wrapper).find((e) => first.element.contains(e.view.dom))!
    await typeInto(editor, 'Agreed.')
    await inline.find('form').trigger('submit')
    await flushPromises()
    expect(callsTo(fetchMock, POST_REPLY)[0]!.body).toEqual({
      body_html: '<p>Agreed.</p>',
      parent_reply_id: 1,
    })
    const children = topLevel(wrapper)[0]!.find('[data-testid="reply-children"]')
    expect(children.text()).toContain('Agreed.')
    expect(topLevel(wrapper)[0]!.find('[data-testid="reply-form"]').exists()).toBe(false)
  })

  it('shows the server error when a reply cannot be posted', async () => {
    mockApi(
      routes({}, makeUser(), {
        [POST_REPLY]: replyError(422, 'validation.failed', { body_html: 'empty' }),
      }),
    )
    const { wrapper } = await mountThread()
    const [bottom] = editors(wrapper)
    await typeInto(bottom!, 'x')
    await wrapper.find('[data-testid="reply-form"] form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('[data-testid="reply-form"]').text()).toContain(t('reply.errors.empty'))
    expect(topLevel(wrapper)).toHaveLength(2)
  })

  it('a locked thread disables replying and shows a notice', async () => {
    mockApi(routes({ is_locked: true }, makeUser()))
    const { wrapper } = await mountThread()
    expect(wrapper.find('[data-testid="reply-form"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="locked-notice"]').text()).toContain(t('reply.lockedNotice'))
    expect(wrapper.findAll('button').some((b) => b.text() === t('reply.reply'))).toBe(false)
  })

  it('asks anonymous visitors to log in and unverified members to verify', async () => {
    mockApi(routes())
    let { wrapper } = await mountThread()
    expect(wrapper.find('[data-testid="reply-form"]').exists()).toBe(false)
    const login = wrapper.find(`a[href="/login?next=/forum/t/${SLUG}"]`)
    expect(login.text()).toBe(t('reply.loginToReply'))
    unmountAll()

    mockApi(routes({}, makeUser({ is_verified: false })))
    ;({ wrapper } = await mountThread())
    expect(wrapper.find('[data-testid="reply-form"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="unverified-notice"]').text()).toContain(
      t('reply.unverified'),
    )
  })

  it('the author edits a reply inline and deletes one after a modal', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-30T10:00:00Z'))
    const fetchMock = mockApi(
      routes({}, makeUser({ id: OTHER.id }), {
        [`PATCH ${replyUrl(2)}`]: reply(
          200,
          makeReply(2, { body_html: '<p>Reply 2 changed</p>', is_edited: true }),
        ),
        [`DELETE ${replyUrl(2)}`]: reply(204),
      }),
    )
    const { wrapper } = await mountThread()
    const second = () => topLevel(wrapper)[1]!
    await second()
      .findAll('button')
      .find((b) => b.text() === t('reply.edit'))!
      .trigger('click')
    await flushPromises()
    const editor = editors(wrapper).find((e) => second().element.contains(e.view.dom))!
    expect(editor.getHTML()).toContain('Reply 2')
    await typeInto(editor, ' changed')
    await second().find('[data-testid="reply-form"] form').trigger('submit')
    await flushPromises()
    expect(callsTo(fetchMock, `PATCH ${replyUrl(2)}`)[0]!.body).toEqual({
      body_html: '<p>Reply 2 changed</p>',
    })
    expect(second().find('[data-testid="reply-body"]').text()).toBe('Reply 2 changed')
    expect(second().find('[data-testid="reply-edited"]').exists()).toBe(true)

    await second()
      .findAll('button')
      .find((b) => b.text() === t('reply.delete'))!
      .trigger('click')
    await flushPromises()
    buttonIn(dialog(), t('reply.deleteConfirm.confirm')).click()
    await flushPromises()
    expect(callsTo(fetchMock, `DELETE ${replyUrl(2)}`)).toHaveLength(1)
    expect(topLevel(wrapper)).toHaveLength(1)
  })

  it('admins pin and lock; the badges follow the response', async () => {
    const fetchMock = mockApi(
      routes({}, makeUser({ id: 99, role: 'admin' }), {
        'POST /api/v1/threads/42/pin': reply(200, makeThreadDetail({ is_pinned: true })),
        'POST /api/v1/threads/42/lock': reply(
          200,
          makeThreadDetail({ is_pinned: true, is_locked: true }),
        ),
        'POST /api/v1/threads/42/unpin': reply(200, makeThreadDetail({ is_locked: true })),
      }),
    )
    const { wrapper } = await mountThread()
    expect(wrapper.find('[data-testid="thread-pinned"]').exists()).toBe(false)
    button(t('thread.admin.pin'))!.click()
    await flushPromises()
    expect(callsTo(fetchMock, 'POST /api/v1/threads/42/pin')).toHaveLength(1)
    expect(wrapper.find('[data-testid="thread-pinned"]').exists()).toBe(true)

    button(t('thread.admin.lock'))!.click()
    await flushPromises()
    expect(callsTo(fetchMock, 'POST /api/v1/threads/42/lock')).toHaveLength(1)
    expect(wrapper.find('[data-testid="thread-locked"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="locked-notice"]').exists()).toBe(true)
    expect(button(t('thread.admin.unlock'))).toBeDefined()

    button(t('thread.admin.unpin'))!.click()
    await flushPromises()
    expect(callsTo(fetchMock, 'POST /api/v1/threads/42/unpin')).toHaveLength(1)
    expect(wrapper.find('[data-testid="thread-pinned"]').exists()).toBe(false)
  })

  it('hides the admin controls from members', async () => {
    mockApi(routes({}, makeUser({ id: 11 })))
    await mountThread()
    expect(button(t('thread.admin.pin'))).toBeUndefined()
    expect(button(t('thread.admin.lock'))).toBeUndefined()
  })

  it.each([
    ['the author', makeUser({ id: 11 })],
    ['an admin', makeUser({ id: 99, role: 'admin' })],
  ])('shows Edit and Delete of the thread to %s', async (_who, user) => {
    mockApi(routes({}, user))
    const { wrapper } = await mountThread()
    expect(wrapper.find(`a[href="/forum/t/${SLUG}/edit"]`).text()).toBe(t('thread.edit'))
    expect(button(t('thread.delete'))).toBeDefined()
  })

  it('shows an admin a deleted thread with its deletion date and the moderation menu, without Edit or Delete', async () => {
    mockApi(
      routes(
        { status: 'deleted', deleted_at: '2026-10-30T15:00:00Z' },
        makeUser({ id: 99, role: 'admin' }),
      ),
    )
    const { wrapper } = await mountThread()
    expect(wrapper.find('[data-testid="post-status"]').text()).toBe(t('post.status.deleted'))
    const deletedAt = wrapper.find('[data-testid="deleted-at"]')
    expect(deletedAt.attributes('datetime')).toBe('2026-10-30T15:00:00Z')
    expect(deletedAt.text()).not.toBe('')
    expect(button(t('moderation.menu'))).toBeDefined()
    expect(wrapper.find(`a[href="/forum/t/${SLUG}/edit"]`).exists()).toBe(false)
    const header = wrapper.find('article > header')
    const headerButtons = header.findAll('button').map((b) => b.text())
    expect(headerButtons).not.toContain(t('thread.delete'))
    // Pin and lock answer 404 for a deleted thread, so they are not offered either.
    expect(headerButtons).not.toContain(t('thread.admin.pin'))
    expect(headerButtons).not.toContain(t('thread.admin.lock'))
  })

  it('deletes the thread after a modal, then goes to /forum', async () => {
    const fetchMock = mockApi(routes({}, makeUser({ id: 11 }), { [DELETE_THREAD]: reply(204) }))
    const { router } = await mountThread()
    button(t('thread.delete'))!.click()
    await flushPromises()
    buttonIn(dialog(), t('thread.deleteConfirm.confirm')).click()
    await flushPromises()
    expect(callsTo(fetchMock, DELETE_THREAD)).toHaveLength(1)
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/forum'))
  })

  it('shows not-found content for a 404', async () => {
    mockApi(routes(replyError(404, 'threads.not_found')))
    const { wrapper } = await mountThread()
    expect(wrapper.find('h1').text()).toBe(t('thread.notFound'))
  })

  it('shows an error with retry for other failures', async () => {
    mockApi(routes(replyError(500, 'server.error')))
    const { wrapper } = await mountThread()
    expect(wrapper.find('[role="alert"]').text()).toContain(t('thread.loadError'))
  })

  it('sets the page title and description', async () => {
    mockApi(routes())
    await mountApp(`/forum/t/${SLUG}`)
    await vi.waitFor(() =>
      expect(document.title).toBe(`Sirens or SMS for flood warnings? · ${t('app.title')}`),
    )
    expect(document.head.querySelector('meta[name="description"]')?.getAttribute('content')).toBe(
      'Which channel reaches residents faster?',
    )
  })

  it('emits DiscussionForumPosting JSON-LD', async () => {
    mockApi(routes())
    await mountApp(`/forum/t/${SLUG}`)
    const script = () => document.head.querySelector('script[type="application/ld+json"]')
    await vi.waitFor(() =>
      expect(JSON.parse(script()!.textContent!)['@type']).toBe('DiscussionForumPosting'),
    )
    const data = JSON.parse(script()!.textContent!)
    expect(data.headline).toBe('Sirens or SMS for flood warnings?')
    expect(data.url).toBe(`${window.location.origin}/forum/t/${SLUG}`)
    expect(data.author['@type']).toBe('Person')
    expect(data.inLanguage).toBe('en')
    expect(data.interactionStatistic.userInteractionCount).toBe(3)
  })
})

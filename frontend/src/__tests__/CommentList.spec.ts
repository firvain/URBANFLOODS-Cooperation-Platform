import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import type { Editor } from '@tiptap/vue-3'

import CommentList from '@/components/comments/CommentList.vue'
import RichTextEditor from '@/components/editor/RichTextEditor.vue'
import i18n from '@/i18n'
import type { UserMe } from '@/services/auth'
import {
  callsTo,
  deferred,
  jsonResponse,
  makeUser,
  mockApi,
  reply,
  replyError,
  type Handler,
} from './helpers/api'
import { commentPage, commentUrl, commentsOf, makeComment } from './helpers/comments'
import { buttonIn, dialog } from './helpers/editor'
import { OTHER } from './helpers/forum'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'
const LIST = `GET ${commentsOf(42)}`
const CREATE = `POST ${commentsOf(42)}`
const PATH = '/blog/rain-gardens-in-kozani'

afterEach(() => {
  vi.useRealTimers()
  unmountAll()
})

const COMMENTS = {
  total: 2,
  items: [
    makeComment(1, { body_html: '<p>First!</p><script>window.hacked = 1</script>' }),
    makeComment(2, {
      created_at: '2026-10-30T09:00:00Z',
      body_html: '<p>Second</p>',
      is_edited: true,
    }),
  ],
}

function routes(
  list: Handler = reply(200, COMMENTS),
  user: UserMe | null = null,
  extra: Record<string, Handler> = {},
) {
  return { [LIST]: list, ...(user ? { [ME]: reply(200, user) } : {}), ...extra }
}

const mountList = (props: Record<string, unknown> = {}) =>
  mountWithApp(CommentList, {
    path: PATH,
    props: { postId: 42, count: 2, status: 'published', ...props },
  })

const items = (wrapper: VueWrapper) => wrapper.findAll('[data-testid="comment"]')
const heading = (wrapper: VueWrapper) => wrapper.find('h2').text()
const buttonOf = (root: VueWrapper | ReturnType<VueWrapper['find']>, text: string) =>
  root.findAll('button').find((b) => b.text() === text)

function editor(wrapper: VueWrapper, within?: Element): Editor {
  const editors = wrapper
    .findAllComponents(RichTextEditor)
    .map((c) => (c.vm as unknown as { editor: Editor }).editor)
  return within ? editors.find((e) => within.contains(e.view.dom))! : editors.at(-1)!
}

async function typeInto(target: Editor, text: string) {
  target.chain().focus('end').insertContent(text).run()
  await flushPromises()
}

describe('CommentList', () => {
  it('loads the first page and lists comments oldest first with author, time and "edited"', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-30T10:00:00Z'))
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountList()
    const query = new URL(callsTo(fetchMock, LIST)[0]!.url, 'http://x').searchParams
    expect(query.get('skip')).toBe('0')
    expect(query.get('limit')).toBe('50')
    expect(heading(wrapper)).toBe(t('comments.title', 2))
    expect(items(wrapper)).toHaveLength(2)
    const [first, second] = items(wrapper)
    expect(first!.text()).toContain('First!')
    expect(second!.text()).toContain('Second')
    expect(first!.find('[data-testid="comment-author"]').text()).toContain(OTHER.display_name)
    expect(first!.find('[data-testid="comment-author"] a').attributes('href')).toBe('/u/12')
    expect(first!.find('time').text()).toBe('2 hours ago')
    expect(first!.find('time').attributes('datetime')).toBe('2026-10-30T08:00:00Z')
    expect(first!.find('[data-testid="comment-edited"]').exists()).toBe(false)
    expect(second!.find('[data-testid="comment-edited"]').text()).toBe(t('comments.edited'))
    expect(first!.find('[data-testid="comment-body"] script').exists()).toBe(false)
  })

  it('says when there are no comments yet', async () => {
    mockApi(routes(reply(200, { total: 0, items: [] })))
    const { wrapper } = await mountList({ count: 0 })
    expect(wrapper.text()).toContain(t('comments.empty'))
    expect(heading(wrapper)).toBe(t('comments.title', 0))
  })

  it('shows an error with retry when the list cannot be loaded', async () => {
    mockApi(routes(replyError(500, 'server.error')))
    const { wrapper } = await mountList()
    expect(wrapper.find('[role="alert"]').text()).toContain(t('comments.loadError'))
  })

  it('posts a comment, shows it at once and replaces it with the server copy', async () => {
    const pending = deferred<Response>()
    const fetchMock = mockApi(
      routes(reply(200, COMMENTS), makeUser(), {
        [CREATE]: () => pending.promise,
      }),
    )
    const { wrapper } = await mountList()
    const form = wrapper.find('[data-testid="comment-form"]')
    expect(form.exists()).toBe(true)
    const input = editor(wrapper, form.element)
    await typeInto(input, 'Great work.')
    await form.find('form').trigger('submit')
    await flushPromises()

    expect(callsTo(fetchMock, CREATE)[0]!.body).toEqual({ body_html: '<p>Great work.</p>' })
    // Optimistic: listed before the server answers, marked as sending.
    expect(items(wrapper)).toHaveLength(3)
    expect(items(wrapper)[2]!.text()).toContain('Great work.')
    expect(items(wrapper)[2]!.find('[data-testid="comment-sending"]').exists()).toBe(true)
    expect(heading(wrapper)).toBe(t('comments.title', 3))

    pending.resolve(
      jsonResponse(
        makeComment(10, {
          author: { ...OTHER, id: 1, display_name: 'Maria' },
          body_html: '<p>Great work (server copy).</p>',
        }),
        201,
      ),
    )
    await flushPromises()
    expect(items(wrapper)).toHaveLength(3)
    const saved = items(wrapper)[2]!
    expect(saved.attributes('id')).toBe('comment-10')
    expect(saved.text()).toContain('Great work (server copy).')
    expect(saved.find('[data-testid="comment-sending"]').exists()).toBe(false)
    expect(heading(wrapper)).toBe(t('comments.title', 3))
    // The form is emptied for the next comment.
    expect(input.getHTML()).toBe('<p></p>')
  })

  it('removes the optimistic comment again and shows the error when posting fails', async () => {
    mockApi(
      routes(reply(200, COMMENTS), makeUser(), {
        [CREATE]: replyError(422, 'validation.failed', { body_html: 'too_long' }),
      }),
    )
    const { wrapper } = await mountList()
    await typeInto(editor(wrapper), 'Too much')
    await wrapper.find('[data-testid="comment-form"] form').trigger('submit')
    await flushPromises()
    expect(items(wrapper)).toHaveLength(2)
    expect(wrapper.find('[data-testid="comment-form"] [role="alert"]').text()).toBe(
      t('comments.errors.tooLong'),
    )
    expect(heading(wrapper)).toBe(t('comments.title', 2))
  })

  it('maps "post not published" from the server', async () => {
    mockApi(
      routes(reply(200, COMMENTS), makeUser(), {
        [CREATE]: replyError(422, 'comments.post_not_published'),
      }),
    )
    const { wrapper } = await mountList()
    await typeInto(editor(wrapper), 'Hello')
    await wrapper.find('[data-testid="comment-form"] form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('[data-testid="comment-form"]').text()).toContain(
      t('errors.api.comments.post_not_published'),
    )
  })

  it('refuses an empty comment without calling the server', async () => {
    const fetchMock = mockApi(routes(reply(200, COMMENTS), makeUser()))
    const { wrapper } = await mountList()
    await wrapper.find('[data-testid="comment-form"] form').trigger('submit')
    await flushPromises()
    expect(callsTo(fetchMock, CREATE)).toHaveLength(0)
    expect(wrapper.find('[data-testid="comment-form"]').text()).toContain(
      t('comments.errors.empty'),
    )
  })

  it('shows Edit and Delete on the viewer’s own comments, and to admins on all', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-30T10:00:00Z'))
    mockApi(routes(reply(200, COMMENTS), makeUser({ id: 99 })))
    let { wrapper } = await mountList()
    // Another member may only report.
    expect(
      wrapper
        .findAll('[data-testid="comment-actions"]')
        .map((row) => row.findAll('button').map((button) => button.text())),
    ).toEqual([[t('report.button')], [t('report.button')]])
    unmountAll()

    mockApi(routes(reply(200, COMMENTS), makeUser({ id: OTHER.id })))
    ;({ wrapper } = await mountList())
    let actions = wrapper.findAll('[data-testid="comment-actions"]')
    expect(actions).toHaveLength(2)
    expect(actions[0]!.text()).toContain(t('comments.edit'))
    expect(actions[0]!.text()).toContain(t('comments.delete'))
    unmountAll()

    vi.setSystemTime(new Date('2026-11-05T10:00:00Z'))
    mockApi(routes(reply(200, COMMENTS), makeUser({ id: 99, role: 'admin' })))
    ;({ wrapper } = await mountList())
    actions = wrapper.findAll('[data-testid="comment-actions"]')
    expect(actions).toHaveLength(2)
    expect(actions[0]!.text()).toContain(t('comments.edit'))
  })

  it('hides Edit from the author after 24 hours but keeps Delete', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-02T10:00:00Z'))
    mockApi(routes(reply(200, COMMENTS), makeUser({ id: OTHER.id })))
    const { wrapper } = await mountList()
    const first = wrapper.findAll('[data-testid="comment-actions"]')[0]!
    expect(first.text()).not.toContain(t('comments.edit'))
    expect(first.text()).toContain(t('comments.delete'))
  })

  it('the author edits a comment inline', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-30T10:00:00Z'))
    const fetchMock = mockApi(
      routes(reply(200, COMMENTS), makeUser({ id: OTHER.id }), {
        [`PATCH ${commentUrl(2)}`]: reply(
          200,
          makeComment(2, { body_html: '<p>Second, revised</p>', is_edited: true }),
        ),
      }),
    )
    const { wrapper } = await mountList()
    const second = () => items(wrapper)[1]!
    await buttonOf(second(), t('comments.edit'))!.trigger('click')
    await flushPromises()
    const input = editor(wrapper, second().element)
    expect(input.getHTML()).toContain('Second')
    await typeInto(input, ', revised')
    await second().find('[data-testid="comment-form"] form').trigger('submit')
    await flushPromises()
    expect(callsTo(fetchMock, `PATCH ${commentUrl(2)}`)[0]!.body).toEqual({
      body_html: '<p>Second, revised</p>',
    })
    expect(second().find('[data-testid="comment-form"]').exists()).toBe(false)
    expect(second().find('[data-testid="comment-body"]').text()).toBe('Second, revised')
    expect(second().find('[data-testid="comment-edited"]').exists()).toBe(true)
  })

  it('deletes a comment after confirming in a modal; it simply disappears', async () => {
    const fetchMock = mockApi(
      routes(reply(200, COMMENTS), makeUser({ id: OTHER.id }), {
        [`DELETE ${commentUrl(1)}`]: reply(204),
      }),
    )
    const { wrapper } = await mountList()
    await buttonOf(items(wrapper)[0]!, t('comments.delete'))!.trigger('click')
    await flushPromises()
    const box = dialog()
    expect(box.textContent).toContain(t('comments.deleteConfirm.title'))
    expect(callsTo(fetchMock, `DELETE ${commentUrl(1)}`)).toHaveLength(0)
    buttonIn(box, t('comments.deleteConfirm.confirm')).click()
    await flushPromises()
    expect(callsTo(fetchMock, `DELETE ${commentUrl(1)}`)).toHaveLength(1)
    expect(items(wrapper)).toHaveLength(1)
    expect(wrapper.text()).not.toContain('First!')
    expect(heading(wrapper)).toBe(t('comments.title', 1))
  })

  it('keeps the modal open with the error when deleting fails', async () => {
    mockApi(
      routes(reply(200, COMMENTS), makeUser({ id: OTHER.id }), {
        [`DELETE ${commentUrl(1)}`]: replyError(403, 'comments.forbidden'),
      }),
    )
    const { wrapper } = await mountList()
    await buttonOf(items(wrapper)[0]!, t('comments.delete'))!.trigger('click')
    await flushPromises()
    buttonIn(dialog(), t('comments.deleteConfirm.confirm')).click()
    await flushPromises()
    expect(dialog().textContent).toContain(t('errors.api.comments.forbidden'))
    expect(items(wrapper)).toHaveLength(2)
  })

  it('offers a report button on comments by others, not on own comments', async () => {
    const list = {
      total: 2,
      items: [makeComment(1, { author: { ...OTHER, id: 1 } }), makeComment(2)],
    }
    mockApi(routes(reply(200, list), makeUser()))
    const { wrapper } = await mountList()
    const [own, other] = items(wrapper)
    expect(own!.find('[data-testid="report-button"]').exists()).toBe(false)
    expect(
      other!
        .find('[data-testid="comment-actions"] [data-testid="report-button"]')
        .attributes('aria-label'),
    ).toBe(t('report.title.comment'))
  })

  it('asks anonymous visitors to log in', async () => {
    mockApi(routes())
    const { wrapper } = await mountList()
    expect(wrapper.find('[data-testid="comment-form"]').exists()).toBe(false)
    const login = wrapper.find(`a[href="/login?next=${PATH}"]`)
    expect(login.text()).toBe(t('comments.loginToComment'))
    expect(t('comments.loginToComment')).toBe('Log in to comment')
  })

  it('tells unverified members to verify their email', async () => {
    mockApi(routes(reply(200, COMMENTS), makeUser({ is_verified: false })))
    const { wrapper } = await mountList()
    expect(wrapper.find('[data-testid="comment-form"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="comment-unverified"]').text()).toContain(
      t('comments.unverified'),
    )
  })

  it('a pending post loads no comments and has no form, only a note', async () => {
    const fetchMock = mockApi(routes(reply(200, COMMENTS), makeUser()))
    const { wrapper } = await mountList({ status: 'pending', count: 0 })
    expect(callsTo(fetchMock, LIST)).toHaveLength(0)
    expect(wrapper.find('[data-testid="comment-form"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="comments-closed"]').text()).toContain(
      t('comments.notPublished'),
    )
  })

  it('a hidden post lists its comments but takes no new ones', async () => {
    mockApi(routes(reply(200, COMMENTS), makeUser({ id: 11 })))
    const { wrapper } = await mountList({ status: 'hidden' })
    expect(items(wrapper)).toHaveLength(2)
    expect(wrapper.find('[data-testid="comment-form"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="comments-closed"]').text()).toContain(t('comments.closed'))
  })

  it('"Load more comments" fetches the next page with skip', async () => {
    const fetchMock = mockApi(
      routes((request) => {
        const skip = Number(new URL(request.url, 'http://x').searchParams.get('skip'))
        return jsonResponse(commentPage(55, skip))
      }),
    )
    const { wrapper } = await mountList({ count: 55 })
    expect(items(wrapper)).toHaveLength(50)
    await buttonOf(wrapper, t('comments.loadMore'))!.trigger('click')
    await flushPromises()
    const last = new URL(callsTo(fetchMock, LIST).at(-1)!.url, 'http://x').searchParams
    expect(last.get('skip')).toBe('50')
    expect(last.get('limit')).toBe('50')
    expect(items(wrapper)).toHaveLength(55)
    expect(items(wrapper)[50]!.text()).toContain('Comment 51')
    expect(buttonOf(wrapper, t('comments.loadMore'))).toBeUndefined()
  })
})

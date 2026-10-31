import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, type VueWrapper } from '@vue/test-utils'

import ReplyList from '@/components/forum/ReplyList.vue'
import i18n from '@/i18n'
import type { UserMe } from '@/services/auth'
import { callsTo, jsonResponse, makeUser, mockApi, reply, type Handler } from './helpers/api'
import { buttonIn, dialog } from './helpers/editor'
import { OTHER, makeReply, repliesOf, replyUrl } from './helpers/forum'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'
const LIST = `GET ${repliesOf(42)}`

afterEach(() => {
  vi.useRealTimers()
  unmountAll()
})

const TREE = {
  total: 2,
  items: [
    makeReply(1, {
      children: [
        makeReply(3, { parent_reply_id: 1, body_html: '<p>First child</p>' }),
        makeReply(4, { parent_reply_id: 1, body_html: '<p>Second child</p>', is_edited: true }),
      ],
    }),
    makeReply(2, { body_html: '<p>Top two</p><script>window.hacked = 1</script>' }),
  ],
}

function routes(list: Handler = reply(200, TREE), user: UserMe | null = null) {
  return { [LIST]: list, ...(user ? { [ME]: reply(200, user) } : {}) }
}

const mountList = (props: Record<string, unknown> = {}) =>
  mountWithApp(ReplyList, { path: '/forum/t/sirens-or-sms', props: { threadId: 42, ...props } })

const items = (wrapper: VueWrapper) => wrapper.findAll('[data-testid="reply"]')
const topLevel = (wrapper: VueWrapper) =>
  wrapper.findAll('[data-testid="reply-list"] > [data-testid="reply"]')

describe('ReplyList', () => {
  it('loads the first page and renders top-level replies with their children one level in', async () => {
    const fetchMock = mockApi(routes())
    const { wrapper } = await mountList()
    const query = new URL(callsTo(fetchMock, LIST)[0]!.url, 'http://x').searchParams
    expect(query.get('skip')).toBe('0')
    expect(query.get('limit')).toBe('20')
    expect(topLevel(wrapper)).toHaveLength(2)
    expect(items(wrapper)).toHaveLength(4)
    const children = topLevel(wrapper)[0]!.find('[data-testid="reply-children"]')
    expect(children.exists()).toBe(true)
    expect(children.findAll('[data-testid="reply"]')).toHaveLength(2)
    expect(children.text()).toContain('First child')
    // Never deeper than one level.
    expect(children.find('[data-testid="reply-children"]').exists()).toBe(false)
    expect(topLevel(wrapper)[1]!.find('[data-testid="reply-children"]').exists()).toBe(false)
  })

  it('shows author, relative time with the full date, the edited marker and a safe body', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-30T10:00:00Z'))
    mockApi(routes())
    const { wrapper } = await mountList()
    const first = items(wrapper)[0]!
    expect(first.find('[data-testid="reply-author"]').text()).toContain(OTHER.display_name)
    expect(first.find('time').text()).toBe('2 hours ago')
    expect(first.find('time').attributes('datetime')).toBe('2026-10-30T08:00:00Z')
    expect(first.find('time').attributes('title')).toBeTruthy()
    const edited = items(wrapper)[2]!
    expect(edited.find('[data-testid="reply-edited"]').text()).toBe(t('reply.edited'))
    // `find` on a top-level item also searches its children: look at its own article only.
    expect(items(wrapper)[0]!.find('article').find('[data-testid="reply-edited"]').exists()).toBe(
      false,
    )
    const body = topLevel(wrapper)[1]!.find('[data-testid="reply-body"]')
    expect(body.text()).toContain('Top two')
    expect(body.find('script').exists()).toBe(false)
  })

  it('renders a deleted parent as a muted "[deleted]" placeholder, its children intact', async () => {
    mockApi(
      routes(
        reply(200, {
          total: 1,
          items: [
            makeReply(1, {
              status: 'deleted',
              body_html: '',
              author: null,
              children: [makeReply(5, { parent_reply_id: 1, body_html: '<p>Still here</p>' })],
            }),
          ],
        }),
        makeUser({ role: 'admin' }),
      ),
    )
    const { wrapper } = await mountList()
    const placeholder = topLevel(wrapper)[0]!
    const deleted = placeholder.find('[data-testid="reply-deleted"]')
    expect(deleted.text()).toBe(t('reply.deleted'))
    expect(t('reply.deleted')).toBe('[deleted]')
    expect(deleted.classes()).toContain('text-muted')
    expect(placeholder.find('article').find('[data-testid="reply-author"]').exists()).toBe(false)
    // No actions on the placeholder itself, only on the surviving child.
    expect(placeholder.findAll('[data-testid="reply-actions"]')).toHaveLength(1)
    expect(placeholder.find('[data-testid="reply-children"]').text()).toContain('Still here')
  })

  it('offers "Reply" on top-level replies only, to verified users of an unlocked thread', async () => {
    mockApi(routes(reply(200, TREE), makeUser({ id: 99 })))
    let { wrapper } = await mountList()
    const replyButtons = () =>
      wrapper.findAll('button').filter((b) => b.text() === t('reply.reply'))
    expect(replyButtons()).toHaveLength(2)
    unmountAll()

    mockApi(routes(reply(200, TREE), makeUser({ id: 99 })))
    ;({ wrapper } = await mountList({ locked: true }))
    expect(replyButtons()).toHaveLength(0)
    unmountAll()

    mockApi(routes(reply(200, TREE)))
    ;({ wrapper } = await mountList())
    expect(replyButtons()).toHaveLength(0)
  })

  it('shows Edit and Delete on the viewer’s own replies only', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-30T10:00:00Z'))
    mockApi(routes(reply(200, TREE), makeUser({ id: OTHER.id })))
    let { wrapper } = await mountList()
    const actions = wrapper.findAll('[data-testid="reply-actions"]')
    expect(actions).toHaveLength(4)
    expect(actions[0]!.text()).toContain(t('reply.edit'))
    expect(actions[0]!.text()).toContain(t('reply.delete'))
    unmountAll()

    mockApi(routes(reply(200, TREE), makeUser({ id: 99 })))
    ;({ wrapper } = await mountList())
    const texts = wrapper.findAll('[data-testid="reply-actions"]').map((a) => a.text())
    for (const text of texts) {
      expect(text).not.toContain(t('reply.edit'))
      expect(text).not.toContain(t('reply.delete'))
    }
  })

  it('hides Edit from the author after 24 hours but keeps Delete', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-02T10:00:00Z'))
    mockApi(routes(reply(200, TREE), makeUser({ id: OTHER.id })))
    const { wrapper } = await mountList()
    const first = wrapper.findAll('[data-testid="reply-actions"]')[0]!
    expect(first.text()).not.toContain(t('reply.edit'))
    expect(first.text()).toContain(t('reply.delete'))
  })

  it('deletes a reply after confirming in a modal and removes it from the list', async () => {
    const fetchMock = mockApi({
      ...routes(reply(200, TREE), makeUser({ id: OTHER.id })),
      [`DELETE ${replyUrl(2)}`]: reply(204),
    })
    const { wrapper } = await mountList()
    const second = topLevel(wrapper)[1]!
    await second
      .findAll('button')
      .find((b) => b.text() === t('reply.delete'))!
      .trigger('click')
    await flushPromises()
    const box = dialog()
    expect(box.textContent).toContain(t('reply.deleteConfirm.title'))
    expect(callsTo(fetchMock, `DELETE ${replyUrl(2)}`)).toHaveLength(0)
    buttonIn(box, t('reply.deleteConfirm.confirm')).click()
    await flushPromises()
    expect(callsTo(fetchMock, `DELETE ${replyUrl(2)}`)).toHaveLength(1)
    expect(topLevel(wrapper)).toHaveLength(1)
    expect(wrapper.text()).not.toContain('Top two')
  })

  it('a deleted parent with children stays as a placeholder', async () => {
    mockApi({
      ...routes(reply(200, TREE), makeUser({ id: OTHER.id })),
      [`DELETE ${replyUrl(1)}`]: reply(204),
    })
    const { wrapper } = await mountList()
    const first = topLevel(wrapper)[0]!
    await first
      .findAll('button')
      .find((b) => b.text() === t('reply.delete'))!
      .trigger('click')
    await flushPromises()
    buttonIn(dialog(), t('reply.deleteConfirm.confirm')).click()
    await flushPromises()
    expect(topLevel(wrapper)).toHaveLength(2)
    expect(topLevel(wrapper)[0]!.find('[data-testid="reply-deleted"]').exists()).toBe(true)
    expect(topLevel(wrapper)[0]!.text()).toContain('First child')
  })

  it('"Load more replies" fetches the next page of top-level replies', async () => {
    const page = (skip: number) => ({
      total: 25,
      items: Array.from({ length: skip === 0 ? 20 : 5 }, (_, i) => makeReply(skip + i + 1)),
    })
    const fetchMock = mockApi(
      routes((request) => {
        const skip = Number(new URL(request.url, 'http://x').searchParams.get('skip'))
        return jsonResponse(page(skip))
      }),
    )
    const { wrapper } = await mountList()
    expect(topLevel(wrapper)).toHaveLength(20)
    const more = wrapper.findAll('button').find((b) => b.text() === t('reply.loadMore'))!
    await more.trigger('click')
    await flushPromises()
    const last = new URL(callsTo(fetchMock, LIST).at(-1)!.url, 'http://x').searchParams
    expect(last.get('skip')).toBe('20')
    expect(topLevel(wrapper)).toHaveLength(25)
    expect(wrapper.findAll('button').some((b) => b.text() === t('reply.loadMore'))).toBe(false)
  })

  it('says when there are no replies yet', async () => {
    mockApi(routes(reply(200, { total: 0, items: [] })))
    const { wrapper } = await mountList()
    expect(wrapper.text()).toContain(t('reply.empty'))
  })
})

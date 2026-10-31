import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import PostDetailView from '@/views/PostDetailView.vue'
import i18n from '@/i18n'
import { formatDateTime } from '@/utils/datetime'
import type { PostDetail } from '@/services/posts'
import { callsTo, makeUser, mockApi, reply, replyError, type Handler } from './helpers/api'
import { COVER, makePostDetail } from './helpers/blog'
import { commentsOf, makeComment } from './helpers/comments'
import { buttonIn, dialog } from './helpers/editor'
import { mountApp, mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const ME = 'GET /api/v1/auth/me'
const SLUG = 'rain-gardens-in-kozani'
const GET_POST = `GET /api/v1/posts/${SLUG}`
const DELETE_POST = 'DELETE /api/v1/posts/42'
const LIST_COMMENTS = `GET ${commentsOf(42)}`
const COMMENTS = {
  total: 3,
  items: [makeComment(1), makeComment(2), makeComment(3, { body_html: '<p>Third comment</p>' })],
}

afterEach(unmountAll)

function routes(post: Partial<PostDetail> | Handler = {}, extra: Record<string, Handler> = {}) {
  return {
    [GET_POST]: typeof post === 'function' ? post : reply(200, makePostDetail(post)),
    [LIST_COMMENTS]: reply(200, COMMENTS),
    ...extra,
  }
}

const mountPost = () => mountWithApp(PostDetailView, { path: `/blog/${SLUG}` })
const button = (text: string) =>
  Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === text)

describe('PostDetailView', () => {
  it('renders the title, cover, author, dates, category and tags', async () => {
    mockApi(routes())
    const { wrapper } = await mountPost()
    expect(wrapper.find('h1').text()).toBe('Rain gardens in Kozani')
    expect(wrapper.find('h1').attributes('tabindex')).toBe('-1')
    const cover = wrapper.find('[data-testid="post-cover"]')
    expect(cover.attributes('src')).toBe(COVER.url)
    expect(cover.attributes('alt')).toBe(COVER.alt_text)
    const author = wrapper.find('[data-testid="post-author"]')
    expect(author.find('a').attributes('href')).toBe('/u/11')
    expect(author.text()).toContain('Eleni Papadopoulou')
    expect(author.text()).toContain('University of Western Macedonia')
    expect(wrapper.find('time').attributes('datetime')).toBe('2026-10-20T09:00:00Z')
    expect(wrapper.find('a[href="/blog/category/best-practices"]').text()).toBe('Best practices')
    expect(wrapper.find('a[href="/blog/tag/nbs"]').exists()).toBe(true)
    expect(wrapper.find('a[href="/blog/tag/urban-drainage"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="post-status"]').exists()).toBe(false)
  })

  it('renders the body through SafeHtml with the post language, without scripts', async () => {
    mockApi(
      routes({
        locale: 'el',
        body_html: '<p>Καλημέρα <em>Κοζάνη</em></p><script>window.hacked = true</script>',
      }),
    )
    const { wrapper } = await mountPost()
    const body = wrapper.find('[data-testid="post-body"]')
    expect(body.attributes('lang')).toBe('el')
    expect(body.html()).toContain('<em>Κοζάνη</em>')
    expect(body.find('script').exists()).toBe(false)
    expect(body.html()).not.toContain('hacked')
  })

  it('links the KNOWBASE items to our KNOWBASE pages, labelled measure or document', async () => {
    mockApi(routes())
    const { wrapper } = await mountPost()
    const cards = wrapper.findAll('[data-testid="kb-link-card"]')
    expect(cards).toHaveLength(2)
    const measure = cards[0]!
    expect(measure.find('a').attributes('href')).toBe('/knowbase/measures/2')
    expect(measure.text()).toContain('Rain gardens')
    expect(measure.text()).toContain(t('post.knowbase.measure'))
    expect(cards[1]!.find('a').attributes('href')).toBe('/knowbase/documents/1')
    expect(cards[1]!.text()).toContain(t('post.knowbase.document'))
  })

  it('shows the event date and its external link', async () => {
    const at = '2026-11-20T16:00:00Z'
    mockApi(routes({ event_at: at, event_url: 'https://example.org/webinar' }))
    const { wrapper } = await mountPost()
    const event = wrapper.find('[data-testid="post-event"]')
    expect(event.text()).toContain(formatDateTime(at, 'en'))
    const link = event.find('a')
    expect(link.attributes('href')).toBe('https://example.org/webinar')
    expect(link.attributes('target')).toBe('_blank')
  })

  it('has no event block without an event', async () => {
    mockApi(routes())
    const { wrapper } = await mountPost()
    expect(wrapper.find('[data-testid="post-event"]').exists()).toBe(false)
  })

  it('shows the comments under the post: "N comments", oldest first', async () => {
    mockApi(routes())
    const { wrapper } = await mountPost()
    const section = wrapper.find('[data-testid="post-comments"]')
    expect(section.find('h2').text()).toBe(t('comments.title', 3))
    expect(t('comments.title', 3)).toBe('3 comments')
    const items = section.findAll('[data-testid="comment"]')
    expect(items).toHaveLength(3)
    expect(items[2]!.text()).toContain('Third comment')
  })

  it('offers the comment form to verified members and a login link to visitors', async () => {
    mockApi(routes({}, { [ME]: reply(200, makeUser({ id: 99 })) }))
    let { wrapper } = await mountPost()
    expect(wrapper.find('[data-testid="comment-form"]').exists()).toBe(true)
    unmountAll()

    mockApi(routes())
    ;({ wrapper } = await mountPost())
    expect(wrapper.find('[data-testid="comment-form"]').exists()).toBe(false)
    expect(wrapper.find(`a[href="/login?next=/blog/${SLUG}"]`).text()).toBe(
      t('comments.loginToComment'),
    )
  })

  it('a pending post shows a note instead of the comment form', async () => {
    const fetchMock = mockApi(
      routes(
        { status: 'pending', published_at: null, comment_count: 0 },
        { [ME]: reply(200, makeUser({ id: 11 })) },
      ),
    )
    const { wrapper } = await mountPost()
    expect(wrapper.find('[data-testid="comment-form"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="comments-closed"]').text()).toContain(
      t('comments.notPublished'),
    )
    expect(callsTo(fetchMock, LIST_COMMENTS)).toHaveLength(0)
  })

  it('explains a pending status to its author', async () => {
    mockApi(
      routes({ status: 'pending', published_at: null }, { [ME]: reply(200, makeUser({ id: 11 })) }),
    )
    const { wrapper } = await mountPost()
    expect(wrapper.find('[data-testid="post-status"]').text()).toBe(t('post.status.pending'))
    expect(wrapper.text()).toContain(t('post.statusHint.pending'))
    expect(t('post.statusHint.pending')).toContain('Waiting for approval by an admin')
  })

  it('offers a report button on the post to verified members other than the author', async () => {
    mockApi(routes({}, { [ME]: reply(200, makeUser({ id: 99 })) }))
    let { wrapper } = await mountPost()
    const header = wrapper.find('article > header')
    expect(header.find('[data-testid="report-button"]').attributes('aria-label')).toBe(
      t('report.title.post'),
    )
    unmountAll()

    mockApi(routes({}, { [ME]: reply(200, makeUser({ id: 11 })) }))
    ;({ wrapper } = await mountPost())
    expect(wrapper.find('article > header [data-testid="report-button"]').exists()).toBe(false)
  })

  it('shows the author why a hidden post is hidden, without a report button', async () => {
    mockApi(
      routes(
        { status: 'hidden', hidden_reason: 'auto_reports' },
        { [ME]: reply(200, makeUser({ id: 11 })) },
      ),
    )
    const { wrapper } = await mountPost()
    expect(wrapper.find('[data-testid="post-status"]').text()).toBe(t('post.status.hidden'))
    const hint = wrapper.find('[data-testid="status-hint"]')
    expect(hint.text()).toContain(t('post.statusHint.hidden'))
    expect(hint.text()).toContain(t('status.reason.auto_reports'))
    expect(hint.find('a[href^="mailto:"]').exists()).toBe(true)
    expect(wrapper.find('article > header [data-testid="report-button"]').exists()).toBe(false)
  })

  it('hides Edit and Delete from visitors and from other members', async () => {
    mockApi(routes())
    let { wrapper } = await mountPost()
    expect(wrapper.find(`a[href="/blog/${SLUG}/edit"]`).exists()).toBe(false)
    expect(button(t('post.delete'))).toBeUndefined()
    unmountAll()

    mockApi(routes({}, { [ME]: reply(200, makeUser({ id: 99 })) }))
    ;({ wrapper } = await mountPost())
    expect(wrapper.find(`a[href="/blog/${SLUG}/edit"]`).exists()).toBe(false)
    expect(button(t('post.delete'))).toBeUndefined()
  })

  it.each([
    ['the author', makeUser({ id: 11 })],
    ['an admin', makeUser({ id: 99, role: 'admin' })],
  ])('shows Edit and Delete to %s', async (_who, user) => {
    mockApi(routes({}, { [ME]: reply(200, user) }))
    const { wrapper } = await mountPost()
    expect(wrapper.find(`a[href="/blog/${SLUG}/edit"]`).text()).toBe(t('post.edit'))
    expect(button(t('post.delete'))).toBeDefined()
  })

  it('deletes after confirming in a dialog, then goes to /blog', async () => {
    const fetchMock = mockApi(
      routes({}, { [ME]: reply(200, makeUser({ id: 11 })), [DELETE_POST]: reply(204) }),
    )
    const { router } = await mountPost()
    button(t('post.delete'))!.click()
    await flushPromises()
    const box = dialog()
    expect(box.textContent).toContain(t('post.deleteConfirm.title'))
    expect(callsTo(fetchMock, DELETE_POST)).toHaveLength(0)
    buttonIn(box, t('post.deleteConfirm.confirm')).click()
    await flushPromises()
    expect(callsTo(fetchMock, DELETE_POST)).toHaveLength(1)
    // The blog list is a lazy route: wait for its chunk.
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/blog'))
  })

  it('cancelling the dialog does not delete', async () => {
    const fetchMock = mockApi(
      routes({}, { [ME]: reply(200, makeUser({ id: 11 })), [DELETE_POST]: reply(204) }),
    )
    const { router } = await mountPost()
    button(t('post.delete'))!.click()
    await flushPromises()
    buttonIn(dialog(), t('post.deleteConfirm.cancel')).click()
    await flushPromises()
    expect(callsTo(fetchMock, DELETE_POST)).toHaveLength(0)
    expect(router.currentRoute.value.path).toBe(`/blog/${SLUG}`)
  })

  it('shows an error in the dialog when deleting fails', async () => {
    mockApi(
      routes(
        {},
        {
          [ME]: reply(200, makeUser({ id: 11 })),
          [DELETE_POST]: replyError(403, 'posts.forbidden'),
        },
      ),
    )
    const { router } = await mountPost()
    button(t('post.delete'))!.click()
    await flushPromises()
    buttonIn(dialog(), t('post.deleteConfirm.confirm')).click()
    await flushPromises()
    expect(dialog().textContent).toContain(t('errors.api.posts.forbidden'))
    expect(router.currentRoute.value.path).toBe(`/blog/${SLUG}`)
  })

  it('shows not-found content for a 404', async () => {
    mockApi(routes(replyError(404, 'posts.not_found')))
    const { wrapper } = await mountPost()
    expect(wrapper.find('h1').text()).toBe(t('post.notFound'))
    expect(wrapper.find('a[href="/blog"]').exists()).toBe(true)
  })

  it('shows an error with retry for other failures', async () => {
    mockApi(routes(replyError(500, 'server.error')))
    const { wrapper } = await mountPost()
    expect(wrapper.find('[role="alert"]').text()).toContain(t('post.loadError'))
  })

  it('sets the page title, description and og:image', async () => {
    mockApi(routes())
    await mountApp(`/blog/${SLUG}`)
    await vi.waitFor(() =>
      expect(document.title).toBe(`Rain gardens in Kozani · ${t('app.title')}`),
    )
    expect(document.head.querySelector('meta[name="description"]')?.getAttribute('content')).toBe(
      'How Kozani reduces surface runoff with rain gardens.',
    )
    expect(
      document.head.querySelector('meta[property="og:image"]')?.getAttribute('content'),
    ).toContain(COVER.url)
  })

  it('leaves the post title behind when navigating away', async () => {
    mockApi(routes())
    const { router } = await mountApp(`/blog/${SLUG}`)
    await vi.waitFor(() => expect(document.title).toContain('Rain gardens in Kozani'))
    await router.push('/about')
    await flushPromises()
    await vi.waitFor(() => expect(document.title).toBe(`${t('nav.about')} · ${t('app.title')}`))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(document.title).toBe(`${t('nav.about')} · ${t('app.title')}`)
  })

  it('emits Article JSON-LD with headline, dates, author, language and the CC BY 4.0 licence', async () => {
    mockApi(routes({ locale: 'el' }))
    await mountApp(`/blog/${SLUG}`)
    const script = () => document.head.querySelector('script[type="application/ld+json"]')
    await vi.waitFor(() => expect(JSON.parse(script()!.textContent!)['@type']).toBe('Article'))
    const data = JSON.parse(script()!.textContent!)
    expect(data['@context']).toBe('https://schema.org')
    expect(data.headline).toBe('Rain gardens in Kozani')
    expect(data.datePublished).toBe('2026-10-20T09:00:00Z')
    expect(data.author).toEqual({ '@type': 'Person', name: 'Eleni Papadopoulou' })
    expect(data.inLanguage).toBe('el')
    expect(data.license).toBe('https://creativecommons.org/licenses/by/4.0/')
    expect(data.url).toBe(`${window.location.origin}/blog/${SLUG}`)
    expect(document.head.querySelectorAll('script[type="application/ld+json"]')).toHaveLength(1)
    expect(document.head.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe(
      `${window.location.origin}/blog/${SLUG}`,
    )
  })
})

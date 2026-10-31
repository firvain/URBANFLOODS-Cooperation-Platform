import { afterEach, describe, expect, it } from 'vitest'

import PostCard from '@/components/blog/PostCard.vue'
import i18n from '@/i18n'
import { formatDate, formatDateTime } from '@/utils/datetime'
import type { PostSummary } from '@/services/posts'
import { COVER, TAG_DRAINAGE, TAG_NBS, makePost } from './helpers/blog'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t

afterEach(unmountAll)

const mountCard = async (post: PostSummary) =>
  (await mountWithApp(PostCard, { props: { post } })).wrapper

describe('PostCard', () => {
  it('shows the cover thumbnail with its alt text', async () => {
    const card = await mountCard(makePost(1, { cover: COVER }))
    const img = card.find('img')
    expect(img.attributes('src')).toBe(COVER.thumb_url)
    expect(img.attributes('alt')).toBe(COVER.alt_text)
  })

  it('falls back to the full image without a thumbnail, and shows no image without a cover', async () => {
    const card = await mountCard(makePost(1, { cover: { ...COVER, thumb_url: null } }))
    expect(card.find('img').attributes('src')).toBe(COVER.url)
    unmountAll()
    const bare = await mountCard(makePost(2))
    expect(bare.find('img').exists()).toBe(false)
  })

  it('links the title to the post and the category badge to the category', async () => {
    const card = await mountCard(makePost(3))
    expect(card.find('h2 a').attributes('href')).toBe('/blog/post-3')
    expect(card.find('h2 a').text()).toBe('Post 3')
    const category = card.find('[data-testid="post-category"]')
    expect(category.text()).toBe('Best practices')
    expect(category.attributes('href')).toBe('/blog/category/best-practices')
  })

  it('shows the excerpt, the author with organisation, the date and the tags', async () => {
    const card = await mountCard(makePost(4, { tags: [TAG_NBS, TAG_DRAINAGE] }))
    expect(card.text()).toContain('Excerpt of post 4.')
    const author = card.find('[data-testid="post-author"]')
    expect(author.text()).toContain('Eleni Papadopoulou')
    expect(author.text()).toContain('University of Western Macedonia')
    const time = card.find('time')
    expect(time.attributes('datetime')).toBe('2026-10-20T09:00:00Z')
    expect(time.text()).toBe(formatDate('2026-10-20T09:00:00Z', 'en'))
    const tags = card.findAll('[data-testid="post-tag"]')
    expect(tags.map((a) => a.attributes('href'))).toEqual([
      '/blog/tag/nbs',
      '/blog/tag/urban-drainage',
    ])
    expect(tags[1]!.text()).toContain('urban drainage')
  })

  it('shows the comment count', async () => {
    const card = await mountCard(makePost(5, { comment_count: 3 }))
    expect(card.find('[data-testid="post-comments"]').text()).toBe(t('post.comments', 3))
  })

  it('shows an event badge with the event date only for events', async () => {
    const plain = await mountCard(makePost(6))
    expect(plain.find('[data-testid="post-event"]').exists()).toBe(false)
    unmountAll()
    const at = '2026-11-20T16:00:00Z'
    const card = await mountCard(makePost(7, { event_at: at }))
    const badge = card.find('[data-testid="post-event"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain(formatDateTime(at, 'en'))
  })

  it('shows a status badge only for posts that are not published', async () => {
    const published = await mountCard(makePost(8))
    expect(published.find('[data-testid="post-status"]').exists()).toBe(false)
    unmountAll()
    const pending = await mountCard(makePost(9, { status: 'pending', published_at: null }))
    expect(pending.find('[data-testid="post-status"]').text()).toBe(t('post.status.pending'))
    // Without a publication date the card shows the creation date.
    expect(pending.find('time').attributes('datetime')).toBe('2026-10-20T09:00:00Z')
  })

  it('renders without an author (deleted account)', async () => {
    const card = await mountCard(makePost(10, { author: null }))
    expect(card.find('[data-testid="post-author"]').text()).toContain(t('post.formerMember'))
  })
})

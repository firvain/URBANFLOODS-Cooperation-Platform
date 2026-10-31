import { afterEach, describe, expect, it, vi } from 'vitest'

import ThreadCard from '@/components/forum/ThreadCard.vue'
import i18n from '@/i18n'
import type { ThreadSummary } from '@/services/threads'
import { formatDateTime, formatRelative } from '@/utils/datetime'
import { makeThread } from './helpers/forum'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t

afterEach(() => {
  vi.useRealTimers()
  unmountAll()
})

const mountCard = async (thread: ThreadSummary) =>
  (await mountWithApp(ThreadCard, { props: { thread } })).wrapper

describe('ThreadCard', () => {
  it('links the title to the thread and the category badge to the forum category', async () => {
    const card = await mountCard(makeThread(3))
    expect(card.find('h2 a').attributes('href')).toBe('/forum/t/thread-3')
    expect(card.find('h2 a').text()).toBe('Thread 3')
    const category = card.find('[data-testid="thread-category"]')
    expect(category.text()).toBe('Early warning')
    expect(category.attributes('href')).toBe('/forum/c/early-warning')
    expect(card.text()).toContain('Excerpt of thread 3.')
  })

  it('shows the author with the organisation and the reply count', async () => {
    const card = await mountCard(makeThread(1, { reply_count: 5 }))
    const author = card.find('[data-testid="thread-author"]')
    expect(author.text()).toContain('Eleni Papadopoulou')
    expect(author.text()).toContain('University of Western Macedonia')
    expect(card.find('[data-testid="thread-replies"]').text()).toBe(t('thread.replies', 5))
    expect(t('thread.replies', 1)).toBe('1 reply')
  })

  it('shows "last activity" as relative time with the full date in title and datetime', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-30T12:00:00Z'))
    const card = await mountCard(makeThread(1, { last_activity_at: '2026-10-30T09:00:00Z' }))
    const activity = card.find('[data-testid="thread-activity"]')
    expect(activity.text()).toContain(t('thread.lastActivity'))
    const time = activity.find('time')
    expect(time.attributes('datetime')).toBe('2026-10-30T09:00:00Z')
    expect(time.attributes('title')).toBe(formatDateTime('2026-10-30T09:00:00Z', 'en'))
    expect(time.text()).toBe('3 hours ago')
  })

  it('marks pinned threads with an icon and a "Pinned" label, locked ones with a lock', async () => {
    const card = await mountCard(makeThread(1, { is_pinned: true, is_locked: true }))
    const pinned = card.find('[data-testid="thread-pinned"]')
    expect(pinned.text()).toBe(t('thread.pinned'))
    expect(pinned.find('[data-icon="i-lucide-pin"]').exists()).toBe(true)
    const locked = card.find('[data-testid="thread-locked"]')
    expect(locked.find('[data-icon="i-lucide-lock"]').exists()).toBe(true)
    expect(locked.text()).toContain(t('thread.locked'))
  })

  it('has no pinned or locked marks on an ordinary thread', async () => {
    const card = await mountCard(makeThread(1))
    expect(card.find('[data-testid="thread-pinned"]').exists()).toBe(false)
    expect(card.find('[data-testid="thread-locked"]').exists()).toBe(false)
  })

  it('shows a status badge only for threads that are not published', async () => {
    let card = await mountCard(makeThread(1, { status: 'pending', published_at: null }))
    expect(card.find('[data-testid="post-status"]').text()).toBe(t('post.status.pending'))
    unmountAll()
    card = await mountCard(makeThread(2))
    expect(card.find('[data-testid="post-status"]').exists()).toBe(false)
  })

  it('names a deleted account "Former member"', async () => {
    const card = await mountCard(makeThread(1, { author: null }))
    expect(card.find('[data-testid="thread-author"]').text()).toContain(t('post.formerMember'))
  })
})

describe('formatRelative', () => {
  const now = new Date('2026-10-30T12:00:00Z').getTime()
  it.each([
    ['2026-10-30T11:59:40Z', 'now'],
    ['2026-10-30T11:55:00Z', '5 minutes ago'],
    ['2026-10-30T09:00:00Z', '3 hours ago'],
    ['2026-10-29T12:00:00Z', 'yesterday'],
    ['2026-10-25T12:00:00Z', '5 days ago'],
    ['2026-10-16T12:00:00Z', '2 weeks ago'],
    ['2026-07-30T12:00:00Z', '3 months ago'],
    ['2024-10-30T12:00:00Z', '2 years ago'],
  ])('%s → %s', (iso, expected) => {
    expect(formatRelative(iso, 'en', now)).toBe(expected)
  })

  it('uses the UI locale', () => {
    expect(formatRelative('2026-10-30T09:00:00Z', 'el', now)).toBe('πριν από 3 ώρες')
  })
})

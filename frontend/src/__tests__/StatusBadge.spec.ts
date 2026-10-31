import { afterEach, describe, expect, it } from 'vitest'

import StatusBadge from '@/components/moderation/StatusBadge.vue'
import i18n from '@/i18n'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t

afterEach(unmountAll)

const mountBadge = (props: Record<string, unknown>) => mountWithApp(StatusBadge, { props })
const badge = () => document.querySelector<HTMLElement>('[data-testid="post-status"]')

describe('StatusBadge', () => {
  it('renders nothing for published content', async () => {
    await mountBadge({ status: 'published' })
    expect(badge()).toBeNull()
  })

  it.each([
    ['pending', 'Pending approval'],
    ['hidden', 'Hidden'],
    ['deleted', 'Deleted'],
  ] as const)('labels %s content and explains it in the title', async (status, label) => {
    await mountBadge({ status })
    expect(badge()!.textContent?.trim()).toBe(label)
    expect(badge()!.textContent?.trim()).toBe(t(`post.status.${status}`))
    expect(badge()!.getAttribute('title')).toBe(t(`status.title.${status}`))
  })

  it.each(['auto_reports', 'admin', 'rejected'] as const)(
    'adds the %s reason to the title of hidden content',
    async (reason) => {
      await mountBadge({ status: 'hidden', hiddenReason: reason })
      const title = badge()!.getAttribute('title')!
      expect(title).toContain(t('status.title.hidden'))
      expect(title).toContain(t(`status.reason.${reason}`))
    },
  )

  it('ignores a reason on content that is not hidden', async () => {
    await mountBadge({ status: 'pending', hiddenReason: 'admin' })
    expect(badge()!.getAttribute('title')).toBe(t('status.title.pending'))
  })
})

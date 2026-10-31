import { afterEach, describe, expect, it } from 'vitest'

import PendingBanner from '@/components/moderation/PendingBanner.vue'
import i18n from '@/i18n'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t
const EMAIL = ['louta', 'uowm.gr'].join('@')

afterEach(unmountAll)

const mountBanner = (props: Record<string, unknown>) =>
  mountWithApp(PendingBanner, { props: { kind: 'post', forAuthor: true, ...props } })
const banner = () => document.querySelector<HTMLElement>('[data-testid="status-hint"]')
const text = () => banner()!.textContent ?? ''

describe('PendingBanner', () => {
  it('renders nothing for published content', async () => {
    await mountBanner({ status: 'published' })
    expect(banner()).toBeNull()
  })

  it('tells the author a pending post waits for approval and what happens after', async () => {
    await mountBanner({ status: 'pending' })
    expect(text()).toContain(t('post.statusHint.pending'))
    expect(t('post.statusHint.pending')).toBe(
      'Waiting for approval by an admin. Only you and the admins can see this post until it is approved.',
    )
    expect(text()).toContain(t('status.banner.firstApproval'))
  })

  it('uses the discussion wording for a pending thread', async () => {
    await mountBanner({ kind: 'thread', status: 'pending' })
    expect(text()).toContain(t('thread.statusHint.pending'))
    expect(t('thread.statusHint.pending')).toBe(
      'Waiting for approval by an admin. Only you and the admins can see this discussion until it is approved.',
    )
  })

  it('does not promise an admin viewer anything about later posts', async () => {
    await mountBanner({ status: 'pending', forAuthor: false })
    expect(text()).toContain(t('post.statusHint.pending'))
    expect(text()).not.toContain(t('status.banner.firstApproval'))
  })

  it('tells the author a rejected post was not approved, with a contact address', async () => {
    await mountBanner({ status: 'hidden', hiddenReason: 'rejected' })
    expect(text()).toContain(t('post.statusHint.rejected'))
    const mail = banner()!.querySelector<HTMLAnchorElement>('a[href^="mailto:"]')
    expect(mail?.getAttribute('href')).toBe(`mailto:${EMAIL}`)
    expect(mail?.textContent?.trim()).toBe(EMAIL)
  })

  it('shows the author the admin note on a rejected post as text, with a Resubmit button', async () => {
    const { wrapper } = await mountBanner({
      status: 'hidden',
      hiddenReason: 'rejected',
      moderationNote: '<b>Add</b> sources',
    })
    expect(text()).toContain(t('status.banner.reason'))
    const note = banner()!.querySelector('[data-testid="moderation-note"]')!
    expect(note.textContent).toContain('<b>Add</b> sources')
    expect(note.querySelector('b')).toBeNull()
    const resubmit = banner()!.querySelector<HTMLButtonElement>('[data-testid="resubmit"]')!
    expect(resubmit.textContent?.trim()).toBe(t('status.banner.resubmit'))
    resubmit.click()
    expect(wrapper.emitted('resubmit')).toHaveLength(1)
  })

  it('offers Resubmit on a rejected post without a note', async () => {
    await mountBanner({ status: 'hidden', hiddenReason: 'rejected' })
    expect(banner()!.querySelector('[data-testid="moderation-note"]')).toBeNull()
    expect(text()).not.toContain(t('status.banner.reason'))
    expect(banner()!.querySelector('[data-testid="resubmit"]')).not.toBeNull()
  })

  it('shows an admin viewer the note but no Resubmit button', async () => {
    await mountBanner({
      status: 'hidden',
      hiddenReason: 'rejected',
      moderationNote: 'Too short',
      forAuthor: false,
    })
    expect(banner()!.querySelector('[data-testid="moderation-note"]')?.textContent).toContain(
      'Too short',
    )
    expect(banner()!.querySelector('[data-testid="resubmit"]')).toBeNull()
  })

  it('disables Resubmit while it is being sent', async () => {
    await mountBanner({ status: 'hidden', hiddenReason: 'rejected', resubmitting: true })
    const resubmit = banner()!.querySelector<HTMLButtonElement>('[data-testid="resubmit"]')!
    expect(resubmit.disabled).toBe(true)
  })

  it('keeps the note on a resubmitted post waiting for approval, without Resubmit', async () => {
    await mountBanner({ status: 'pending', moderationNote: 'Add a map' })
    expect(text()).toContain(t('post.statusHint.pending'))
    expect(text()).toContain(t('status.banner.reason'))
    expect(banner()!.querySelector('[data-testid="moderation-note"]')?.textContent).toContain(
      'Add a map',
    )
    expect(banner()!.querySelector('[data-testid="resubmit"]')).toBeNull()
  })

  it('offers no Resubmit on content hidden by an admin', async () => {
    await mountBanner({ status: 'hidden', hiddenReason: 'admin', moderationNote: 'x' })
    expect(banner()!.querySelector('[data-testid="resubmit"]')).toBeNull()
    expect(banner()!.querySelector('[data-testid="moderation-note"]')).toBeNull()
  })

  it.each(['admin', 'auto_reports'] as const)(
    'explains a thread hidden for reason %s to its author',
    async (reason) => {
      await mountBanner({ kind: 'thread', status: 'hidden', hiddenReason: reason })
      expect(text()).toContain(t('thread.statusHint.hidden'))
      expect(text()).toContain(t(`status.reason.${reason}`))
      expect(banner()!.querySelector('a[href^="mailto:"]')).not.toBeNull()
    },
  )

  it('shows no contact address to an admin viewer', async () => {
    await mountBanner({ status: 'hidden', hiddenReason: 'auto_reports', forAuthor: false })
    expect(text()).toContain(t('status.reason.auto_reports'))
    expect(banner()!.querySelector('a[href^="mailto:"]')).toBeNull()
  })

  it('says a post was deleted', async () => {
    await mountBanner({ status: 'deleted' })
    expect(text()).toContain(t('post.statusHint.deleted'))
  })
})

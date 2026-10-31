import { afterEach, describe, expect, it } from 'vitest'

import { reply } from './helpers/api'
import { makeLogEntry, mountAdmin, page, tableRows } from './helpers/admin'
import { unmountAll } from './helpers/mount'

const LOG = 'GET /api/v1/moderation/log/'

afterEach(unmountAll)

describe('Admin audit log targets', () => {
  it('links a post or discussion that still exists to its page', async () => {
    await mountAdmin('/admin/log', {
      [LOG]: reply(
        200,
        page([
          makeLogEntry({ target_path: '/forum/t/sandbags-or-barriers' }),
          makeLogEntry({
            id: 502,
            target_type: 'post',
            target_id: 3,
            target_path: '/blog/green-roofs',
          }),
        ]),
      ),
    })
    const [thread, post] = tableRows('log')
    const threadLink = thread!.querySelector('a[href="/forum/t/sandbags-or-barriers"]')
    expect(threadLink?.textContent?.trim()).toBe('thread #12')
    expect(post!.querySelector('a[href="/blog/green-roofs"]')?.textContent?.trim()).toBe('post #3')
  })

  it('shows plain text when there is no page to link', async () => {
    await mountAdmin('/admin/log', {
      [LOG]: reply(
        200,
        page([
          makeLogEntry({ target_type: 'post', target_id: 3, target_path: null }),
          makeLogEntry({ id: 502, target_type: 'user', target_id: 9 }),
        ]),
      ),
    })
    const [purged, user] = tableRows('log')
    expect(purged!.textContent).toContain('post #3')
    expect(purged!.querySelector('a[href^="/blog/"]')).toBeNull()
    expect(user!.textContent).toContain('user #9')
    expect(user!.querySelector('a[href^="/blog/"], a[href^="/forum/"]')).toBeNull()
  })
})

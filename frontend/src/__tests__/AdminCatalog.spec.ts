import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import i18n from '@/i18n'
import { callsTo, reply, replyError } from './helpers/api'
import {
  click,
  findButton,
  makeCategory,
  makeLogEntry,
  makeTag,
  mountAdmin,
  openSelectInDialog,
  page,
  queryOf,
  tableRows,
} from './helpers/admin'
import { buttonIn, dialog, field } from './helpers/editor'
import { clickOption } from './helpers/select'
import { unmountAll } from './helpers/mount'

const t = i18n.global.t
const CATEGORIES = 'GET /api/v1/categories/'
const TAGS = 'GET /api/v1/tags/'
const LOG = 'GET /api/v1/moderation/log/'
const c = (key: string, params: Record<string, unknown> = {}) =>
  t(`admin.categories.${key}`, params)

afterEach(unmountAll)

describe('Admin categories', () => {
  const NBS = makeCategory()
  const OLD = makeCategory({
    id: 4,
    kind: 'forum',
    name: 'Old forum',
    slug: 'old',
    is_archived: true,
  })

  it('lists categories with kind, order, posts and archived state', async () => {
    await mountAdmin('/admin/categories', { [CATEGORIES]: reply(200, page([NBS, OLD])) })
    const rows = tableRows('categories')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.textContent).toContain('Nature-based solutions')
    expect(rows[0]!.textContent).toContain(c('kinds.blog'))
    expect(rows[1]!.textContent).toContain(c('archived'))
    expect(findButton(c('unarchiveLabel', { name: 'Old forum' }))).toBeDefined()
  })

  it('validates the new category before sending it', async () => {
    const { fetchMock } = await mountAdmin('/admin/categories', {
      [CATEGORIES]: reply(200, page([NBS])),
    })
    await click(c('create'))
    const box = dialog()
    await field(box, c('slug')).setValue('Bad Slug!')
    buttonIn(box, c('save')).click()
    await flushPromises()
    expect(callsTo(fetchMock, 'POST /api/v1/categories/')).toHaveLength(0)
    expect(dialog().textContent).toContain(c('validation.nameRequired', { min: 2 }))
    expect(dialog().textContent).toContain(c('validation.slugInvalid'))
  })

  it('creates a category and lists it', async () => {
    const created = makeCategory({
      id: 9,
      name: 'Early warning',
      slug: 'early-warning',
      sort_order: 3,
    })
    const { fetchMock } = await mountAdmin('/admin/categories', {
      [CATEGORIES]: reply(200, page([NBS])),
      'POST /api/v1/categories/': reply(201, created),
    })
    await click(c('create'))
    const box = dialog()
    await field(box, c('name')).setValue('Early warning')
    await field(box, c('sortOrder')).setValue('3')
    buttonIn(box, c('save')).click()
    await flushPromises()
    expect(callsTo(fetchMock, 'POST /api/v1/categories/')[0]!.body).toEqual({
      kind: 'blog',
      name: 'Early warning',
      slug: null,
      description: null,
      sort_order: 3,
      admin_only: false,
    })
    expect(tableRows('categories')).toHaveLength(2)
  })

  it('shows a slug conflict from the server', async () => {
    await mountAdmin('/admin/categories', {
      [CATEGORIES]: reply(200, page([NBS])),
      'POST /api/v1/categories/': replyError(409, 'categories.slug_taken'),
    })
    await click(c('create'))
    await field(dialog(), c('name')).setValue('NBS again')
    buttonIn(dialog(), c('save')).click()
    await flushPromises()
    expect(dialog().textContent).toContain(t('admin.errors.categories.slug_taken'))
  })

  it('edits only the changed fields', async () => {
    const { fetchMock } = await mountAdmin('/admin/categories', {
      [CATEGORIES]: reply(200, page([NBS])),
      'PATCH /api/v1/categories/2': reply(200, { ...NBS, name: 'NBS' }),
    })
    await click(c('editLabel', { name: NBS.name }))
    await field(dialog(), c('name')).setValue('NBS')
    buttonIn(dialog(), c('save')).click()
    await flushPromises()
    expect(callsTo(fetchMock, 'PATCH /api/v1/categories/2')[0]!.body).toEqual({ name: 'NBS' })
  })

  it('archives after confirming', async () => {
    const { fetchMock } = await mountAdmin('/admin/categories', {
      [CATEGORIES]: reply(200, page([NBS])),
      'DELETE /api/v1/categories/2': reply(204),
    })
    await click(c('archiveLabel', { name: NBS.name }))
    expect(dialog().textContent).toContain(c('archiveTitle', { name: NBS.name }))
    buttonIn(dialog(), c('archive')).click()
    await flushPromises()
    expect(callsTo(fetchMock, 'DELETE /api/v1/categories/2')).toHaveLength(1)
    expect(tableRows('categories')[0]!.textContent).toContain(c('archived'))
  })
})

describe('Admin tags', () => {
  const FLOODING = makeTag()
  const FLOODS = makeTag({ id: 4, name: 'floods', slug: 'floods', usage_count: 2 })
  const UNUSED = makeTag({ id: 5, name: 'misc', slug: 'misc', usage_count: 0 })

  it('lists tags by name with their usage and sends the search', async () => {
    const { fetchMock } = await mountAdmin('/admin/tags?q=flo', {
      [TAGS]: reply(200, page([FLOODING, FLOODS])),
    })
    const query = queryOf(callsTo(fetchMock, TAGS)[0]!.url)
    expect(query.get('q')).toBe('flo')
    expect(query.get('sort')).toBe('name')
    const rows = tableRows('tags')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.textContent).toContain('12')
  })

  it('merges a tag into another after confirming', async () => {
    const route = 'POST /api/v1/tags/4/merge'
    const { fetchMock } = await mountAdmin('/admin/tags', {
      [TAGS]: reply(200, page([FLOODING, FLOODS, UNUSED])),
      [route]: reply(200, { ...FLOODING, usage_count: 14 }),
    })
    await click(t('admin.tags.mergeLabel', { name: 'floods' }))
    const box = dialog()
    expect(box.textContent).toContain(t('admin.tags.mergeTitle', { name: 'floods' }))
    buttonIn(box, t('admin.tags.mergeConfirm')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)).toHaveLength(0)

    await openSelectInDialog(t('admin.tags.mergeTarget'))
    await clickOption('flooding')
    expect(dialog().textContent).toContain(
      t('admin.tags.mergeWarning', { source: 'floods', target: 'flooding', count: 2 }),
    )
    buttonIn(dialog(), t('admin.tags.mergeConfirm')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)[0]!.body).toEqual({ target_id: 3 })
    const rows = tableRows('tags')
    expect(rows.map((r) => r.textContent)).not.toEqual(
      expect.arrayContaining([expect.stringContaining('floods')]),
    )
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain(
        t('admin.tags.merged', { source: 'floods', target: 'flooding' }),
      ),
    )
  })

  it('deletes only unused tags, after confirming', async () => {
    const route = 'DELETE /api/v1/tags/5'
    const { fetchMock } = await mountAdmin('/admin/tags', {
      [TAGS]: reply(200, page([FLOODING, UNUSED])),
      [route]: reply(204),
    })
    expect(findButton(t('admin.tags.deleteLabel', { name: 'flooding' }))).toBeUndefined()
    await click(t('admin.tags.deleteLabel', { name: 'misc' }))
    buttonIn(dialog(), t('admin.tags.delete')).click()
    await flushPromises()
    expect(callsTo(fetchMock, route)).toHaveLength(1)
    expect(tableRows('tags')).toHaveLength(1)
  })
})

describe('Admin audit log', () => {
  it('shows entries with actor, target and metadata as plain key/value text', async () => {
    await mountAdmin('/admin/log', {
      [LOG]: reply(
        200,
        page([
          makeLogEntry(),
          makeLogEntry({ id: 502, actor: null, action: 'moderation.auto_hidden', metadata: {} }),
        ]),
      ),
    })
    const rows = tableRows('log')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.textContent).toContain('moderation.hide')
    expect(rows[0]!.textContent).toContain('Ada Admin')
    expect(rows[0]!.textContent).toContain('thread #12')
    const meta = rows[0]!.querySelector('dl')!
    expect(Array.from(meta.querySelectorAll('dt')).map((d) => d.textContent?.trim())).toEqual([
      'reason',
      'from',
      'to',
    ])
    expect(meta.textContent).toContain('Spam <b>link</b>')
    expect(meta.querySelector('b')).toBeNull()
    expect(rows[1]!.textContent).toContain(t('admin.common.system'))
  })

  it('a quick chip sets the action prefix in the URL and the request', async () => {
    const { fetchMock, router } = await mountAdmin('/admin/log', { [LOG]: reply(200, page([])) })
    const chip = Array.from(
      document.querySelectorAll<HTMLButtonElement>('[data-testid="action-chip"]'),
    ).find((b) => b.textContent?.trim() === 'admin.')!
    expect(chip.getAttribute('aria-pressed')).toBe('false')
    chip.click()
    await flushPromises()
    expect(router.currentRoute.value.query.action).toBe('admin.')
    expect(queryOf(callsTo(fetchMock, LOG).at(-1)!.url).get('action')).toBe('admin.')
    expect(chip.getAttribute('aria-pressed')).toBe('true')
  })

  it('takes actor, target type and page from the URL', async () => {
    const { fetchMock } = await mountAdmin('/admin/log?actor_id=4&target_type=user&page=2', {
      [LOG]: reply(200, page([makeLogEntry()], 120)),
    })
    const query = queryOf(callsTo(fetchMock, LOG)[0]!.url)
    expect(query.get('actor_id')).toBe('4')
    expect(query.get('target_type')).toBe('user')
    expect(query.get('skip')).toBe('50')
    expect(
      document.querySelector(`nav[aria-label="${t('admin.common.pagination')}"]`),
    ).not.toBeNull()
  })
})

/** Fixtures for the admin area (4g): stats, users, queue, reports, audit log, categories, tags. */
import { flushPromises } from '@vue/test-utils'
import { expect } from 'vitest'

import type { AdminStats, AdminUser } from '@/services/admin'
import type { CategoryOut } from '@/services/categories'
import type { AuditLogEntry, QueueItem, ReportDetail } from '@/services/moderation'
import type { TagOut } from '@/services/tags'
import type { UserMe } from '@/services/auth'
import { makeUser, mockApi, reply, type Handler } from './api'
import { mountApp } from './mount'

export const ADMIN_ME: UserMe = makeUser({ id: 1, display_name: 'Ada Admin', role: 'admin' })
export const SUPERADMIN_ME: UserMe = makeUser({
  id: 1,
  display_name: 'Sam Super',
  role: 'superadmin',
})

export function makeStats(overrides: Partial<AdminStats> = {}): AdminStats {
  return {
    users: { total: 128, verified: 120, trusted: 42, admins: 3, new_30d: 17 },
    content: {
      posts_published: 64,
      threads_published: 23,
      replies: 311,
      comments: 95,
      pending: 4,
    },
    reports_open: 6,
    knowbase: {
      reachable: true,
      last_success_at: '2026-10-31T09:00:00Z',
      last_error_at: null,
      last_error: null,
      cache: { lists: 11, details: 7, lookups: 5, stale: 2 },
    },
    ...overrides,
  }
}

export function makeAdminUser(overrides: Partial<AdminUser> = {}): AdminUser {
  return {
    id: 7,
    email: 'nikos@example.org',
    display_name: 'Nikos',
    organisation: null,
    organisation_other: null,
    country: 'GR',
    locale: 'en',
    bio: null,
    role: 'member',
    is_verified: true,
    trusted_at: null,
    created_at: '2026-09-15T10:00:00Z',
    expertise: [],
    show_email: false,
    show_in_directory: true,
    avatar_url: null,
    is_active: true,
    last_login_at: null,
    deleted_at: null,
    is_trusted: false,
    ...overrides,
  }
}

export function makeQueueItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    content_type: 'post',
    id: 11,
    title: 'Green roofs in Kozani',
    slug: 'green-roofs-in-kozani',
    excerpt: 'How the municipality retrofitted public buildings.',
    locale: 'en',
    author: { id: 7, display_name: 'Nikos', trusted: false },
    category: { id: 2, name: 'Nature-based solutions', slug: 'nbs' },
    created_at: '2026-10-30T08:00:00Z',
    ...overrides,
  }
}

export function makeReport(overrides: Partial<ReportDetail> = {}): ReportDetail {
  return {
    id: 31,
    content_type: 'thread',
    content_id: 12,
    reason: 'spam',
    details: 'Advertises a pump shop.',
    status: 'open',
    created_at: '2026-10-30T12:00:00Z',
    resolved_at: null,
    reporter: { id: 9, display_name: 'Elena' },
    resolver: null,
    content: {
      type: 'thread',
      id: 12,
      title: 'Cheap pumps here',
      excerpt: 'Buy now',
      status: 'published',
      author_id: 7,
      url_slug: 'cheap-pumps-here',
    },
    ...overrides,
  }
}

export function makeLogEntry(overrides: Partial<AuditLogEntry> = {}): AuditLogEntry {
  return {
    id: 501,
    action: 'moderation.hide',
    actor: { id: 1, display_name: 'Ada Admin' },
    target_type: 'thread',
    target_id: 12,
    metadata: { reason: 'Spam <b>link</b>', from: 'published', to: 'hidden' },
    created_at: '2026-10-31T08:30:00Z',
    ...overrides,
  }
}

export function makeCategory(overrides: Partial<CategoryOut> = {}): CategoryOut {
  return {
    id: 2,
    kind: 'blog',
    slug: 'nbs',
    name: 'Nature-based solutions',
    name_i18n: {},
    description: null,
    sort_order: 10,
    is_archived: false,
    admin_only: false,
    post_count: 5,
    ...overrides,
  }
}

export function makeTag(overrides: Partial<TagOut> = {}): TagOut {
  return { id: 3, slug: 'flooding', name: 'flooding', usage_count: 12, ...overrides }
}

export const page = <T>(items: T[], total = items.length) => ({ total, items })

/** Mount the whole app at an admin URL as `me` (the admin by default) with extra routes. */
export async function mountAdmin(
  path: string,
  routes: Record<string, Handler> = {},
  me: UserMe = ADMIN_ME,
) {
  const fetchMock = mockApi({ 'GET /api/v1/auth/me': reply(200, me), ...routes })
  const mounted = await mountApp(path)
  await flushPromises()
  return { ...mounted, fetchMock }
}

/** Query parameters of a recorded request. */
export const queryOf = (url: string) => new URL(url, 'http://test.invalid').searchParams

/** A button anywhere in the document by its text or aria-label. */
export function findButton(text: string): HTMLButtonElement | undefined {
  return Array.from(document.querySelectorAll('button')).find(
    (b) => b.textContent?.trim() === text || b.getAttribute('aria-label') === text,
  )
}

export function button(text: string): HTMLButtonElement {
  const el = findButton(text)
  expect(el, `button ${text}`).toBeDefined()
  return el!
}

export async function click(text: string) {
  button(text).click()
  await flushPromises()
}

/** Open a Nuxt UI dropdown menu by its trigger's aria-label; returns the menu items. */
export async function openMenu(label: string): Promise<HTMLElement[]> {
  const trigger = button(label)
  trigger.focus()
  trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await flushPromises()
  return Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"]'))
}

export async function chooseMenuItem(label: string, item: string) {
  const items = await openMenu(label)
  const found = items.find((i) => i.textContent?.trim() === item)
  expect(found, `menu item ${item}`).toBeDefined()
  found!.click()
  await flushPromises()
}

/** Visible texts of the open dropdown menu items. */
export function menuItemTexts(): string[] {
  return Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"]')).map(
    (i) => i.textContent?.trim() ?? '',
  )
}

/** Data rows of the `UTable` wrapped in `[data-testid="<name>-table"]` (not the empty-state row). */
export function tableRows(name: string): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(`[data-testid="${name}-table"] tbody tr`),
  ).filter((tr) => tr.querySelector('td[data-slot="td"]'))
}

/** Open the select labelled `labelText` inside the open dialog (teleported out of the wrapper). */
export async function openSelectInDialog(labelText: string): Promise<void> {
  const box = document.querySelector<HTMLElement>('[role="dialog"]')!
  const label = Array.from(box.querySelectorAll('label')).find((l) =>
    l.textContent?.trim().startsWith(labelText),
  )
  expect(label, `label ${labelText}`).toBeDefined()
  const el = document.getElementById(label!.htmlFor)!
  el.focus()
  el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await flushPromises()
  if (!document.querySelector('[role="option"]')) {
    el.click()
    await flushPromises()
  }
}

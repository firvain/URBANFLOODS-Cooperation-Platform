import { expect, type APIRequestContext, type Page } from '@playwright/test'

/**
 * The seeded demo accounts (backend/README.md, backend/scripts/seed_dev.py) and the API helpers
 * the content specs share. Logins are rate limited (10 per 15 min per IP, refilling one every
 * 90 s): log each role in once per spec and keep its context.
 */

export const API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000'

/** The backend's CSRF middleware wants this header on every request carrying the cookie. */
export const API_HEADERS = { 'X-Requested-With': 'XMLHttpRequest' }

export interface DemoAccount {
  email: string
  password: string
  name: string
}

export const ADMIN: DemoAccount = {
  email: 'admin@urbanfloods.example',
  password: 'Admin-Dev-Pass-2026',
  name: 'Dev Superadmin',
}
export const EDITOR: DemoAccount = {
  email: 'editor@urbanfloods.example',
  password: 'Editor-Dev-Pass-2026',
  name: 'Dev Editor',
}
export const MEMBER: DemoAccount = {
  email: 'member@urbanfloods.example',
  password: 'Member-Dev-Pass-2026',
  name: 'Dev Member',
}
export const NEWBIE: DemoAccount = {
  email: 'newbie@urbanfloods.example',
  password: 'Newbie-Dev-Pass-2026',
  name: 'Dev Newbie',
}

/** Log in through the form; ends on the home page with the account menu in the header. */
export async function loginViaForm(page: Page, account: DemoAccount): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Email').fill(account.email)
  await page.getByLabel('Password', { exact: true }).fill(account.password)
  await page.getByRole('button', { name: 'Log in' }).click()
  await page.waitForURL('/')
  await expect(page.getByRole('banner').getByRole('button', { name: account.name })).toBeVisible()
}

/** Log in an API request context (no browser); its cookie jar keeps the session. */
export async function loginViaApi(request: APIRequestContext, account: DemoAccount): Promise<void> {
  const res = await request.post(`${API_URL}/api/v1/auth/login`, {
    headers: API_HEADERS,
    data: { email: account.email, password: account.password },
  })
  expect(res.status(), `login as ${account.email}`).toBe(200)
}

/** Status of `GET /api/v1/threads/:slug` for an anonymous client. */
export async function anonThreadStatus(slug: string): Promise<number> {
  const res = await fetch(`${API_URL}/api/v1/threads/${encodeURIComponent(slug)}`)
  return res.status
}

/**
 * Best-effort delete with the given session (cleanup): looks the item up by slug (its author
 * and admins still see it while it is pending) and deletes it by id.
 */
async function deleteBySlugViaApi(
  request: APIRequestContext,
  resource: 'posts' | 'threads',
  slug: string,
): Promise<void> {
  const base = `${API_URL}/api/v1/${resource}`
  const res = await request.get(`${base}/${encodeURIComponent(slug)}`, { headers: API_HEADERS })
  if (!res.ok()) return
  const { id } = (await res.json()) as { id: number }
  await request.delete(`${base}/${id}`, { headers: API_HEADERS })
}

/** Best-effort delete of a blog post by slug with the given session (cleanup). */
export const deletePostViaApi = (request: APIRequestContext, slug: string) =>
  deleteBySlugViaApi(request, 'posts', slug)

/** Best-effort delete of a forum thread by slug with the given session (cleanup). */
export const deleteThreadViaApi = (request: APIRequestContext, slug: string) =>
  deleteBySlugViaApi(request, 'threads', slug)

/** The id of a forum (or blog) category by slug, from the public categories endpoint. */
export async function categoryId(slug: string, kind: 'forum' | 'blog' = 'forum'): Promise<number> {
  const res = await fetch(`${API_URL}/api/v1/categories/`)
  const { items } = (await res.json()) as { items: { id: number; kind: string; slug: string }[] }
  const category = items.find((c) => c.kind === kind && c.slug === slug)
  if (!category) throw new Error(`No ${kind} category "${slug}"`)
  return category.id
}

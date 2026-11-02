import { expect, type APIRequestContext, type Page } from '@playwright/test'

/**
 * The seeded demo accounts (backend/README.md, backend/scripts/seed_dev.py) and the API helpers
 * the content specs share. Logins are rate limited (60 per 15 min per IP, refilling one every
 * 15 s): log each role in once per spec and keep its context.
 */

export const API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000'

/** The backend's CSRF middleware wants this header on every request carrying the cookie. */
export const API_HEADERS = { 'X-Requested-With': 'XMLHttpRequest' }

export interface DemoAccount {
  email: string
  password: string
  /**
   * The seeded display name. Manual testing may rename an account, so specs assert the live
   * name from `displayNameOf`; this is only a fallback for content a spec creates itself.
   */
  name: string
}

/** Every demo account shares one password (backend/README.md, "Development seed"). */
const DEMO_PASSWORD = 'Urbanfloods-2026'

/** Superadmin (UOWM, Greece). */
export const ADMIN: DemoAccount = {
  email: 'eleni.papadopoulou@urbanfloods.example',
  password: DEMO_PASSWORD,
  name: 'Eleni Papadopoulou',
}
/** Admin (Development Centre Murska Sobota, Slovenia). */
export const EDITOR: DemoAccount = {
  email: 'matej.kovacic@urbanfloods.example',
  password: DEMO_PASSWORD,
  name: 'Matej Kovačič',
}
/** Trusted member (Macerata Municipality, Italy): publishes directly. */
export const MEMBER: DemoAccount = {
  email: 'giulia.romano@urbanfloods.example',
  password: DEMO_PASSWORD,
  name: 'Giulia Romano',
}
/** Verified, untrusted member (Hydrowater-Albania): the first post waits for approval. */
export const NEWBIE: DemoAccount = {
  email: 'arben.hoxha@urbanfloods.example',
  password: DEMO_PASSWORD,
  name: 'Arben Hoxha',
}

/** The local part of an account's address: a search term that matches only that account. */
export const searchTermOf = (account: DemoAccount): string => account.email.split('@')[0]

/** `value` with RegExp metacharacters escaped (for URL assertions on search terms). */
export const escapeRegExp = (value: string): string => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Log in through the form; ends on the home page with the account menu in the header. */
export async function loginViaForm(page: Page, account: DemoAccount): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Email').fill(account.email)
  await page.getByLabel('Password', { exact: true }).fill(account.password)
  await page.getByRole('button', { name: 'Log in' }).click()
  await page.waitForURL('/')
  // The page's request context shares the browser's cookie jar: no second login.
  const name = await displayNameOf(page.request, account)
  await expect(page.getByRole('banner').getByRole('button', { name })).toBeVisible()
}

/** Log in an API request context (no browser); its cookie jar keeps the session. */
export async function loginViaApi(request: APIRequestContext, account: DemoAccount): Promise<void> {
  const res = await request.post(`${API_URL}/api/v1/auth/login`, {
    headers: API_HEADERS,
    data: { email: account.email, password: account.password },
  })
  expect(res.status(), `login as ${account.email}`).toBe(200)
}

/** The fields of `GET /api/v1/auth/me` the specs use. */
export interface Me {
  id: number
  email: string
  display_name: string
  trusted_at: string | null
}

/**
 * `GET /api/v1/auth/me` for a request context logged in as `account` (asserts it is that
 * account's session).
 */
export async function meOf(request: APIRequestContext, account: DemoAccount): Promise<Me> {
  const res = await request.get(`${API_URL}/api/v1/auth/me`, { headers: API_HEADERS })
  expect(res.status(), `GET /auth/me as ${account.email}`).toBe(200)
  const me = (await res.json()) as Me
  expect(me.email.toLowerCase(), 'the session belongs to the account').toBe(
    account.email.toLowerCase(),
  )
  return me
}

/**
 * The account's current display name, read from its own API session: an admin may have renamed
 * a demo account during manual testing, so never assert the seeded `name`.
 */
export async function displayNameOf(
  request: APIRequestContext,
  account: DemoAccount,
): Promise<string> {
  return (await meOf(request, account)).display_name
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

export interface Category {
  id: number
  kind: 'forum' | 'blog'
  slug: string
  name: string
  admin_only: boolean
  is_archived: boolean
}

/** Every category (both kinds), from the public categories endpoint. */
export async function listCategories(): Promise<Category[]> {
  const res = await fetch(`${API_URL}/api/v1/categories/`)
  expect(res.status, 'GET /categories/').toBe(200)
  return ((await res.json()) as { items: Category[] }).items
}

/**
 * A forum (or blog) category by slug, from the public categories endpoint. Slugs are stable;
 * names can be edited by an admin, so specs take the name they click or assert from here.
 */
export async function categoryBySlug(
  slug: string,
  kind: 'forum' | 'blog' = 'forum',
): Promise<Category> {
  const category = (await listCategories()).find((c) => c.kind === kind && c.slug === slug)
  if (!category) throw new Error(`No ${kind} category "${slug}"`)
  return category
}

/** The id of a forum (or blog) category by slug, from the public categories endpoint. */
export async function categoryId(slug: string, kind: 'forum' | 'blog' = 'forum'): Promise<number> {
  return (await categoryBySlug(slug, kind)).id
}

import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
} from '@playwright/test'

import {
  ADMIN,
  API_HEADERS,
  API_URL,
  MEMBER,
  NEWBIE,
  categoryBySlug,
  deletePostViaApi,
  displayNameOf,
  listCategories,
  loginViaApi,
  meOf,
} from './helpers/demo'
import { makePng } from './helpers/png'

/**
 * M2 blog flow against the real dev stack and its seeded demo data (backend/README.md):
 * anonymous browsing (list, category chips, search, post detail, KNOWBASE link cards and the
 * "Mentioned in" round trip), a trusted member writing → editing → deleting a post, an untrusted
 * member's post waiting for approval, and the editor's unsaved-changes guard.
 * One page per role, logged in once through the API (the UI login is covered by auth.spec.ts;
 * logins are rate limited) and kept across the tests, which run in order. Titles carry a
 * per-run suffix and everything created is deleted again (the afterAll hook is a safety net for
 * failed runs).
 *
 * Manual testing changes the dev data, so the spec does not rely on its exact state: display
 * names come from `GET /auth/me`, category names from `GET /categories/`, counts from the public
 * post list, and the pending content it asserts on is created here. If newbie is trusted (an
 * admin approved one of its posts), the mark is removed for the run and put back afterwards.
 */
test.describe.configure({ mode: 'serial' })

/** Seeded post by the member, with KNOWBASE links (backend/scripts/seed_dev.py). */
const GREEN_ROOFS = {
  slug: 'green-roofs-and-retention-basins-what-two-years-of-pilot-data-show',
  title: 'Green roofs and retention basins: what two years of pilot data show',
}
/** The live KNOWBASE title of measure 2, linked from the green-roofs post. */
const MEASURE_2_TITLE = 'floodplain reconnection'

const RUN = `${Date.now().toString(36)}`
const memberTitle = `E2E trusted post ${RUN}`
const memberTitleEdited = `E2E trusted post ${RUN} (edited)`
const newbieTitle = `E2E pending post ${RUN}`
const coverAlt = `E2E cover: a teal and violet gradient ${RUN}`
const TAGS = ['e2e-test', 'playwright']
/** A word no other post contains: test 1 searches for newbie's pending post by it. */
const PENDING_TOKEN = `pendingprobe${RUN}`
const pendingProbeTitle = `E2E pending search probe ${PENDING_TOKEN}`

let anonContext: BrowserContext
let memberContext: BrowserContext
let newbieContext: BrowserContext
let anon: Page
let member: Page
let newbie: Page

/** Slugs of posts this run created and has not deleted yet (cleaned up in afterAll). */
const created = new Map<string, BrowserContext>()
let memberSlug = ''
let newbieSlug = ''
/** The member's live display name (the seeded one may have been changed in the UI). */
let memberName = ''
/** Set when newbie was trusted at the start: the admin removes the mark and restores it. */
let adminContext: BrowserContext | undefined
let newbieId = 0

async function newPage(browser: Browser): Promise<[BrowserContext, Page]> {
  const context = await browser.newContext()
  return [context, await context.newPage()]
}

/** The post cards of the blog list. */
const cards = (page: Page) => page.getByTestId('post-card')

/** The titles of the cards on screen (for `expect.poll`). */
const cardTitles = (page: Page) => cards(page).getByRole('heading', { level: 2 }).allTextContents()

/** The post the browser is on after a create/edit, from its URL (`/blog/:slug`). */
async function waitForPostPage(page: Page): Promise<string> {
  await page.waitForURL(
    (url) => /^\/blog\/[^/]+$/.test(url.pathname) && url.pathname !== '/blog/new',
  )
  return decodeURIComponent(new URL(page.url()).pathname.split('/').pop() ?? '')
}

/** The rich-text editor's editing surface (a contenteditable with role="textbox"). */
const editorBody = (page: Page) => page.getByRole('textbox', { name: 'Text', exact: true })
const toolbarButton = (page: Page, name: string) =>
  page.getByRole('toolbar', { name: 'Formatting' }).getByRole('button', { name, exact: true })

async function chooseCategory(page: Page, name: string) {
  await page.getByRole('combobox', { name: 'Category' }).click()
  await page.getByRole('option', { name, exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Category' })).toContainText(name)
}

/** Status of `GET /posts/:slug` for an anonymous client. */
async function anonPostStatus(slug: string): Promise<number> {
  const res = await fetch(`${API_URL}/api/v1/posts/${encodeURIComponent(slug)}`)
  return res.status
}

interface ListedPost {
  slug: string
  title: string
  category: { id: number; slug: string; name: string }
}

/** The public post list as an anonymous client sees it (optionally searched). */
async function anonPosts(q?: string): Promise<{ total: number; items: ListedPost[] }> {
  const query = q ? `&q=${encodeURIComponent(q)}` : ''
  const res = await fetch(`${API_URL}/api/v1/posts/?limit=50${query}`)
  expect(res.status, 'GET /posts/').toBe(200)
  return (await res.json()) as { total: number; items: ListedPost[] }
}

/** The English list count ("blog.count" in en.json). */
const postCount = (total: number) =>
  total === 0 ? 'No posts' : total === 1 ? '1 post' : `${total} posts`

/** Mark or unmark newbie as trusted with the admin session. */
async function setNewbieTrust(context: BrowserContext, action: 'trust' | 'untrust') {
  const res = await context.request.post(`${API_URL}/api/v1/admin/users/${newbieId}/${action}`, {
    headers: API_HEADERS,
  })
  expect(res.status(), `${action} newbie`).toBe(200)
}

/** A success toast (Nuxt UI also mirrors it into a hidden live region, hence `exact`). */
const toast = (page: Page, text: string) => page.getByText(text, { exact: true })

async function deletePost(page: Page) {
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Delete this post?' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Delete post' }).click()
  await page.waitForURL((url) => url.pathname === '/blog')
  await expect(toast(page, 'The post was deleted.')).toBeVisible()
}

test.beforeAll(async ({ browser }) => {
  ;[anonContext, anon] = await newPage(browser)
  ;[memberContext, member] = await newPage(browser)
  ;[newbieContext, newbie] = await newPage(browser)
  // The pages share their context's cookie jar, so these sessions are the browsers' too.
  await loginViaApi(memberContext.request, MEMBER)
  await loginViaApi(newbieContext.request, NEWBIE)
  memberName = await displayNameOf(memberContext.request, MEMBER)

  // Tests 1 and 5 need newbie untrusted. An admin approving one of its posts trusts it: then
  // (only then) log the admin in, remove the mark and put it back in afterAll.
  const newbieMe = await meOf(newbieContext.request, NEWBIE)
  newbieId = newbieMe.id
  if (newbieMe.trusted_at) {
    adminContext = await browser.newContext()
    await loginViaApi(adminContext.request, ADMIN)
    await setNewbieTrust(adminContext, 'untrust')
  }
})

test.afterAll(async () => {
  // Cleanup after a failed run only: the tests delete what they create.
  for (const [slug, context] of created) {
    await deletePostViaApi(context.request, slug).catch(() => {})
  }
  if (adminContext) {
    await setNewbieTrust(adminContext, 'trust').catch(() => {})
    await adminContext.close()
  }
  await Promise.all([anonContext, memberContext, newbieContext].map((c) => c.close()))
})

test('1. anonymous: the blog lists the posts; category chips and search filter them', async () => {
  // What an anonymous visitor may see right now (counts and categories drift with manual testing).
  const published = await anonPosts()
  expect(published.total, 'published posts in the dev data').toBeGreaterThan(0)
  await anon.goto('/blog')
  await expect(anon.getByRole('heading', { level: 1, name: 'Blog' })).toBeVisible()
  const count = anon.getByTestId('blog-count')
  await expect(count).toHaveText(postCount(published.total))
  await expect.poll(() => cards(anon).count()).toBeGreaterThan(0)
  // Only verified members can write.
  await expect(anon.getByRole('link', { name: 'Write a post' })).toHaveCount(0)

  // Category chip → only that category, reflected in the URL. The category of a published post,
  // so the filtered list is not empty; its name as the API has it now.
  const { slug: categorySlug, name: categoryName } = published.items[0]!.category
  const chips = anon.getByRole('group', { name: 'Category' })
  await chips.getByRole('button', { name: categoryName, exact: true }).click()
  await expect(anon).toHaveURL(new RegExp(`[?&]category=${categorySlug}(&|$)`))
  await expect(chips.getByRole('button', { name: categoryName, exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await expect
    .poll(async () => {
      const names = await cards(anon).getByTestId('post-category').allTextContents()
      return names.length > 0 && names.every((name) => name.trim() === categoryName)
    })
    .toBe(true)

  await chips.getByRole('button', { name: 'All', exact: true }).click()
  await expect(anon).not.toHaveURL(/category=/)
  await expect(count).toHaveText(postCount(published.total))

  // Search never finds a post that is not published: newbie (untrusted) sends one for review
  // whose title and body carry a word no other post has, and the anonymous search for it is
  // empty (were the pending post leaking, it would be the one hit).
  const category = (await listCategories()).find(
    (c) => c.kind === 'blog' && !c.admin_only && !c.is_archived,
  )
  if (!category) throw new Error('No blog category open to members')
  const res = await newbieContext.request.post(`${API_URL}/api/v1/posts/`, {
    headers: API_HEADERS,
    data: {
      title: pendingProbeTitle,
      body_html: `<p>A pending post the blog e2e search must not find: ${PENDING_TOKEN}.</p>`,
      category_id: category.id,
    },
  })
  expect(res.status(), 'newbie creates the pending probe').toBe(201)
  const probe = (await res.json()) as { slug: string; status: string }
  created.set(probe.slug, newbieContext)
  expect(probe.status).toBe('pending')

  const search = anon.getByRole('searchbox', { name: 'Search', exact: true })
  await search.fill(PENDING_TOKEN)
  await expect(anon).toHaveURL(new RegExp(`[?&]q=${PENDING_TOKEN}(&|$)`))
  await expect(count).toHaveText('No posts')
  await expect(anon.getByRole('link', { name: pendingProbeTitle })).toHaveCount(0)
  expect((await anonPosts(PENDING_TOKEN)).total).toBe(0)
  await deletePostViaApi(newbieContext.request, probe.slug)
  created.delete(probe.slug)

  // A published post is found by a word of its title.
  await search.fill('green')
  await expect(anon).toHaveURL(/[?&]q=green(&|$)/)
  await expect(anon.getByRole('link', { name: GREEN_ROOFS.title })).toBeVisible()
  await expect.poll(() => cardTitles(anon)).not.toContain(pendingProbeTitle)
})

test('2. anonymous: a post shows its content, and its KNOWBASE links lead back to it', async () => {
  await anon.getByRole('link', { name: GREEN_ROOFS.title }).click()
  await expect(anon).toHaveURL(`/blog/${GREEN_ROOFS.slug}`)

  await expect(anon.getByRole('heading', { level: 1, name: GREEN_ROOFS.title })).toBeVisible()
  await expect(anon.getByTestId('post-author')).toContainText(memberName)
  await expect(anon.getByTestId('post-body')).toContainText('Sarajevo pilot')
  await expect(
    anon.getByTestId('post-body').getByRole('heading', { name: 'Results' }),
  ).toBeVisible()
  const tags = anon.getByRole('list', { name: 'Tags' })
  await expect(tags.getByRole('link', { name: '#NBS' })).toBeVisible()
  await expect(tags.getByRole('link', { name: '#urban-drainage' })).toBeVisible()
  // Not the author: no management buttons.
  await expect(anon.getByRole('link', { name: 'Edit' })).toHaveCount(0)

  await expect(anon.getByRole('heading', { level: 2, name: 'From the KNOWBASE' })).toBeVisible()
  const linkCards = anon.getByTestId('kb-link-card')
  await expect(linkCards).toHaveCount(2)
  await linkCards.getByRole('link', { name: MEASURE_2_TITLE }).click()

  await expect(anon).toHaveURL('/knowbase/measures/2')
  const mentions = anon.getByTestId('kb-mentions')
  await expect(mentions.getByRole('heading', { level: 2, name: 'Mentioned in' })).toBeVisible()
  await mentions.getByRole('link', { name: GREEN_ROOFS.title }).click()
  await expect(anon).toHaveURL(`/blog/${GREEN_ROOFS.slug}`)
  await expect(anon.getByRole('heading', { level: 1, name: GREEN_ROOFS.title })).toBeVisible()
})

test('3. trusted member: write a post with formatting, tags, cover and a KNOWBASE link', async () => {
  await member.goto('/blog')
  await member.getByRole('link', { name: 'Write a post' }).click()
  await expect(member).toHaveURL('/blog/new')
  await expect(member.getByRole('heading', { level: 1, name: 'Write a post' })).toBeVisible()
  // Trusted: published directly, no review note.
  await expect(member.getByTestId('untrusted-note')).toHaveCount(0)

  await member.getByLabel('Title', { exact: true }).fill(memberTitle)
  await chooseCategory(member, (await categoryBySlug('best-practices', 'blog')).name)

  // Body: a heading, a paragraph and a bulleted list, made with the toolbar.
  const body = editorBody(member)
  await body.click()
  await toolbarButton(member, 'Heading').click()
  await expect(toolbarButton(member, 'Heading')).toHaveAttribute('aria-pressed', 'true')
  await member.keyboard.type('Pilot results')
  await member.keyboard.press('Enter')
  await member.keyboard.type('What we measured during the pilot.')
  await member.keyboard.press('Enter')
  await toolbarButton(member, 'Bulleted list').click()
  await expect(toolbarButton(member, 'Bulleted list')).toHaveAttribute('aria-pressed', 'true')
  await member.keyboard.type('Peak discharge went down')
  await member.keyboard.press('Enter')
  await member.keyboard.type('Maintenance stayed affordable')
  await expect(body.locator('h2')).toHaveText('Pilot results')
  await expect(body.locator('ul > li')).toHaveCount(2)

  // Tags: Enter after each.
  const tagInput = member.getByRole('textbox', { name: 'Tags' })
  for (const tag of TAGS) {
    await tagInput.fill(tag)
    await tagInput.press('Enter')
  }
  for (const tag of TAGS) await expect(member.getByTestId('post-form')).toContainText(tag)

  // Cover: a PNG generated in memory, with its alternative text.
  await member.getByRole('button', { name: 'Add a cover image' }).click()
  const dialog = member.getByRole('dialog', { name: 'Insert image' })
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('Image file').setInputFiles({
    name: `e2e-cover-${RUN}.png`,
    mimeType: 'image/png',
    buffer: makePng(),
  })
  await dialog.getByLabel('Alternative text').fill(coverAlt)
  await dialog.getByRole('button', { name: 'Upload and insert' }).click()
  await expect(dialog).toBeHidden({ timeout: 20_000 })
  await expect(
    member.getByTestId('cover-preview').getByRole('img', { name: coverAlt }),
  ).toBeVisible()

  // KNOWBASE link: search "flood", add the first measure.
  await member.getByRole('searchbox', { name: 'Search the KNOWBASE' }).fill('flood')
  const results = member.getByRole('list', { name: 'Search results' })
  const firstAdd: Locator = results.getByRole('button', { name: /^Add / }).first()
  await expect(firstAdd).toBeVisible({ timeout: 15_000 })
  const kbTitle = ((await firstAdd.getAttribute('aria-label')) ?? '').replace(/^Add /, '')
  expect(kbTitle).not.toBe('')
  await firstAdd.click()
  await expect(member.getByRole('list', { name: 'Linked items' })).toContainText(kbTitle)

  await member.getByRole('button', { name: 'Publish' }).click()
  memberSlug = await waitForPostPage(member)
  created.set(memberSlug, memberContext)
  await expect(toast(member, 'The post is published.')).toBeVisible()

  await expect(member.getByRole('heading', { level: 1, name: memberTitle })).toBeVisible()
  await expect(member.getByTestId('post-status')).toHaveCount(0)
  await expect(member.getByTestId('status-hint')).toHaveCount(0)
  const cover = member.getByTestId('post-cover')
  await expect(cover).toBeVisible()
  await expect(cover).toHaveAttribute('alt', coverAlt)
  await expect(member.getByTestId('post-body').locator('h2')).toHaveText('Pilot results')
  await expect(member.getByTestId('post-body').locator('ul > li')).toHaveCount(2)
  const tags = member.getByRole('list', { name: 'Tags' })
  for (const tag of TAGS) await expect(tags.getByRole('link', { name: `#${tag}` })).toBeVisible()
  await expect(
    member.getByTestId('kb-link-card').getByRole('link', { name: kbTitle }),
  ).toBeVisible()

  // Published: visible to anyone.
  await expect.poll(() => anonPostStatus(memberSlug)).toBe(200)
})

test('4. trusted member: edit the title, then delete the post', async () => {
  await member.getByRole('link', { name: 'Edit' }).click()
  await expect(member).toHaveURL(`/blog/${memberSlug}/edit`)
  await expect(member.getByRole('heading', { level: 1, name: 'Edit the post' })).toBeVisible()
  const title = member.getByLabel('Title', { exact: true })
  await expect(title).toHaveValue(memberTitle)
  await title.fill(memberTitleEdited)
  await member.getByRole('button', { name: 'Save changes' }).click()

  const slug = await waitForPostPage(member)
  if (slug !== memberSlug) {
    created.delete(memberSlug)
    created.set(slug, memberContext)
    memberSlug = slug
  }
  await expect(toast(member, 'The changes are saved.')).toBeVisible()
  await expect(member.getByRole('heading', { level: 1, name: memberTitleEdited })).toBeVisible()

  await deletePost(member)
  created.delete(memberSlug)
  // A fresh load, so the list is not the one cached from before the post existed.
  await member.reload()
  await expect(member.getByTestId('blog-count')).toBeVisible()
  await expect.poll(() => cardTitles(member)).not.toContain(memberTitleEdited)
  await expect(member.getByRole('link', { name: memberTitleEdited })).toHaveCount(0)
  await expect.poll(() => anonPostStatus(memberSlug)).toBe(404)
})

test('5. untrusted member: a new post waits for approval and stays private', async () => {
  await newbie.goto('/blog')
  await newbie.getByRole('link', { name: 'Write a post' }).click()
  await expect(newbie).toHaveURL('/blog/new')
  await expect(
    newbie.getByText('Your first post will be reviewed by an admin before it is published.'),
  ).toBeVisible()

  await newbie.getByLabel('Title', { exact: true }).fill(newbieTitle)
  await chooseCategory(newbie, (await categoryBySlug('news', 'blog')).name)
  await editorBody(newbie).click()
  await newbie.keyboard.type('A short report from our municipality, written by an e2e test.')

  await newbie.getByRole('button', { name: 'Send for review' }).click()
  newbieSlug = await waitForPostPage(newbie)
  created.set(newbieSlug, newbieContext)
  await expect(
    toast(newbie, 'The post was sent. It will be published once an admin approves it.'),
  ).toBeVisible()

  await expect(newbie.getByRole('heading', { level: 1, name: newbieTitle })).toBeVisible()
  await expect(newbie.getByTestId('post-status')).toHaveText('Pending approval')
  await expect(newbie.getByTestId('status-hint')).toContainText(
    'Waiting for approval by an admin. Only you and the admins can see this post until it is approved.',
  )

  // A fresh anonymous visitor sees neither the post page nor a card for it.
  await anon.goto(`/blog/${newbieSlug}`)
  await expect(anon.getByRole('heading', { level: 1, name: 'Post not found' })).toBeVisible()
  await anon.goto('/blog')
  await expect(anon.getByTestId('blog-count')).toBeVisible()
  await expect.poll(() => cardTitles(anon)).not.toContain(newbieTitle)
  expect(await anonPostStatus(newbieSlug)).toBe(404)
})

test('6. editor guard: leaving with unsaved changes asks first; "Keep editing" stays', async () => {
  await member.goto('/blog/new')
  await expect(member.getByRole('heading', { level: 1, name: 'Write a post' })).toBeVisible()
  const title = member.getByLabel('Title', { exact: true })
  await title.fill(`E2E unsaved ${RUN}`)

  await member.getByRole('link', { name: 'Back to the blog' }).click()
  const dialog = member.getByRole('dialog', { name: 'Leave without saving?' })
  await expect(dialog).toBeVisible()
  await expect(
    dialog.getByText('Your changes to this post are not saved and will be lost.'),
  ).toBeVisible()
  await dialog.getByRole('button', { name: 'Keep editing' }).click()

  await expect(dialog).toBeHidden()
  await expect(member).toHaveURL('/blog/new')
  await expect(title).toHaveValue(`E2E unsaved ${RUN}`)
})

test('7. untrusted member: delete the pending post (cleanup)', async () => {
  await newbie.goto(`/blog/${newbieSlug}`)
  await expect(newbie.getByRole('heading', { level: 1, name: newbieTitle })).toBeVisible()
  await deletePost(newbie)
  created.delete(newbieSlug)
})

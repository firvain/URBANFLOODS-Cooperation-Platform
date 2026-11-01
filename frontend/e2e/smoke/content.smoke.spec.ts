import { strongPassword, uniqueEmail } from '../helpers/accounts'
import { extractLink, waitForEmailTo } from '../helpers/mailpit'
import { makePng } from '../helpers/png'
import { expect, test } from './fixtures'
import {
  VERIFY_SUBJECT,
  anonPostStatus,
  imageLoaded,
  loginViaForm,
  registerViaApi,
  smokeAdmin,
  toast,
  type NewAccount,
} from './helpers'

/**
 * Production-mode smoke: a new member's first post with a cover image goes to the approval
 * queue, the upload is re-encoded to WebP and served by the backend through nginx `/static/`
 * with the right content type (a production-image-only MIME bug once served it wrongly), and a
 * superadmin (created by scripts/smoke.sh with the backend CLI) approves it.
 * The two tests share the post and run in order: 1 registration, 1 login.
 */
test.describe.configure({ mode: 'serial' })

const RUN = Date.now().toString(36)
const member: NewAccount = {
  email: uniqueEmail('smoke-member'),
  password: strongPassword(),
  displayName: `Smoke Member ${RUN}`,
}
const title = `Smoke first post ${RUN}`
const coverAlt = `Smoke cover: a teal and violet gradient ${RUN}`
let slug = ''

test('5. a new member’s first post with a cover image is pending; the cover is served as WebP', async ({
  page,
  request,
}) => {
  test.setTimeout(120_000)
  await registerViaApi(request, member)
  const message = await waitForEmailTo(member.email, { subjectIncludes: VERIFY_SUBJECT })
  await page.goto(extractLink(message, '/verify-email?token='))
  await page.getByRole('button', { name: 'Verify my email' }).click()
  await expect(
    page.getByText('Your email address is verified and you are logged in. Welcome!'),
  ).toBeVisible()

  await page.goto('/blog/new')
  await expect(page.getByRole('heading', { level: 1, name: 'Write a post' })).toBeVisible()
  await expect(
    page.getByText('Your first post will be reviewed by an admin before it is published.'),
  ).toBeVisible()
  await page.getByLabel('Title', { exact: true }).fill(title)
  await page.getByRole('combobox', { name: 'Category' }).click()
  await page.getByRole('option', { name: 'News', exact: true }).click()
  await page.getByRole('textbox', { name: 'Text', exact: true }).click()
  await page.keyboard.type('A short report written by the production-mode smoke test.')

  // Cover: a PNG generated in memory; the backend re-encodes it to WebP.
  await page.getByRole('button', { name: 'Add a cover image' }).click()
  const dialog = page.getByRole('dialog', { name: 'Insert image' })
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('Image file').setInputFiles({
    name: `smoke-cover-${RUN}.png`,
    mimeType: 'image/png',
    buffer: makePng(),
  })
  await dialog.getByLabel('Alternative text').fill(coverAlt)
  await dialog.getByRole('button', { name: 'Upload and insert' }).click()
  await expect(dialog).toBeHidden({ timeout: 20_000 })
  await expect(page.getByTestId('cover-preview').getByRole('img', { name: coverAlt })).toBeVisible()

  await page.getByRole('button', { name: 'Send for review' }).click()
  await page.waitForURL(
    (url) => /^\/blog\/[^/]+$/.test(url.pathname) && url.pathname !== '/blog/new',
  )
  slug = decodeURIComponent(new URL(page.url()).pathname.split('/').pop() ?? '')
  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
  await expect(page.getByTestId('post-status')).toHaveText('Pending approval')

  // The cover, served by the backend through nginx /static/, loads in the page.
  const cover = page.getByTestId('post-cover')
  await expect(cover).toBeVisible()
  await expect(cover).toHaveAttribute('alt', coverAlt)
  await expect.poll(() => imageLoaded(cover), { message: 'the cover image loads' }).toBe(true)
  const src = new URL((await cover.getAttribute('src')) ?? '', page.url())
  expect(src.origin, 'uploads are same-origin').toBe(new URL(page.url()).origin)
  expect(src.pathname).toMatch(/^\/static\/uploads\/.+\.webp$/)
  const image = await request.get(src.toString())
  expect(image.status()).toBe(200)
  expect(image.headers()['content-type']).toBe('image/webp')
  // nginx hides the backend's copy and adds its own: exactly one value.
  expect(image.headers()['x-content-type-options']).toBe('nosniff')
  expect((await image.body()).subarray(8, 12).toString('ascii'), 'RIFF....WEBP magic').toBe('WEBP')

  // Pending: invisible to anyone else.
  expect(await anonPostStatus(slug)).toBe(404)
})

test('6. a superadmin approves it in /admin/queue; the post and its cover become public', async ({
  page,
  newPage,
}) => {
  expect(slug, 'test 5 created the post').not.toBe('')
  const admin = smokeAdmin()
  await loginViaForm(page, admin.email, admin.password, admin.name)

  await page.goto('/admin/queue')
  await expect(page.getByRole('heading', { level: 1, name: 'Approval queue' })).toBeVisible()
  const row = page
    .getByTestId('queue-table')
    .getByRole('row')
    .filter({ has: page.getByRole('link', { name: title, exact: true }) })
  await expect(row).toHaveCount(1)
  await expect(row).toContainText(member.displayName)
  await row.getByRole('button', { name: `Approve “${title}”` }).click()
  await expect(toast(page, `“${title}” is published.`)).toBeVisible()
  await expect(row).toHaveCount(0)

  await expect.poll(() => anonPostStatus(slug)).toBe(200)
  const anon = await newPage()
  await anon.goto(`/blog/${slug}`)
  await expect(anon.getByRole('heading', { level: 1, name: title })).toBeVisible()
  await expect(anon.getByTestId('post-status')).toHaveCount(0)
  const cover = anon.getByTestId('post-cover')
  await expect(cover).toBeVisible()
  await expect.poll(() => imageLoaded(cover), { message: 'the cover image loads' }).toBe(true)
})

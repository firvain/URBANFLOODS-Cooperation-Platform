import { expect, test } from './fixtures'

/**
 * Production-mode smoke: what the production nginx adds or routes, checked on the real stack.
 * The security headers come from frontend/nginx.conf (the host nginx adds only HSTS, over TLS);
 * feeds, sitemap, robots and the API are proxied to the backend; client routes fall back to the
 * SPA; KNOWBASE content comes through the backend proxy (real public API, GET only).
 * Independent tests, no account needed.
 */

const SECURITY_HEADERS = {
  'x-content-type-options': 'nosniff',
  'x-frame-options': 'DENY',
  'referrer-policy': 'strict-origin-when-cross-origin',
  'permissions-policy': 'camera=(), microphone=(), geolocation=()',
}

/** The CSP directives the production build depends on (Turnstile, KNOWBASE photos, no framing). */
const CSP_DIRECTIVES = [
  "default-src 'self'",
  "script-src 'self' https://challenges.cloudflare.com",
  'frame-src https://challenges.cloudflare.com',
  'img-src',
  'https://knowbase.urbanfloods.app',
  "connect-src 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
]

test('7. the home page renders under the production CSP with every nginx security header', async ({
  page,
  request,
}) => {
  const res = await request.get('/')
  expect(res.status()).toBe(200)
  const headers = res.headers()
  const csp = headers['content-security-policy']
  expect(csp, 'Content-Security-Policy on /').toBeTruthy()
  for (const directive of CSP_DIRECTIVES) expect(csp).toContain(directive)
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    expect(headers[name], name).toBe(value)
  }
  expect(headers['server'] ?? '', 'server_tokens off: no nginx version').not.toMatch(/\d/)

  // The hashed bundle (its own location block repeats the headers) is cached for a year.
  const html = await res.text()
  const script = html.match(/<script[^>]+src="(\/assets\/[^"]+\.js)"/)?.[1]
  expect(script, 'index.html loads a hashed bundle from /assets/').toBeTruthy()
  const asset = await request.get(script!)
  expect(asset.status()).toBe(200)
  expect(asset.headers()['content-security-policy']).toBe(csp)
  expect(asset.headers()['x-content-type-options']).toBe('nosniff')
  expect(asset.headers()['cache-control']).toContain('immutable')

  // In the browser: the SPA boots (one h1) and the CSP guard sees no violation.
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
})

test('8. feeds, sitemap, robots.txt and the OpenAPI spec are served through nginx', async ({
  request,
}) => {
  const feed = await request.get('/feeds/posts.atom')
  expect(feed.status()).toBe(200)
  expect(feed.headers()['content-type']).toContain('application/atom+xml')
  expect(await feed.text()).toContain('<feed')

  const threads = await request.get('/feeds/threads.atom')
  expect(threads.status()).toBe(200)
  expect(threads.headers()['content-type']).toContain('application/atom+xml')

  const sitemap = await request.get('/sitemap.xml')
  expect(sitemap.status()).toBe(200)
  expect(sitemap.headers()['content-type']).toMatch(/xml/)
  expect(await sitemap.text()).toContain('<urlset')

  const robots = await request.get('/robots.txt')
  expect(robots.status()).toBe(200)
  expect(await robots.text()).toMatch(/^Sitemap: http\S+\/sitemap\.xml$/m)

  const openapi = await request.get('/api/v1/openapi.json')
  expect(openapi.status()).toBe(200)
  expect(((await openapi.json()) as { openapi?: string }).openapi).toMatch(/^3\./)
})

test('9. /knowbase/measures renders its h1 and then the measures or its error state', async ({
  page,
}) => {
  await page.goto('/knowbase/measures')
  await expect(
    page.getByRole('heading', { level: 1, name: 'Flood Management Measures' }),
  ).toBeVisible()
  // The real KNOWBASE through the backend proxy: the list, or (KNOWBASE unreachable) the
  // page's error alert. Either proves the page works; a blank page or an endless spinner fails.
  await expect(
    page
      .getByTestId('glance-count')
      .or(page.getByRole('alert').filter({ hasText: 'The measures could not be loaded.' })),
  ).toBeVisible({ timeout: 20_000 })
})

test('10. client routes fall back to the SPA; a missing bundle file is a real 404', async ({
  page,
  request,
}) => {
  const deepLink = await request.get('/this/route/does/not/exist')
  expect(deepLink.status(), 'nginx serves index.html for client routes').toBe(200)
  expect(deepLink.headers()['content-type']).toContain('text/html')

  await page.goto('/this/route/does/not/exist')
  await expect(page.getByRole('heading', { level: 1, name: 'Page not found' })).toBeVisible()

  const missing = await request.get('/assets/does-not-exist-0000.js')
  expect(missing.status(), 'never index.html for a missing chunk').toBe(404)
})

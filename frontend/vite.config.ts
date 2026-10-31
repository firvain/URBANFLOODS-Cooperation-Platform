import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import { defineConfig, searchForWorkspaceRoot, type Plugin } from 'vite'
import { configDefaults } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import ui from '@nuxt/ui/vite'

import { prepareLegalDocument } from './src/utils/legalDocument.ts'

const LEGAL_SUFFIX = '?legal'

/**
 * `import doc from '…/docs/legal/x.md?legal'` gives the publishable document
 * ({ version, date, markdown }) prepared at build time, so the reviewer material in the source
 * files (draft status, [CHECK] items, notes for the reviewer) never reaches the bundle.
 */
function legalDocuments(): Plugin {
  return {
    name: 'urbanfloods:legal-documents',
    enforce: 'pre',
    async resolveId(source, importer) {
      if (!source.endsWith(LEGAL_SUFFIX)) return null
      const resolved = await this.resolve(source.slice(0, -LEGAL_SUFFIX.length), importer, {
        skipSelf: true,
      })
      return resolved ? resolved.id + LEGAL_SUFFIX : null
    },
    load(id) {
      if (!id.endsWith(LEGAL_SUFFIX)) return null
      const file = id.slice(0, -LEGAL_SUFFIX.length)
      this.addWatchFile(file)
      return `export default ${JSON.stringify(prepareLegalDocument(readFileSync(file, 'utf8')))}`
    },
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [
    legalDocuments(),
    vue(),
    // Devtools only in interactive dev; it injects client code that is useless under vitest.
    mode !== 'test' && vueDevTools(),
    ui({
      // Bundle the Lucide icons we use (and Nuxt UI's defaults) into the build, so the browser
      // never fetches icons from the third-party Iconify API.
      icon: { clientBundle: { scan: true } },
      // Light mode only (docs/branding.md: the project logo must sit on white). `false` drops Nuxt
      // UI's color-mode plugin (`useDark()` from @vueuse/core), so nothing ever adds the `dark`
      // class to <html> or reads/writes `vueuse-color-scheme`, and the color-mode components
      // (UColorModeButton, …) are not registered.
      colorMode: false,
      ui: {
        colors: {
          primary: 'primary',
          secondary: 'secondary',
        },
        // Solid buttons (WCAG 2.1 AA 1.4.3, increment 5k). Nuxt UI lightens a solid button to its
        // 75 % tint on hover and press (`hover:bg-x/75`), and the white label then falls below
        // 4.5:1 (white text on the tint over white / on shade 900 instead):
        //   secondary 800 → /75 3.91, 900 #354415 10.56
        //   success   800 → /75 4.05, 900 #0d542b  9.07
        //   warning   800 → /75 3.91, 900 #733e0a  8.69  (Nuxt UI's warning is Tailwind yellow)
        //   info      700 → /75 4.12, 900 #1c398e 10.40
        // so these darken to shade 900 instead (tailwind-merge replaces the default classes).
        // Primary (#11395c, 5.63 at 75 %) and error (700 #c10007, 4.66) keep the default. Class
        // names are written out in full so Tailwind's source scan finds them. Other variants
        // (outline, soft, subtle, ghost, link) are unchanged.
        button: {
          compoundVariants: [
            {
              color: 'secondary',
              variant: 'solid',
              class: 'hover:bg-secondary-900 active:bg-secondary-900',
            },
            {
              color: 'success',
              variant: 'solid',
              class: 'hover:bg-success-900 active:bg-success-900',
            },
            {
              color: 'warning',
              variant: 'solid',
              class: 'hover:bg-warning-900 active:bg-warning-900',
            },
            { color: 'info', variant: 'solid', class: 'hover:bg-info-900 active:bg-info-900' },
          ],
        },
      },
    }),
  ],
  server: {
    // Same-origin backend paths that the production container nginx (frontend/nginx.conf) routes
    // to the backend: uploaded images (`/static/uploads/...`), the Atom feeds, sitemap.xml and
    // robots.txt. In dev the browser talks to Vite, so proxy them to the backend too; inside
    // docker compose the target is the backend service, not localhost. (The API itself is
    // reached directly through VITE_API_BASE_URL in dev.)
    proxy: Object.fromEntries(
      ['/static', '/feeds', '/sitemap.xml', '/robots.txt'].map((prefix) => [
        prefix,
        {
          target: process.env.VITE_DEV_PROXY_TARGET ?? 'http://localhost:8000',
          changeOrigin: true,
        },
      ]),
    ),
    fs: {
      // The legal texts are imported (`?legal`, see above) from docs/legal/ at the repository root, outside this
      // project. Allow only that folder, plus Vite's default (the workspace root), so the dev
      // server never serves the rest of the repository (backend, .env files) through /@fs/.
      allow: [
        searchForWorkspaceRoot(process.cwd()),
        fileURLToPath(new URL('../docs/legal', import.meta.url)),
      ],
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    setupFiles: ['./src/__tests__/setup.ts'],
    include: ['src/**/*.spec.ts'],
    // Playwright specs (e2e/) run with `npm run e2e`, never under vitest.
    exclude: [...configDefaults.exclude, 'e2e/**'],
    css: false,
    server: {
      deps: {
        // Nuxt UI ships .vue/.css runtime files that must go through Vite's transform pipeline.
        inline: ['@nuxt/ui'],
      },
    },
  },
}))

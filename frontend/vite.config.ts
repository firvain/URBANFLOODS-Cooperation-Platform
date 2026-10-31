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
      },
    }),
  ],
  server: {
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

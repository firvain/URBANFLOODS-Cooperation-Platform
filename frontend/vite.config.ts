/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import ui from '@nuxt/ui/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [
    vue(),
    // Devtools only in interactive dev; it injects client code that is useless under vitest.
    mode !== 'test' && vueDevTools(),
    ui({
      // Bundle the Lucide icons we use (and Nuxt UI's defaults) into the build, so the browser
      // never fetches icons from the third-party Iconify API.
      icon: { clientBundle: { scan: true } },
      ui: {
        colors: {
          primary: 'primary',
          secondary: 'secondary',
        },
      },
    }),
  ],
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
    css: false,
    server: {
      deps: {
        // Nuxt UI ships .vue/.css runtime files that must go through Vite's transform pipeline.
        inline: ['@nuxt/ui'],
      },
    },
  },
}))

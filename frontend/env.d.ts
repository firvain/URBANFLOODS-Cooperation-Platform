/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  /**
   * Cloudflare Turnstile site key; when unset no form renders the captcha (register, resend
   * verification, forgot password) and submit does not wait for a token.
   */
  readonly VITE_TURNSTILE_SITE_KEY?: string
  /** Unified DSS web app; when empty the DSS nav item and home card are hidden. */
  readonly VITE_DSS_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

/** `docs/legal/*.md?legal`: prepared at build time by the `legalDocuments` plugin (vite.config.ts). */
declare module '*.md?legal' {
  const document: import('./src/utils/legalDocument').LegalDocument
  export default document
}

/**
 * Cloudflare Turnstile configuration. The site key (`VITE_TURNSTILE_SITE_KEY`) is absent in dev
 * and tests, where the backend runs with `TURNSTILE_ENABLED=false`: the widget then renders
 * nothing and forms submit without a token. Read at call time (not cached at import) so tests can
 * stub the variable, like `dssUrl()`.
 */

/** Global name the script calls once `window.turnstile` is ready (`onload=` below). */
export const TURNSTILE_ONLOAD = 'ufTurnstileOnload'

/** Loaded once, explicit rendering only (the CSP allows script-src challenges.cloudflare.com). */
export const TURNSTILE_SCRIPT_SRC = `https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=${TURNSTILE_ONLOAD}`

export function turnstileSiteKey(): string {
  return (import.meta.env.VITE_TURNSTILE_SITE_KEY ?? '').trim()
}

/** Whether forms must wait for a Turnstile token before they can submit. */
export function turnstileRequired(): boolean {
  return turnstileSiteKey() !== ''
}

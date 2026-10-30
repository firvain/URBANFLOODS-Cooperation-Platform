/**
 * Open-redirect guard for `?next=`: only same-origin absolute paths are accepted.
 * `//host` and `/\host` are protocol-relative to browsers, so they are rejected too.
 */
export function safeRedirect(next: unknown): string | null {
  if (typeof next !== 'string' || !next.startsWith('/')) return null
  if (next.startsWith('//') || next.startsWith('/\\')) return null
  return next
}

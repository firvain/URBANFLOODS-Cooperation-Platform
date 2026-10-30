import { randomBytes } from 'node:crypto'

/** A fresh address per run, so tests never collide with earlier accounts or rate-limit keys. */
export function uniqueEmail(prefix: string): string {
  return `e2e+${prefix}-${Date.now()}-${randomBytes(2).toString('hex')}@example.org`
}

/** A random password well above the 10-character minimum (src/constants/auth.ts). */
export function strongPassword(): string {
  return `E2e-${randomBytes(12).toString('base64url')}-pass`
}

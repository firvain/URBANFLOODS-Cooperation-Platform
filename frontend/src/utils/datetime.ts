/**
 * Dates of posts and events. Display uses `Intl` in the UI locale (English as a fallback);
 * the editor converts between `<input type="datetime-local">` values (local wall time, no zone)
 * and ISO 8601 strings with the local UTC offset, which the API requires (`AwareDatetime`).
 */

/** "20 Oct 2026" in `locale`. */
export function formatDate(iso: string, locale: string): string {
  return new Intl.DateTimeFormat([locale, 'en'], { dateStyle: 'medium' }).format(new Date(iso))
}

/** "20 Nov 2026, 18:00" in `locale`. */
export function formatDateTime(iso: string, locale: string): string {
  return new Intl.DateTimeFormat([locale, 'en'], {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso))
}

const pad = (n: number) => String(Math.abs(n)).padStart(2, '0')

/** `2026-11-20T18:00` (local time) → `2026-11-20T18:00:00+02:00`; `null` when empty/invalid. */
export function localInputToIso(value: string): string | null {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  const offset = -date.getTimezoneOffset()
  const sign = offset >= 0 ? '+' : '-'
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:00` +
    `${sign}${pad(Math.trunc(offset / 60))}:${pad(offset % 60)}`
  )
}

/** An ISO date-time → the `datetime-local` value in local time (`''` when empty/invalid). */
export function isoToLocalInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

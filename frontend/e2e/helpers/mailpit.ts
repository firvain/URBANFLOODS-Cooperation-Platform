/**
 * Minimal client for the Mailpit REST API (https://mailpit.axllent.org/docs/api-v1/), used to
 * read the emails the dev backend sends (verification, password reset, …).
 */

export const MAILPIT_URL = process.env.E2E_MAILPIT_URL ?? 'http://localhost:8025'
/** The backend's FRONTEND_URL: the prefix of every link in the emails. */
export const FRONTEND_URL =
  process.env.E2E_FRONTEND_URL ?? process.env.E2E_BASE_URL ?? 'http://localhost:5173'

interface Address {
  Name: string
  Address: string
}

/** A message summary as returned by the list/search endpoints. */
export interface MessageSummary {
  ID: string
  Subject: string
  To: Address[]
  Created: string
}

/** A full message (`GET /api/v1/message/{ID}`). */
export interface Message {
  ID: string
  Subject: string
  To: Address[]
  Date: string
  Text: string
  HTML: string
}

interface MessagesResponse {
  total: number
  messages: MessageSummary[]
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${MAILPIT_URL}/api/v1${path}`, init)
  if (!res.ok) throw new Error(`Mailpit ${init?.method ?? 'GET'} ${path}: HTTP ${res.status}`)
  const type = res.headers.get('content-type') ?? ''
  return (type.includes('application/json') ? await res.json() : await res.text()) as T
}

/** Delete every message in the mailbox (shared dev mailbox: use sparingly). */
export async function clearMailbox(): Promise<void> {
  await api<string>('/messages', { method: 'DELETE' })
}

/** Delete only the messages sent to `address`. */
export async function clearMailboxFor(address: string): Promise<void> {
  const query = new URLSearchParams({ query: `to:"${address}"` })
  await api<string>(`/search?${query}`, { method: 'DELETE' })
}

export interface WaitForEmailOptions {
  /** Only messages whose subject contains this text (case-sensitive). */
  subjectIncludes?: string
  /** Only messages received at or after this moment (ignores older mails to the same address). */
  since?: Date
  timeoutMs?: number
  intervalMs?: number
}

/** Poll Mailpit until a message to `address` arrives; returns the newest match in full. */
export async function waitForEmailTo(
  address: string,
  { subjectIncludes, since, timeoutMs = 15_000, intervalMs = 250 }: WaitForEmailOptions = {},
): Promise<Message> {
  const query = new URLSearchParams({ query: `to:"${address}"`, limit: '50' })
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const { messages } = await api<MessagesResponse>(`/search?${query}`)
    // Search results are newest first.
    const match = messages.find(
      (m) =>
        (!subjectIncludes || m.Subject.includes(subjectIncludes)) &&
        (!since || new Date(m.Created).getTime() >= since.getTime() - 1000),
    )
    if (match) return api<Message>(`/message/${match.ID}`)
    if (Date.now() > deadline) {
      const what = subjectIncludes ? ` with subject containing "${subjectIncludes}"` : ''
      throw new Error(`No email to ${address}${what} within ${timeoutMs} ms`)
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
}

/**
 * The first URL in the plain-text body that starts with `<FRONTEND_URL><pathPrefix>`
 * (e.g. `/verify-email`). Throws if there is none.
 */
export function extractLink(message: Message, pathPrefix: string): string {
  const prefix = `${FRONTEND_URL.replace(/\/$/, '')}${pathPrefix}`
  const url = message.Text.match(/https?:\/\/\S+/g)?.find((u) => u.startsWith(prefix))
  if (!url) throw new Error(`No link starting with ${prefix} in "${message.Subject}"`)
  return url
}

/** How many messages to `address` the mailbox holds (optionally only those whose subject contains `subjectIncludes`). */
export async function countEmailsTo(address: string, subjectIncludes?: string): Promise<number> {
  const query = new URLSearchParams({ query: `to:"${address}"`, limit: '50' })
  const { messages } = await api<MessagesResponse>(`/search?${query}`)
  return messages.filter((m) => !subjectIncludes || m.Subject.includes(subjectIncludes)).length
}

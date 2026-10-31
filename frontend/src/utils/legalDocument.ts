export interface LegalDocument {
  /** Version number from the first bold line ("Version 1 (draft …), 31 October 2026."). */
  version: string | null
  /** Date from the same line, as written ("31 October 2026"). */
  date: string | null
  /** The publishable markdown: no title, no draft paragraph, no reviewer notes, no CHECK markers. */
  markdown: string
}

const VERSION_LINE = /^\*\*Version\s+(\d+)\b[^*]*?,\s*([^*]+?)\.?\*\*/m
const REVIEWER_NOTES = /^##\s+Notes for the reviewer[\s\S]*$/m
/** `**[CHECK]**`, `**[CHECK: …]**`, `**[CHECK with …]**`, possibly across lines. */
const CHECK_MARKER = /[ \t]*\n?[ \t]*\*\*\[CHECK\b[^\]]*\]\*\*/g
const HORIZONTAL_RULE = /^(?:-{3,}|\*{3,}|_{3,})\s*$/

/**
 * Turn a `docs/legal/*.md` source into what the platform publishes. The files are the single
 * source of truth but carry reviewer material (draft status, increments, `[CHECK]` items, notes
 * for the reviewer) that must never ship.
 */
export function prepareLegalDocument(raw: string): LegalDocument {
  const source = raw.replace(/\r\n?/g, '\n')
  const match = source.match(VERSION_LINE)

  const paragraphs = source
    .replace(REVIEWER_NOTES, '')
    .replace(CHECK_MARKER, '')
    .split(/\n{2,}/)
    .map((block) => block.replace(/^\n+|\s+$/g, ''))
    .filter(Boolean)

  // Leading title (`# …`), draft paragraph and rules; trailing rules.
  while (paragraphs.length) {
    const first = paragraphs[0]!
    if (/^#\s/.test(first) || first.startsWith('**Version') || HORIZONTAL_RULE.test(first)) {
      paragraphs.shift()
    } else break
  }
  while (paragraphs.length && HORIZONTAL_RULE.test(paragraphs[paragraphs.length - 1]!)) {
    paragraphs.pop()
  }

  return {
    version: match?.[1] ?? null,
    date: match?.[2]?.trim() ?? null,
    markdown: paragraphs.join('\n\n') + '\n',
  }
}

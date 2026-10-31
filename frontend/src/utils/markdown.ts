import { Marked, type Tokens } from 'marked'

export interface MarkdownHeading {
  depth: number
  /** Element id, always prefixed `section-` so it can never clobber a DOM property. */
  id: string
  /** Plain text of the heading (no markup). */
  text: string
}

export interface RenderedMarkdown {
  /** Unsanitised HTML: render it only through `SafeHtml`. */
  html: string
  /** h2 and h3 headings in document order, with the ids written into `html`. */
  headings: MarkdownHeading[]
}

/** Headings that get an id (and appear in `headings`). */
const ANCHORED_DEPTHS = new Set([2, 3])

function slugify(text: string): string {
  const slug = text
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return `section-${slug || 'heading'}`
}

/**
 * Markdown (GFM) to HTML with ids on h2/h3 headings for in-page links, and tables wrapped in a
 * focusable, horizontally scrollable container (keyboard users can scroll wide tables).
 * A fresh `Marked` instance per call keeps the id bookkeeping local and the global `marked` clean.
 */
export function renderMarkdown(markdown: string): RenderedMarkdown {
  const headings: MarkdownHeading[] = []
  const used = new Map<string, number>()

  const marked = new Marked({
    gfm: true,
    renderer: {
      heading({ tokens, depth }: Tokens.Heading) {
        if (!ANCHORED_DEPTHS.has(depth)) return false
        const text = this.parser.parseInline(tokens, this.parser.textRenderer).trim()
        const base = slugify(text)
        const count = (used.get(base) ?? 0) + 1
        used.set(base, count)
        const id = count === 1 ? base : `${base}-${count}`
        headings.push({ depth, id, text })
        return `<h${depth} id="${id}">${this.parser.parseInline(tokens)}</h${depth}>\n`
      },
    },
  })

  const html = (marked.parse(markdown, { async: false }) as string)
    .replaceAll('<table>', '<div class="legal-table overflow-x-auto" tabindex="0"><table>')
    .replaceAll('</table>', '</table></div>')
  return { html, headings }
}

import DOMPurify from 'dompurify'

/**
 * Allowed link targets: http, https and mailto, plus scheme-less URLs (relative paths and
 * `#fragment` anchors). Everything else (`javascript:`, `data:`, `tel:`, `ftp:` …) is dropped.
 * Same shape as DOMPurify's default pattern, with the scheme list narrowed.
 */
const ALLOWED_URI_REGEXP = /^(?:(?:https?|mailto):|[^a-z]|[a-z+.-]+(?:[^a-z+.\-:]|$))/i

/** Absolute http(s) URL on another origin. */
function isExternal(href: string): boolean {
  if (!/^https?:\/\//i.test(href)) return false
  try {
    return new URL(href).origin !== window.location.origin
  } catch {
    return true
  }
}

/**
 * A private DOMPurify instance, so its hook never affects other code using the default one.
 * External links open in a new tab without `window.opener` or a referrer; any other link loses
 * a `target` the input may have smuggled in.
 */
const purifier = DOMPurify(window)
purifier.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName !== 'A') return
  const href = node.getAttribute('href') ?? ''
  if (isExternal(href)) {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  } else {
    node.removeAttribute('target')
  }
})

/** Sanitise an HTML string for `v-html`. Use through `components/common/SafeHtml.vue`. */
export function sanitizeHtml(html: string): string {
  return purifier.sanitize(html, { ALLOWED_URI_REGEXP })
}

/*
 * Rich-text editor output. `normalizeHtml` keeps exactly the subset the backend sanitiser (nh3)
 * accepts, so what the editor emits is stored unchanged. Keep these lists in step with the
 * backend allow-list.
 */

/** Elements the editor may emit (backend nh3 allow-list). */
// prettier-ignore
export const EDITOR_ALLOWED_TAGS: readonly string[] = [
  'p', 'br', 'h2', 'h3', 'h4', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'strong', 'em', 'u',
  's', 'a', 'img', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'sup', 'sub',
]

/**
 * Attributes DOMPurify lets through; the hook below narrows them per element (`class` only as
 * `language-*` on code/pre, `target` only `_blank`, image `src` only http(s) or uploads, …).
 */
const EDITOR_ALLOWED_ATTR = [
  'href',
  'title',
  'target',
  'rel',
  'src',
  'alt',
  'width',
  'height',
  'class',
]

/** Attributes each element keeps (after DOMPurify's global pass). */
const EDITOR_ATTRS_BY_TAG: Record<string, readonly string[]> = {
  A: ['href', 'title', 'target', 'rel'],
  IMG: ['src', 'alt', 'title', 'width', 'height'],
  CODE: ['class'],
  PRE: ['class'],
}

/** Headings outside levels 2–4 are mapped to the nearest allowed level. */
const HEADING_MAP: Record<string, string> = { H1: 'h2', H5: 'h4', H6: 'h4' }

const LANGUAGE_CLASS = /^language-[\w+#-]+$/
const IMAGE_SRC = /^(?:https?:\/\/|\/static\/uploads\/)/i
const DIMENSION = /^\d{1,5}$/

/** The DOMPurify configuration of the editor; use through `normalizeHtml`. */
export const editorPurifyConfig = {
  ALLOWED_TAGS: [...EDITOR_ALLOWED_TAGS],
  ALLOWED_ATTR: EDITOR_ALLOWED_ATTR,
  ALLOWED_URI_REGEXP,
  ALLOW_DATA_ATTR: false,
  ALLOW_ARIA_ATTR: false,
  KEEP_CONTENT: true,
}

const editorPurifier = DOMPurify(window)
editorPurifier.addHook('afterSanitizeAttributes', (node) => {
  const kept = EDITOR_ATTRS_BY_TAG[node.tagName] ?? []
  for (const name of node.getAttributeNames()) {
    if (!kept.includes(name)) node.removeAttribute(name)
  }
  switch (node.tagName) {
    case 'A':
      if (node.getAttribute('target') === '_blank') {
        node.setAttribute('rel', 'noopener noreferrer')
      } else {
        node.removeAttribute('target')
        node.removeAttribute('rel')
      }
      break
    case 'IMG':
      if (!IMAGE_SRC.test(node.getAttribute('src') ?? '')) {
        node.remove()
        return
      }
      for (const name of ['width', 'height']) {
        const value = node.getAttribute(name)
        if (value !== null && !DIMENSION.test(value)) node.removeAttribute(name)
      }
      break
    case 'CODE':
    case 'PRE': {
      const value = node.getAttribute('class')
      if (value !== null && !LANGUAGE_CLASS.test(value)) node.removeAttribute('class')
      break
    }
  }
})

/** Rename h1/h5/h6 to the nearest allowed heading level (in an inert document). */
function remapHeadings(html: string): string {
  if (!/<h[156][\s>]/i.test(html)) return html
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html')
  for (const heading of Array.from(doc.body.querySelectorAll('h1, h5, h6'))) {
    const replacement = doc.createElement(HEADING_MAP[heading.tagName]!)
    replacement.append(...Array.from(heading.childNodes))
    heading.replaceWith(replacement)
  }
  return doc.body.innerHTML
}

/**
 * Reduce editor HTML (initial values, pasted HTML, the editor's own output) to the backend
 * allow-list: unknown elements are unwrapped (their text kept), scripts and styles dropped,
 * links limited to http/https/mailto (`rel="noopener noreferrer"` with `target="_blank"`),
 * images to http(s) or `/static/uploads/` sources.
 */
export function normalizeHtml(html: string): string {
  if (!html) return ''
  return editorPurifier.sanitize(remapHeadings(html), editorPurifyConfig)
}

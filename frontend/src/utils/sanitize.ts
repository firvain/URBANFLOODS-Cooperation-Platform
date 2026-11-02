import DOMPurify from 'dompurify'

import { EXTERNAL_LINKS } from '@/constants/links'

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

export interface SanitizeOptions {
  /**
   * Keep only these elements, without any attribute (the text of every other element is kept;
   * scripts and styles are dropped with their content). For text with light markup, such as
   * search snippets (`['mark']`). Without it the rich-text configuration applies.
   */
  allowedTags?: readonly string[]
}

/** Sanitise an HTML string for `v-html`. Use through `components/common/SafeHtml.vue`. */
export function sanitizeHtml(html: string, options: SanitizeOptions = {}): string {
  if (options.allowedTags) {
    return purifier.sanitize(html, {
      ALLOWED_TAGS: [...options.allowedTags],
      ALLOWED_ATTR: [],
      ALLOW_DATA_ATTR: false,
      ALLOW_ARIA_ATTR: false,
    })
  }
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
 * `language-*` on code/pre, `target` only `_blank`, image `src` only uploads or the KNOWBASE, …).
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
const DIMENSION = /^\d{1,5}$/

/*
 * Image sources (7n, owner's decision 2026-11-02): only our uploads and the KNOWBASE, the two
 * sources the production CSP (`img-src 'self' data: blob: https://knowbase.urbanfloods.app`)
 * lets readers' browsers load. Mirrors `_allowed_img_src` in backend `services/sanitize.py`.
 */
const UPLOADS_PREFIX = '/static/uploads/'
const KNOWBASE_ORIGIN = new URL(EXTERNAL_LINKS.knowbase).origin
// Whitespace, control characters and backslashes never pass (browsers read `\` as `/`).
const UNSAFE_URL_CHARS = /[\s\x00-\x1f\x7f\\]/
// A dot segment, literal or percent-encoded (browsers decode `%2e` segments), or an encoded `\`.
const PATH_TRICKS = /\.\.|%2e|%5c/i
const ABSOLUTE_HTTP = /^https?:\/\/([^/?#]*)/i

function uploadPath(path: string): string | null {
  return path.startsWith(UPLOADS_PREFIX) && !PATH_TRICKS.test(path) ? path : null
}

/**
 * The `src` to keep for an image, or `null` to drop the image: a path under `/static/uploads/`;
 * an upload URL on our own origin (`window.location.origin`), as that path; an https URL on the
 * KNOWBASE origin. Origins compare scheme, host and port (the URL parser lower-cases them and
 * drops a default port); credentials never pass.
 */
export function allowedImageSrc(src: string): string | null {
  if (UNSAFE_URL_CHARS.test(src)) return null
  if (src.startsWith(UPLOADS_PREFIX)) return uploadPath(src)
  const authority = ABSOLUTE_HTTP.exec(src)?.[1]
  if (!authority || authority.includes('@')) return null
  let url: URL
  try {
    url = new URL(src)
  } catch {
    return null
  }
  if (url.origin === window.location.origin) {
    if (url.search || url.hash || PATH_TRICKS.test(src)) return null
    return uploadPath(url.pathname)
  }
  return url.origin === KNOWBASE_ORIGIN && url.protocol === 'https:' ? src : null
}

/** Set while `normalizeHtml` runs with `onImageDropped` (sanitising is synchronous). */
let reportDroppedImage: ((src: string) => void) | undefined

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
    case 'IMG': {
      const src = node.getAttribute('src') ?? ''
      const kept = allowedImageSrc(src)
      if (kept === null) {
        reportDroppedImage?.(src)
        node.remove()
        return
      }
      if (kept !== src) node.setAttribute('src', kept)
      for (const name of ['width', 'height']) {
        const value = node.getAttribute(name)
        if (value !== null && !DIMENSION.test(value)) node.removeAttribute(name)
      }
      break
    }
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

export interface NormalizeOptions {
  /** Called with the `src` of every image dropped for its source (the editor explains why). */
  onImageDropped?: (src: string) => void
}

/**
 * Reduce editor HTML (initial values, pasted HTML, the editor's own output) to the backend
 * allow-list: unknown elements are unwrapped (their text kept), scripts and styles dropped,
 * links limited to http/https/mailto (`rel="noopener noreferrer"` with `target="_blank"`),
 * images to our uploads and the KNOWBASE (`allowedImageSrc`).
 */
export function normalizeHtml(html: string, options: NormalizeOptions = {}): string {
  if (!html) return ''
  reportDroppedImage = options.onImageDropped
  try {
    return editorPurifier.sanitize(remapHeadings(html), editorPurifyConfig)
  } finally {
    reportDroppedImage = undefined
  }
}

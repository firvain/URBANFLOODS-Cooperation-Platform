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

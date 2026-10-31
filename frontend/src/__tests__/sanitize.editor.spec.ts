import { describe, expect, it } from 'vitest'

import { EDITOR_ALLOWED_TAGS, normalizeHtml } from '@/utils/sanitize'

/** Tag names (lower case) used anywhere in `html`. */
function tagsIn(html: string): string[] {
  const div = document.createElement('div')
  div.innerHTML = html
  return [...new Set(Array.from(div.querySelectorAll('*'), (el) => el.tagName.toLowerCase()))]
}

function parse(html: string): HTMLElement {
  const div = document.createElement('div')
  div.innerHTML = html
  return div
}

describe('normalizeHtml (editor output allow-list, mirrors the backend nh3 config)', () => {
  it('keeps the whole allowed subset', () => {
    const html =
      '<h2>T</h2><h3>a</h3><h4>b</h4><p>x<br><strong>b</strong><em>i</em><u>u</u><s>s</s>' +
      '<sup>1</sup><sub>2</sub><code>c</code></p><ul><li><p>one</p></li></ul><ol><li>two</li></ol>' +
      '<blockquote><p>q</p></blockquote><pre><code class="language-python">x = 1</code></pre><hr>' +
      '<table><thead><tr><th>h</th></tr></thead><tbody><tr><td>d</td></tr></tbody></table>'
    const clean = normalizeHtml(html)
    expect(tagsIn(clean).sort()).toEqual(
      [
        'h2',
        'h3',
        'h4',
        'p',
        'br',
        'strong',
        'em',
        'u',
        's',
        'sup',
        'sub',
        'code',
        'ul',
        'li',
        'ol',
        'blockquote',
        'pre',
        'hr',
        'table',
        'thead',
        'tr',
        'th',
        'tbody',
        'td',
      ].sort(),
    )
    expect(clean).toContain('<code class="language-python">')
  })

  it('every tag it can emit is in the backend allow-list', () => {
    expect([...EDITOR_ALLOWED_TAGS].sort()).toEqual(
      [
        'p',
        'br',
        'h2',
        'h3',
        'h4',
        'ul',
        'ol',
        'li',
        'blockquote',
        'pre',
        'code',
        'strong',
        'em',
        'u',
        's',
        'a',
        'img',
        'hr',
        'table',
        'thead',
        'tbody',
        'tr',
        'th',
        'td',
        'sup',
        'sub',
      ].sort(),
    )
  })

  it('removes scripts, event handlers, styles, ids and unknown elements (keeping their text)', () => {
    const clean = normalizeHtml(
      '<p id="x" style="color:red" data-x="1" aria-label="l">a</p><script>alert(1)</script>' +
        '<div onclick="alert(1)"><span class="c">kept</span></div><iframe src="https://e.org"></iframe>' +
        '<style>p{}</style><font>f</font>',
    )
    expect(clean).not.toMatch(
      /script|onclick|style|iframe|font|span|div|id=|data-x|aria-label|class=/,
    )
    expect(clean).toContain('kept')
    expect(clean).toContain('<p>a</p>')
  })

  it('maps h1 to h2 and h5/h6 to h4', () => {
    expect(normalizeHtml('<h1>A</h1><h5>B</h5><h6>C</h6>')).toBe('<h2>A</h2><h4>B</h4><h4>C</h4>')
  })

  it('keeps only language-* classes on code and pre', () => {
    const clean = normalizeHtml(
      '<pre class="hljs"><code class="language-js extra">x</code></pre><p class="language-js">p</p>',
    )
    expect(clean).toBe('<pre><code>x</code></pre><p>p</p>')
    expect(normalizeHtml('<pre><code class="language-ts">x</code></pre>')).toBe(
      '<pre><code class="language-ts">x</code></pre>',
    )
  })

  it('allows only http, https and mailto links; adds rel to target=_blank only', () => {
    const el = parse(
      normalizeHtml(
        '<a id="a" href="https://e.org" target="_blank">n</a><a href="http://e.org" target="_top" rel="opener">o</a>' +
          '<a href="mailto:x@e.org" title="Mail">m</a><a href="javascript:alert(1)">j</a><a href="data:text/html,x">d</a>',
      ),
    )
    const links = Array.from(el.querySelectorAll('a'))
    expect(links[0]!.getAttribute('target')).toBe('_blank')
    expect(links[0]!.getAttribute('rel')).toBe('noopener noreferrer')
    expect(links[1]!.hasAttribute('target')).toBe(false)
    expect(links[1]!.hasAttribute('rel')).toBe(false)
    expect(links[2]!.getAttribute('title')).toBe('Mail')
    expect(links[2]!.getAttribute('href')).toBe('mailto:x@e.org')
    expect(links[3]!.hasAttribute('href')).toBe(false)
    expect(links[4]!.hasAttribute('href')).toBe(false)
    expect(el.querySelector('#a')).toBeNull()
  })

  it('keeps images from http(s) or /static/uploads/ with alt, title and numeric size; drops others', () => {
    const el = parse(
      normalizeHtml(
        '<img src="/static/uploads/2026/10/a.webp" alt="A" width="640" height="480" title="T">' +
          '<img src="https://knowbase.urbanfloods.app/static/x.jpg" alt="B" width="100%" onerror="x()">' +
          '<img src="data:image/png;base64,AAAA" alt="C"><img src="/elsewhere/d.png" alt="D">' +
          '<img src="javascript:alert(1)" alt="E">',
      ),
    )
    const imgs = Array.from(el.querySelectorAll('img'))
    expect(imgs.map((i) => i.getAttribute('alt'))).toEqual(['A', 'B'])
    expect(imgs[0]!.getAttribute('width')).toBe('640')
    expect(imgs[0]!.getAttribute('height')).toBe('480')
    expect(imgs[0]!.getAttribute('title')).toBe('T')
    expect(imgs[1]!.hasAttribute('width')).toBe(false)
    expect(imgs[1]!.hasAttribute('onerror')).toBe(false)
  })

  it('returns an empty string for empty input', () => {
    expect(normalizeHtml('')).toBe('')
  })
})

import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import SafeHtml from '@/components/common/SafeHtml.vue'
import { sanitizeHtml } from '@/utils/sanitize'

const mounted: ReturnType<typeof mount>[] = []
afterEach(() => {
  while (mounted.length) mounted.pop()!.unmount()
})

function render(html: string, tag?: string) {
  const wrapper = mount(SafeHtml, { props: tag ? { html, tag } : { html } })
  mounted.push(wrapper)
  return wrapper
}

describe('sanitizeHtml', () => {
  it('removes javascript: URLs, scripts and event handlers', () => {
    const clean = sanitizeHtml(
      '<p><a href="javascript:alert(1)">x</a><img src="x" onerror="alert(1)"><script>alert(1)</script></p>',
    )
    expect(clean).not.toContain('javascript:')
    expect(clean).not.toContain('onerror')
    expect(clean).not.toContain('<script')
    expect(clean).toContain('>x</a>')
  })

  it('allows only http, https and mailto schemes (plus relative and fragment links)', () => {
    const div = document.createElement('div')
    div.innerHTML = sanitizeHtml(
      [
        '<a id="a1" href="https://example.org/">https</a>',
        '<a id="a2" href="http://example.org/">http</a>',
        '<a id="a3" href="mailto:someone@example.org">mail</a>',
        '<a id="a4" href="#section-1">fragment</a>',
        '<a id="a5" href="/terms">relative</a>',
        '<a id="a6" href="data:text/html,hi">data</a>',
        '<a id="a7" href="ftp://example.org/">ftp</a>',
        '<a id="a8" href="tel:+3000">tel</a>',
      ].join(''),
    )
    const href = (id: string) => div.querySelector(`#${id}`)?.getAttribute('href') ?? null
    expect(href('a1')).toBe('https://example.org/')
    expect(href('a2')).toBe('http://example.org/')
    expect(href('a3')).toBe('mailto:someone@example.org')
    expect(href('a4')).toBe('#section-1')
    expect(href('a5')).toBe('/terms')
    expect(href('a6')).toBeNull()
    expect(href('a7')).toBeNull()
    expect(href('a8')).toBeNull()
  })

  it('opens external links in a new tab without opener or referrer', () => {
    const div = document.createElement('div')
    div.innerHTML = sanitizeHtml(
      '<a id="ext" href="https://www.dpa.gr">dpa</a><a id="mail" href="mailto:a@b.c">m</a><a id="frag" href="#x">f</a><a id="rel" href="/privacy">p</a>',
    )
    const ext = div.querySelector('#ext')!
    expect(ext.getAttribute('target')).toBe('_blank')
    expect(ext.getAttribute('rel')).toContain('noopener')
    expect(ext.getAttribute('rel')).toContain('noreferrer')
    for (const id of ['mail', 'frag', 'rel']) {
      expect(div.querySelector(`#${id}`)!.hasAttribute('target'), id).toBe(false)
    }
  })

  it('drops a target smuggled into an internal link', () => {
    const div = document.createElement('div')
    div.innerHTML = sanitizeHtml('<a href="/terms" target="_top">t</a>')
    expect(div.querySelector('a')!.hasAttribute('target')).toBe(false)
  })
})

describe('SafeHtml', () => {
  it('renders sanitised HTML in a div by default', () => {
    const wrapper = render(
      '<p>Hello <a href="javascript:alert(1)">there</a></p><script>x()</script>',
    )
    expect(wrapper.element.tagName).toBe('DIV')
    expect(wrapper.find('p').text()).toBe('Hello there')
    expect(wrapper.html()).not.toContain('javascript:')
    expect(wrapper.find('script').exists()).toBe(false)
  })

  it('keeps mailto links and marks external links', () => {
    const wrapper = render(
      '<p><a href="mailto:louta@uowm.gr">louta@uowm.gr</a> <a href="https://www.dpa.gr">dpa</a></p>',
    )
    const [mail, ext] = wrapper.findAll('a')
    expect(mail!.attributes('href')).toBe('mailto:louta@uowm.gr')
    expect(mail!.attributes('target')).toBeUndefined()
    expect(ext!.attributes('target')).toBe('_blank')
    expect(ext!.attributes('rel')).toContain('noopener')
  })

  it('renders into the requested tag and updates with the html prop', async () => {
    const wrapper = render('<p>one</p>', 'section')
    expect(wrapper.element.tagName).toBe('SECTION')
    await wrapper.setProps({ html: '<p>two</p>' })
    expect(wrapper.text()).toBe('two')
  })
})

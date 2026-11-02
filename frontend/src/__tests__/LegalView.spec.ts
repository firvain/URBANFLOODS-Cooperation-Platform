import { afterEach, describe, expect, it } from 'vitest'

import termsMd from '../../../docs/legal/terms-of-use.md?raw'
import privacyMd from '../../../docs/legal/privacy-policy.md?raw'
import accessibilityMd from '../../../docs/legal/accessibility-statement.md?raw'
import openDataMd from '../../../docs/legal/open-data.md?raw'
import type { LegalDoc } from '@/constants/legal'
import { LEGAL_DOCUMENTS } from '@/content/legal'
import i18n, { setLocale } from '@/i18n'
import { prepareLegalDocument } from '@/utils/legalDocument'
import { renderMarkdown } from '@/utils/markdown'
import LegalView from '@/views/LegalView.vue'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t

afterEach(() => {
  setLocale('en')
  unmountAll()
})

async function mountLegal(doc: LegalDoc) {
  const { wrapper } = await mountWithApp(LegalView, { path: `/${doc}`, props: { doc } })
  return wrapper
}

/** The numbered `## n. Title` headings of a source document (the published sections). */
function sourceSections(raw: string): string[] {
  return Array.from(raw.matchAll(/^## (\d+\. .+)$/gm), (m) => m[1]!.trim())
}

const SAMPLE = [
  '# Terms of Use — Sample',
  '',
  '**Version 3 (draft for legal review), 5 May 2027.** This is the text for increment 9. Items',
  'marked **[CHECK]** need confirmation.',
  '',
  '---',
  '',
  '## 1. First',
  '',
  'Age 16 **[CHECK: Greek law sets 15',
  'as the age of digital consent]**, see the courts of Kozani',
  '**[CHECK with UOWM legal office]**. Backups are kept for 14 days **[CHECK]**.',
  '',
  '## 2. Second',
  '',
  'Text.',
  '',
  '---',
  '',
  '## Notes for the reviewer (not part of the terms)',
  '',
  '- secret reviewer note',
].join('\n')

describe('prepareLegalDocument', () => {
  it('parses the version number and date from the first bold line', () => {
    const doc = prepareLegalDocument(SAMPLE)
    expect(doc.version).toBe('3')
    expect(doc.date).toBe('5 May 2027')
  })

  it('strips the title, the draft paragraph, the reviewer notes and every CHECK marker', () => {
    const { markdown } = prepareLegalDocument(SAMPLE)
    expect(markdown.startsWith('## 1. First')).toBe(true)
    expect(markdown.trimEnd().endsWith('Text.')).toBe(true)
    for (const gone of [
      '# Terms of Use',
      'Version 3',
      'increment',
      'draft',
      '[CHECK',
      'Notes for the reviewer',
      'secret reviewer note',
      '---',
    ]) {
      expect(markdown, gone).not.toContain(gone)
    }
    expect(markdown).toContain('Age 16, see the courts of Kozani.')
    expect(markdown).toContain('kept for 14 days.')
  })

  it('removes the CHECK markers from every real document', () => {
    for (const raw of [termsMd, privacyMd, accessibilityMd, openDataMd]) {
      const { markdown, version, date } = prepareLegalDocument(raw)
      expect(markdown).not.toMatch(/CHECK/)
      expect(markdown).not.toContain('Notes for the reviewer')
      expect(markdown).not.toMatch(/increment/i)
      expect(version).toBe('1')
      // The privacy policy was revised on 2 Nov 2026 (v1.3, 7m); the other texts are unchanged.
      expect(date).toBe(raw === privacyMd ? '2 November 2026' : '31 October 2026')
    }
  })
})

describe('LEGAL_DOCUMENTS (?legal imports, prepared at build time)', () => {
  it('holds only the publishable text, so reviewer material never reaches the bundle', () => {
    for (const [doc, raw] of [
      ['terms', termsMd],
      ['privacy', privacyMd],
      ['accessibility', accessibilityMd],
      ['openData', openDataMd],
    ] as const) {
      expect(LEGAL_DOCUMENTS[doc]).toEqual(prepareLegalDocument(raw))
      expect(JSON.stringify(LEGAL_DOCUMENTS[doc])).not.toMatch(/CHECK|Notes for the reviewer/)
    }
  })
})

describe('renderMarkdown', () => {
  it('gives h2/h3 headings stable, unique, prefixed ids and lists them', () => {
    const { html, headings } = renderMarkdown(
      '## 1. Who we are\n\n### 3.1 Visitors (no account)\n\n## 10. Children\n\n## 10. Children\n',
    )
    expect(headings).toEqual([
      { depth: 2, id: 'section-1-who-we-are', text: '1. Who we are' },
      { depth: 3, id: 'section-3-1-visitors-no-account', text: '3.1 Visitors (no account)' },
      { depth: 2, id: 'section-10-children', text: '10. Children' },
      { depth: 2, id: 'section-10-children-2', text: '10. Children' },
    ])
    expect(html).toContain('<h2 id="section-1-who-we-are">1. Who we are</h2>')
    expect(html).toContain('<h3 id="section-3-1-visitors-no-account">')
  })

  it('uses the plain heading text for the list, without markup', () => {
    const { headings } = renderMarkdown('## A **bold** `code` title\n')
    expect(headings[0]!.text).toBe('A bold code title')
    expect(headings[0]!.id).toBe('section-a-bold-code-title')
  })

  it('wraps tables in a horizontally scrollable, focusable container', () => {
    const { html } = renderMarkdown('| a | b |\n|---|---|\n| 1 | 2 |\n')
    const div = document.createElement('div')
    div.innerHTML = html
    const wrapper = div.querySelector('table')!.parentElement!
    expect(wrapper.classList.contains('overflow-x-auto')).toBe(true)
    expect(wrapper.getAttribute('tabindex')).toBe('0')
  })

  it('autolinks bare URLs and email addresses', () => {
    const { html } = renderMarkdown('See https://www.dpa.gr or write to louta@uowm.gr.\n')
    expect(html).toContain('href="https://www.dpa.gr"')
    expect(html).toContain('href="mailto:louta@uowm.gr"')
  })
})

describe('LegalView: terms', () => {
  it('uses the About-page header: h1 "Terms of Use" with the accent bar', async () => {
    const wrapper = await mountLegal('terms')
    const h1 = wrapper.find('h1')
    expect(h1.text()).toBe('Terms of Use')
    expect(t('legal.termsTitle')).toBe('Terms of Use')
    expect(h1.attributes('tabindex')).toBe('-1')
    expect(h1.classes()).toEqual(expect.arrayContaining(['text-4xl', 'text-primary-600']))
    expect(wrapper.find('.h-1.w-20.bg-secondary-500').exists()).toBe(true)
  })

  it('shows the version caption parsed from the document', async () => {
    const wrapper = await mountLegal('terms')
    const caption = wrapper.find('[data-testid="legal-version"]')
    expect(caption.text()).toContain('Version 1')
    expect(caption.text()).toContain('31 October 2026')
  })

  it('renders the terms without any reviewer material', async () => {
    const wrapper = await mountLegal('terms')
    const headings = wrapper.findAll('.legal-prose h2').map((h) => h.text())
    expect(headings).toContain('8. Licence for the content you contribute')
    const text = wrapper.text()
    expect(text).toContain('CC BY 4.0')
    expect(text).toContain('louta@uowm.gr')
    expect(text).not.toContain('[CHECK')
    expect(text).not.toContain('CHECK')
    expect(text).not.toContain('Notes for the reviewer')
    expect(text).not.toMatch(/increment/i)
    expect(text).not.toContain('draft for legal review')
    expect(wrapper.html()).not.toContain('[CHECK')
  })

  it('marks the document as English and keeps mailto links', async () => {
    const wrapper = await mountLegal('terms')
    const prose = wrapper.find('.legal-prose')
    expect(prose.attributes('lang')).toBe('en')
    expect(prose.find('a[href="mailto:louta@uowm.gr"]').exists()).toBe(true)
  })

  it('opens external links in a new tab with rel=noopener', async () => {
    const wrapper = await mountLegal('terms')
    const external = wrapper
      .findAll('.legal-prose a')
      .filter((a) => /^https?:/.test(a.attributes('href') ?? ''))
    expect(external.length).toBeGreaterThan(0)
    for (const a of external) {
      expect(a.attributes('target'), a.attributes('href')).toBe('_blank')
      expect(a.attributes('rel'), a.attributes('href')).toContain('noopener')
    }
    expect(
      external.some((a) => a.attributes('href') === 'https://creativecommons.org/licenses/by/4.0/'),
    ).toBe(true)
  })

  it('lists every section in the table of contents, in order, with working anchors', async () => {
    const wrapper = await mountLegal('terms')
    const toc = wrapper.find(`nav[aria-label="${t('legal.contents')}"]`)
    expect(toc.exists()).toBe(true)
    const links = toc.findAll('a')
    const headings = wrapper.findAll('.legal-prose h2')
    expect(headings.map((h) => h.text())).toEqual(sourceSections(termsMd))
    expect(links.map((a) => a.text())).toEqual(headings.map((h) => h.text()))
    links.forEach((a, i) => {
      const id = headings[i]!.attributes('id')
      expect(id).toBeTruthy()
      expect(a.attributes('href')).toBe(`#${id}`)
      expect(document.getElementById(id!)).not.toBeNull()
    })
  })

  it('says the document is English-only when the interface is in another language', async () => {
    setLocale('el')
    const wrapper = await mountLegal('terms')
    expect(wrapper.text()).toContain(t('legal.englishOnly'))
    setLocale('en')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).not.toContain(t('legal.englishOnly'))
  })
})

describe('LegalView: privacy', () => {
  it('renders h1 "Privacy Policy", the cookie table and the supervisory authority', async () => {
    const wrapper = await mountLegal('privacy')
    expect(wrapper.find('h1').text()).toBe('Privacy Policy')
    const tables = wrapper.findAll('.legal-prose table')
    expect(tables.length).toBeGreaterThanOrEqual(2)
    expect(tables.some((table) => table.text().includes('Session cookie'))).toBe(true)
    for (const table of tables) {
      expect(table.element.parentElement!.classList.contains('overflow-x-auto')).toBe(true)
    }
    // Source lines wrap inside paragraphs; compare the text as a browser shows it.
    const text = wrapper.text().replace(/\s+/g, ' ')
    expect(text).toContain('Hellenic Data Protection Authority')
    expect(text).not.toContain('[CHECK')
    expect(text).not.toContain('Notes for the reviewer')
    expect(wrapper.find('[data-testid="legal-version"]').text()).toContain('2 November 2026')
  })

  it('lists the privacy sections in the table of contents', async () => {
    const wrapper = await mountLegal('privacy')
    const links = wrapper.findAll(`nav[aria-label="${t('legal.contents')}"] a`)
    expect(links.map((a) => a.text())).toEqual(sourceSections(privacyMd))
    const ids = wrapper.findAll('.legal-prose h2').map((h) => `#${h.attributes('id')}`)
    expect(links.map((a) => a.attributes('href'))).toEqual(ids)
  })
})

describe('LegalView: accessibility statement', () => {
  it('renders h1 "Accessibility statement" with the version caption', async () => {
    const wrapper = await mountLegal('accessibility')
    expect(wrapper.find('h1').text()).toBe('Accessibility statement')
    expect(t('legal.accessibilityTitle')).toBe('Accessibility statement')
    expect(wrapper.find('[data-testid="legal-version"]').text()).toContain('31 October 2026')
  })

  it('states WCAG 2.1 conformance and the feedback contact, without reviewer material', async () => {
    const wrapper = await mountLegal('accessibility')
    const text = wrapper.text().replace(/\s+/g, ' ')
    expect(text).toContain('WCAG 2.1')
    expect(text).toContain('louta@uowm.gr')
    expect(wrapper.find('.legal-prose a[href="mailto:louta@uowm.gr"]').exists()).toBe(true)
    expect(text).not.toContain('CHECK')
    expect(text).not.toContain('Notes for the reviewer')
    expect(text).not.toMatch(/increment/i)
  })

  it('lists the statement sections in the table of contents', async () => {
    const wrapper = await mountLegal('accessibility')
    const links = wrapper.findAll(`nav[aria-label="${t('legal.contents')}"] a`)
    expect(links.map((a) => a.text())).toEqual(sourceSections(accessibilityMd))
  })
})

describe('LegalView: open data', () => {
  it('renders h1 "Open data" with the version caption', async () => {
    const wrapper = await mountLegal('openData')
    expect(wrapper.find('h1').text()).toBe('Open data')
    expect(t('legal.openDataTitle')).toBe('Open data')
    expect(wrapper.find('[data-testid="legal-version"]').text()).toContain('31 October 2026')
  })

  it('links the data package, the licence and the API description', async () => {
    const wrapper = await mountLegal('openData')
    const hrefs = wrapper.findAll('.legal-prose a').map((a) => a.attributes('href'))
    expect(hrefs).toContain('https://cooperation.urbanfloods.app/api/v1/export/datapackage.json')
    expect(hrefs).toContain('https://creativecommons.org/licenses/by/4.0/')
    expect(hrefs).toContain('https://cooperation.urbanfloods.app/api/v1/openapi.json')
    expect(hrefs).toContain('https://cooperation.urbanfloods.app/feeds/posts.atom')
    const text = wrapper.text().replace(/\s+/g, ' ')
    expect(text).toContain('CC BY 4.0')
    expect(text).not.toContain('CHECK')
    expect(text).not.toContain('Notes for the reviewer')
  })

  it('lists the open-data sections in the table of contents', async () => {
    const wrapper = await mountLegal('openData')
    const links = wrapper.findAll(`nav[aria-label="${t('legal.contents')}"] a`)
    expect(links.map((a) => a.text())).toEqual(sourceSections(openDataMd))
  })
})

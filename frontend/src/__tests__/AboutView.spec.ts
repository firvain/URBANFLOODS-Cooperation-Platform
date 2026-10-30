import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

import AboutView from '@/views/AboutView.vue'
import i18n from '@/i18n'
import en from '@/i18n/locales/en.json'
import { mountWithApp, unmountAll } from './helpers/mount'

const t = i18n.global.t

afterEach(unmountAll)

async function mountAbout() {
  const { wrapper } = await mountWithApp(AboutView, { path: '/about' })
  return wrapper
}

describe('AboutView', () => {
  it('uses the KNOWBASE header pattern: h1 and accent bar', async () => {
    const wrapper = await mountAbout()
    const h1 = wrapper.find('h1')
    expect(h1.classes()).toEqual(expect.arrayContaining(['text-4xl', 'text-primary-600']))
    expect(wrapper.find('.h-1.w-20.bg-secondary-500').exists()).toBe(true)
  })

  it('shows the acronym and the full title in the highlight box', async () => {
    const wrapper = await mountAbout()
    expect(wrapper.text()).toContain('URBANFLOODS')
    const box = wrapper.find('[data-testid="full-title"]')
    expect(box.classes()).toEqual(
      expect.arrayContaining(['bg-primary-50', 'border-l-4', 'border-primary-500']),
    )
    expect(box.text()).toContain(
      'Promoting Urban Resilience Through an Integrated Advanced Decision Support System for Flood Control',
    )
  })

  it('lists the project facts', async () => {
    const wrapper = await mountAbout()
    const text = wrapper.text()
    for (const fact of [
      'Interreg IPA ADRION 2021–2027',
      'IPA ADRION 1st Call for Proposals',
      '2. Supporting a greener and climate resilient Adriatic-Ionian region',
      'SO2.1. Promoting climate change adaptation and disaster risk prevention, resilience taking into account eco-system based approaches',
      '01/09/2024 – 31/08/2027',
      'EUR 1.747.583,17',
      'EUR 1.485.445,68',
    ]) {
      expect(text, fact).toContain(fact)
    }
    for (const key of [
      'acronym',
      'fullTitle',
      'programme',
      'priority',
      'call',
      'specificObjective',
      'dates',
      'totalBudget',
      'interregFunds',
    ]) {
      expect(text, key).toContain(t(`about.facts.${key}`))
    }
  })

  it('shows the Priority 2 icon with alt text beside the priority', async () => {
    const wrapper = await mountAbout()
    const icon = wrapper.find('img[src*="priority-2-greener"]')
    expect(icon.exists()).toBe(true)
    expect(icon.attributes('alt')).toBe(t('about.priorityIconAlt'))
    expect(icon.classes()).toEqual(expect.arrayContaining(['h-12', 'w-12']))
    expect(existsSync(resolve(__dirname, '../assets/logos/priority-2-greener.png'))).toBe(true)
  })

  it('shows the lead partner card with address and a mailto for the scientific coordinator', async () => {
    const wrapper = await mountAbout()
    const lead = wrapper.find('[data-testid="lead-partner"]')
    expect(lead.text()).toContain('LEAD')
    expect(lead.text()).toContain('University of Western Macedonia')
    expect(lead.text()).toContain('Active Urban Planning Zone (ZEP) I, 50100 Kozani, Greece')
    expect(lead.text()).toContain('Prof. Malamati Louta')
    expect(lead.text()).toContain(t('about.leadPartner.coordinatorRole'))
    const mail = lead.find('a[href^="mailto:"]')
    expect(mail.attributes('href')).toBe('mailto:louta@uowm.gr')
    expect(mail.attributes('aria-label')).toBe(
      t('about.leadPartner.emailLabel', { name: 'Prof. Malamati Louta' }),
    )
  })

  it('keeps the address out of the translation files and the template source', async () => {
    expect(JSON.stringify(en)).not.toContain('louta@uowm.gr')
    const source = await import('@/views/AboutView.vue?raw')
    expect(source.default).not.toContain('louta@uowm.gr')
  })

  it('renders every summary paragraph and output from en.json', async () => {
    const wrapper = await mountAbout()
    const text = wrapper.text()
    for (const paragraph of en.about.summary.paragraphs) expect(text).toContain(paragraph)
    for (const output of en.about.summary.outputs) {
      expect(text).toContain(output.title)
      expect(text).toContain(output.text)
    }
    expect(text).toContain(en.about.summary.closing)
  })

  it('no longer shows the budget placeholder', async () => {
    const wrapper = await mountAbout()
    expect(wrapper.text()).not.toMatch(/to be provided/i)
  })

  it('links to the partners page', async () => {
    const wrapper = await mountAbout()
    expect(wrapper.find('a[href="/partners"]').text()).toBe(t('about.partnersLink'))
  })
})

/**
 * Colour contrast at the source (WCAG 2.1 AA 1.4.3 / 1.4.11, increment 5d): the Nuxt UI colour
 * aliases and text tokens set in main.css, the focus ring, and guards against the low-contrast
 * classes the axe scans found (e2e/a11y.spec.ts is the acceptance test on rendered pages).
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { contrast, overWhite, parseColor, WHITE } from './helpers/contrast'
import { mountWithApp } from './helpers/mount'

const frontend = resolve(__dirname, '../..')
const mainCss = readFileSync(join(frontend, 'src/assets/main.css'), 'utf8')
const tailwindTheme = readFileSync(join(frontend, 'node_modules/tailwindcss/theme.css'), 'utf8')

/** Nuxt UI's default palette for each alias (only primary/secondary are configured). */
const PALETTE: Record<string, string> = {
  primary: 'primary',
  secondary: 'secondary',
  success: 'green',
  info: 'blue',
  warning: 'yellow',
  error: 'red',
  neutral: 'slate',
}

/** A shade of an alias: the project scale from main.css, else Tailwind's default palette. */
function shade(alias: string, step: number | string): string {
  const own = mainCss.match(new RegExp(`--color-${alias}-${step}:\\s*(#[0-9a-f]{6})`, 'i'))
  if (own) return own[1]!
  const palette = PALETTE[alias]!
  const tw = tailwindTheme.match(new RegExp(`--color-${palette}-${step}:\\s*(oklch\\([^)]*\\))`))
  if (!tw) throw new Error(`No shade ${palette}-${step}`)
  return tw[1]!
}

/** The unlayered `:root` overrides of Nuxt UI's tokens: `--ui-x: var(--ui-color-<alias>-<n>)`. */
function override(token: string): string {
  const match = mainCss.match(new RegExp(`--ui-${token}:\\s*var\\(--ui-color-([a-z]+)-(\\d+)\\)`))
  if (!match) throw new Error(`main.css does not override --ui-${token}`)
  return shade(match[1]!, match[2]!)
}

/** Nuxt UI's shade-500 default for aliases main.css leaves alone. */
const aliasColour = (alias: string) =>
  mainCss.includes(`--ui-${alias}:`) ? override(alias) : shade(alias, 500)

/** Brace depth of `css` at `index`, counting from the start of the file. */
function depthAt(css: string, index: number): number {
  const withoutComments = css.slice(0, index).replace(/\/\*[\s\S]*?\*\//g, '')
  return [...withoutComments].reduce((d, c) => d + (c === '{' ? 1 : c === '}' ? -1 : 0), 0)
}

describe('Nuxt UI colour aliases', () => {
  // Used as text on white and on their own 10 % tint (outline, soft, subtle, link variants;
  // UBadge subtle, UAvatar), and as solid backgrounds under white text (solid UButton, UAlert).
  it.each(['primary', 'secondary', 'success', 'info', 'warning', 'error'])(
    '%s reaches 4.5:1 as text on white, on its tint and under white text',
    (alias) => {
      const colour = parseColor(aliasColour(alias))
      expect(contrast(colour, WHITE)).toBeGreaterThanOrEqual(4.5)
      expect(contrast(colour, overWhite(colour, 0.1))).toBeGreaterThanOrEqual(4.5)
    },
  )

  it('keeps the brand green #97c137 as the secondary scale (backgrounds), not as the alias', () => {
    expect(shade('secondary', 500).toLowerCase()).toBe('#97c137')
    expect(contrast(parseColor('#97c137'), WHITE)).toBeLessThan(4.5)
    expect(aliasColour('secondary').toLowerCase()).not.toBe('#97c137')
  })
})

describe('neutral text tokens', () => {
  it('text-dimmed (placeholders) reaches 4.5:1 on white', () => {
    expect(contrast(parseColor(override('text-dimmed')), WHITE)).toBeGreaterThanOrEqual(4.5)
  })

  it('text-muted reaches 4.5:1 on white and on bg-elevated (the avatar initials)', () => {
    const muted = parseColor(override('text-muted'))
    expect(contrast(muted, WHITE)).toBeGreaterThanOrEqual(4.5)
    // --ui-bg-elevated is neutral-100 in Nuxt UI's light theme.
    expect(contrast(muted, parseColor(shade('neutral', 100)))).toBeGreaterThanOrEqual(4.5)
  })

  it('the avatar initials fallback uses text-muted on bg-elevated', async () => {
    const UAvatar = (await import('@nuxt/ui/components/Avatar.vue')).default
    const { wrapper } = await mountWithApp(UAvatar, { props: { alt: 'Dev Member' } })
    const fallback = wrapper.find('[data-slot="fallback"]')
    expect(fallback.text()).toBe('DM')
    expect(fallback.classes()).toContain('text-muted')
    expect(wrapper.find('[data-slot="root"]').classes()).toContain('bg-elevated')
  })
})

describe('focus ring', () => {
  it('uses a colour with at least 3:1 against white', () => {
    const match = mainCss.match(/--focus-ring-color:\s*var\(--color-([a-z]+)-(\d+)\)/)
    expect(match).not.toBeNull()
    expect(contrast(parseColor(shade(match![1]!, match![2]!)), WHITE)).toBeGreaterThanOrEqual(3)
  })

  it('is an unlayered :focus-visible rule for links and buttons (beats Nuxt UI utilities)', () => {
    const index = mainCss.search(/:is\(\s*a,\s*button,[^{]*\):focus-visible\s*\{/)
    expect(index).toBeGreaterThan(-1)
    expect(depthAt(mainCss, index)).toBe(0)
    const rule = mainCss.slice(index, mainCss.indexOf('}', index))
    expect(rule).toContain('outline: 3px solid var(--focus-ring-color)')
    expect(rule).toContain('outline-offset: 2px')
  })

  it('overrides the aliases outside any cascade layer', () => {
    const index = mainCss.indexOf('--ui-secondary:')
    expect(depthAt(mainCss, index)).toBe(1)
  })
})

describe('source guards', () => {
  function vueFiles(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const path = join(dir, name)
      if (statSync(path).isDirectory()) return name === '__tests__' ? [] : vueFiles(path)
      return name.endsWith('.vue') ? [path] : []
    })
  }

  it('uses no text colour classes below 4.5:1 on white', () => {
    // text-secondary-500/600/700: 2.10 / 3.02 / 4.54 (4.0 on secondary-50 cards); gray-400/500:
    // 2.5 / 4.6 (fails on tinted panels). Use text-secondary (the alias) or text-muted instead.
    const banned =
      /\btext-(secondary-(300|400|500|600|700)|gray-(300|400|500)|slate-(300|400|500))\b/
    const offenders = vueFiles(join(frontend, 'src'))
      .filter((file) => banned.test(readFileSync(file, 'utf8')))
      .map((file) => file.slice(frontend.length + 1))
    expect(offenders).toEqual([])
  })
})

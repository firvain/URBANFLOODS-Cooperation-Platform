/**
 * WCAG 2.x contrast ratios for the theme tests (a11y.theme.spec.ts): hex and Tailwind v4
 * `oklch()` colours, optionally blended over white (Tailwind's `bg-x/10` tints).
 */
type Linear = [number, number, number]

const toLinear = (v: number) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
const toGamma = (v: number) => (v <= 0.0031308 ? v * 12.92 : 1.055 * v ** (1 / 2.4) - 0.055)
const clamp = (v: number) => Math.min(1, Math.max(0, v))

/** `#rrggbb` or `oklch(L% C H)` → linear sRGB. */
export function parseColor(color: string): Linear {
  const value = color.trim()
  if (value.startsWith('#')) {
    const hex = value.slice(1)
    return [0, 2, 4].map((i) => toLinear(parseInt(hex.slice(i, i + 2), 16) / 255)) as Linear
  }
  const match = value.match(/^oklch\(\s*([\d.]+)(%?)\s+([\d.]+)\s+([\d.]+)\s*\)$/)
  if (!match) throw new Error(`Unsupported colour: ${color}`)
  const L = match[2] ? Number(match[1]) / 100 : Number(match[1])
  const C = Number(match[3])
  const h = (Number(match[4]) * Math.PI) / 180
  const a = C * Math.cos(h)
  const b = C * Math.sin(h)
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3
  return [
    clamp(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    clamp(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    clamp(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ]
}

/** `color` at `alpha` over white (blended in gamma-encoded sRGB). */
export function overWhite(color: Linear, alpha: number): Linear {
  return color.map((v) => toLinear(toGamma(v) * alpha + (1 - alpha))) as Linear
}

const luminance = ([r, g, b]: Linear) => 0.2126 * r + 0.7152 * g + 0.0722 * b

export function contrast(a: Linear, b: Linear): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}

export const WHITE = parseColor('#ffffff')

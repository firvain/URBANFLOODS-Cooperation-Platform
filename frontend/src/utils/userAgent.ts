/**
 * A coarse "browser on OS" reading of a User-Agent string for the sessions list. Order matters:
 * Edge and Opera also say "Chrome", Chrome also says "Safari", Android also says "Linux" and
 * iPadOS also says "Mac OS X".
 */
const BROWSERS: [RegExp, string][] = [
  [/\bEdg(e|A|iOS)?\//, 'Edge'],
  [/\bOPR\/|\bOpera\b/, 'Opera'],
  [/\bFirefox\/|\bFxiOS\//, 'Firefox'],
  [/\bChrome\/|\bCriOS\//, 'Chrome'],
  [/\bSafari\//, 'Safari'],
]

const SYSTEMS: [RegExp, string][] = [
  [/\bAndroid\b/, 'Android'],
  [/\b(iPhone|iPad|iPod)\b/, 'iOS'],
  [/\bWindows\b/, 'Windows'],
  [/\bCrOS\b/, 'ChromeOS'],
  [/\bMac OS X\b|\bMacintosh\b/, 'macOS'],
  [/\bLinux\b/, 'Linux'],
]

const match = (ua: string, table: [RegExp, string][]) =>
  table.find(([pattern]) => pattern.test(ua))?.[1] ?? null

export function describeUserAgent(ua: string | null | undefined): {
  browser: string | null
  os: string | null
} {
  if (!ua) return { browser: null, os: null }
  return { browser: match(ua, BROWSERS), os: match(ua, SYSTEMS) }
}

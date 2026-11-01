/**
 * Display names of KNOWBASE items.
 *
 * The KNOWBASE stores measure names in lower case ("floodplain reconnection") and its own frontend
 * shows them in title case (`toTitleCase` in its MeasureCard.vue: lower-case everything, then a
 * capital at the start and after a space or "("). The platform uses the same rule so a measure
 * has the same name on both sites. Document names are legal titles, stored properly cased, and are
 * shown as they are.
 */
export function measureTitle(text: string): string {
  if (!text) return ''
  return text.toLowerCase().replace(/(?:^|\s|\()([a-z])/g, (match) => match.toUpperCase())
}

export function kbTitle(kbType: 'measure' | 'document', text: string): string {
  return kbType === 'measure' ? measureTitle(text) : text
}

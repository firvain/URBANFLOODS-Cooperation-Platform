/**
 * The legal texts from `docs/legal/` (the single source of truth, outside `frontend/`), prepared
 * at build time by the `?legal` plugin in `vite.config.ts`: reviewer material is stripped before
 * bundling. Import this module only from the lazily loaded legal view, so the texts stay out of
 * the main chunk.
 */
import accessibility from '../../../docs/legal/accessibility-statement.md?legal'
import openData from '../../../docs/legal/open-data.md?legal'
import privacy from '../../../docs/legal/privacy-policy.md?legal'
import terms from '../../../docs/legal/terms-of-use.md?legal'
import type { LegalDoc } from '@/constants/legal'
import type { LegalDocument } from '@/utils/legalDocument'

export const LEGAL_DOCUMENTS: Record<LegalDoc, LegalDocument> = {
  terms,
  privacy,
  accessibility,
  openData,
}

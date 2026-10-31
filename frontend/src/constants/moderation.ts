/** Reporting and moderation settings shared by the report button and the status components. */
import type { ReportReason } from '@/services/reports'

/** The reasons a member can give, in the order the report dialog lists them. */
export const REPORT_REASONS = [
  'spam',
  'abuse',
  'off_topic',
  'misinformation',
  'other',
] as const satisfies readonly ReportReason[]

/** Report details length in characters, mirroring the backend (`schemas/report.py`). */
export const REPORT_DETAILS_MAX_LENGTH = 1000

/** `sessionStorage` key of the items reported in this session (`"<type>:<id>"` strings). */
export const REPORTED_STORAGE_KEY = 'reported-content'

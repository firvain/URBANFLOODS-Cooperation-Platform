/**
 * Reports (`/api/v1/reports/`). A verified member reports a published post, thread, reply or
 * comment once; enough distinct reporters hide it automatically (`auto_hidden`). Rate limited
 * (429). Errors arrive as `ApiError`: 404 `report.content_not_found`, 400 `report.own_content`,
 * 409 `report.already_reported`, 422 `validation.failed`.
 */
import type { components } from '@/types/api-schema'
import { api } from './api'

export type ContentType = components['schemas']['ContentType']
export type ContentStatus = components['schemas']['ContentStatus']
export type HiddenReason = components['schemas']['HiddenReason']
export type ReportReason = components['schemas']['ReportReason']
export type ReportCreate = components['schemas']['ReportCreate']
export type ReportCreated = components['schemas']['ReportCreated']

const BASE = '/api/v1/reports/'

export const reportsService = {
  /** 201. */
  create: (body: ReportCreate) => api<ReportCreated>(BASE, { method: 'POST', body }),
}

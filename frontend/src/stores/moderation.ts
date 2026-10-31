/**
 * Moderation store (admins): the approval queue, the reports and the audit log. Approving or
 * rejecting removes the queue item at once (put back if the server refuses); report and content
 * actions update the rows with the server's answer.
 */
import { defineStore } from 'pinia'

import {
  moderationService,
  type ContentType,
  type LogParams,
  type ModerationAction,
  type ModerationResult,
  type QueueItem,
  type QueueParams,
  type ReportDetail,
  type ReportListParams,
} from '@/services/moderation'
import { pagedList } from './pagedList'

/** The content actions offered on a report (approve/reject belong to the queue). */
export type ContentAction = Exclude<ModerationAction, 'approve' | 'reject'>

export const useModerationStore = defineStore('moderation', () => {
  // --- Queue ------------------------------------------------------------------------------------

  const queueList = pagedList((params: QueueParams) => moderationService.queue(params))
  const queue = queueList.state

  const sameItem = (a: QueueItem, b: QueueItem) =>
    a.id === b.id && a.content_type === b.content_type

  async function review(item: QueueItem, action: 'approve' | 'reject', reason?: string | null) {
    const index = queue.items.findIndex((i) => sameItem(i, item))
    if (index !== -1) {
      queue.items.splice(index, 1)
      queue.total = Math.max(0, queue.total - 1)
    }
    try {
      return await moderationService.act(item.content_type, item.id, action, reason)
    } catch (error) {
      if (index !== -1 && !queue.items.some((i) => sameItem(i, item))) {
        queue.items.splice(Math.min(index, queue.items.length), 0, item)
        queue.total += 1
      }
      throw error
    }
  }

  const approve = (item: QueueItem) => review(item, 'approve')
  const reject = (item: QueueItem, reason?: string | null) => review(item, 'reject', reason)

  // --- Reports ----------------------------------------------------------------------------------

  const reportsList = pagedList((params: ReportListParams) => moderationService.listReports(params))
  const reports = reportsList.state

  function replaceReport(updated: ReportDetail) {
    const index = reports.items.findIndex((r) => r.id === updated.id)
    if (index !== -1) reports.items.splice(index, 1, updated)
    return updated
  }

  const resolveReport = async (id: number) =>
    replaceReport(await moderationService.resolveReport(id))
  const dismissReport = async (id: number) =>
    replaceReport(await moderationService.dismissReport(id))

  /** Hide/unhide/delete/restore reported content; every report of it shows the new status. */
  async function contentAction(
    type: ContentType,
    id: number,
    action: ContentAction,
    reason?: string | null,
  ): Promise<ModerationResult> {
    const result = await moderationService.act(type, id, action, reason)
    for (const report of reports.items) {
      if (report.content && report.content.type === type && report.content.id === id) {
        report.content = { ...report.content, status: result.status }
      }
    }
    return result
  }

  // --- Audit log --------------------------------------------------------------------------------

  const logList = pagedList((params: LogParams) => moderationService.log(params))
  const log = logList.state

  return {
    queue,
    fetchQueue: queueList.fetch,
    reloadQueue: queueList.reload,
    approve,
    reject,
    reports,
    fetchReports: reportsList.fetch,
    reloadReports: reportsList.reload,
    resolveReport,
    dismissReport,
    contentAction,
    log,
    fetchLog: logList.fetch,
    reloadLog: logList.reload,
  }
})

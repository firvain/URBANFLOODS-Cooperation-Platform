/**
 * Moderation store (admins): the approval queue, the deleted items, the reports and the audit log.
 * Approving or rejecting removes the queue item at once (put back if the server refuses); restoring
 * or purging a deleted item removes it once the server agreed; report and content actions update
 * the rows with the server's answer.
 */
import { defineStore } from 'pinia'

import {
  moderationService,
  type ContentType,
  type DeletedItem,
  type DeletedParams,
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

  // --- Deleted items ----------------------------------------------------------------------------

  const deletedList = pagedList((params: DeletedParams) => moderationService.listDeleted(params))
  const deleted = deletedList.state

  function dropDeleted(item: DeletedItem) {
    const index = deleted.items.findIndex(
      (i) => i.id === item.id && i.content_type === item.content_type,
    )
    if (index === -1) return
    deleted.items.splice(index, 1)
    deleted.total = Math.max(0, deleted.total - 1)
  }

  async function restoreDeleted(item: DeletedItem) {
    const result = await moderationService.act(item.content_type, item.id, 'restore')
    dropDeleted(item)
    return result
  }

  async function purgeDeleted(item: DeletedItem) {
    const result = await moderationService.purge(item.content_type, item.id)
    dropDeleted(item)
    return result
  }

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
    deleted,
    fetchDeleted: deletedList.fetch,
    reloadDeleted: deletedList.reload,
    restoreDeleted,
    purgeDeleted,
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

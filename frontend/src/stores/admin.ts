/**
 * Admin store: the dashboard stats, the user list and its actions, and the admin side of
 * categories and tags. Every action calls the API first and then updates the rows with the
 * server's answer (errors propagate to the view, which shows the translated `admin.*` code).
 */
import { ref } from 'vue'
import { defineStore } from 'pinia'

import {
  adminService,
  type AdminStats,
  type AdminUser,
  type AdminUserListParams,
  type PromoteTarget,
  type UserAction,
} from '@/services/admin'
import {
  categoriesService,
  type CategoryCreate,
  type CategoryOut,
  type CategoryUpdate,
} from '@/services/categories'
import { tagsService, type TagListParams, type TagOut } from '@/services/tags'
import { pagedList } from './pagedList'

const KIND_ORDER = { blog: 0, forum: 1 } as const

const byKindAndOrder = (a: CategoryOut, b: CategoryOut) =>
  KIND_ORDER[a.kind] - KIND_ORDER[b.kind] ||
  a.sort_order - b.sort_order ||
  a.name.localeCompare(b.name)

export const useAdminStore = defineStore('admin', () => {
  // --- Dashboard --------------------------------------------------------------------------------

  const stats = ref<AdminStats | null>(null)
  const statsLoading = ref(false)
  const statsFailed = ref(false)

  async function fetchStats(): Promise<void> {
    statsLoading.value = true
    statsFailed.value = false
    try {
      stats.value = await adminService.stats()
    } catch {
      statsFailed.value = true
    } finally {
      statsLoading.value = false
    }
  }

  /** Empty the KNOWBASE proxy cache; returns how many responses were dropped. */
  async function clearKnowbaseCache(): Promise<number> {
    const { cleared } = await adminService.clearKnowbaseCache()
    void fetchStats()
    return cleared
  }

  // --- Users ------------------------------------------------------------------------------------

  const usersList = pagedList((params: AdminUserListParams) => adminService.listUsers(params))
  const users = usersList.state

  function replaceUser(updated: AdminUser) {
    const index = users.items.findIndex((u) => u.id === updated.id)
    if (index !== -1) users.items.splice(index, 1, updated)
  }

  async function userAction(id: number, action: UserAction, to?: PromoteTarget) {
    const updated = await adminService.userAction(id, action, to)
    replaceUser(updated)
    return updated
  }

  const resendVerification = (id: number) => adminService.resendVerification(id)

  // --- Categories -------------------------------------------------------------------------------

  const categories = ref<CategoryOut[]>([])
  const categoriesLoading = ref(false)
  const categoriesFailed = ref(false)

  async function fetchCategories(): Promise<void> {
    categoriesLoading.value = true
    categoriesFailed.value = false
    try {
      const { items } = await categoriesService.list({ include_archived: true })
      categories.value = [...items].sort(byKindAndOrder)
    } catch {
      categoriesFailed.value = true
    } finally {
      categoriesLoading.value = false
    }
  }

  function putCategory(category: CategoryOut) {
    const rest = categories.value.filter((c) => c.id !== category.id)
    categories.value = [...rest, category].sort(byKindAndOrder)
  }

  async function createCategory(payload: CategoryCreate): Promise<CategoryOut> {
    const created = await categoriesService.create(payload)
    putCategory(created)
    return created
  }

  async function updateCategory(id: number, changes: CategoryUpdate): Promise<CategoryOut> {
    const updated = await categoriesService.update(id, changes)
    putCategory(updated)
    return updated
  }

  async function archiveCategory(id: number): Promise<void> {
    await categoriesService.archive(id)
    const category = categories.value.find((c) => c.id === id)
    if (category) putCategory({ ...category, is_archived: true })
  }

  // --- Tags -------------------------------------------------------------------------------------

  const tagsList = pagedList((params: TagListParams) =>
    tagsService.list({ sort: 'name', ...params }),
  )
  const tags = tagsList.state

  function dropTag(id: number) {
    const before = tags.items.length
    tags.items = tags.items.filter((t) => t.id !== id)
    if (tags.items.length < before) tags.total = Math.max(0, tags.total - 1)
  }

  /** Merge `sourceId` into `targetId`; returns the target with its new usage count. */
  async function mergeTag(sourceId: number, targetId: number): Promise<TagOut> {
    const target = await tagsService.merge(sourceId, targetId)
    dropTag(sourceId)
    const index = tags.items.findIndex((t) => t.id === target.id)
    if (index !== -1) tags.items.splice(index, 1, target)
    return target
  }

  async function deleteTag(id: number): Promise<void> {
    await tagsService.remove(id)
    dropTag(id)
  }

  return {
    stats,
    statsLoading,
    statsFailed,
    fetchStats,
    clearKnowbaseCache,
    users,
    fetchUsers: usersList.fetch,
    reloadUsers: usersList.reload,
    userAction,
    resendVerification,
    categories,
    categoriesLoading,
    categoriesFailed,
    fetchCategories,
    createCategory,
    updateCategory,
    archiveCategory,
    tags,
    fetchTags: tagsList.fetch,
    reloadTags: tagsList.reload,
    mergeTag,
    deleteTag,
  }
})

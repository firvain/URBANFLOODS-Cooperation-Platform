/**
 * Admin store: the dashboard stats, the user list and its actions, and the admin side of
 * categories, tags, organisations and expertise areas. Every action calls the API first and then
 * updates the rows with the server's answer (errors propagate to the view, which shows the
 * translated `admin.*` code).
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
import {
  expertiseService,
  type ExpertiseTag,
  type ExpertiseTagCreate,
  type ExpertiseTagUpdate,
} from '@/services/expertise'
import {
  organisationsService,
  type Organisation,
  type OrganisationCreate,
  type OrganisationUpdate,
} from '@/services/organisations'
import { tagsService, type TagListParams, type TagOut } from '@/services/tags'
import { useExpertiseStore } from '@/stores/expertise'
import { useOrganisationsStore } from '@/stores/organisations'
import { pagedList } from './pagedList'

const KIND_ORDER = { blog: 0, forum: 1 } as const

const byKindAndOrder = (a: CategoryOut, b: CategoryOut) =>
  KIND_ORDER[a.kind] - KIND_ORDER[b.kind] ||
  a.sort_order - b.sort_order ||
  a.name.localeCompare(b.name)

const TYPE_ORDER = { PP: 0, AP: 1, other: 2 } as const
/** The backend's order: partners first, then PP, AP, other, then `sort_order` and name. */
const byPartnerTypeAndOrder = (a: Organisation, b: Organisation) =>
  Number(b.is_partner) - Number(a.is_partner) ||
  TYPE_ORDER[a.type] - TYPE_ORDER[b.type] ||
  a.sort_order - b.sort_order ||
  a.name.localeCompare(b.name)

const byOrderAndLabel = (a: ExpertiseTag, b: ExpertiseTag) =>
  a.sort_order - b.sort_order || a.label.localeCompare(b.label)

/** The backend caps a page of organisations at 200; the platform has a few dozen. */
const ORGANISATIONS_LIMIT = 200

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

  // --- Organisations ----------------------------------------------------------------------------

  const organisations = ref<Organisation[]>([])
  const organisationsLoading = ref(false)
  const organisationsFailed = ref(false)

  async function fetchOrganisations(): Promise<void> {
    organisationsLoading.value = true
    organisationsFailed.value = false
    try {
      const { items } = await organisationsService.list({ limit: ORGANISATIONS_LIMIT })
      organisations.value = [...items].sort(byPartnerTypeAndOrder)
    } catch {
      organisationsFailed.value = true
    } finally {
      organisationsLoading.value = false
    }
  }

  function putOrganisation(organisation: Organisation) {
    const rest = organisations.value.filter((o) => o.id !== organisation.id)
    organisations.value = [...rest, organisation].sort(byPartnerTypeAndOrder)
    // The pickers' and `/partners` cached lists are stale now; refresh the loaded ones.
    const shared = useOrganisationsStore()
    if (shared.allLoaded) shared.fetchAll({ force: true }).catch(() => {})
    if (shared.partnersLoaded) shared.fetchPartners({ force: true }).catch(() => {})
  }

  async function createOrganisation(payload: OrganisationCreate): Promise<Organisation> {
    const created = await organisationsService.create(payload)
    putOrganisation(created)
    return created
  }

  async function updateOrganisation(
    id: number,
    changes: OrganisationUpdate,
  ): Promise<Organisation> {
    const updated = await organisationsService.update(id, changes)
    putOrganisation(updated)
    return updated
  }

  // --- Expertise areas --------------------------------------------------------------------------

  const expertise = ref<ExpertiseTag[]>([])
  const expertiseLoading = ref(false)
  const expertiseFailed = ref(false)

  async function fetchExpertise(): Promise<void> {
    expertiseLoading.value = true
    expertiseFailed.value = false
    try {
      const { items } = await expertiseService.list({ include_inactive: true })
      expertise.value = [...items].sort(byOrderAndLabel)
    } catch {
      expertiseFailed.value = true
    } finally {
      expertiseLoading.value = false
    }
  }

  function putExpertise(tag: ExpertiseTag) {
    const rest = expertise.value.filter((e) => e.id !== tag.id)
    expertise.value = [...rest, tag].sort(byOrderAndLabel)
    // The pickers' shared vocabulary is stale now; refresh it if it was loaded.
    const vocabulary = useExpertiseStore()
    if (vocabulary.loaded) vocabulary.fetch({ force: true }).catch(() => {})
  }

  async function createExpertise(payload: ExpertiseTagCreate): Promise<ExpertiseTag> {
    const created = await expertiseService.create(payload)
    putExpertise(created)
    return created
  }

  async function updateExpertise(id: number, changes: ExpertiseTagUpdate): Promise<ExpertiseTag> {
    const updated = await expertiseService.update(id, changes)
    putExpertise(updated)
    return updated
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
    organisations,
    organisationsLoading,
    organisationsFailed,
    fetchOrganisations,
    createOrganisation,
    updateOrganisation,
    expertise,
    expertiseLoading,
    expertiseFailed,
    fetchExpertise,
    createExpertise,
    updateExpertise,
  }
})

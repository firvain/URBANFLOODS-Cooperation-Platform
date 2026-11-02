<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useToast } from '@nuxt/ui/composables'
import type { DropdownMenuItem, TableColumn } from '@nuxt/ui'

import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import AdminPagination from '@/components/admin/AdminPagination.vue'
import ListState from '@/components/admin/ListState.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import RelativeTime from '@/components/common/RelativeTime.vue'
import { useAdminErrors } from '@/composables/useAdminErrors'
import { useDebouncedSearch } from '@/composables/useKnowbaseList'
import { useQueryFilters } from '@/composables/useQueryFilters'
import { ADMIN_PAGE_SIZE, ADMIN_SEARCH_DEBOUNCE_MS } from '@/constants/admin'
import type { AdminUser, AdminUserListParams, UserRole } from '@/services/admin'
import { useAdminStore } from '@/stores/admin'
import { useAuthStore } from '@/stores/auth'

/**
 * Users: the accounts (search, role and state filters in the URL; deleted accounts only with
 * "Show deleted accounts", `?deleted=1`) with role changes, ban,
 * trust and "resend verification", each confirmed. Actions the API would refuse for the current
 * admin are not offered: superadmin changes need a superadmin, and nobody changes their own role
 * or bans themselves. The last superadmin is protected by the API (`admin.last_superadmin`).
 */
const { t } = useI18n()
const route = useRoute()
const toast = useToast()
const admin = useAdminStore()
const users = admin.users
const { user: me, isSuperadmin } = storeToRefs(useAuthStore())
const { adminError } = useAdminErrors()

const { filters, page, setFilters, setPage } = useQueryFilters({
  q: 'string',
  role: 'string',
  verified: 'string',
  trusted: 'string',
  active: 'string',
  deleted: 'string',
})

/** Select value for "no filter" (reka-ui selects cannot hold an empty string). */
const ANY = 'any'
const ROLES: UserRole[] = ['member', 'admin', 'superadmin']
const isRole = (v: string): v is UserRole => (ROLES as string[]).includes(v)
const asBool = (v: string) => (v === 'true' ? true : v === 'false' ? false : undefined)

const search = useDebouncedSearch(
  () => filters.value.q,
  (q) => setFilters({ q }),
  ADMIN_SEARCH_DEBOUNCE_MS,
)

const roleFilter = computed<string>({
  get: () => (isRole(filters.value.role) ? filters.value.role : ANY),
  set: (value) => void setFilters({ role: value === ANY ? '' : value }),
})

type FlagKey = 'verified' | 'trusted' | 'active'
const FLAGS: FlagKey[] = ['verified', 'trusted', 'active']

function flagModel(key: FlagKey) {
  return computed<string>({
    get: () => (asBool(filters.value[key]) === undefined ? ANY : filters.value[key]),
    set: (value) => void setFilters({ [key]: value === ANY ? '' : value }),
  })
}
const flagFilters = {
  verified: flagModel('verified'),
  trusted: flagModel('trusted'),
  active: flagModel('active'),
}

const roleItems = computed(() => [
  { label: t('admin.common.any'), value: ANY },
  ...ROLES.map((role) => ({ label: t(`admin.role.${role}`), value: role })),
])
/** "Show deleted accounts": off unless `?deleted=1`; the API leaves deleted accounts out. */
const showDeleted = computed<boolean>({
  get: () => filters.value.deleted === '1',
  set: (value) => void setFilters({ deleted: value ? '1' : '' }),
})

const flagItems = computed(() => [
  { label: t('admin.common.any'), value: ANY },
  { label: t('admin.common.yes'), value: 'true' },
  { label: t('admin.common.no'), value: 'false' },
])

const params = computed<AdminUserListParams>(() => ({
  q: filters.value.q || undefined,
  role: isRole(filters.value.role) ? filters.value.role : undefined,
  verified: asBool(filters.value.verified),
  trusted: asBool(filters.value.trusted),
  active: asBool(filters.value.active),
  include_deleted: showDeleted.value || undefined,
  skip: (page.value - 1) * ADMIN_PAGE_SIZE,
  limit: ADMIN_PAGE_SIZE,
}))

watch(
  () => JSON.stringify(params.value),
  () => {
    if (route.name === 'admin-users') void admin.fetchUsers(params.value)
  },
  { immediate: true },
)

const columns = computed<TableColumn<AdminUser>[]>(() => [
  { id: 'user', header: t('admin.users.user') },
  { id: 'role', header: t('admin.users.role') },
  { id: 'verified', header: t('admin.users.verified') },
  { id: 'trusted', header: t('admin.users.trusted') },
  { id: 'active', header: t('admin.users.active') },
  { id: 'created', header: t('admin.common.created') },
  { id: 'actions', header: t('admin.common.actions') },
])

const ROLE_COLOR = { member: 'neutral', admin: 'primary', superadmin: 'secondary' } as const

// --- Actions ----------------------------------------------------------------------------------

type Operation =
  | 'makeAdmin'
  | 'makeSuperadmin'
  | 'makeMember'
  | 'demoteToAdmin'
  | 'ban'
  | 'unban'
  | 'trust'
  | 'untrust'
  | 'resend'

const OPERATIONS: Record<
  Operation,
  { icon: string; danger?: boolean; run: (id: number) => Promise<unknown> }
> = {
  makeAdmin: {
    icon: 'i-lucide-shield-plus',
    run: (id) => admin.userAction(id, 'promote', 'admin'),
  },
  makeSuperadmin: {
    icon: 'i-lucide-shield-check',
    run: (id) => admin.userAction(id, 'promote', 'superadmin'),
  },
  makeMember: {
    icon: 'i-lucide-shield-minus',
    danger: true,
    run: (id) => admin.userAction(id, 'demote'),
  },
  demoteToAdmin: {
    icon: 'i-lucide-shield-minus',
    danger: true,
    run: (id) => admin.userAction(id, 'demote'),
  },
  ban: { icon: 'i-lucide-ban', danger: true, run: (id) => admin.userAction(id, 'ban') },
  unban: { icon: 'i-lucide-user-check', run: (id) => admin.userAction(id, 'unban') },
  trust: { icon: 'i-lucide-badge-check', run: (id) => admin.userAction(id, 'trust') },
  untrust: { icon: 'i-lucide-badge-x', run: (id) => admin.userAction(id, 'untrust') },
  resend: { icon: 'i-lucide-mail', run: (id) => admin.resendVerification(id) },
}

/** What the current admin may do to `user` (mirrors the API's role rules). */
function operationsFor(user: AdminUser): Operation[] {
  if (user.deleted_at) return []
  const self = me.value?.id === user.id
  const ops: Operation[] = []
  if (!self) {
    if (user.role === 'member') ops.push('makeAdmin')
    if (user.role === 'admin') {
      if (isSuperadmin.value) ops.push('makeSuperadmin')
      ops.push('makeMember')
    }
    if (user.role === 'superadmin' && isSuperadmin.value) ops.push('demoteToAdmin')
  }
  if (user.role !== 'superadmin' || isSuperadmin.value) {
    if (user.is_active && !self) ops.push('ban')
    if (!user.is_active) ops.push('unban')
  }
  ops.push(user.is_trusted ? 'untrust' : 'trust')
  if (!user.is_verified) ops.push('resend')
  return ops
}

const pending = ref<{ user: AdminUser; op: Operation } | null>(null)
const confirmOpen = ref(false)
const running = ref(false)
const runError = ref('')

function ask(user: AdminUser, op: Operation) {
  pending.value = { user, op }
  runError.value = ''
  confirmOpen.value = true
}

function menuItems(user: AdminUser): DropdownMenuItem[] {
  return operationsFor(user).map((op) => ({
    label: t(`admin.users.actions.${op}`),
    icon: OPERATIONS[op].icon,
    color: OPERATIONS[op].danger ? 'error' : undefined,
    onSelect: () => ask(user, op),
  }))
}

async function run() {
  const current = pending.value
  if (!current || running.value) return
  running.value = true
  runError.value = ''
  try {
    await OPERATIONS[current.op].run(current.user.id)
    confirmOpen.value = false
    toast.add({
      title: t(`admin.users.done.${current.op}`, { name: current.user.display_name }),
      color: 'success',
      icon: 'i-lucide-check',
    })
  } catch (error) {
    runError.value = adminError(error)
  } finally {
    running.value = false
  }
}

const dialog = computed(() => {
  const current = pending.value
  if (!current) return { title: '', description: '', label: '', color: 'primary' as const }
  const name = current.user.display_name
  return {
    title: t(`admin.users.confirm.${current.op}`, { name }),
    description: t(`admin.users.descriptions.${current.op}`),
    label: t(`admin.users.actions.${current.op}`),
    color: OPERATIONS[current.op].danger ? ('error' as const) : ('primary' as const),
  }
})
</script>

<template>
  <div>
    <AdminPageHeader :title="t('admin.users.title')" :intro="t('admin.users.intro')" />

    <section aria-labelledby="users-filters" class="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
      <h2 id="users-filters" class="sr-only">{{ t('admin.users.search') }}</h2>
      <UFormField :label="t('admin.users.search')" name="q" class="sm:col-span-2 xl:col-span-1">
        <UInput
          v-model="search"
          type="search"
          icon="i-lucide-search"
          :placeholder="t('admin.users.searchPlaceholder')"
          class="w-full"
        />
      </UFormField>
      <UFormField :label="t('admin.users.role')" name="role">
        <USelect v-model="roleFilter" :items="roleItems" class="w-full" />
      </UFormField>
      <UFormField v-for="flag in FLAGS" :key="flag" :label="t(`admin.users.${flag}`)" :name="flag">
        <USelect v-model="flagFilters[flag].value" :items="flagItems" class="w-full" />
      </UFormField>
      <USwitch
        v-model="showDeleted"
        name="deleted"
        :label="t('admin.users.showDeleted')"
        class="sm:col-span-2 xl:col-span-5"
      />
    </section>

    <ListState
      :initial="users.initial"
      :loading="users.loading"
      :failed="users.failed"
      @retry="admin.reloadUsers()"
    >
      <p
        v-if="!users.items.length"
        class="rounded border border-default p-6 text-center text-muted"
      >
        {{ t('admin.users.empty') }}
      </p>
      <div v-else data-testid="users-table" class="overflow-x-auto">
        <UTable
          :data="users.items"
          :columns="columns"
          :caption="t('admin.users.caption')"
          :loading="users.loading"
          :ui="{ caption: 'sr-only', td: 'align-top' }"
        >
          <template #user-cell="{ row }">
            <div class="min-w-48 space-y-0.5">
              <div class="flex flex-wrap items-center gap-1.5">
                <ULink :to="`/u/${row.original.id}`" class="font-medium hover:underline">
                  {{ row.original.display_name }}
                </ULink>
                <UBadge
                  v-if="row.original.id === me?.id"
                  color="neutral"
                  variant="outline"
                  size="sm"
                >
                  {{ t('admin.users.you') }}
                </UBadge>
                <UBadge v-if="row.original.deleted_at" color="neutral" variant="subtle" size="sm">
                  {{ t('admin.users.deleted') }}
                </UBadge>
              </div>
              <p class="text-sm text-muted">{{ row.original.email }}</p>
            </div>
          </template>
          <template #role-cell="{ row }">
            <UBadge :color="ROLE_COLOR[row.original.role]" variant="subtle" size="sm">
              {{ t(`admin.role.${row.original.role}`) }}
            </UBadge>
          </template>
          <template #verified-cell="{ row }">
            {{ row.original.is_verified ? t('admin.common.yes') : t('admin.common.no') }}
          </template>
          <template #trusted-cell="{ row }">
            {{ row.original.is_trusted ? t('admin.common.yes') : t('admin.common.no') }}
          </template>
          <template #active-cell="{ row }">
            <!-- Deletion also switches the account off (is_active false), so check it first:
                 a deleted account is not a banned one. -->
            <span v-if="row.original.deleted_at" class="text-muted">
              {{ t('admin.users.deleted') }}
            </span>
            <UBadge v-else-if="!row.original.is_active" color="error" variant="subtle" size="sm">
              {{ t('admin.users.banned') }}
            </UBadge>
            <span v-else>{{ t('admin.common.yes') }}</span>
          </template>
          <template #created-cell="{ row }">
            <RelativeTime :datetime="row.original.created_at" />
          </template>
          <template #actions-cell="{ row }">
            <UDropdownMenu
              v-if="menuItems(row.original).length"
              :items="menuItems(row.original)"
              :content="{ align: 'end' }"
            >
              <UButton
                color="neutral"
                variant="ghost"
                icon="i-lucide-ellipsis-vertical"
                :aria-label="t('admin.users.menu', { name: row.original.display_name })"
              />
            </UDropdownMenu>
          </template>
        </UTable>
      </div>
      <AdminPagination
        :page="page"
        :total="users.total"
        :page-size="ADMIN_PAGE_SIZE"
        @update:page="setPage"
      />
    </ListState>

    <ConfirmDialog
      v-model:open="confirmOpen"
      :title="dialog.title"
      :description="dialog.description"
      :confirm-label="dialog.label"
      :color="dialog.color"
      :loading="running"
      :error="runError"
      @confirm="run"
    />
  </div>
</template>

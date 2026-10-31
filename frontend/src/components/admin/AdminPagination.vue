<script setup lang="ts">
import { useI18n } from 'vue-i18n'

/** Page links under an admin list (only when there is more than one page). */
defineProps<{ page: number; total: number; pageSize: number }>()
const emit = defineEmits<{ 'update:page': [page: number] }>()

const { t } = useI18n()
</script>

<template>
  <div v-if="total > pageSize" class="flex justify-center pt-4">
    <UPagination
      :page="page"
      :total="total"
      :items-per-page="pageSize"
      :aria-label="t('admin.common.pagination')"
      @update:page="(next: number) => emit('update:page', next)"
    />
  </div>
</template>

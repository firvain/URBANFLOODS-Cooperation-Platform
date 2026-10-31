<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { useKnowbaseStore, type KbFamily } from '@/stores/knowbase'

/**
 * Warning shown when the KNOWBASE could not be reached on the last list request of the given
 * families (all by default): cached data (`X-Knowbase-Cache: stale`) or none at all (503).
 */
const props = defineProps<{ families?: KbFamily[] }>()

const { t } = useI18n()
const store = useKnowbaseStore()
const status = computed(() => store.statusOf(props.families))
</script>

<template>
  <div role="status">
    <UAlert
      v-if="status !== 'ok'"
      data-testid="knowbase-status"
      color="warning"
      variant="subtle"
      icon="i-lucide-triangle-alert"
      :title="status === 'stale' ? t('knowbase.status.stale') : t('knowbase.status.unavailable')"
    />
  </div>
</template>

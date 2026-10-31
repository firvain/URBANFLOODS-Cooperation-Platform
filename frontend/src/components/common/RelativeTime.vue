<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { formatDateTime, formatRelative } from '@/utils/datetime'

/**
 * A moment as relative time ("3 hours ago") in a `<time>` element whose `datetime` carries the
 * ISO value and whose `title` the full local date and time.
 */
const props = defineProps<{ datetime: string }>()

const { locale } = useI18n()

const relative = computed(() => formatRelative(props.datetime, locale.value))
const full = computed(() => formatDateTime(props.datetime, locale.value))
</script>

<template>
  <time :datetime="datetime" :title="full">{{ relative }}</time>
</template>

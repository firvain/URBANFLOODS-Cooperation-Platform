<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { knowbaseService, type KbType, type MentionPost } from '@/services/knowbase'

/**
 * "Mentioned in": platform posts that link this KNOWBASE item. Rendered only when the request
 * succeeds with at least one post; otherwise nothing is shown.
 */
const props = defineProps<{ kbType: KbType; kbId: number }>()

const { t } = useI18n()
const posts = ref<MentionPost[]>([])

onMounted(async () => {
  try {
    const { data } = await knowbaseService.mentions(props.kbType, props.kbId)
    posts.value = data.items
  } catch {
    posts.value = []
  }
})
</script>

<template>
  <section
    v-if="posts.length"
    data-testid="kb-mentions"
    aria-labelledby="kb-mentions-heading"
    class="space-y-3"
  >
    <h2 id="kb-mentions-heading" class="text-lg font-semibold text-secondary">
      {{ t('knowbase.mentions.title') }}
    </h2>
    <ul class="space-y-2">
      <li v-for="post in posts" :key="post.id">
        <ULink
          :to="`/blog/${post.slug}`"
          raw
          class="font-medium text-primary-700 underline underline-offset-2 hover:text-primary-800"
        >
          {{ post.title }}
        </ULink>
        <p v-if="post.excerpt" class="text-sm text-gray-700">{{ post.excerpt }}</p>
      </li>
    </ul>
  </section>
</template>

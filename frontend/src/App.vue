<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useHead } from '@unhead/vue'

import AppFooter from '@/components/layout/AppFooter.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import SkipLink from '@/components/layout/SkipLink.vue'
import UnverifiedBanner from '@/components/auth/UnverifiedBanner.vue'
import { useFocusOnRouteChange } from '@/composables/useFocusOnRouteChange'
import { pageTitle } from '@/router'

const { announcement } = useFocusOnRouteChange()

// The route title as the base `<head>` entry: pages that set their own (`usePageHead`) override
// it, and it comes back when they unmount (unhead would otherwise restore an older title).
const route = useRoute()
useHead({ title: computed(() => pageTitle(route.meta.title)) })
</script>

<template>
  <UApp>
    <SkipLink />
    <!-- Footer at the bottom of the viewport on short pages, after the content on long ones. -->
    <div class="flex min-h-screen flex-col">
      <AppHeader />
      <main id="main" class="flex-1">
        <UnverifiedBanner />
        <RouterView />
      </main>
      <AppFooter />
    </div>
    <div aria-live="polite" aria-atomic="true" class="sr-only">{{ announcement }}</div>
  </UApp>
</template>

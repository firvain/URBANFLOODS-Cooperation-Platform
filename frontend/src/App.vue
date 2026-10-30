<script setup lang="ts">
import AppFooter from '@/components/layout/AppFooter.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import SkipLink from '@/components/layout/SkipLink.vue'
import UnverifiedBanner from '@/components/auth/UnverifiedBanner.vue'
import { useFocusOnRouteChange } from '@/composables/useFocusOnRouteChange'

const { announcement } = useFocusOnRouteChange()
</script>

<template>
  <UApp>
    <SkipLink />
    <AppHeader />
    <main id="main" class="min-h-[calc(100vh-var(--ui-header-height))]">
      <UnverifiedBanner />
      <RouterView />
    </main>
    <AppFooter />
    <div aria-live="polite" aria-atomic="true" class="sr-only">{{ announcement }}</div>
  </UApp>
</template>

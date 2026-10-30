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

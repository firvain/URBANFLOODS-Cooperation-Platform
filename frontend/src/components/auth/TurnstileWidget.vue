<script setup lang="ts">
import { onBeforeUnmount, onMounted, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

/**
 * Cloudflare Turnstile, rendered only when `VITE_TURNSTILE_SITE_KEY` is set (absent in dev and
 * tests, where the backend runs with `TURNSTILE_ENABLED=false`). Loads the script once and
 * exposes the token through `v-model:token` (null when it expires).
 */
const token = defineModel<string | null>('token', { default: null })

const SCRIPT_SRC = 'https://challenges.cloudflare.com/turnstile/v0/api.js'
const CALLBACK = 'ufTurnstileCallback'
const EXPIRED_CALLBACK = 'ufTurnstileExpired'

type TurnstileApi = { render: (el: HTMLElement) => void }
type TurnstileWindow = Window & {
  turnstile?: TurnstileApi
  [CALLBACK]?: (value: string) => void
  [EXPIRED_CALLBACK]?: () => void
}

const siteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY
const container = useTemplateRef<HTMLElement>('container')
const { locale } = useI18n()

onMounted(() => {
  if (!siteKey) return
  const w = window as TurnstileWindow
  w[CALLBACK] = (value) => (token.value = value)
  w[EXPIRED_CALLBACK] = () => (token.value = null)

  if (w.turnstile && container.value) {
    // Script already loaded by an earlier mount: implicit rendering will not rescan the page.
    w.turnstile.render(container.value)
  } else if (!document.querySelector(`script[src="${SCRIPT_SRC}"]`)) {
    const script = document.createElement('script')
    script.src = SCRIPT_SRC
    script.async = true
    script.defer = true
    document.head.appendChild(script)
  }
})

onBeforeUnmount(() => {
  const w = window as TurnstileWindow
  delete w[CALLBACK]
  delete w[EXPIRED_CALLBACK]
})
</script>

<template>
  <div
    v-if="siteKey"
    ref="container"
    class="cf-turnstile"
    :data-sitekey="siteKey"
    :data-callback="CALLBACK"
    :data-expired-callback="EXPIRED_CALLBACK"
    :data-language="locale"
  />
</template>

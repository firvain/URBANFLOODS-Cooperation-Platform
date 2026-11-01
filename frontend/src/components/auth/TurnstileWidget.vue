<script lang="ts">
import { TURNSTILE_ONLOAD, TURNSTILE_SCRIPT_SRC } from '@/constants/turnstile'

type TurnstileParams = {
  sitekey: string
  language: string
  callback: (token: string) => void
  'expired-callback': () => void
  'error-callback': () => void
}
type TurnstileApi = {
  render: (container: HTMLElement, params: TurnstileParams) => string | undefined
  reset: (widgetId: string) => void
  remove: (widgetId: string) => void
}
type TurnstileWindow = Window & {
  turnstile?: TurnstileApi
  [TURNSTILE_ONLOAD]?: () => void
}

// Shared by every instance: the script is added at most once per page.
let loading: Promise<TurnstileApi> | null = null

function loadTurnstile(): Promise<TurnstileApi> {
  const w = window as TurnstileWindow
  if (w.turnstile) return Promise.resolve(w.turnstile)
  loading ??= new Promise<TurnstileApi>((resolve, reject) => {
    w[TURNSTILE_ONLOAD] = () => {
      delete w[TURNSTILE_ONLOAD]
      resolve(w.turnstile!)
    }
    const script = document.createElement('script')
    script.src = TURNSTILE_SCRIPT_SRC
    script.async = true
    script.defer = true
    script.onerror = () => {
      // Let a later mount try again.
      loading = null
      script.remove()
      reject(new Error('turnstile.load_failed'))
    }
    document.head.appendChild(script)
  })
  return loading
}
</script>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import { turnstileSiteKey } from '@/constants/turnstile'

/**
 * Cloudflare Turnstile, rendered explicitly and only when `VITE_TURNSTILE_SITE_KEY` is set (absent
 * in dev and tests). Exposes the token through `v-model:token` (null until solved, and again when
 * it expires or errors) and `reset()`: tokens are single-use, so forms call it after every request
 * that may have spent one.
 */
const token = defineModel<string | null>('token', { default: null })

const siteKey = turnstileSiteKey()
const container = useTemplateRef<HTMLElement>('container')
const { locale } = useI18n()

let api: TurnstileApi | null = null
let widgetId: string | null = null
let unmounted = false

onMounted(async () => {
  if (!siteKey) return
  try {
    const loaded = await loadTurnstile()
    if (unmounted || !container.value) return
    widgetId =
      loaded.render(container.value, {
        sitekey: siteKey,
        language: locale.value,
        callback: (value) => (token.value = value),
        'expired-callback': () => (token.value = null),
        'error-callback': () => (token.value = null),
      }) ?? null
    api = loaded
  } catch {
    // Script blocked or failed: the token stays null and the backend answers captcha_failed.
  }
})

onBeforeUnmount(() => {
  unmounted = true
  if (api && widgetId !== null) api.remove(widgetId)
  api = null
  widgetId = null
})

/** Forget the (spent) token and ask Cloudflare for a new one. */
function reset() {
  token.value = null
  if (api && widgetId !== null) api.reset(widgetId)
}

defineExpose({ reset })
</script>

<template>
  <div v-if="siteKey" ref="container" class="cf-turnstile" />
</template>

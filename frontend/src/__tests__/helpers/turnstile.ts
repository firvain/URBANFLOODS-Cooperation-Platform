/**
 * Stand-in for `components/auth/TurnstileWidget.vue` in form specs. Use it with
 * `vi.mock('@/components/auth/TurnstileWidget.vue', () => import('./helpers/turnstile'))`.
 *
 * Each solved challenge yields a fresh token (tok-1, tok-2, …): one on mount and one after every
 * `reset()`, as Cloudflare does. With `turnstileStub.autoSolve = false` the challenge stays
 * unsolved (token null), as while a real visitor is still being checked.
 */
import { defineComponent, h, onMounted, type PropType } from 'vue'

export const turnstileStub = { solved: 0, resets: 0, autoSolve: true }

/** Call in `beforeEach`: token numbering starts again at tok-1. */
export function resetTurnstileStub() {
  turnstileStub.solved = 0
  turnstileStub.resets = 0
  turnstileStub.autoSolve = true
}

export const TURNSTILE_STUB_SELECTOR = '[data-testid="turnstile-widget"]'

export default defineComponent({
  name: 'TurnstileWidget',
  props: { token: { type: String as PropType<string | null>, default: null } },
  emits: ['update:token'],
  setup(_props, { emit, expose }) {
    function solve() {
      if (turnstileStub.autoSolve) emit('update:token', `tok-${++turnstileStub.solved}`)
    }
    function reset() {
      turnstileStub.resets++
      emit('update:token', null)
      solve()
    }
    onMounted(solve)
    expose({ reset })
    return () => h('div', { 'data-testid': 'turnstile-widget' })
  },
})

<script lang="ts">
import { computed, defineComponent, h } from 'vue'

import { sanitizeHtml } from '@/utils/sanitize'

/**
 * The only place where HTML strings reach the DOM (CLAUDE.md §5): the input is sanitised with
 * DOMPurify (http/https/mailto links only, external links in a new tab) and set as the
 * `innerHTML` of a native element (`tag`, default `div`). A render function rather than
 * `<component :is v-html>`, which the Vue lint rules reject for components.
 */
export default defineComponent({
  name: 'SafeHtml',
  props: {
    html: { type: String, required: true },
    tag: { type: String, default: 'div' },
  },
  setup(props) {
    const clean = computed(() => sanitizeHtml(props.html))
    return () => h(props.tag, { innerHTML: clean.value })
  },
})
</script>

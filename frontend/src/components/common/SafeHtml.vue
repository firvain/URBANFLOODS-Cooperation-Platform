<script lang="ts">
import { computed, defineComponent, h, type PropType } from 'vue'

import { sanitizeHtml } from '@/utils/sanitize'

/**
 * The only place where HTML strings reach the DOM (CLAUDE.md §5): the input is sanitised with
 * DOMPurify (http/https/mailto links only, external links in a new tab) and set as the
 * `innerHTML` of a native element (`tag`, default `div`). A render function rather than
 * `<component :is v-html>`, which the Vue lint rules reject for components.
 *
 * `allowedTags` narrows the output to those elements, without attributes (search snippets:
 * `['mark']`); without it the default rich-text configuration applies.
 */
export default defineComponent({
  name: 'SafeHtml',
  props: {
    html: { type: String, required: true },
    tag: { type: String, default: 'div' },
    allowedTags: { type: Array as PropType<readonly string[]>, default: undefined },
  },
  setup(props) {
    const clean = computed(() => sanitizeHtml(props.html, { allowedTags: props.allowedTags }))
    return () => h(props.tag, { innerHTML: clean.value })
  },
})
</script>

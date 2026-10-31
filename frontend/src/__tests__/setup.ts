import { afterEach, beforeEach, vi } from 'vitest'

import { mockApi } from './helpers/api'

// happy-dom does not implement matchMedia fully for Nuxt UI color mode; provide a stable stub.
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  })
}

// happy-dom defines `Node.prototype.nodeName` as `''` and overrides it in each subclass, whereas
// browsers (per the DOM spec) have one getter on Node.prototype. DOMPurify reads nodeName through
// the Node.prototype getter (clobbering protection), so under happy-dom every element looked
// nameless and was stripped. Make the base getter dispatch to the subclass getter, as in a browser.
{
  const base = Object.getOwnPropertyDescriptor(Node.prototype, 'nodeName')!.get!
  Object.defineProperty(Node.prototype, 'nodeName', {
    configurable: true,
    get(this: Node) {
      for (let proto = Object.getPrototypeOf(this); proto && proto !== Node.prototype;) {
        const getter = Object.getOwnPropertyDescriptor(proto, 'nodeName')?.get
        if (getter) return getter.call(this)
        proto = Object.getPrototypeOf(proto)
      }
      return base.call(this)
    },
  })
}

// happy-dom's NodeIterator stops when the node it just returned is removed (browsers move the
// iterator back to the preceding node, per the DOM spec). DOMPurify removes nodes while iterating,
// so under happy-dom everything after a removed element (a <script>, a rejected <img>) escaped
// sanitisation. Only when the bug is present: replace createNodeIterator with a spec-compatible
// one (forward traversal that survives removal of the current node, which is all DOMPurify needs).
{
  const probe = document.implementation.createHTMLDocument('')
  probe.body.innerHTML = '<i></i><b></b>'
  const iterator = probe.createNodeIterator(probe.body, NodeFilter.SHOW_ELEMENT)
  iterator.nextNode() // <body>
  ;(iterator.nextNode() as ChildNode).remove() // <i>
  if (iterator.nextNode()?.nodeName !== 'B') {
    /** The node after `node`'s subtree in document order, within `root`. */
    const following = (node: Node | null, root: Node): Node | null => {
      for (let n = node; n && n !== root; n = n.parentNode) if (n.nextSibling) return n.nextSibling
      return null
    }
    // Patch the prototype that defines it (happy-dom's window classes are subclasses of the
    // global `Document`, so patching `Document.prototype` alone would be shadowed).
    let owner: object = Object.getPrototypeOf(document)
    while (!Object.prototype.hasOwnProperty.call(owner, 'createNodeIterator')) {
      owner = Object.getPrototypeOf(owner)
    }
    ;(owner as Document).createNodeIterator = function (
      root: Node,
      whatToShow = NodeFilter.SHOW_ALL,
      filter: NodeFilter | null = null,
    ): NodeIterator {
      let current: Node | null = null
      let parent: Node | null = null
      let previous: Node | null = null
      const accept = (node: Node) => {
        if (!((1 << (node.nodeType - 1)) & whatToShow)) return false
        if (!filter) return true
        const result = typeof filter === 'function' ? filter(node) : filter.acceptNode(node)
        return result === NodeFilter.FILTER_ACCEPT
      }
      const successor = (): Node | null => {
        if (!current) return root
        if (current !== root && current.parentNode !== parent) {
          // The current node was removed: continue where it used to be. (Removing the root does
          // not move the iterator, as in browsers: DOMPurify detaches a disallowed <body> root.)
          const next = previous?.parentNode === parent ? previous!.nextSibling : parent?.firstChild
          return next ?? following(parent, root)
        }
        return current.firstChild ?? following(current, root)
      }
      return {
        root,
        whatToShow,
        filter,
        get referenceNode() {
          return current ?? root
        },
        pointerBeforeReferenceNode: false,
        nextNode() {
          for (let node = successor(); node; node = successor()) {
            current = node
            parent = node.parentNode
            previous = node.previousSibling
            if (accept(node)) return node
          }
          return null
        },
        previousNode: () => {
          throw new Error('previousNode is not implemented by the test shim')
        },
        detach() {},
      } as NodeIterator
    }
  }
}

// No test touches the network: every test starts with a fetch stub (anonymous `GET /auth/me`,
// 404 for anything unmocked). Tests override it with their own `mockApi(...)`/`vi.stubGlobal`.
beforeEach(() => {
  mockApi()
})

afterEach(() => {
  localStorage.clear()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

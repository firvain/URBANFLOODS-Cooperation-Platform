import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'

import i18n from '@/i18n'

declare module 'vue-router' {
  interface RouteMeta {
    /** i18n key of the page title. */
    title: string
  }
}

export const routes = [
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/HomeView.vue'),
    meta: { title: 'app.title' },
  },
  {
    path: '/partners',
    name: 'partners',
    component: () => import('@/views/PartnersView.vue'),
    meta: { title: 'nav.partners' },
  },
  {
    path: '/about',
    name: 'about',
    component: () => import('@/views/AboutView.vue'),
    meta: { title: 'nav.about' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { title: 'errors.notFound' },
  },
]

/** Translated `document.title` for a route title key. */
export function pageTitle(titleKey: string | undefined): string {
  const { t } = i18n.global
  const appTitle = t('app.title')
  if (!titleKey || titleKey === 'app.title') return appTitle
  return `${t(titleKey)} | ${appTitle}`
}

export function createAppRouter(
  history: RouterHistory = createWebHistory(import.meta.env.BASE_URL),
) {
  const router = createRouter({
    history,
    routes,
    scrollBehavior: (_to, _from, saved) => saved ?? { top: 0 },
  })

  router.afterEach((to) => {
    document.title = pageTitle(to.meta.title)
  })

  return router
}

export default createAppRouter()

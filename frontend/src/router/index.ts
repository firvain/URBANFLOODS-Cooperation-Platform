import {
  createRouter,
  createWebHistory,
  type RouteLocationNormalized,
  type RouteLocationRaw,
  type RouteRecordRaw,
  type RouterHistory,
} from 'vue-router'

import i18n from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { safeRedirect } from './redirect'

declare module 'vue-router' {
  interface RouteMeta {
    /** i18n key of the page title. */
    title: string
    /**
     * Who may open the page. `user`: logged in. `verified`: logged in; unverified users get in
     * but the view shows `UnverifiedBanner` and the backend refuses the action. `admin`: admin or
     * superadmin (others see NotFound, so admin URLs are not confirmed to exist).
     */
    auth?: 'user' | 'verified' | 'admin'
    /** Login/register: a logged-in user is sent on to `?next=` (or home). */
    guestOnly?: boolean
  }
}

export const routes: RouteRecordRaw[] = [
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
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: 'auth.login', guestOnly: true },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { title: 'auth.register', guestOnly: true },
  },
  {
    path: '/verify-email',
    name: 'verify-email',
    component: () => import('@/views/VerifyEmailView.vue'),
    meta: { title: 'auth.verify.title' },
  },
  {
    path: '/forgot-password',
    name: 'forgot-password',
    component: () => import('@/views/ForgotPasswordView.vue'),
    meta: { title: 'auth.forgot.title' },
  },
  {
    path: '/reset-password',
    name: 'reset-password',
    component: () => import('@/views/ResetPasswordView.vue'),
    meta: { title: 'auth.reset.title' },
  },
  {
    path: '/account',
    name: 'account',
    component: () => import('@/views/AccountView.vue'),
    meta: { title: 'nav.account', auth: 'user' },
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

/** Render NotFound at the requested URL (no redirect, so the address bar keeps the path). */
function notFoundAt(to: RouteLocationNormalized): RouteLocationRaw {
  return {
    name: 'not-found',
    params: { pathMatch: to.path.substring(1).split('/') },
    query: to.query,
    hash: to.hash,
  }
}

/**
 * Global auth guard. The first navigation waits for `GET /auth/me` (the store shares one
 * in-flight request), so no page renders with an unknown session.
 */
export async function authGuard(to: RouteLocationNormalized): Promise<RouteLocationRaw | void> {
  const auth = useAuthStore()
  if (auth.status === 'unknown') await auth.fetchMe()

  if (to.meta.guestOnly && auth.isAuthenticated) {
    return safeRedirect(to.query.next) ?? { name: 'home' }
  }

  const required = to.meta.auth
  if (!required) return
  if (!auth.isAuthenticated) return { name: 'login', query: { next: to.fullPath } }
  if (required === 'admin' && !auth.isAdmin) return notFoundAt(to)
}

export function createAppRouter(
  history: RouterHistory = createWebHistory(import.meta.env.BASE_URL),
) {
  const router = createRouter({
    history,
    routes,
    scrollBehavior: (_to, _from, saved) => saved ?? { top: 0 },
  })

  router.beforeEach(authGuard)

  router.afterEach((to) => {
    document.title = pageTitle(to.meta.title)
  })

  return router
}

export default createAppRouter()

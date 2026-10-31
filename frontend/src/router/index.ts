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

// Shared loaders: the preset blog/forum lists and the two editor routes render the same view.
const BlogListView = () => import('@/views/BlogListView.vue')
const PostEditorView = () => import('@/views/PostEditorView.vue')
const ForumListView = () => import('@/views/ForumListView.vue')
const ThreadEditorView = () => import('@/views/ThreadEditorView.vue')

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/HomeView.vue'),
    meta: { title: 'app.title' },
  },
  {
    path: '/blog',
    name: 'blog',
    component: BlogListView,
    meta: { title: 'nav.blog' },
  },
  {
    path: '/blog/category/:slug',
    name: 'blog-category',
    component: BlogListView,
    meta: { title: 'nav.blog' },
  },
  {
    path: '/blog/tag/:slug',
    name: 'blog-tag',
    component: BlogListView,
    meta: { title: 'nav.blog' },
  },
  {
    path: '/blog/new',
    name: 'post-new',
    component: PostEditorView,
    meta: { title: 'editor.form.titleNew', auth: 'verified' },
  },
  {
    path: '/blog/:slug',
    name: 'post',
    component: () => import('@/views/PostDetailView.vue'),
    meta: { title: 'post.pageTitle' },
  },
  {
    path: '/blog/:slug/edit',
    name: 'post-edit',
    component: PostEditorView,
    meta: { title: 'editor.form.titleEdit', auth: 'verified' },
  },
  {
    path: '/forum',
    name: 'forum',
    component: ForumListView,
    meta: { title: 'nav.forum' },
  },
  {
    path: '/forum/c/:slug',
    name: 'forum-category',
    component: ForumListView,
    meta: { title: 'nav.forum' },
  },
  {
    path: '/forum/new',
    name: 'thread-new',
    component: ThreadEditorView,
    meta: { title: 'thread.form.titleNew', auth: 'verified' },
  },
  {
    path: '/forum/t/:slug',
    name: 'thread',
    component: () => import('@/views/ThreadDetailView.vue'),
    meta: { title: 'thread.pageTitle' },
  },
  {
    path: '/forum/t/:slug/edit',
    name: 'thread-edit',
    component: ThreadEditorView,
    meta: { title: 'thread.form.titleEdit', auth: 'verified' },
  },
  {
    path: '/partners',
    name: 'partners',
    component: () => import('@/views/PartnersView.vue'),
    meta: { title: 'nav.partners' },
  },
  {
    path: '/network',
    name: 'network',
    component: () => import('@/views/NetworkView.vue'),
    meta: { title: 'nav.network' },
  },
  {
    path: '/knowbase',
    name: 'knowbase',
    component: () => import('@/views/KnowbaseView.vue'),
    meta: { title: 'nav.knowbase' },
  },
  {
    path: '/knowbase/measures',
    name: 'knowbase-measures',
    component: () => import('@/views/MeasuresView.vue'),
    meta: { title: 'knowbase.measures.title' },
  },
  {
    path: '/knowbase/measures/:id',
    name: 'knowbase-measure',
    component: () => import('@/views/MeasureDetailView.vue'),
    meta: { title: 'knowbase.measures.detailTitle' },
  },
  {
    path: '/knowbase/documents',
    name: 'knowbase-documents',
    component: () => import('@/views/DocumentsView.vue'),
    meta: { title: 'knowbase.documents.title' },
  },
  {
    path: '/knowbase/documents/:id',
    name: 'knowbase-document',
    component: () => import('@/views/DocumentDetailView.vue'),
    meta: { title: 'knowbase.documents.detailTitle' },
  },
  {
    path: '/u/:id',
    name: 'profile',
    component: () => import('@/views/ProfileView.vue'),
    meta: { title: 'profile.title' },
  },
  {
    path: '/about',
    name: 'about',
    component: () => import('@/views/AboutView.vue'),
    meta: { title: 'nav.about' },
  },
  {
    path: '/terms',
    name: 'terms',
    component: () => import('@/views/LegalView.vue'),
    props: { doc: 'terms' },
    meta: { title: 'legal.termsTitle' },
  },
  {
    path: '/privacy',
    name: 'privacy',
    component: () => import('@/views/LegalView.vue'),
    props: { doc: 'privacy' },
    meta: { title: 'legal.privacyTitle' },
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

/**
 * Back/forward restores the saved position; a `#hash` scrolls to that element (in-page links on
 * the legal pages) below the sticky header; anything else starts at the top.
 */
export function scrollBehavior(
  to: RouteLocationNormalized,
  _from: RouteLocationNormalized,
  saved: { left: number; top: number } | null,
) {
  if (saved) return saved
  if (to.hash) {
    const headerHeight = document.querySelector<HTMLElement>('header')?.offsetHeight ?? 0
    return { el: to.hash, top: headerHeight + 16 }
  }
  return { top: 0 }
}

export function createAppRouter(
  history: RouterHistory = createWebHistory(import.meta.env.BASE_URL),
) {
  const router = createRouter({
    history,
    routes,
    scrollBehavior,
  })

  router.beforeEach(authGuard)

  router.afterEach((to) => {
    document.title = pageTitle(to.meta.title)
  })

  return router
}

export default createAppRouter()

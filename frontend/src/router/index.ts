import {
  createRouter,
  createWebHistory,
  type RouteLocationNormalized,
  type RouteLocationRaw,
  type RouteRecordRaw,
  type RouterHistory,
} from 'vue-router'

import i18n from '@/i18n'
import { formatPageTitle } from '@/composables/usePageHead'
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
    path: '/search',
    name: 'search',
    component: () => import('@/views/SearchView.vue'),
    meta: { title: 'search.title' },
  },
  {
    // The partners are a section of the About page (user decision 2026-10-31); the route and its
    // name stay so old links and bookmarks land on that section.
    path: '/partners',
    name: 'partners',
    redirect: { name: 'about', hash: '#partnership' },
  },
  {
    path: '/network',
    name: 'network',
    component: () => import('@/views/NetworkView.vue'),
    meta: { title: 'nav.network' },
  },
  {
    path: '/knowbase/measures/:id',
    name: 'knowbase-measure',
    component: () => import('@/views/MeasureDetailView.vue'),
    meta: { title: 'knowbase.measures.detailTitle' },
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
    // Member profiles are for verified users (as `GET /members/{id}`).
    meta: { title: 'profile.title', auth: 'verified' },
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
    path: '/accessibility',
    name: 'accessibility',
    component: () => import('@/views/LegalView.vue'),
    props: { doc: 'accessibility' },
    meta: { title: 'legal.accessibilityTitle' },
  },
  {
    path: '/open-data',
    name: 'open-data',
    component: () => import('@/views/LegalView.vue'),
    props: { doc: 'openData' },
    meta: { title: 'legal.openDataTitle' },
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
    path: '/confirm-email',
    name: 'confirm-email',
    component: () => import('@/views/ConfirmEmailView.vue'),
    meta: { title: 'auth.confirmEmail.title' },
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
    // Admin area: every child inherits `auth: 'admin'` (route meta is merged parent → child).
    path: '/admin',
    component: () => import('@/views/admin/AdminLayout.vue'),
    meta: { title: 'admin.title', auth: 'admin' },
    children: [
      {
        path: '',
        name: 'admin-dashboard',
        component: () => import('@/views/admin/AdminDashboardView.vue'),
        meta: { title: 'admin.dashboard.title' },
      },
      {
        path: 'queue',
        name: 'admin-queue',
        component: () => import('@/views/admin/AdminQueueView.vue'),
        meta: { title: 'admin.queue.title' },
      },
      {
        path: 'reports',
        name: 'admin-reports',
        component: () => import('@/views/admin/AdminReportsView.vue'),
        meta: { title: 'admin.reports.title' },
      },
      {
        path: 'users',
        name: 'admin-users',
        component: () => import('@/views/admin/AdminUsersView.vue'),
        meta: { title: 'admin.users.title' },
      },
      {
        path: 'categories',
        name: 'admin-categories',
        component: () => import('@/views/admin/AdminCategoriesView.vue'),
        meta: { title: 'admin.categories.title' },
      },
      {
        path: 'tags',
        name: 'admin-tags',
        component: () => import('@/views/admin/AdminTagsView.vue'),
        meta: { title: 'admin.tags.title' },
      },
      {
        path: 'organisations',
        name: 'admin-organisations',
        component: () => import('@/views/admin/AdminOrganisationsView.vue'),
        meta: { title: 'admin.organisations.title' },
      },
      {
        path: 'expertise',
        name: 'admin-expertise',
        component: () => import('@/views/admin/AdminExpertiseView.vue'),
        meta: { title: 'admin.expertise.title' },
      },
      {
        path: 'log',
        name: 'admin-log',
        component: () => import('@/views/admin/AdminLogView.vue'),
        meta: { title: 'admin.log.title' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { title: 'errors.notFound' },
  },
]

/**
 * Translated page title for a route title key, in the `usePageHead` format. `App.vue` sets it as
 * the fallback `<head>` title (usePageHead owns `document.title`); the route-change announcement
 * reads it too.
 */
export function pageTitle(titleKey: string | undefined): string {
  return formatPageTitle(titleKey ? i18n.global.t(titleKey) : '')
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
 * the legal pages, `/about#partnership`) below the sticky header; anything else starts at the top.
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

  return router
}

export default createAppRouter()

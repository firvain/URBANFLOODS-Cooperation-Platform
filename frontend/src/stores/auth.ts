/**
 * Auth store: who is logged in. The session lives in the HttpOnly `uf_session` cookie, so the
 * store never sees a token; it learns the user from `GET /auth/me` (once, before the first route
 * guard) and from the endpoints that log in (login, verify-email, password reset).
 */
import { computed, hasInjectionContext, ref } from 'vue'
import { defineStore } from 'pinia'
import { useToast } from '@nuxt/ui/composables'

import i18n from '@/i18n'
import { setApiHooks } from '@/services/api'
import {
  authService,
  type RegisterPayload,
  type UpdateMePayload,
  type UserMe,
} from '@/services/auth'

export type AuthStatus = 'unknown' | 'anonymous' | 'authenticated'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserMe | null>(null)
  const status = ref<AuthStatus>('unknown')
  const loading = ref(false)

  const isAuthenticated = computed(() => status.value === 'authenticated' && user.value !== null)
  const isVerified = computed(() => isAuthenticated.value && user.value!.is_verified)
  const isTrusted = computed(() => isAuthenticated.value && user.value!.is_trusted)
  const isAdmin = computed(
    () =>
      isAuthenticated.value && (user.value!.role === 'admin' || user.value!.role === 'superadmin'),
  )
  const isSuperadmin = computed(() => isAuthenticated.value && user.value!.role === 'superadmin')

  function setUser(next: UserMe): UserMe {
    user.value = next
    status.value = 'authenticated'
    return next
  }

  /** Forget the user locally (logout, or the server said the session is gone). */
  function clear(): void {
    user.value = null
    status.value = 'anonymous'
  }

  let pendingMe: Promise<void> | null = null

  /** Load the current user. Never throws: 401 (or any failure) means anonymous. */
  function fetchMe(): Promise<void> {
    pendingMe ??= (async () => {
      loading.value = true
      try {
        setUser(await authService.me())
      } catch {
        clear()
      } finally {
        loading.value = false
        pendingMe = null
      }
    })()
    return pendingMe
  }

  async function login(email: string, password: string): Promise<UserMe> {
    loading.value = true
    try {
      return setUser(await authService.login(email, password))
    } catch (error) {
      if (status.value === 'unknown') status.value = 'anonymous'
      throw error
    } finally {
      loading.value = false
    }
  }

  async function logout(): Promise<void> {
    try {
      await authService.logout()
    } catch {
      // The local session ends regardless; the cookie expires server-side.
    } finally {
      clear()
    }
  }

  /** Create an account. Does not log in: the user must verify their email first. */
  function register(payload: RegisterPayload) {
    return authService.register(payload)
  }

  async function verifyEmail(token: string): Promise<UserMe> {
    return setUser(await authService.verifyEmail(token))
  }

  function resendVerification(email: string, turnstileToken?: string | null) {
    return authService.resendVerification(email, turnstileToken)
  }

  function forgotPassword(email: string, turnstileToken?: string | null) {
    return authService.forgotPassword(email, turnstileToken)
  }

  async function resetPassword(token: string, password: string): Promise<UserMe> {
    return setUser(await authService.resetPassword(token, password))
  }

  /** Save profile changes and keep the store's user in sync with the server's answer. */
  async function updateProfile(changes: UpdateMePayload): Promise<UserMe> {
    return setUser(await authService.updateMe(changes))
  }

  function changePassword(currentPassword: string, newPassword: string): Promise<void> {
    return authService.changePassword(currentPassword, newPassword)
  }

  /** Delete the account (throws the `ApiError`); on success the user is signed out here too. */
  async function deleteAccount(currentPassword: string): Promise<void> {
    await authService.deleteMe(currentPassword)
    clear()
  }

  // Toasts need the app's injection context (Pinia provides it when installed in an app).
  const toast = hasInjectionContext() ? useToast() : null
  setApiHooks({
    onUnauthorized: clear,
    onRateLimited: () =>
      toast?.add({
        id: 'too-many-requests',
        title: i18n.global.t('errors.tooManyRequests'),
        color: 'warning',
        icon: 'i-lucide-timer',
      }),
  })

  return {
    user,
    status,
    loading,
    isAuthenticated,
    isVerified,
    isTrusted,
    isAdmin,
    isSuperadmin,
    fetchMe,
    login,
    logout,
    register,
    verifyEmail,
    resendVerification,
    forgotPassword,
    resetPassword,
    updateProfile,
    changePassword,
    deleteAccount,
    clear,
  }
})

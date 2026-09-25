import * as React from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { authApi } from '@/api/endpoints/auth'
import { isApiError } from '@/api/errors'
import { setUnauthorizedHandler } from '@/api/http'
import { tokenStore } from '@/api/token-store'
import type { AuthResponse, LoginRequest, SignupRequest, UserDto } from '@/api/types'
import {
  AuthContext,
  type AuthContextValue,
  type AuthStatus,
  type LogoutReason,
} from '@/auth/auth-context'
import { EXPIRY_GRACE_MS, EXPIRY_WARNING_MS, isExpired } from '@/auth/session'
import { clearLastOrgId } from '@/org/last-org'
import { qk } from '@/queries/keys'

/**
 * Owns the session: bootstrap, sign-in/out, and expiry.
 *
 * `GET /api/auth/me` is the single source of truth on load — the API resolves
 * roles per request rather than from JWT claims, so nothing about permissions
 * can be trusted from the stored token.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const [status, setStatus] = React.useState<AuthStatus>(() =>
    tokenStore.get() ? 'loading' : 'anonymous',
  )
  const [user, setUser] = React.useState<UserDto | null>(null)
  const [bootstrapNonce, setBootstrapNonce] = React.useState(0)

  const logout = React.useCallback(
    (reason: LogoutReason = 'user') => {
      tokenStore.clear()
      clearLastOrgId()
      setUser(null)
      setStatus('anonymous')
      // Never leave another account's data in the cache.
      queryClient.clear()

      const next = `${window.location.pathname}${window.location.search}`
      const params = new URLSearchParams()
      if (next && next !== '/' && !next.startsWith('/login')) params.set('next', next)
      if (reason === 'expired') params.set('reason', 'expired')
      const query = params.toString()
      navigate(`/login${query ? `?${query}` : ''}`, { replace: true })
    },
    [navigate, queryClient],
  )

  // A 401 from anywhere means the token is no longer usable.
  React.useEffect(() => {
    setUnauthorizedHandler(() => logout('expired'))
    return () => setUnauthorizedHandler(null)
  }, [logout])

  // Bootstrap: validate the stored token and load the caller's memberships.
  // All state writes happen inside the async body: a synchronous setState in an
  // effect triggers a cascading render, which the React Compiler lint rules flag.
  React.useEffect(() => {
    const controller = new AbortController()
    let cancelled = false

    void (async () => {
      const session = tokenStore.get()
      if (!session || isExpired(session)) {
        tokenStore.clear()
        if (!cancelled) setStatus('anonymous')
        return
      }

      try {
        const me = await authApi.me(controller.signal)
        if (cancelled) return
        setUser(me)
        queryClient.setQueryData(qk.auth.me(), me)
        setStatus('authenticated')
      } catch (error) {
        if (cancelled || controller.signal.aborted) return
        // An unreachable API is not a logout: showing the login page here would
        // look like the session was dropped when it is still perfectly valid.
        if (isApiError(error) && error.isNetwork) {
          setStatus('unreachable')
          return
        }
        tokenStore.clear()
        setUser(null)
        setStatus('anonymous')
      }
    })()

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [queryClient, bootstrapNonce])

  // Expiry timers, re-armed whenever the tab becomes visible again so a laptop
  // resumed from sleep does not sit on stale timeouts.
  React.useEffect(() => {
    if (status !== 'authenticated') return

    let warningTimer: number | undefined
    let logoutTimer: number | undefined

    const arm = () => {
      window.clearTimeout(warningTimer)
      window.clearTimeout(logoutTimer)

      const session = tokenStore.get()
      if (!session) return

      const remaining = new Date(session.expiresAtUtc).getTime() - Date.now()
      if (remaining <= EXPIRY_GRACE_MS) {
        logout('expired')
        return
      }

      if (remaining > EXPIRY_WARNING_MS) {
        warningTimer = window.setTimeout(() => {
          toast.warning('Your session ends in 5 minutes.', {
            description: 'Sign in again to keep working without losing anything.',
            duration: 30_000,
          })
        }, remaining - EXPIRY_WARNING_MS)
      }

      logoutTimer = window.setTimeout(
        () => logout('expired'),
        remaining - EXPIRY_GRACE_MS,
      )
    }

    arm()
    document.addEventListener('visibilitychange', arm)
    return () => {
      window.clearTimeout(warningTimer)
      window.clearTimeout(logoutTimer)
      document.removeEventListener('visibilitychange', arm)
    }
  }, [status, logout])

  const adopt = React.useCallback(
    (response: AuthResponse) => {
      tokenStore.set({
        accessToken: response.accessToken,
        expiresAtUtc: response.expiresAtUtc,
        userId: response.user.id,
      })
      setUser(response.user)
      queryClient.setQueryData(qk.auth.me(), response.user)
      setStatus('authenticated')
      return response
    },
    [queryClient],
  )

  const login = React.useCallback(
    async (input: LoginRequest) => adopt(await authApi.login(input)),
    [adopt],
  )

  const signup = React.useCallback(
    async (input: SignupRequest) => adopt(await authApi.signup(input)),
    [adopt],
  )

  const retry = React.useCallback(() => {
    setStatus('loading')
    setBootstrapNonce((value) => value + 1)
  }, [])

  const value: AuthContextValue = {
    status,
    user,
    memberships: user?.organizations ?? [],
    login,
    signup,
    logout,
    retry,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

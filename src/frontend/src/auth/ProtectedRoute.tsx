import { Navigate, Outlet, useLocation } from 'react-router'
import { Loader2 } from 'lucide-react'

import { Brand } from '@/components/layout/Brand'
import { ErrorState } from '@/components/feedback/ErrorState'
import { networkError } from '@/api/errors'
import { useAuth } from '@/auth/use-auth'

export function ProtectedRoute() {
  const { status, retry } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return (
      <div className="flex min-h-svh flex-col items-center justify-center gap-4">
        <Brand className="text-lg" />
        <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden="true" />
        <p className="text-sm text-muted-foreground" role="status">
          Restoring your session…
        </p>
      </div>
    )
  }

  // A network failure is not a sign-out: bouncing to the login page here would
  // look like the session was lost when the token is still valid.
  if (status === 'unreachable') {
    return (
      <div className="flex min-h-svh items-center justify-center p-6">
        <ErrorState
          error={networkError()}
          onRetry={retry}
          className="max-w-md"
          title="Cannot reach the server"
        />
      </div>
    )
  }

  if (status === 'anonymous') {
    const next = `${location.pathname}${location.search}`
    const query = next && next !== '/' ? `?next=${encodeURIComponent(next)}` : ''
    return <Navigate to={`/login${query}`} replace />
  }

  return <Outlet />
}

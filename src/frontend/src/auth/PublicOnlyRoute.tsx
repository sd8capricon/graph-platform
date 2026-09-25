import { Navigate, Outlet } from 'react-router'

import { useAuth } from '@/auth/use-auth'

/** Keeps a signed-in user off the login and signup pages. */
export function PublicOnlyRoute() {
  const { status } = useAuth()

  if (status === 'loading') return null
  if (status === 'authenticated') return <Navigate to="/" replace />

  return <Outlet />
}

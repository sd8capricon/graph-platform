import { AuthProvider } from '@/auth/AuthProvider'
import { RootLayout } from '@/components/layout/RootLayout'

/**
 * `AuthProvider` must sit inside the router, because it navigates on logout and
 * on a 401, which needs a router context above it.
 */
export function AuthBoundary() {
  return (
    <AuthProvider>
      <RootLayout />
    </AuthProvider>
  )
}

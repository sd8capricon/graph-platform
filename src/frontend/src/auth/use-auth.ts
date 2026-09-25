import * as React from 'react'

import { AuthContext, type AuthContextValue } from '@/auth/auth-context'

export function useAuth(): AuthContextValue {
  const context = React.useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside <AuthProvider>')
  }
  return context
}

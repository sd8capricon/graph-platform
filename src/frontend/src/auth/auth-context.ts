import * as React from 'react'

import type { AuthResponse, LoginRequest, MembershipDto, SignupRequest, UserDto } from '@/api/types'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous' | 'unreachable'

export type LogoutReason = 'user' | 'expired'

export interface AuthContextValue {
  status: AuthStatus
  user: UserDto | null
  /** Convenience view of `user.organizations`; drives all role gating. */
  memberships: MembershipDto[]
  login: (input: LoginRequest) => Promise<AuthResponse>
  signup: (input: SignupRequest) => Promise<AuthResponse>
  logout: (reason?: LogoutReason) => void
  /** Retries the bootstrap `GET /me` after the API was unreachable. */
  retry: () => void
}

export const AuthContext = React.createContext<AuthContextValue | null>(null)

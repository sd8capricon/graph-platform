import { apiJson } from '@/api/http'
import type { AuthResponse, LoginRequest, SignupRequest, UserDto } from '@/api/types'

const base = 'api/auth'

export const authApi = {
  /** A 401 here means bad credentials, so it must not trigger the global logout. */
  login: (body: LoginRequest) =>
    apiJson<AuthResponse>(`${base}/login`, {
      method: 'POST',
      body,
      skipAuthRedirect: true,
    }),

  signup: (body: SignupRequest) =>
    apiJson<AuthResponse>(`${base}/signup`, {
      method: 'POST',
      body,
      skipAuthRedirect: true,
    }),

  /** Revalidates the token server-side and returns fresh organization roles. */
  me: (signal?: AbortSignal) => apiJson<UserDto>(`${base}/me`, { signal }),
}

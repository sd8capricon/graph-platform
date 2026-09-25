import { useParams } from 'react-router'

import type { MembershipDto, OrganizationRole } from '@/api/types'
import { useAuth } from '@/auth/use-auth'
import { canAuthor, canGovern } from '@/org/permissions'

export interface CurrentOrg {
  organizationId: string
  membership: MembershipDto | null
  role: OrganizationRole | null
  isMember: boolean
  canAuthor: boolean
  canGovern: boolean
}

/**
 * Resolves the organization from the URL, plus the caller's role in it.
 *
 * The role comes from `/api/auth/me`'s membership list rather than from the
 * members endpoint, because that is the same data the server resolves
 * permissions against and it is always loaded.
 */
export function useCurrentOrg(): CurrentOrg {
  const { organizationId = '' } = useParams<{ organizationId: string }>()
  const { memberships } = useAuth()

  const membership =
    memberships.find((entry) => entry.organizationId === organizationId) ?? null
  const role = membership?.role ?? null

  return {
    organizationId,
    membership,
    role,
    isMember: membership !== null,
    canAuthor: canAuthor(role),
    canGovern: canGovern(role),
  }
}

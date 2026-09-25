import { Navigate } from 'react-router'

import { useAuth } from '@/auth/use-auth'
import { readLastOrgId } from '@/org/last-org'

/**
 * Sends a signed-in user to the organization they last used, but only if they
 * are still a member of it; otherwise to the organizations list, which doubles
 * as the onboarding screen for a brand-new account.
 */
export function HomeRedirect() {
  const { memberships } = useAuth()
  const lastOrgId = readLastOrgId()

  const target =
    lastOrgId && memberships.some((entry) => entry.organizationId === lastOrgId)
      ? `/orgs/${lastOrgId}`
      : memberships.length === 1
        ? `/orgs/${memberships[0].organizationId}`
        : '/orgs'

  return <Navigate to={target} replace />
}

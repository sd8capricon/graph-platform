import * as React from 'react'
import { Building2 } from 'lucide-react'
import { Link, Outlet } from 'react-router'

import { EmptyState } from '@/components/feedback/EmptyState'
import { Button } from '@/components/ui/button'
import { useCurrentOrg } from '@/org/use-current-org'
import { writeLastOrgId } from '@/org/last-org'

/**
 * Gates the `/orgs/:organizationId/*` subtree on membership.
 *
 * Membership is checked against the already-loaded `/me` list rather than by
 * requesting the organization first: the API returns 404 for a non-member
 * anyway, and skipping the round-trip avoids a spurious error flash.
 */
export function OrgGuard() {
  const { organizationId, isMember } = useCurrentOrg()

  React.useEffect(() => {
    if (isMember && organizationId) writeLastOrgId(organizationId)
  }, [isMember, organizationId])

  if (!isMember) {
    return (
      <EmptyState
        icon={Building2}
        title="Organization not found"
        description="It may have been deleted, or you may no longer be a member of it."
        action={
          <Button asChild variant="outline">
            <Link to="/orgs">Back to organizations</Link>
          </Button>
        }
      />
    )
  }

  return <Outlet />
}

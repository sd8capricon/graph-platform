import { ArrowRight, Building2 } from 'lucide-react'
import { Link } from 'react-router'

import type { MembershipDto, OrganizationDto } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Card, CardAction, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDate } from '@/lib/format'
import { ROLE_LABELS } from '@/org/permissions'

interface OrganizationCardProps {
  organization: OrganizationDto
  membership?: MembershipDto
}

export function OrganizationCard({ organization, membership }: OrganizationCardProps) {
  return (
    <Card className="transition-colors hover:border-primary/40">
      <CardHeader>
        <CardTitle className="flex min-w-0 items-center gap-2">
          <Building2 className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          {/* Stretched link: the whole card is the target, one tab stop. */}
          <Link to={`/orgs/${organization.id}`} className="truncate after:absolute after:inset-0">
            {organization.name}
          </Link>
        </CardTitle>
        <CardDescription>Created {formatDate(organization.createdAtUtc)}</CardDescription>
        <CardAction>
          <ArrowRight className="size-4 text-muted-foreground" aria-hidden="true" />
        </CardAction>
      </CardHeader>
      {membership ? (
        <div className="px-6">
          <Badge variant="secondary">{ROLE_LABELS[membership.role]}</Badge>
        </div>
      ) : null}
    </Card>
  )
}

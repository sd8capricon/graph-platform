import * as React from 'react'
import { Building2, Plus } from 'lucide-react'

import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorState } from '@/components/feedback/ErrorState'
import { PageHeader } from '@/components/feedback/PageHeader'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/auth/use-auth'
import { CreateOrganizationDialog } from '@/features/organizations/CreateOrganizationDialog'
import { OrganizationCard } from '@/features/organizations/OrganizationCard'
import { useDocumentTitle } from '@/hooks/use-document-title'
import { useOrganizationsQuery } from '@/queries/use-organizations'

export function OrganizationsPage() {
  useDocumentTitle('Organizations')
  const { memberships } = useAuth()
  const { data, isPending, isError, error, refetch } = useOrganizationsQuery()
  const [createOpen, setCreateOpen] = React.useState(false)

  const membershipFor = (organizationId: string) =>
    memberships.find((entry) => entry.organizationId === organizationId)

  return (
    <>
      <PageHeader
        title="Organizations"
        description="Every knowledge base, model and member belongs to one organization."
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus aria-hidden="true" />
            New organization
          </Button>
        }
      />

      {isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }, (_, index) => (
            <Card key={index} aria-hidden="true">
              <CardHeader className="space-y-2">
                <Skeleton className="h-5 w-2/3" />
                <Skeleton className="h-4 w-1/3" />
              </CardHeader>
            </Card>
          ))}
        </div>
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : data.length === 0 ? (
        <EmptyState
          icon={Building2}
          title="You're not in any organization yet"
          description="Create one to start adding model configurations and knowledge bases. You'll be its first Organization Admin."
          action={
            <Button onClick={() => setCreateOpen(true)}>
              <Plus aria-hidden="true" />
              Create your first organization
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.map((organization) => (
            <OrganizationCard
              key={organization.id}
              organization={organization}
              membership={membershipFor(organization.id)}
            />
          ))}
        </div>
      )}

      <CreateOrganizationDialog open={createOpen} onOpenChange={setCreateOpen} />
    </>
  )
}

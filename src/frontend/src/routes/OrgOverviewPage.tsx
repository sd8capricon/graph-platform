import { Database, Plus, SlidersHorizontal, Users } from 'lucide-react'
import { Link } from 'react-router'

import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorState } from '@/components/feedback/ErrorState'
import { PageHeader } from '@/components/feedback/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { KbStateBadge } from '@/features/knowledge-bases/KbStateBadge'
import { useDocumentTitle } from '@/hooks/use-document-title'
import { formatRelativeTime } from '@/lib/format'
import { useCurrentOrg } from '@/org/use-current-org'
import { ROLE_LABELS } from '@/org/permissions'
import { useKnowledgeBasesQuery } from '@/queries/use-knowledge-bases'
import { useMembersQuery } from '@/queries/use-members'
import { useModelsQuery } from '@/queries/use-models'
import { useOrganizationQuery } from '@/queries/use-organizations'

interface StatCardProps {
  label: string
  value: number | undefined
  loading: boolean
  icon: typeof Database
  to: string
}

function StatCard({ label, value, loading, icon: Icon, to }: StatCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardDescription className="flex items-center gap-2">
          <Icon className="size-4" aria-hidden="true" />
          {label}
        </CardDescription>
        <CardTitle className="text-3xl tabular-nums">
          {loading ? <Skeleton className="h-8 w-12" /> : (value ?? '—')}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Button asChild variant="link" className="h-auto p-0">
          <Link to={to}>View all</Link>
        </Button>
      </CardContent>
    </Card>
  )
}

export function OrgOverviewPage() {
  const { organizationId, role, canAuthor } = useCurrentOrg()
  const organizationQuery = useOrganizationQuery(organizationId)
  useDocumentTitle(organizationQuery.data?.name ?? 'Overview')

  const knowledgeBasesQuery = useKnowledgeBasesQuery(organizationId)
  const modelsQuery = useModelsQuery(organizationId)
  const membersQuery = useMembersQuery(organizationId)

  const recent = [...(knowledgeBasesQuery.data ?? [])]
    .sort((left, right) => right.updatedAtUtc.localeCompare(left.updatedAtUtc))
    .slice(0, 5)

  const activeModel = (modelsQuery.data ?? []).find(
    (model) => model.id === organizationQuery.data?.activeEmbeddingModelId,
  )

  return (
    <>
      <PageHeader
        title={organizationQuery.data?.name ?? 'Overview'}
        description={
          role ? (
            <span className="flex items-center gap-2">
              Your role here is <Badge variant="secondary">{ROLE_LABELS[role]}</Badge>
            </span>
          ) : undefined
        }
      />

      {organizationQuery.isError ? (
        <ErrorState
          error={organizationQuery.error}
          onRetry={() => void organizationQuery.refetch()}
        />
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard
          label="Knowledge bases"
          value={knowledgeBasesQuery.data?.length}
          loading={knowledgeBasesQuery.isPending}
          icon={Database}
          to={`/orgs/${organizationId}/knowledge-bases`}
        />
        <StatCard
          label="Models"
          value={modelsQuery.data?.length}
          loading={modelsQuery.isPending}
          icon={SlidersHorizontal}
          to={`/orgs/${organizationId}/models`}
        />
        <StatCard
          label="Members"
          value={membersQuery.data?.length}
          loading={membersQuery.isPending}
          icon={Users}
          to={`/orgs/${organizationId}/settings/members`}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Embedding</CardTitle>
          <CardDescription>
            The model used to embed this organization&rsquo;s graph content.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {organizationQuery.isPending || modelsQuery.isPending ? (
            <Skeleton className="h-5 w-64" />
          ) : activeModel ? (
            <p className="text-sm">
              <Link
                to={`/orgs/${organizationId}/models/${activeModel.id}`}
                className="font-medium underline-offset-4 hover:underline"
              >
                {activeModel.displayName}
              </Link>{' '}
              <span className="text-muted-foreground">
                · {activeModel.embeddingDimension} dimensions
              </span>
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">
              No active embedding model is set for this organization.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent knowledge bases</CardTitle>
        </CardHeader>
        <CardContent>
          {knowledgeBasesQuery.isPending ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }, (_, index) => (
                <Skeleton key={index} className="h-6 w-full" />
              ))}
            </div>
          ) : knowledgeBasesQuery.isError ? (
            <ErrorState
              error={knowledgeBasesQuery.error}
              onRetry={() => void knowledgeBasesQuery.refetch()}
            />
          ) : recent.length === 0 ? (
            <EmptyState
              icon={Database}
              title="Nothing here yet"
              description="Create a knowledge base and upload the files to index."
              action={
                canAuthor ? (
                  <Button asChild>
                    <Link to={`/orgs/${organizationId}/knowledge-bases`}>
                      <Plus aria-hidden="true" />
                      New knowledge base
                    </Link>
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <ul className="divide-y">
              {recent.map((knowledgeBase) => (
                <li
                  key={knowledgeBase.id}
                  className="flex items-center justify-between gap-3 py-2 first:pt-0 last:pb-0"
                >
                  <Link
                    to={`/orgs/${organizationId}/knowledge-bases/${knowledgeBase.id}`}
                    className="min-w-0 flex-1 truncate text-sm font-medium underline-offset-4 hover:underline"
                  >
                    {knowledgeBase.name}
                  </Link>
                  <span className="hidden text-xs text-muted-foreground sm:inline">
                    {formatRelativeTime(knowledgeBase.updatedAtUtc)}
                  </span>
                  <KbStateBadge state={knowledgeBase.state} />
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </>
  )
}

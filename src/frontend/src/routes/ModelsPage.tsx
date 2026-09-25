import * as React from 'react'
import { Plus, SlidersHorizontal } from 'lucide-react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { isApiError } from '@/api/errors'
import { ModelType, type ModelDto } from '@/api/types'
import { ActionTooltip } from '@/components/data/ActionTooltip'
import { ClientPagination } from '@/components/data/ClientPagination'
import { DataToolbar } from '@/components/data/DataToolbar'
import { ConfirmDialog } from '@/components/feedback/ConfirmDialog'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorState } from '@/components/feedback/ErrorState'
import { PageHeader } from '@/components/feedback/PageHeader'
import { TableSkeleton } from '@/components/feedback/TableSkeleton'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ModelsTable } from '@/features/models/ModelsTable'
import { useClientCollection } from '@/hooks/use-client-collection'
import { useDocumentTitle } from '@/hooks/use-document-title'
import { useCurrentOrg } from '@/org/use-current-org'
import { useDeleteModel, useModelsQuery } from '@/queries/use-models'
import { useOrganizationQuery } from '@/queries/use-organizations'
import { humanizeEnum } from '@/lib/format'

type TypeFilter = ModelType | 'all'

export function ModelsPage() {
  useDocumentTitle('Models')
  const { organizationId, canAuthor } = useCurrentOrg()

  const { data, isPending, isError, error, refetch } = useModelsQuery(organizationId)
  const organizationQuery = useOrganizationQuery(organizationId)
  const deleteModel = useDeleteModel(organizationId)

  const [deleting, setDeleting] = React.useState<ModelDto | null>(null)
  const [typeFilter, setTypeFilter] = React.useState<TypeFilter>('all')

  const searchFields = React.useCallback(
    (model: ModelDto) => [model.displayName, model.name, model.provider, model.id],
    [],
  )

  const filters = React.useMemo(
    () =>
      typeFilter === 'all'
        ? []
        : [(model: ModelDto) => model.type.includes(typeFilter)],
    [typeFilter],
  )

  const collection = useClientCollection({
    items: data,
    searchFields,
    filters,
    sortKey: 'displayName',
  })

  const gateReason = canAuthor ? null : 'You need the Contributor or Organization Admin role.'

  return (
    <>
      <PageHeader
        title="Models"
        description="Provider connections used for chat and for embeddings."
        actions={
          <ActionTooltip reason={gateReason}>
            <Button asChild={canAuthor} disabled={!canAuthor} aria-disabled={!canAuthor}>
              {canAuthor ? (
                <Link to={`/orgs/${organizationId}/models/new`}>
                  <Plus aria-hidden="true" />
                  Add model
                </Link>
              ) : (
                <span>
                  <Plus aria-hidden="true" />
                  Add model
                </span>
              )}
            </Button>
          </ActionTooltip>
        }
      />

      {isPending ? (
        <TableSkeleton rows={6} columns={6} />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : data.length === 0 ? (
        <EmptyState
          icon={SlidersHorizontal}
          title="No models configured"
          description="Add a provider connection before creating knowledge bases that need embeddings."
          action={
            canAuthor ? (
              <Button asChild>
                <Link to={`/orgs/${organizationId}/models/new`}>
                  <Plus aria-hidden="true" />
                  Add your first model
                </Link>
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="space-y-4">
          <DataToolbar
            search={collection.search}
            onSearchChange={collection.setSearch}
            searchPlaceholder="Search by name or provider…"
            searchLabel="Search models"
            matchedCount={collection.matchedCount}
            totalCount={collection.totalCount}
            noun="models"
            isFiltered={collection.isFiltered}
            onClearFilters={() => {
              collection.setSearch('')
              setTypeFilter('all')
            }}
          >
            <Select
              value={typeFilter}
              onValueChange={(value) => setTypeFilter(value as TypeFilter)}
            >
              <SelectTrigger className="w-full sm:w-44" aria-label="Filter by capability">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All capabilities</SelectItem>
                {Object.values(ModelType).map((capability) => (
                  <SelectItem key={capability} value={capability}>
                    {humanizeEnum(capability)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </DataToolbar>

          {collection.matchedCount === 0 ? (
            <EmptyState
              title="Nothing matches those filters"
              description="Try a different search term or clear the capability filter."
              action={
                <Button
                  variant="outline"
                  onClick={() => {
                    collection.setSearch('')
                    setTypeFilter('all')
                  }}
                >
                  Clear filters
                </Button>
              }
            />
          ) : (
            <>
              <ModelsTable
                models={collection.page}
                organizationId={organizationId}
                activeEmbeddingModelId={organizationQuery.data?.activeEmbeddingModelId ?? null}
                canAuthor={canAuthor}
                onDelete={setDeleting}
              />
              <ClientPagination
                pageIndex={collection.pageIndex}
                pageCount={collection.pageCount}
                pageSize={collection.pageSize}
                matchedCount={collection.matchedCount}
                onPageChange={collection.setPageIndex}
                onPageSizeChange={collection.setPageSize}
              />
            </>
          )}
        </div>
      )}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete ${deleting?.displayName ?? 'this model'}?`}
        description="Anything configured to use it will stop working. This cannot be undone."
        confirmLabel="Delete"
        destructive
        pending={deleteModel.isPending}
        onConfirm={() => {
          if (!deleting) return
          const name = deleting.displayName
          deleteModel.mutate(deleting.id, {
            onSuccess: () => {
              toast.success(`Deleted ${name}`)
              setDeleting(null)
            },
            onError: (mutationError) => {
              // Includes the 409 when it is the active embedding model; the
              // server's own wording is the most actionable thing to show.
              toast.error(
                isApiError(mutationError)
                  ? (mutationError.detail ?? mutationError.title)
                  : 'Could not delete the model.',
              )
              setDeleting(null)
            },
          })
        }}
      />
    </>
  )
}

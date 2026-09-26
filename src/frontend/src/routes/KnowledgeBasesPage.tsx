import * as React from 'react'
import { Database, Plus } from 'lucide-react'
import { toast } from 'sonner'

import { KnowledgeBaseState, type KnowledgeBaseDto } from '@/api/types'
import { ClientPagination } from '@/components/data/ClientPagination'
import { DataToolbar } from '@/components/data/DataToolbar'
import { ActionTooltip } from '@/components/data/ActionTooltip'
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
import { KnowledgeBaseNameDialog } from '@/features/knowledge-bases/KnowledgeBaseNameDialog'
import { RenameKnowledgeBaseDialog } from '@/features/knowledge-bases/RenameKnowledgeBaseDialog'
import { KnowledgeBaseTable } from '@/features/knowledge-bases/KnowledgeBaseTable'
import { useClientCollection } from '@/hooks/use-client-collection'
import { useDocumentTitle } from '@/hooks/use-document-title'
import { useCurrentOrg } from '@/org/use-current-org'
import {
  useCreateKnowledgeBase,
  useDeleteKnowledgeBase,
  useKnowledgeBasesQuery,
} from '@/queries/use-knowledge-bases'
import { isApiError } from '@/api/errors'

type StateFilter = KnowledgeBaseState | 'all'

export function KnowledgeBasesPage() {
  useDocumentTitle('Knowledge bases')
  const { organizationId, canAuthor } = useCurrentOrg()

  const { data, isPending, isError, error, refetch } = useKnowledgeBasesQuery(organizationId)
  const createKnowledgeBase = useCreateKnowledgeBase(organizationId)
  const deleteKnowledgeBase = useDeleteKnowledgeBase(organizationId)

  const [createOpen, setCreateOpen] = React.useState(false)
  const [renaming, setRenaming] = React.useState<KnowledgeBaseDto | null>(null)
  const [deleting, setDeleting] = React.useState<KnowledgeBaseDto | null>(null)
  const [stateFilter, setStateFilter] = React.useState<StateFilter>('all')

  const searchFields = React.useCallback(
    (knowledgeBase: KnowledgeBaseDto) => [knowledgeBase.name, knowledgeBase.id],
    [],
  )

  const filters = React.useMemo(
    () =>
      stateFilter === 'all'
        ? []
        : [(knowledgeBase: KnowledgeBaseDto) => knowledgeBase.state === stateFilter],
    [stateFilter],
  )

  const collection = useClientCollection({
    items: data,
    searchFields,
    filters,
    sortKey: 'name',
  })

  const gateReason = canAuthor ? null : 'You need the Contributor or Organization Admin role.'

  return (
    <>
      <PageHeader
        title="Knowledge bases"
        description="Upload the files that will be indexed into a knowledge graph."
        actions={
          <ActionTooltip reason={gateReason}>
            <Button onClick={() => setCreateOpen(true)} aria-disabled={!canAuthor} disabled={!canAuthor}>
              <Plus aria-hidden="true" />
              New knowledge base
            </Button>
          </ActionTooltip>
        }
      />

      {isPending ? (
        <TableSkeleton rows={6} columns={5} />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : data.length === 0 ? (
        <EmptyState
          icon={Database}
          title="No knowledge bases yet"
          description="Create one, upload its source files, then publish it for indexing."
          action={
            canAuthor ? (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus aria-hidden="true" />
                New knowledge base
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="space-y-4">
          <DataToolbar
            search={collection.search}
            onSearchChange={collection.setSearch}
            searchPlaceholder="Search by name or id…"
            searchLabel="Search knowledge bases"
            matchedCount={collection.matchedCount}
            totalCount={collection.totalCount}
            noun="knowledge bases"
            isFiltered={collection.isFiltered}
            onClearFilters={() => {
              collection.setSearch('')
              setStateFilter('all')
            }}
          >
            <Select
              value={stateFilter}
              onValueChange={(value) => setStateFilter(value as StateFilter)}
            >
              <SelectTrigger className="w-full sm:w-40" aria-label="Filter by state">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All states</SelectItem>
                <SelectItem value={KnowledgeBaseState.Draft}>Draft</SelectItem>
                <SelectItem value={KnowledgeBaseState.Indexing}>Indexing</SelectItem>
                <SelectItem value={KnowledgeBaseState.Published}>Published</SelectItem>
                <SelectItem value={KnowledgeBaseState.Failed}>Failed</SelectItem>
              </SelectContent>
            </Select>
          </DataToolbar>

          {collection.matchedCount === 0 ? (
            <EmptyState
              title="Nothing matches those filters"
              description="Try a different search term or clear the state filter."
              action={
                <Button
                  variant="outline"
                  onClick={() => {
                    collection.setSearch('')
                    setStateFilter('all')
                  }}
                >
                  Clear filters
                </Button>
              }
            />
          ) : (
            <>
              <KnowledgeBaseTable
                items={collection.page}
                organizationId={organizationId}
                canAuthor={canAuthor}
                onRename={setRenaming}
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

      <KnowledgeBaseNameDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New knowledge base"
        description="It starts as a draft, so you can add files before publishing."
        submitLabel="Create"
        onSubmit={async (name) => {
          const created = await createKnowledgeBase.mutateAsync({ name })
          toast.success(`Created ${created.name}`)
        }}
      />

      {renaming ? (
        <RenameKnowledgeBaseDialog
          key={renaming.id}
          knowledgeBase={renaming}
          organizationId={organizationId}
          onClose={() => setRenaming(null)}
        />
      ) : null}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete ${deleting?.name ?? 'this knowledge base'}?`}
        description="Its uploaded files and their stored content are deleted too. This cannot be undone."
        confirmLabel="Delete"
        destructive
        pending={deleteKnowledgeBase.isPending}
        onConfirm={() => {
          if (!deleting) return
          deleteKnowledgeBase.mutate(deleting.id, {
            onSuccess: () => {
              toast.success(`Deleted ${deleting.name}`)
              setDeleting(null)
            },
            onError: (mutationError) => {
              toast.error(
                isApiError(mutationError)
                  ? (mutationError.detail ?? mutationError.title)
                  : 'Could not delete the knowledge base.',
              )
              setDeleting(null)
            },
          })
        }}
      />
    </>
  )
}

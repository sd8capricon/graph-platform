import * as React from 'react'
import { ArrowLeft, SlidersHorizontal, Trash2 } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'

import { isApiError } from '@/api/errors'
import { AuthMode, ModelType, type UpdateModelRequest } from '@/api/types'
import { ActionTooltip } from '@/components/data/ActionTooltip'
import { ConfirmDialog } from '@/components/feedback/ConfirmDialog'
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
import { deleteReasonFor } from '@/features/models/delete-reason'
import { ModelForm } from '@/features/models/ModelForm'
import { useDocumentTitle } from '@/hooks/use-document-title'
import { formatDateTime, humanizeEnum } from '@/lib/format'
import { useCurrentOrg } from '@/org/use-current-org'
import { useDeleteModel, useModelQuery, useUpdateModel } from '@/queries/use-models'
import { useOrganizationQuery } from '@/queries/use-organizations'

export function ModelDetailPage() {
  const { modelId = '' } = useParams<{ modelId: string }>()
  const { organizationId, canAuthor } = useCurrentOrg()
  const navigate = useNavigate()

  const modelQuery = useModelQuery(organizationId, modelId)
  const organizationQuery = useOrganizationQuery(organizationId)
  const updateModel = useUpdateModel(organizationId, modelId)
  const deleteModel = useDeleteModel(organizationId)
  const model = modelQuery.data

  const [deleteOpen, setDeleteOpen] = React.useState(false)

  useDocumentTitle(model?.displayName ?? 'Model')

  if (modelQuery.isPending) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-96 w-full max-w-2xl" />
      </div>
    )
  }

  if (modelQuery.isError) {
    const notFound = isApiError(modelQuery.error) && modelQuery.error.status === 404
    if (notFound) {
      return (
        <EmptyState
          icon={SlidersHorizontal}
          title="Model not found"
          description="It may have been deleted, or it belongs to another organization."
          action={
            <Button asChild variant="outline">
              <Link to={`/orgs/${organizationId}/models`}>
                <ArrowLeft aria-hidden="true" />
                Back to models
              </Link>
            </Button>
          }
        />
      )
    }
    return <ErrorState error={modelQuery.error} onRetry={() => void modelQuery.refetch()} />
  }

  if (!model) return null

  const isEmbedding = model.type.includes(ModelType.Embedding)
  const deleteReason = deleteReasonFor(
    model,
    canAuthor,
    organizationQuery.data?.activeEmbeddingModelId ?? null,
  )

  return (
    <>
      <PageHeader
        title={model.displayName}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
              {model.provider}/{model.name}
            </code>
            {model.type.map((capability) => (
              <Badge key={capability} variant="outline">
                {humanizeEnum(capability)}
              </Badge>
            ))}
          </span>
        }
        actions={
          <>
            <Button asChild variant="outline">
              <Link to={`/orgs/${organizationId}/models`}>
                <ArrowLeft aria-hidden="true" />
                All models
              </Link>
            </Button>
            <ActionTooltip reason={deleteReason}>
              <Button
                variant="outline"
                className="text-destructive hover:text-destructive"
                disabled={!!deleteReason}
                aria-disabled={!!deleteReason}
                onClick={() => setDeleteOpen(true)}
              >
                <Trash2 aria-hidden="true" />
                Delete
              </Button>
            </ActionTooltip>
          </>
        }
      />

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <dt className="text-xs text-muted-foreground">Authentication</dt>
              <dd className="text-sm">
                {model.authMode === AuthMode.ApiKey
                  ? model.hasApiKey
                    ? 'API key (stored)'
                    : 'API key (none stored)'
                  : 'Managed identity'}
              </dd>
            </div>
            {isEmbedding ? (
              <div>
                <dt className="text-xs text-muted-foreground">Embedding dimension</dt>
                <dd className="text-sm">{model.embeddingDimension ?? '—'}</dd>
              </div>
            ) : (
              <div>
                <dt className="text-xs text-muted-foreground">Reasoning effort</dt>
                <dd className="text-sm">{model.reasoningEffort ?? '—'}</dd>
              </div>
            )}
            <div>
              <dt className="text-xs text-muted-foreground">Updated</dt>
              <dd className="text-sm">{formatDateTime(model.updatedAtUtc)}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      {canAuthor ? (
        <Card className="max-w-2xl">
          <CardHeader>
            <CardTitle>Edit configuration</CardTitle>
            <CardDescription>
              Saving replaces the whole configuration.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ModelForm
              key={model.id}
              mode="edit"
              model={model}
              submitLabel="Save changes"
              pending={updateModel.isPending}
              onSubmit={async (body) => {
                await updateModel.mutateAsync(body as UpdateModelRequest)
                toast.success('Model updated')
              }}
            />
          </CardContent>
        </Card>
      ) : (
        <p className="text-sm text-muted-foreground">
          Editing a model configuration needs the Contributor or Organization Admin role.
        </p>
      )}

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={`Delete ${model.displayName}?`}
        description="Anything configured to use it will stop working. This cannot be undone."
        confirmLabel="Delete"
        destructive
        pending={deleteModel.isPending}
        onConfirm={() => {
          const name = model.displayName
          deleteModel.mutate(model.id, {
            onSuccess: () => {
              toast.success(`Deleted ${name}`)
              setDeleteOpen(false)
              navigate(`/orgs/${organizationId}/models`)
            },
            onError: (mutationError) => {
              toast.error(
                isApiError(mutationError)
                  ? (mutationError.detail ?? mutationError.title)
                  : 'Could not delete the model.',
              )
              setDeleteOpen(false)
            },
          })
        }}
      />
    </>
  )
}

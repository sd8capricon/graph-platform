import { Link } from 'react-router'
import { toast } from 'sonner'

import { isApiError } from '@/api/errors'
import { ModelType, type ModelDto, type OrganizationDto } from '@/api/types'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useSetActiveEmbeddingModel } from '@/queries/use-organizations'

const NONE = '__none'

interface EmbeddingModelCardProps {
  organization: OrganizationDto
  models: ModelDto[] | undefined
  modelsLoading: boolean
}

export function EmbeddingModelCard({
  organization,
  models,
  modelsLoading,
}: EmbeddingModelCardProps) {
  const setActive = useSetActiveEmbeddingModel(organization.id)
  const embeddingModels = (models ?? []).filter((model) =>
    model.type.includes(ModelType.Embedding),
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle>Active embedding model</CardTitle>
        <CardDescription>
          Used to embed this organization&rsquo;s graph nodes and schema.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {modelsLoading ? (
          <Skeleton className="h-9 w-full max-w-sm" />
        ) : embeddingModels.length === 0 ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              No model in this organization declares the embedding capability yet.
            </p>
            <Button asChild variant="outline" size="sm">
              <Link to={`/orgs/${organization.id}/models/new`}>Add an embedding model</Link>
            </Button>
          </div>
        ) : (
          <div className="max-w-sm space-y-2">
            <Label htmlFor="active-embedding-model">Model</Label>
            <Select
              value={organization.activeEmbeddingModelId ?? NONE}
              disabled={setActive.isPending}
              onValueChange={(value) =>
                setActive.mutate(
                  { modelId: value === NONE ? null : value },
                  {
                    onSuccess: () => toast.success('Active embedding model updated'),
                    onError: (error) =>
                      toast.error(
                        isApiError(error) ? (error.detail ?? error.title) : 'Could not save.',
                      ),
                  },
                )
              }
            >
              <SelectTrigger id="active-embedding-model">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>None</SelectItem>
                {embeddingModels.map((model) => (
                  <SelectItem key={model.id} value={model.id}>
                    {model.displayName} ({model.embeddingDimension} dimensions)
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        <Alert>
          <AlertTitle>Changing this does not re-embed existing data</AlertTitle>
          <AlertDescription>
            The setting is recorded, but recalculating stored embeddings is not
            implemented yet. A search only sees rows produced by the model doing the
            searching.
          </AlertDescription>
        </Alert>
      </CardContent>
    </Card>
  )
}

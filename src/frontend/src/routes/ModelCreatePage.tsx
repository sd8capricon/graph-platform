import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import type { CreateModelRequest } from '@/api/types'
import { PageHeader } from '@/components/feedback/PageHeader'
import { Card, CardContent } from '@/components/ui/card'
import { ModelForm } from '@/features/models/ModelForm'
import { useDocumentTitle } from '@/hooks/use-document-title'
import { useCurrentOrg } from '@/org/use-current-org'
import { useCreateModel } from '@/queries/use-models'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ShieldAlert } from 'lucide-react'

export function ModelCreatePage() {
  useDocumentTitle('Add model')
  const { organizationId, canAuthor } = useCurrentOrg()
  const navigate = useNavigate()
  const createModel = useCreateModel(organizationId)

  if (!canAuthor) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="You cannot add models here"
        description="Adding a model configuration needs the Contributor or Organization Admin role."
      />
    )
  }

  return (
    <>
      <PageHeader
        title="Add model"
        description="Connect a provider for chat completions, embeddings, or both."
      />

      <Card className="max-w-2xl">
        <CardContent>
          <ModelForm
            mode="create"
            submitLabel="Create model"
            pending={createModel.isPending}
            onCancel={() => void navigate(`/orgs/${organizationId}/models`)}
            onSubmit={async (body) => {
              const created = await createModel.mutateAsync(body as CreateModelRequest)
              toast.success(`Created ${created.displayName}`)
              void navigate(`/orgs/${organizationId}/models/${created.id}`, {
                replace: true,
              })
            }}
          />
        </CardContent>
      </Card>
    </>
  )
}

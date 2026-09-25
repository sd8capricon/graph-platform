import * as React from 'react'
import { ShieldAlert } from 'lucide-react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { isApiError } from '@/api/errors'
import { ConfirmDialog } from '@/components/feedback/ConfirmDialog'
import { EmptyState } from '@/components/feedback/EmptyState'
import { ErrorState } from '@/components/feedback/ErrorState'
import { PageHeader } from '@/components/feedback/PageHeader'
import { FormRootError } from '@/components/form/FormRootError'
import { SubmitButton } from '@/components/form/SubmitButton'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/form/form'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { EmbeddingModelCard } from '@/features/organizations/EmbeddingModelCard'
import { useDocumentTitle } from '@/hooks/use-document-title'
import { useCurrentOrg } from '@/org/use-current-org'
import { useModelsQuery } from '@/queries/use-models'
import {
  useDeleteOrganization,
  useOrganizationQuery,
  useUpdateOrganization,
} from '@/queries/use-organizations'
import {
  organizationNameSchema,
  type OrganizationNameValues,
} from '@/schemas/organization.schema'

export function OrgSettingsPage() {
  useDocumentTitle('Settings')
  const { organizationId, canGovern } = useCurrentOrg()
  const navigate = useNavigate()

  const organizationQuery = useOrganizationQuery(organizationId)
  const modelsQuery = useModelsQuery(organizationId)
  const updateOrganization = useUpdateOrganization(organizationId)
  const deleteOrganization = useDeleteOrganization(organizationId)

  const [deleteOpen, setDeleteOpen] = React.useState(false)
  const [rootError, setRootError] = React.useState<string | null>(null)

  const organization = organizationQuery.data

  const form = useForm<OrganizationNameValues>({
    resolver: zodResolver(organizationNameSchema),
    values: { name: organization?.name ?? '' },
  })

  if (!canGovern) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="Only an Organization Admin can change these settings"
        description="Ask an admin of this organization if you need something changed here."
      />
    )
  }

  if (organizationQuery.isPending) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-48" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  if (organizationQuery.isError) {
    return (
      <ErrorState
        error={organizationQuery.error}
        onRetry={() => void organizationQuery.refetch()}
      />
    )
  }

  if (!organization) return null

  const rename = async (values: OrganizationNameValues) => {
    setRootError(null)
    try {
      await updateOrganization.mutateAsync({ name: values.name })
      toast.success('Organization renamed')
    } catch (error) {
      if (isApiError(error) && error.status === 409) {
        form.setError('name', { message: error.title })
        return
      }
      setRootError(isApiError(error) ? (error.detail ?? error.title) : 'Could not rename.')
    }
  }

  return (
    <>
      <PageHeader
        title="Settings"
        description={`Governance for ${organization.name}.`}
      />

      <Card>
        <CardHeader>
          <CardTitle>General</CardTitle>
          <CardDescription>The organization name must be unique.</CardDescription>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form
              onSubmit={form.handleSubmit(rename)}
              className="max-w-sm space-y-4"
              noValidate
            >
              <FormRootError message={rootError ?? undefined} />
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <SubmitButton
                pending={form.formState.isSubmitting}
                disabled={!form.formState.isDirty}
              >
                Save
              </SubmitButton>
            </form>
          </Form>
        </CardContent>
      </Card>

      <EmbeddingModelCard
        organization={organization}
        models={modelsQuery.data}
        modelsLoading={modelsQuery.isPending}
      />

      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="text-destructive">Danger zone</CardTitle>
          <CardDescription>
            Deleting the organization removes its members, models, knowledge bases and
            every stored file. This cannot be undone.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="destructive" onClick={() => setDeleteOpen(true)}>
            Delete this organization
          </Button>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={`Delete ${organization.name}?`}
        description="Every knowledge base, model configuration, membership and uploaded file in this organization is permanently removed."
        confirmLabel="Delete organization"
        destructive
        pending={deleteOrganization.isPending}
        confirmationPhrase={organization.name}
        onConfirm={() =>
          deleteOrganization.mutate(undefined, {
            onSuccess: () => {
              toast.success(`Deleted ${organization.name}`)
              void navigate('/orgs', { replace: true })
            },
            onError: (error) => {
              toast.error(
                isApiError(error) ? (error.detail ?? error.title) : 'Could not delete.',
              )
              setDeleteOpen(false)
            },
          })
        }
      />
    </>
  )
}

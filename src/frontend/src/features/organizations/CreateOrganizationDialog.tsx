import * as React from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2 } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { isApiError } from '@/api/errors'
import { FormRootError } from '@/components/form/FormRootError'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/form/form'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useCreateOrganization } from '@/queries/use-organizations'
import {
  organizationNameSchema,
  type OrganizationNameValues,
} from '@/schemas/organization.schema'

interface CreateOrganizationDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CreateOrganizationDialog({
  open,
  onOpenChange,
}: CreateOrganizationDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Radix unmounts this on close, so the form state resets by itself. */}
      <DialogContent>
        <CreateOrganizationDialogBody onOpenChange={onOpenChange} />
      </DialogContent>
    </Dialog>
  )
}

function CreateOrganizationDialogBody({
  onOpenChange,
}: {
  onOpenChange: (open: boolean) => void
}) {
  const formId = React.useId()
  const navigate = useNavigate()
  const createOrganization = useCreateOrganization()
  const [rootError, setRootError] = React.useState<string | null>(null)

  const form = useForm<OrganizationNameValues>({
    resolver: zodResolver(organizationNameSchema),
    defaultValues: { name: '' },
  })

  const onSubmit = async (values: OrganizationNameValues) => {
    setRootError(null)
    try {
      const organization = await createOrganization.mutateAsync({ name: values.name })
      toast.success(`Created ${organization.name}`)
      onOpenChange(false)
      void navigate(`/orgs/${organization.id}`)
    } catch (error) {
      if (isApiError(error) && error.status === 409) {
        form.setError('name', { message: error.title })
        return
      }
      setRootError(
        isApiError(error)
          ? (error.detail ?? error.title)
          : 'Could not create the organization.',
      )
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>New organization</DialogTitle>
        <DialogDescription>You become its first Organization Admin.</DialogDescription>
      </DialogHeader>

      <Form {...form}>
        <form id={formId} onSubmit={form.handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <FormRootError message={rootError ?? undefined} />
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Name</FormLabel>
                <FormControl>
                  <Input {...field} autoFocus placeholder="Acme Research" />
                </FormControl>
                <FormDescription>Must be unique across the deployment.</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        </form>
      </Form>

      <DialogFooter>
        <Button
          type="button"
          variant="outline"
          onClick={() => onOpenChange(false)}
          disabled={form.formState.isSubmitting}
        >
          Cancel
        </Button>
        <Button type="submit" form={formId} disabled={form.formState.isSubmitting}>
          {form.formState.isSubmitting ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : null}
          Create
        </Button>
      </DialogFooter>
    </>
  )
}

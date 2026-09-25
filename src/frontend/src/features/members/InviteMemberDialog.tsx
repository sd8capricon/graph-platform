import * as React from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2 } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'

import { isApiError } from '@/api/errors'
import { OrganizationRole } from '@/api/types'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ROLE_DESCRIPTIONS, ROLE_LABELS } from '@/org/permissions'
import { useAddMember } from '@/queries/use-members'
import { addMemberSchema, type AddMemberValues } from '@/schemas/member.schema'

interface InviteMemberDialogProps {
  organizationId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function InviteMemberDialog({
  organizationId,
  open,
  onOpenChange,
}: InviteMemberDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Radix unmounts this on close, so the form state resets by itself. */}
      <DialogContent>
        <InviteMemberDialogBody
          organizationId={organizationId}
          onOpenChange={onOpenChange}
        />
      </DialogContent>
    </Dialog>
  )
}

interface InviteMemberDialogBodyProps {
  organizationId: string
  onOpenChange: (open: boolean) => void
}

function InviteMemberDialogBody({
  organizationId,
  onOpenChange,
}: InviteMemberDialogBodyProps) {
  const formId = React.useId()
  const addMember = useAddMember(organizationId)
  const [rootError, setRootError] = React.useState<string | null>(null)

  const form = useForm<AddMemberValues>({
    resolver: zodResolver(addMemberSchema),
    defaultValues: { email: '', role: OrganizationRole.User },
  })

  const submit = async (values: AddMemberValues) => {
    setRootError(null)
    try {
      await addMember.mutateAsync(values)
      toast.success(`Added ${values.email}`)
      onOpenChange(false)
    } catch (error) {
      if (isApiError(error) && (error.status === 404 || error.status === 409)) {
        // The API distinguishes "no such account" from "already a member" in
        // its own wording, which is more useful than anything generic here.
        form.setError('email', { message: error.detail ?? error.title })
        return
      }
      setRootError(isApiError(error) ? (error.detail ?? error.title) : 'Could not add the member.')
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Add a member</DialogTitle>
        <DialogDescription>
          They must already have an account. Adding someone does not send an email.
        </DialogDescription>
      </DialogHeader>

        <Form {...form}>
          <form id={formId} onSubmit={form.handleSubmit(submit)} className="space-y-4" noValidate>
            <FormRootError message={rootError ?? undefined} />

            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input {...field} type="email" autoFocus placeholder="teammate@example.com" />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="role"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Role</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {Object.values(OrganizationRole).map((role) => (
                        <SelectItem key={role} value={role}>
                          {ROLE_LABELS[role]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormDescription>{ROLE_DESCRIPTIONS[field.value]}</FormDescription>
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
            Add member
          </Button>
      </DialogFooter>
    </>
  )
}

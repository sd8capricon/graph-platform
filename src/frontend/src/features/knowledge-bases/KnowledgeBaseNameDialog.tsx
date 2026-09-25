import * as React from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2 } from 'lucide-react'
import { useForm } from 'react-hook-form'

import { isApiError } from '@/api/errors'
import { FormRootError } from '@/components/form/FormRootError'
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  knowledgeBaseNameSchema,
  type KnowledgeBaseNameValues,
} from '@/schemas/knowledge-base.schema'

interface KnowledgeBaseNameDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  submitLabel: string
  initialName?: string
  onSubmit: (name: string) => Promise<unknown>
}

/** Shared by create and rename: both take only a name. */
export function KnowledgeBaseNameDialog({
  open,
  onOpenChange,
  ...body
}: KnowledgeBaseNameDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Radix unmounts this on close, so the form below starts fresh each time
          it opens and needs no reset-on-close effect. */}
      <DialogContent>
        <KnowledgeBaseNameDialogBody {...body} onOpenChange={onOpenChange} />
      </DialogContent>
    </Dialog>
  )
}

type BodyProps = Omit<KnowledgeBaseNameDialogProps, 'open'>

function KnowledgeBaseNameDialogBody({
  onOpenChange,
  title,
  description,
  submitLabel,
  initialName = '',
  onSubmit,
}: BodyProps) {
  const formId = React.useId()
  const [rootError, setRootError] = React.useState<string | null>(null)

  const form = useForm<KnowledgeBaseNameValues>({
    resolver: zodResolver(knowledgeBaseNameSchema),
    defaultValues: { name: initialName },
  })

  const submit = async (values: KnowledgeBaseNameValues) => {
    setRootError(null)
    try {
      await onSubmit(values.name)
      onOpenChange(false)
    } catch (error) {
      setRootError(
        isApiError(error) ? (error.detail ?? error.title) : 'Could not save the change.',
      )
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </DialogHeader>

      <Form {...form}>
        <form id={formId} onSubmit={form.handleSubmit(submit)} className="space-y-4" noValidate>
          <FormRootError message={rootError ?? undefined} />
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Name</FormLabel>
                <FormControl>
                  <Input {...field} autoFocus placeholder="Formula 1 regulations" />
                </FormControl>
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
          {submitLabel}
        </Button>
      </DialogFooter>
    </>
  )
}

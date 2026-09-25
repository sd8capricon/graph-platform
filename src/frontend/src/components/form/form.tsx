/**
 * React Hook Form bindings over the shadcn `field` primitives.
 *
 * The current shadcn registry ships presentational `Field*` components with no
 * form-library binding, so this module supplies what the old `form.tsx` did: a
 * `Controller` wrapper plus the id/aria plumbing that associates a label, a
 * description and an error message with their control. Doing it once here is
 * what keeps `aria-describedby`/`aria-invalid` correct on every form instead of
 * being re-derived per screen.
 */
import * as React from 'react'
import { Slot } from 'radix-ui'
import {
  Controller,
  FormProvider,
  type ControllerProps,
  type FieldPath,
  type FieldValues,
} from 'react-hook-form'

import { FormFieldContext, FormItemContext } from '@/components/form/form-context'
import { useFormField } from '@/components/form/use-form-field'
import { Field, FieldDescription, FieldError, FieldLabel } from '@/components/ui/field'
import { cn } from '@/lib/utils'

const Form = FormProvider

function FormField<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
>({ ...props }: ControllerProps<TFieldValues, TName>) {
  const value = React.useMemo(() => ({ name: props.name }), [props.name])
  return (
    <FormFieldContext.Provider value={value}>
      <Controller {...props} />
    </FormFieldContext.Provider>
  )
}

function FormItem({ className, ...props }: React.ComponentProps<typeof Field>) {
  const id = React.useId()
  const value = React.useMemo(() => ({ id }), [id])
  return (
    <FormItemContext.Provider value={value}>
      <Field data-slot="form-item" className={cn(className)} {...props} />
    </FormItemContext.Provider>
  )
}

function FormLabel({ className, ...props }: React.ComponentProps<typeof FieldLabel>) {
  const { error, formItemId } = useFormField()
  return (
    <FieldLabel
      data-error={!!error}
      className={cn('data-[error=true]:text-destructive', className)}
      htmlFor={formItemId}
      {...props}
    />
  )
}

/**
 * Applies the generated id and the aria wiring to whichever control it wraps,
 * so a control never has to know its own error or description ids.
 */
function FormControl({ ...props }: React.ComponentProps<typeof Slot.Root>) {
  const { error, formItemId, formDescriptionId, formMessageId } = useFormField()
  return (
    <Slot.Root
      data-slot="form-control"
      id={formItemId}
      aria-describedby={
        error ? `${formDescriptionId} ${formMessageId}` : formDescriptionId
      }
      aria-invalid={!!error}
      {...props}
    />
  )
}

function FormDescription({ className, ...props }: React.ComponentProps<'p'>) {
  const { formDescriptionId } = useFormField()
  return <FieldDescription id={formDescriptionId} className={cn(className)} {...props} />
}

function FormMessage({ className, children, ...props }: React.ComponentProps<'div'>) {
  const { error, formMessageId } = useFormField()
  const body = error ? String(error.message ?? '') : children

  if (!body) {
    return null
  }

  return (
    <FieldError id={formMessageId} className={cn(className)} {...props}>
      {body}
    </FieldError>
  )
}

export {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
}

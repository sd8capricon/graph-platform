import * as React from 'react'
import { useFormContext, useFormState } from 'react-hook-form'

import { FormFieldContext, FormItemContext } from '@/components/form/form-context'

/**
 * Resolves the ids and validation state for the field the caller sits inside.
 *
 * Kept out of `form.tsx` so that file exports only components, which is what
 * Fast Refresh (and the `react-refresh/only-export-components` rule) requires.
 */
export function useFormField() {
  const fieldContext = React.useContext(FormFieldContext)
  const itemContext = React.useContext(FormItemContext)
  const { getFieldState } = useFormContext()
  const formState = useFormState({ name: fieldContext?.name })

  if (!fieldContext || !itemContext) {
    throw new Error('useFormField must be used inside <FormField> and <FormItem>')
  }

  const fieldState = getFieldState(fieldContext.name, formState)
  const { id } = itemContext

  return {
    id,
    name: fieldContext.name,
    formItemId: `${id}-form-item`,
    formDescriptionId: `${id}-form-item-description`,
    formMessageId: `${id}-form-item-message`,
    ...fieldState,
  }
}

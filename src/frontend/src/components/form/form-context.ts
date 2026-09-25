import * as React from 'react'

/** Identifies which form field the surrounding `FormField` is bound to. */
export type FormFieldContextValue = { name: string }
export const FormFieldContext = React.createContext<FormFieldContextValue | null>(null)

/** Carries the generated id that ties a label, control, description and error together. */
export type FormItemContextValue = { id: string }
export const FormItemContext = React.createContext<FormItemContextValue | null>(null)

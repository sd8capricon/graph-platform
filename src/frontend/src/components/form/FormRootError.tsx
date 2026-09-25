import { AlertCircle } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'

interface FormRootErrorProps {
  title?: string
  message?: string
}

/**
 * Form-level failures (a 401 on login, a 409, an unattributable validation
 * message) belong next to the fields with `role="alert"`, not only in a toast
 * that disappears before a screen-reader user reaches it.
 */
export function FormRootError({ title, message }: FormRootErrorProps) {
  if (!message) return null

  return (
    <Alert variant="destructive" role="alert">
      <AlertCircle aria-hidden="true" />
      <AlertTitle>{title ?? 'Something went wrong'}</AlertTitle>
      {message && message !== title ? (
        <AlertDescription>{message}</AlertDescription>
      ) : null}
    </Alert>
  )
}

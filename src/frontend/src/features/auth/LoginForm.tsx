import * as React from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { useNavigate, useSearchParams } from 'react-router'

import { isApiError } from '@/api/errors'
import { useAuth } from '@/auth/use-auth'
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
import { SecretInput } from '@/components/form/SecretInput'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { loginSchema, type LoginValues } from '@/schemas/auth.schema'

export function LoginForm() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [rootError, setRootError] = React.useState<string | null>(null)

  const expired = searchParams.get('reason') === 'expired'
  const next = searchParams.get('next')

  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  })

  const onSubmit = async (values: LoginValues) => {
    setRootError(null)
    try {
      await login(values)
      void navigate(next && next.startsWith('/') ? next : '/', { replace: true })
    } catch (error) {
      // The API deliberately returns the same 401 for an unknown account, a
      // wrong password and a lockout, so this stays a form-level message
      // rather than being attached to one of the fields.
      setRootError(
        isApiError(error)
          ? (error.detail ?? error.title)
          : 'Could not sign you in. Try again.',
      )
    }
  }

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4" noValidate>
        {expired ? (
          <Alert>
            <AlertTitle>Your session ended</AlertTitle>
            <AlertDescription>Sign in again to pick up where you left off.</AlertDescription>
          </Alert>
        ) : null}

        <FormRootError title="Cannot sign in" message={rootError ?? undefined} />

        <FormField
          control={form.control}
          name="email"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Email</FormLabel>
              <FormControl>
                <Input
                  {...field}
                  type="email"
                  autoComplete="email"
                  autoFocus
                  placeholder="you@example.com"
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="password"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Password</FormLabel>
              <FormControl>
                <SecretInput {...field} autoComplete="current-password" />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        <SubmitButton
          pending={form.formState.isSubmitting}
          pendingLabel="Signing in…"
          className="w-full"
        >
          Sign in
        </SubmitButton>
      </form>
    </Form>
  )
}

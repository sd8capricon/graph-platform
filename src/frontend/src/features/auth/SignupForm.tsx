import * as React from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router'

import { getFieldErrors, isApiError } from '@/api/errors'
import { useAuth } from '@/auth/use-auth'
import { FormRootError } from '@/components/form/FormRootError'
import { SubmitButton } from '@/components/form/SubmitButton'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/form/form'
import { SecretInput } from '@/components/form/SecretInput'
import { Input } from '@/components/ui/input'
import { signupSchema, type SignupValues } from '@/schemas/auth.schema'

export function SignupForm() {
  const { signup } = useAuth()
  const navigate = useNavigate()
  const [rootError, setRootError] = React.useState<string | null>(null)

  const form = useForm<SignupValues>({
    resolver: zodResolver(signupSchema),
    defaultValues: { email: '', password: '', displayName: '' },
  })

  const onSubmit = async (values: SignupValues) => {
    setRootError(null)
    try {
      await signup({
        email: values.email,
        password: values.password,
        displayName: values.displayName?.trim() || null,
      })
      // A new account belongs to no organization yet, so send them to the
      // organizations page, which is also the onboarding screen.
      void navigate('/orgs', { replace: true })
    } catch (error) {
      if (!isApiError(error)) {
        setRootError('Could not create your account. Try again.')
        return
      }

      if (error.status === 409) {
        form.setError('email', { message: error.title })
        return
      }

      // Identity's password-policy failures key on their error code
      // (`PasswordTooShort`, …), so surface anything unattributable as a
      // form-level message instead of dropping it.
      const fields = getFieldErrors(error)
      const emailMessage = fields.email?.[0]
      const passwordMessage = fields.password?.[0]
      if (emailMessage) form.setError('email', { message: emailMessage })
      if (passwordMessage) form.setError('password', { message: passwordMessage })
      if (!emailMessage && !passwordMessage) {
        const messages = Object.values(fields).flat()
        setRootError(messages[0] ?? error.detail ?? error.title)
      }
    }
  }

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <FormRootError title="Cannot create account" message={rootError ?? undefined} />

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
          name="displayName"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Display name</FormLabel>
              <FormControl>
                <Input {...field} autoComplete="name" placeholder="Optional" />
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
                <SecretInput {...field} autoComplete="new-password" />
              </FormControl>
              <FormDescription>At least 8 characters. Length is the only rule.</FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <SubmitButton
          pending={form.formState.isSubmitting}
          pendingLabel="Creating account…"
          className="w-full"
        >
          Create account
        </SubmitButton>
      </form>
    </Form>
  )
}

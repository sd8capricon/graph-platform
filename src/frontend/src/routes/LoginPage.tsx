import { Link } from 'react-router'

import { AuthLayout } from '@/components/layout/AuthLayout'
import { LoginForm } from '@/features/auth/LoginForm'
import { useDocumentTitle } from '@/hooks/use-document-title'

export function LoginPage() {
  useDocumentTitle('Sign in')

  return (
    <AuthLayout
      title="Sign in"
      description="Use the email address you signed up with."
      footer={
        <>
          No account?{' '}
          <Link to="/signup" className="font-medium text-primary underline-offset-4 hover:underline">
            Create one
          </Link>
        </>
      }
    >
      <LoginForm />
    </AuthLayout>
  )
}

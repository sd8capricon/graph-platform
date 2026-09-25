import { Link } from 'react-router'

import { AuthLayout } from '@/components/layout/AuthLayout'
import { SignupForm } from '@/features/auth/SignupForm'
import { useDocumentTitle } from '@/hooks/use-document-title'

export function SignupPage() {
  useDocumentTitle('Create account')

  return (
    <AuthLayout
      title="Create your account"
      description="You will set up or join an organization next."
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" className="font-medium text-primary underline-offset-4 hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <SignupForm />
    </AuthLayout>
  )
}

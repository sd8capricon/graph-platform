import { Link } from 'react-router'

import { Brand } from '@/components/layout/Brand'
import { Button } from '@/components/ui/button'
import { useDocumentTitle } from '@/hooks/use-document-title'

export function NotFoundPage() {
  useDocumentTitle('Page not found')

  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 p-6 text-center">
      <Brand className="text-lg" />
      <p className="text-5xl font-semibold tabular-nums">404</p>
      <p className="text-muted-foreground">
        That page does not exist, or you do not have access to it.
      </p>
      <Button asChild>
        <Link to="/">Go to the dashboard</Link>
      </Button>
    </div>
  )
}

import { Link, isRouteErrorResponse, useRouteError } from 'react-router'

import { ErrorState } from '@/components/feedback/ErrorState'
import { Button } from '@/components/ui/button'

/** Catches render and loader failures so one broken page is not a blank app. */
export function RouteErrorBoundary() {
  const error = useRouteError()

  const title = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : undefined

  return (
    <div className="flex min-h-[50vh] items-center justify-center p-6">
      <div className="w-full max-w-md space-y-4">
        <ErrorState
          error={error}
          title={title}
          onRetry={() => window.location.reload()}
        />
        <div className="text-center">
          <Button asChild variant="ghost" size="sm">
            <Link to="/">Go to the dashboard</Link>
          </Button>
        </div>
      </div>
    </div>
  )
}

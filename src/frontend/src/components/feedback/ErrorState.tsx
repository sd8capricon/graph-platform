import { AlertCircle, RefreshCw, WifiOff } from 'lucide-react'

import { isApiError } from '@/api/errors'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface ErrorStateProps {
  error: unknown
  onRetry?: () => void
  className?: string
  title?: string
}

/** Renders whatever the server actually said, rather than a generic message. */
export function ErrorState({ error, onRetry, className, title }: ErrorStateProps) {
  const apiError = isApiError(error) ? error : null
  const offline = apiError?.isNetwork ?? false
  const Icon = offline ? WifiOff : AlertCircle

  const heading =
    title ?? apiError?.title ?? (error instanceof Error ? error.message : 'Request failed')
  const detail = apiError?.detail

  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col items-center justify-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-6 py-10 text-center',
        className,
      )}
    >
      <Icon className="size-8 text-destructive" aria-hidden="true" />
      <div className="space-y-1">
        <p className="font-medium">{heading}</p>
        {detail ? (
          <p className="mx-auto max-w-md text-sm text-muted-foreground text-pretty">
            {detail}
          </p>
        ) : null}
      </div>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw aria-hidden="true" />
          Try again
        </Button>
      ) : null}
    </div>
  )
}

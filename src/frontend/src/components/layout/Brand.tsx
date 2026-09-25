import { Waypoints } from 'lucide-react'

import { env } from '@/app/env'
import { cn } from '@/lib/utils'

/** The product name, sourced from VITE_APP_NAME rather than hard-coded. */
export function Brand({ className }: { className?: string }) {
  return (
    <span className={cn('flex items-center gap-2 font-semibold', className)}>
      <Waypoints className="size-5 shrink-0 text-primary" aria-hidden="true" />
      <span className="truncate">{env.appName}</span>
    </span>
  )
}

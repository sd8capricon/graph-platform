import type { ReactNode } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

interface ActionTooltipProps {
  /** When absent, the child renders unwrapped and fully enabled. */
  reason?: string | null
  children: ReactNode
}

/**
 * Explains why an action is unavailable.
 *
 * A natively `disabled` button fires no pointer events, so a tooltip on it
 * never opens. Wrapping in a focusable span keeps the explanation reachable by
 * keyboard and screen reader; callers pair this with `aria-disabled` rather
 * than the `disabled` attribute when the reason matters.
 */
export function ActionTooltip({ reason, children }: ActionTooltipProps) {
  if (!reason) return <>{children}</>

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className="inline-flex rounded-md">
          {children}
        </span>
      </TooltipTrigger>
      <TooltipContent>{reason}</TooltipContent>
    </Tooltip>
  )
}

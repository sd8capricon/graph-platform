import type { ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'

import { queryClient } from '@/app/query-client'
import { TooltipProvider } from '@/components/ui/tooltip'

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={200}>{children}</TooltipProvider>
    </QueryClientProvider>
  )
}

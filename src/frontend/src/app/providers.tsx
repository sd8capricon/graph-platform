import type { ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from 'next-themes'

import { queryClient } from '@/app/query-client'
import { TooltipProvider } from '@/components/ui/tooltip'

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      {/*
        `attribute="class"` is what Tailwind's `@custom-variant dark (&:is(.dark *))`
        in index.css keys off; the default `data-theme` attribute would leave every
        dark token unused. next-themes also backs `ui/sonner`'s `useTheme()`, which
        until now always fell back to "system".
      */}
      <ThemeProvider
        attribute="class"
        defaultTheme="system"
        enableSystem
        disableTransitionOnChange
      >
        <TooltipProvider delayDuration={200}>{children}</TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}

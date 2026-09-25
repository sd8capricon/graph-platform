import { QueryClient } from '@tanstack/react-query'

import { isApiError } from '@/api/errors'

/**
 * A 4xx is a decision the server already made — retrying a 403 or a 409 only
 * adds latency. Server faults and "never reached the server" are worth a retry.
 */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= 2) return false
  if (!isApiError(error)) return true
  return error.status === 0 || error.status >= 500
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: true,
      retry: shouldRetry,
    },
    mutations: {
      retry: false,
    },
  },
})

import type { QueryClient } from '@tanstack/react-query'
import type { ObservabilityCall } from '../types/api'

export function getObservabilityCallPlaceholder(
  queryClient: QueryClient,
  callShortId: string,
): ObservabilityCall | undefined {
  const cached = queryClient.getQueryData<ObservabilityCall>(['observability-call', callShortId])
  if (cached) return cached

  const queries = queryClient.getQueriesData<ObservabilityCall[]>({
    queryKey: ['observability-calls'],
  })
  for (const [, data] of queries) {
    if (!Array.isArray(data)) continue
    const row = data.find((call) => call.call_short_id === callShortId)
    if (row) return row
  }
  return undefined
}

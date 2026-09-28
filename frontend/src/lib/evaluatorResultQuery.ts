import type { QueryClient } from '@tanstack/react-query'

type ResultRow = Record<string, unknown>

function rowFromQueries(
  queryClient: QueryClient,
  id: string,
  queryKeyPrefix: string,
): ResultRow | undefined {
  const queries = queryClient.getQueriesData<{ items?: ResultRow[] } | ResultRow[]>({
    queryKey: [queryKeyPrefix],
  })
  for (const [, data] of queries) {
    const items = Array.isArray(data) ? data : data?.items
    if (!items?.length) continue
    const row = items.find((item) => item.id === id || item.result_id === id)
    if (row) return row
  }
  return undefined
}

export function getEvaluatorResultPlaceholder(
  queryClient: QueryClient,
  id: string,
): Record<string, unknown> | undefined {
  const cached = queryClient.getQueryData<Record<string, unknown>>(['evaluator-result', id])
  if (cached) return cached

  const row =
    rowFromQueries(queryClient, id, 'test-voice-agent-results') ||
    rowFromQueries(queryClient, id, 'evaluator-results')
  if (!row) return undefined

  return {
    id: row.id,
    result_id: row.result_id,
    name: row.name,
    status: row.status,
    metric_scores: row.metric_scores ?? null,
    agent: row.agent ?? null,
    scenario: row.scenario ?? null,
    timestamp: row.timestamp,
    duration_seconds: row.duration_seconds,
    error_message: row.error_message ?? null,
  }
}

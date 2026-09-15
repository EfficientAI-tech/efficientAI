import type { QueryClient } from '@tanstack/react-query'
import { apiClient } from './api'
import {
  hasCallRecordingDetails,
  hasEnrichedCallRecordingDetails,
} from './callRecordingDetails'
import { clearCallRecordingAudioCache } from './waveformAudioCache'

export { hasCallRecordingDetails, hasEnrichedCallRecordingDetails }

function findCallRecordingRow(
  queryClient: QueryClient,
  callShortId: string,
): Record<string, unknown> | undefined {
  const queries = queryClient.getQueriesData<Array<Record<string, unknown>> | Record<string, unknown>>({
    queryKey: ['call-recordings'],
  })
  for (const [, data] of queries) {
    const list = Array.isArray(data) ? data : null
    if (!list) continue
    const row = list.find((item) => item.call_short_id === callShortId)
    if (row) return row
  }
  return undefined
}

export function getCallRecordingPlaceholder(
  queryClient: QueryClient,
  callShortId: string,
): Record<string, unknown> | undefined {
  const cached = queryClient.getQueryData<Record<string, unknown>>(['call-recording', callShortId])
  if (cached && hasEnrichedCallRecordingDetails(cached)) return cached

  const row = findCallRecordingRow(queryClient, callShortId)
  if (!row) return undefined

  return placeholderFromRow(row)
}

function placeholderFromRow(row: Record<string, unknown>): Record<string, unknown> {
  return {
    id: row.id,
    call_short_id: row.call_short_id,
    provider_platform: row.provider_platform,
    provider_call_id: row.provider_call_id,
    agent_id: row.agent_id,
    status: row.status,
    created_at: row.created_at,
    updated_at: row.updated_at,
    call_data: row.call_data ?? null,
  }
}

export function warmCallRecordingQueryFromList(
  queryClient: QueryClient,
  rows: Array<Record<string, unknown>>,
): void {
  for (const row of rows) {
    const callShortId = row.call_short_id
    if (typeof callShortId !== 'string' || !callShortId) continue
    const existing = queryClient.getQueryData<Record<string, unknown>>(['call-recording', callShortId])
    if (existing && hasEnrichedCallRecordingDetails(existing)) continue
    if (hasEnrichedCallRecordingDetails(placeholderFromRow(row))) {
      queryClient.setQueryData(['call-recording', callShortId], placeholderFromRow(row))
    }
  }
}

export function prefetchCallRecordingQuery(
  queryClient: QueryClient,
  callShortId: string,
): Promise<void> {
  const existing = queryClient.getQueryData<Record<string, unknown>>(['call-recording', callShortId])
  if (hasEnrichedCallRecordingDetails(existing)) return Promise.resolve()

  return queryClient
    .fetchQuery({
      queryKey: ['call-recording', callShortId],
      queryFn: () => apiClient.getCallRecording(callShortId),
      staleTime: 30_000,
    })
    .then(() => undefined)
}

export async function refreshCallRecordingQueries(
  queryClient: QueryClient,
  callShortId: string,
): Promise<void> {
  clearCallRecordingAudioCache(callShortId)
  await apiClient.refreshCallRecording(callShortId)
  await queryClient.invalidateQueries({ queryKey: ['call-recording', callShortId] })
  await queryClient.invalidateQueries({ queryKey: ['call-recording-logs', callShortId] })
  await queryClient.invalidateQueries({ queryKey: ['call-recordings'] })
}

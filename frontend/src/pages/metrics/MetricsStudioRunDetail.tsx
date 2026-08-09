import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { apiClient } from '../../lib/api'
import { getApiErrorMessage } from '../../lib/apiErrors'
import MetricsStudioRunHeader from './components/MetricsStudioRunHeader'
import MetricsStudioSourceList from './components/MetricsStudioSourceList'
import MetricsStudioScorePanel from './components/MetricsStudioScorePanel'
import { buildChildMetricIds } from './utils/metricScoreFilters'

function flattenMetricNames(metrics: any[]): Record<string, string> {
  const map: Record<string, string> = {}
  for (const metric of metrics) {
    map[metric.id] = metric.name
    for (const child of metric.children ?? []) {
      map[child.id] = child.name
    }
  }
  return map
}

export default function MetricsStudioRunDetail() {
  const { runId = '' } = useParams<{ runId: string }>()
  const queryClient = useQueryClient()
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null)

  const { data: run, isLoading: runLoading } = useQuery({
    queryKey: ['metric-studio-run', runId],
    queryFn: () => apiClient.getMetricStudioRun(runId),
    enabled: !!runId,
    refetchInterval: (query) =>
      query.state.data?.status === 'running' ? 3000 : false,
  })

  const { data: resultsData, isLoading: resultsLoading } = useQuery({
    queryKey: ['metric-studio-run-results', runId],
    queryFn: () => apiClient.listMetricStudioRunResults(runId),
    enabled: !!runId,
    refetchInterval: () => (run?.status === 'running' ? 3000 : false),
  })

  const { data: activeMetrics = [] } = useQuery({
    queryKey: ['metrics', 'studio', 'active'],
    queryFn: () => apiClient.listMetrics(undefined, true, { includeDrafts: false }),
  })

  const { data: draftMetrics = [] } = useQuery({
    queryKey: ['metrics', 'studio', 'drafts'],
    queryFn: () => apiClient.listMetrics(undefined, true, { draftsOnly: true }),
  })

  const retryMutation = useMutation({
    mutationFn: (resultIds?: string[]) => apiClient.retryMetricStudioRun(runId, resultIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metric-studio-run', runId] })
      queryClient.invalidateQueries({ queryKey: ['metric-studio-run-results', runId] })
    },
  })

  const promoteMutation = useMutation({
    mutationFn: (metricId: string) => apiClient.promoteMetric(metricId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['metrics'] }),
  })

  const results = resultsData?.items ?? []
  const selectedResult =
    results.find((r: any) => r.id === selectedResultId) ?? results[0]

  const metricNameById = useMemo(
    () => flattenMetricNames([...activeMetrics, ...draftMetrics]),
    [activeMetrics, draftMetrics],
  )

  const draftMetricIds = useMemo(
    () => new Set(draftMetrics.map((m: any) => m.id)),
    [draftMetrics],
  )

  const childMetricIds = useMemo(
    () => buildChildMetricIds([...activeMetrics, ...draftMetrics]),
    [activeMetrics, draftMetrics],
  )

  if (runLoading || resultsLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900" />
      </div>
    )
  }

  if (!run) {
    return (
      <div className="space-y-4">
        <Link to="/metrics-management/studio" className="text-sm text-primary-700">
          ← Back to Studio
        </Link>
        <p className="text-sm text-gray-600">Run not found.</p>
      </div>
    )
  }

  const retryError = retryMutation.isError
    ? getApiErrorMessage(retryMutation.error, 'Retry failed.')
    : null

  return (
    <div className="space-y-6">
      <Link
        to="/metrics-management/studio"
        className="text-sm text-primary-700 hover:text-primary-900"
      >
        ← Back to Studio
      </Link>

      <MetricsStudioRunHeader
        run={run}
        onRetryFailed={run.failed_items > 0 ? () => retryMutation.mutate(undefined) : undefined}
        retryPending={retryMutation.isPending}
      />

      {retryError && <p className="text-sm text-red-600">{retryError}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <MetricsStudioSourceList
          results={results}
          selectedResultId={selectedResultId ?? selectedResult?.id ?? null}
          onSelect={setSelectedResultId}
        />
        <MetricsStudioScorePanel
          result={selectedResult}
          transcriptSource={run.transcript_source ?? 'diarised'}
          metricNameById={metricNameById}
          childMetricIds={childMetricIds}
          draftMetricIds={draftMetricIds}
          onPromoteDraft={(metricId) => promoteMutation.mutate(metricId)}
        />
      </div>
    </div>
  )
}

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { format } from 'date-fns'
import { RefreshCw } from 'lucide-react'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'
import { getApiErrorMessage } from '../../lib/apiErrors'

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
  const selectedResult = results.find((r: any) => r.id === selectedResultId) ?? results[0]

  const { data: draftMetrics = [] } = useQuery({
    queryKey: ['metrics', 'studio', 'drafts'],
    queryFn: () => apiClient.listMetrics(undefined, true, { draftsOnly: true }),
  })

  const draftMetricIds = useMemo(
    () => new Set(draftMetrics.map((m: any) => m.id)),
    [draftMetrics],
  )

  const metricIds = run?.selected_metric_ids ?? []
  const scoreColumns = metricIds as string[]

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
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link
            to="/metrics-management/studio"
            className="text-sm text-primary-700 hover:text-primary-900"
          >
            ← Back to Studio
          </Link>
          <h2 className="mt-2 text-xl font-semibold text-gray-900">
            {run.name || `Studio run ${run.id.slice(0, 8)}`}
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            {format(new Date(run.created_at), 'MMM d, yyyy HH:mm')} · Status:{' '}
            <span className="font-medium text-gray-700">{run.status}</span> ·{' '}
            {run.completed_items}/{run.total_items} completed
            {run.failed_items > 0 ? ` · ${run.failed_items} failed` : ''}
          </p>
        </div>
        <div className="flex gap-2">
          {run.failed_items > 0 && (
            <Button
              variant="secondary"
              leftIcon={<RefreshCw className="h-4 w-4" />}
              disabled={retryMutation.isPending}
              onClick={() => retryMutation.mutate(undefined)}
            >
              Retry failed
            </Button>
          )}
        </div>
      </div>

      {retryError && <p className="text-sm text-red-600">{retryError}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="rounded-lg border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left font-medium text-gray-600">Source</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600">Status</th>
                  {scoreColumns.slice(0, 4).map((mid) => (
                    <th key={mid} className="px-4 py-2 text-left font-medium text-gray-600">
                      {mid.slice(0, 6)}…
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {results.map((row: any) => (
                  <tr
                    key={row.id}
                    onClick={() => setSelectedResultId(row.id)}
                    className={`cursor-pointer hover:bg-gray-50 ${
                      (selectedResult?.id ?? row.id) === row.id ? 'bg-primary-50/40' : ''
                    }`}
                  >
                    <td className="px-4 py-2">
                      <div className="font-medium text-gray-900 truncate max-w-[180px]">
                        {row.display_label || row.source_ref}
                      </div>
                      <div className="text-xs text-gray-500">{row.source_kind}</div>
                    </td>
                    <td className="px-4 py-2 capitalize text-gray-700">{row.status}</td>
                    {scoreColumns.slice(0, 4).map((mid) => {
                      const score = row.metric_scores?.[mid]
                      const value =
                        score?.value ?? score?.skipped ?? (score ? JSON.stringify(score) : '—')
                      return (
                        <td key={mid} className="px-4 py-2 text-gray-700">
                          {String(value)}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 p-4 space-y-4">
          <h3 className="text-sm font-semibold text-gray-900">Simulation & scores</h3>
          {selectedResult ? (
            <>
              <div className="text-sm text-gray-600 space-y-1">
                <p>
                  <span className="font-medium text-gray-800">Source:</span>{' '}
                  {selectedResult.display_label}
                </p>
                {selectedResult.source_metadata?.persona_name && (
                  <p>
                    <span className="font-medium text-gray-800">Persona:</span>{' '}
                    {selectedResult.source_metadata.persona_name}
                  </p>
                )}
                {selectedResult.source_metadata?.scenario_name && (
                  <p>
                    <span className="font-medium text-gray-800">Scenario:</span>{' '}
                    {selectedResult.source_metadata.scenario_name}
                  </p>
                )}
                {selectedResult.source_metadata?.call_import_id && (
                  <p>
                    <Link
                      to={`/call-imports/${selectedResult.source_metadata.call_import_id}`}
                      className="text-primary-700 hover:text-primary-900"
                    >
                      View call import →
                    </Link>
                  </p>
                )}
                {selectedResult.source_kind === 'evaluator_result' && (
                  <p>
                    <Link
                      to={`/results/${selectedResult.source_ref}`}
                      className="text-primary-700 hover:text-primary-900"
                    >
                      View full simulation →
                    </Link>
                  </p>
                )}
                {selectedResult.source_kind === 'call_recording' && (
                  <p>
                    <Link
                      to={`/playground/call-recordings/${selectedResult.source_ref}`}
                      className="text-primary-700 hover:text-primary-900"
                    >
                      View recording →
                    </Link>
                  </p>
                )}
              </div>

              {selectedResult.error_message && (
                <p className="text-sm text-red-600">{selectedResult.error_message}</p>
              )}

              <div className="space-y-3 max-h-96 overflow-y-auto">
                {Object.entries(selectedResult.metric_scores ?? {}).map(
                  ([metricId, score]: [string, any]) => (
                    <div
                      key={metricId}
                      className="rounded-md border border-gray-100 bg-gray-50 px-3 py-2"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium text-gray-900">
                          {score?.metric_name ?? metricId.slice(0, 8)}
                        </span>
                        <span className="text-sm text-gray-700">
                          {score?.value ?? score?.skipped ?? '—'}
                        </span>
                      </div>
                      {score?.rationale && (
                        <p className="text-xs text-gray-600 mt-1">{score.rationale}</p>
                      )}
                      {draftMetricIds.has(metricId) && (
                        <button
                          type="button"
                          className="mt-2 text-xs font-medium text-primary-700"
                          onClick={() => promoteMutation.mutate(metricId)}
                        >
                          Promote draft metric
                        </button>
                      )}
                    </div>
                  ),
                )}
              </div>
            </>
          ) : (
            <p className="text-sm text-gray-500">Select a result row to inspect scores.</p>
          )}
        </div>
      </div>
    </div>
  )
}

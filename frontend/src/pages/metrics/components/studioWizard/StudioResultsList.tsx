import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { RefreshCw, Sparkles, Trash2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { apiClient } from '../../../../lib/api'
import { itemsOf } from '../../../../lib/safeData'
import { formatStudioModelLabel } from '../MetricsStudioRunHeader'

type StudioResultsListProps = {
  runsData: unknown
  runsLoading: boolean
  onRefresh: () => void
}

export default function StudioResultsList({
  runsData,
  runsLoading,
  onRefresh,
}: StudioResultsListProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [pendingDeleteRunId, setPendingDeleteRunId] = useState<string | null>(null)

  const deleteRunMutation = useMutation({
    mutationFn: (runId: string) => apiClient.deleteMetricStudioRun(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metric-studio-runs'] })
      setPendingDeleteRunId(null)
    },
  })

  return (
    <section className="rounded-lg border border-gray-200 bg-white">
      <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-amber-500" />
          Studio runs
        </h2>
        <button
          type="button"
          onClick={onRefresh}
          className="text-gray-500 hover:text-gray-800"
          aria-label="Refresh runs"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>
      {runsLoading ? (
        <div className="p-8 text-center text-sm text-gray-500">Loading runs…</div>
      ) : itemsOf(runsData).length === 0 ? (
        <div className="p-8 text-center text-sm text-gray-500">
          No Studio runs yet. Start a new evaluation from the Setup tab.
        </div>
      ) : (
        <div className="divide-y divide-gray-100">
          {itemsOf(runsData).map((run: any) => {
            const progress =
              run.total_items > 0
                ? Math.round((run.completed_items / run.total_items) * 100)
                : 0
            const inProgress = run.status === 'running' || run.status === 'pending'

            return (
              <div
                key={run.id}
                role="link"
                tabIndex={0}
                className="px-4 py-3 hover:bg-gray-50 cursor-pointer group"
                onClick={() => navigate(`/metrics-management/studio/runs/${run.id}`)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    navigate(`/metrics-management/studio/runs/${run.id}`)
                  }
                }}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-900 group-hover:text-primary-800 truncate">
                      {run.name || `Run ${run.id.slice(0, 8)}`}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {format(new Date(run.created_at), 'MMM d, yyyy HH:mm')} ·{' '}
                      {run.completed_items}/{run.total_items} completed · {run.status}
                    </p>
                    <p className="text-xs text-gray-400 mt-0.5 truncate">
                      {formatStudioModelLabel(run)}
                    </p>
                    {inProgress && (
                      <div className="mt-2 flex items-center gap-2 max-w-md">
                        <div className="flex-1 h-1 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-primary-600 rounded-full transition-all"
                            style={{ width: `${progress}%` }}
                          />
                        </div>
                        <span className="text-[10px] tabular-nums text-gray-500">{progress}%</span>
                      </div>
                    )}
                  </div>
                  {pendingDeleteRunId === run.id ? (
                    <div
                      className="flex flex-col items-end gap-1 shrink-0 mt-0.5"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <span className="text-[10px] text-gray-600">Delete this run?</span>
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          className="px-2 py-0.5 text-xs font-medium rounded bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
                          disabled={deleteRunMutation.isPending}
                          onClick={() => deleteRunMutation.mutate(run.id)}
                        >
                          Confirm
                        </button>
                        <button
                          type="button"
                          className="px-2 py-0.5 text-xs font-medium rounded border border-gray-300 text-gray-700 hover:bg-gray-50"
                          disabled={deleteRunMutation.isPending}
                          onClick={() => setPendingDeleteRunId(null)}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      type="button"
                      className="text-gray-400 hover:text-red-600 shrink-0 mt-0.5"
                      onClick={(event) => {
                        event.stopPropagation()
                        setPendingDeleteRunId(run.id)
                      }}
                      aria-label="Delete run"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

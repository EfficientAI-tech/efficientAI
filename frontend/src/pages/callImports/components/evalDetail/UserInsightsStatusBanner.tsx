import { Loader2 } from 'lucide-react'
import { useState } from 'react'
import type { EvaluationUserInsightsState } from '../../../../types/api'
import Button from '../../../../components/Button'
import { apiClient } from '../../../../lib/api'

function UserInsightsStatusBanner({
  state,
  isLoading,
  callImportId,
  evaluationId,
  onRefresh,
}: {
  state: EvaluationUserInsightsState | null
  isLoading: boolean
  callImportId: string
  evaluationId: string
  onRefresh?: () => void
}) {
  const [cancelling, setCancelling] = useState(false)
  const [resuming, setResuming] = useState(false)

  if (isLoading) {
    return (
      <section className="mt-4 rounded-lg border border-gray-200 bg-white px-4 py-3">
        <p className="text-xs text-gray-500 inline-flex items-center gap-1.5">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading user insights…
        </p>
      </section>
    )
  }

  if (!state || state.status === 'idle' || state.status === 'completed') {
    return null
  }

  const handleCancel = async () => {
    setCancelling(true)
    try {
      await apiClient.callImports.cancelCallImportEvaluationUserInsights(
        callImportId,
        evaluationId,
      )
      onRefresh?.()
    } finally {
      setCancelling(false)
    }
  }

  const handleResume = async () => {
    setResuming(true)
    try {
      await apiClient.callImports.generateCallImportEvaluationUserInsights(
        callImportId,
        evaluationId,
        { resume: true },
      )
      onRefresh?.()
    } finally {
      setResuming(false)
    }
  }

  if (state.status === 'running') {
    const progress = state.progress
    const completedBatches = progress?.completed_batches ?? 0
    const totalBatches = progress?.total_batches ?? 0
    const completedRows = progress?.completed_rows ?? 0
    const totalRows = progress?.total_rows ?? 0
    const batchPct =
      totalBatches > 0 ? Math.round((completedBatches / totalBatches) * 100) : 0
    const rowPct = totalRows > 0 ? Math.round((completedRows / totalRows) * 100) : 0
    const pct = totalBatches > 0 ? batchPct : rowPct
    return (
      <section className="mt-4 rounded-lg border border-primary-200 bg-primary-50/40 px-4 py-3">
        <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
          <p className="text-xs font-semibold text-gray-900 inline-flex items-center gap-1.5">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-primary-600" />
            AI User Insights — processing all completed calls in batches…
          </p>
          {totalBatches > 0 ? (
            <p className="text-[10px] text-gray-500 tabular-nums">
              Batch {completedBatches} / {totalBatches} ({pct}%)
            </p>
          ) : null}
        </div>
        {totalRows > 0 ? (
          <p className="text-[10px] text-gray-500 mb-2 tabular-nums">
            {completedRows.toLocaleString()} / {totalRows.toLocaleString()} rows
          </p>
        ) : null}
        {pct > 0 || totalBatches > 0 ? (
          <div className="mb-2">
            <div className="h-2 rounded-full bg-primary-100 overflow-hidden">
              <div
                className="h-full bg-primary-600 transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        ) : null}
        <Button
          variant="outline"
          onClick={handleCancel}
          isLoading={cancelling}
          disabled={cancelling}
          className="text-xs"
        >
          Stop
        </Button>
      </section>
    )
  }

  if (state.status === 'cancelled') {
    return (
      <section className="mt-4 rounded-lg border border-gray-200 bg-gray-50/80 px-4 py-3">
        <p className="text-xs font-semibold text-gray-900 mb-1">User insights stopped</p>
        <p className="text-xs text-gray-600">
          {state.error_message || 'Generation was cancelled. Checkpointed batches were kept.'}
        </p>
        <div className="mt-2 flex gap-2">
          <Button variant="primary" onClick={handleResume} isLoading={resuming} disabled={resuming}>
            Resume
          </Button>
        </div>
      </section>
    )
  }

  return (
    <section className="mt-4 rounded-lg border border-red-200 bg-red-50/50 px-4 py-3">
      <p className="text-xs font-semibold text-gray-900 mb-1">
        AI User Insights generation failed
      </p>
      <p className="text-xs text-red-700">
        {state.error_message || 'User insights generation failed.'}
      </p>
      <div className="mt-2 flex gap-2">
        <Button variant="primary" onClick={handleResume} isLoading={resuming} disabled={resuming}>
          Resume
        </Button>
      </div>
    </section>
  )
}

export { UserInsightsStatusBanner }

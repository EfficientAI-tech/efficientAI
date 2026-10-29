import { Link, useNavigate } from 'react-router-dom'
import { Loader2, Trash2, XCircle } from 'lucide-react'
import type { UseMutationResult } from '@tanstack/react-query'
import { itemsOf } from '../../../lib/safeData'
import type {
  CallImportEvaluation,
  CallImportEvaluationBulkActionResponse,
  CallImportEvaluationListResponse,
} from '../../../types/api'
import Button from '../../../components/Button'
import StatusBadge from '../../../components/shared/StatusBadge'
import {
  evaluationBulkOperationLabel,
  evaluationHasActiveBulkOperation,
} from '../evaluationBulkOperation'

export type ImportEvaluationsTabProps = {
  importId: string
  evaluationsData: CallImportEvaluationListResponse | undefined
  evaluationsWithBulkOperation: CallImportEvaluation[]
  selectedEvalIds: Set<string>
  setSelectedEvalIds: React.Dispatch<React.SetStateAction<Set<string>>>
  setBulkDeleteEvalsError: (message: string | null) => void
  setShowBulkDeleteEvals: (open: boolean) => void
  bulkCancelEvalsMutation: UseMutationResult<
    {
      results: PromiseSettledResult<{
        evalId: string
        response: CallImportEvaluationBulkActionResponse
      }>[]
      fulfilled: number
      rejected: number
    },
    unknown,
    string[],
    unknown
  >
  cancellingEvalId: string | null
  cancelEvaluationMutation: UseMutationResult<
    CallImportEvaluationBulkActionResponse,
    unknown,
    string,
    unknown
  >
}

export default function ImportEvaluationsTab({
  importId,
  evaluationsData,
  evaluationsWithBulkOperation,
  selectedEvalIds,
  setSelectedEvalIds,
  setBulkDeleteEvalsError,
  setShowBulkDeleteEvals,
  bulkCancelEvalsMutation,
  cancellingEvalId,
  cancelEvaluationMutation,
}: ImportEvaluationsTabProps) {
  const navigate = useNavigate()

  return (
    <div className="bg-white shadow rounded-lg p-6">
      <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Evaluations</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Click a run to view its results in detail. Use the Run Evaluation
            button at the top to start a new run.
          </p>
        </div>
        {selectedEvalIds.size > 0 && (() => {
          const items = itemsOf<CallImportEvaluation>(evaluationsData)
          const cancellableSelected = items.filter(
            (run) =>
              selectedEvalIds.has(run.id) &&
              (run.status === 'pending' || run.status === 'running'),
          )
          return (
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-600">
                {selectedEvalIds.size} selected
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSelectedEvalIds(new Set())}
              >
                Clear
              </Button>
              {cancellableSelected.length > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  leftIcon={<XCircle className="h-4 w-4" />}
                  isLoading={bulkCancelEvalsMutation.isPending}
                  disabled={bulkCancelEvalsMutation.isPending}
                  onClick={() =>
                    bulkCancelEvalsMutation.mutate(
                      cancellableSelected.map((run) => run.id),
                    )
                  }
                  className="text-amber-700 hover:text-amber-800 hover:bg-amber-50"
                  title={`Abort ${cancellableSelected.length} in-progress run${
                    cancellableSelected.length === 1 ? '' : 's'
                  }`}
                >
                  Abort selected ({cancellableSelected.length})
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<Trash2 className="h-4 w-4" />}
                onClick={() => {
                  setBulkDeleteEvalsError(null)
                  setShowBulkDeleteEvals(true)
                }}
                className="text-red-600 hover:text-red-700 hover:bg-red-50"
              >
                Delete selected
              </Button>
            </div>
          )
        })()}
      </div>

      {evaluationsWithBulkOperation.length > 0 && (
        <div className="mb-4 bg-amber-50 border border-amber-200 rounded-lg p-3">
          <div className="flex items-start gap-2">
            <Loader2 className="h-4 w-4 text-amber-600 mt-0.5 animate-spin shrink-0" />
            <div className="flex-1 space-y-2">
              <p className="text-sm font-medium text-amber-900">
                Background operations in progress
              </p>
              <ul className="space-y-1">
                {evaluationsWithBulkOperation.map((evaluation) => {
                  const headerLabel = evaluation.name?.trim()
                    ? evaluation.name
                    : `Evaluation ${evaluation.id.slice(0, 8)}`
                  return (
                    <li
                      key={evaluation.id}
                      className="text-xs text-amber-800 flex flex-wrap items-center gap-x-1.5 gap-y-0.5"
                    >
                      <Link
                        to={`/call-imports/${importId}/evaluations/${evaluation.id}`}
                        className="font-medium text-amber-900 hover:text-amber-950 underline-offset-2 hover:underline"
                      >
                        {headerLabel}
                      </Link>
                      <span aria-hidden="true">·</span>
                      <span>
                        {evaluationBulkOperationLabel(
                          evaluation.bulk_operation!,
                        )}
                      </span>
                    </li>
                  )
                })}
              </ul>
            </div>
          </div>
        </div>
      )}

      {(evaluationsData?.items?.length || 0) === 0 ? (
        <p className="text-sm text-gray-500">
          No evaluations have been run for this dataset yet.
        </p>
      ) : (
        <div className="overflow-x-auto border border-gray-200 rounded-lg">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="w-10 px-3 py-3">
                  {(() => {
                    const items = itemsOf<CallImportEvaluation>(evaluationsData)
                    const allSelected =
                      items.length > 0 &&
                      items.every((row) => selectedEvalIds.has(row.id))
                    return (
                      <input
                        type="checkbox"
                        aria-label="Select all evaluations"
                        checked={allSelected}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedEvalIds(new Set(items.map((row) => row.id)))
                          } else {
                            setSelectedEvalIds(new Set())
                          }
                        }}
                      />
                    )
                  })()}
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Evaluation
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Run by
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Last updated by
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Progress
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="w-0 px-2 py-3" aria-hidden />
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
          {itemsOf<CallImportEvaluation>(evaluationsData).map((evaluation) => {
            const isSelected = selectedEvalIds.has(evaluation.id)
            const bulkOperationActive = evaluationHasActiveBulkOperation(
              evaluation,
            )
            const headerLabel = evaluation.name?.trim()
              ? evaluation.name
              : `Evaluation ${evaluation.id.slice(0, 8)}`
            const runBy = evaluation.created_by_email?.trim() || '—'
            const lastUpdatedBy = evaluation.last_updated_by_email?.trim() || '—'
            return (
              <tr
                key={evaluation.id}
                role="link"
                tabIndex={0}
                onClick={() =>
                  navigate(
                    `/call-imports/${importId}/evaluations/${evaluation.id}`,
                  )
                }
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    navigate(
                      `/call-imports/${importId}/evaluations/${evaluation.id}`,
                    )
                  }
                }}
                className={`cursor-pointer group hover:bg-gray-50 ${
                  isSelected ? 'bg-primary-50/40' : ''
                }`}
              >
                <td
                  className="px-3 py-4 align-middle"
                  onClick={(e) => e.stopPropagation()}
                >
                  <input
                    type="checkbox"
                    aria-label={`Select ${headerLabel}`}
                    checked={isSelected}
                    onChange={(e) => {
                      setSelectedEvalIds((prev) => {
                        const next = new Set(prev)
                        if (e.target.checked) next.add(evaluation.id)
                        else next.delete(evaluation.id)
                        return next
                      })
                    }}
                    onClick={(e) => e.stopPropagation()}
                  />
                </td>
                <td className="px-4 py-4 align-top min-w-[10rem]">
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-gray-900 truncate group-hover:text-primary-700">
                      {headerLabel}
                    </div>
                    <div className="text-xs text-gray-400 font-mono mt-0.5">
                      {evaluation.id.slice(0, 8)}
                    </div>
                  </div>
                </td>
                <td className="px-4 py-4 align-top text-sm text-gray-700 max-w-[12rem]">
                  <span className="break-all">{runBy}</span>
                </td>
                <td className="px-4 py-4 align-top text-sm text-gray-700 max-w-[12rem]">
                  <span className="break-all">{lastUpdatedBy}</span>
                </td>
                <td className="px-4 py-4 align-top whitespace-nowrap text-sm text-gray-600">
                  {evaluation.completed_rows}/{evaluation.total_rows} rows
                </td>
                <td className="px-4 py-4 align-top whitespace-nowrap">
                  <StatusBadge status={evaluation.status} size="sm" />
                  {evaluation.bulk_operation && (
                    <p className="text-[11px] text-amber-700 mt-1 flex items-center gap-1">
                      <Loader2 className="h-3 w-3 animate-spin shrink-0" />
                      {evaluationBulkOperationLabel(evaluation.bulk_operation)}
                    </p>
                  )}
                </td>
                <td
                  className="px-2 py-4 align-top text-right whitespace-nowrap"
                  onClick={(e) => e.stopPropagation()}
                >
                  {(evaluation.status === 'pending' ||
                    evaluation.status === 'running') && (
                    <Button
                      variant="ghost"
                      size="sm"
                      leftIcon={<XCircle className="h-4 w-4" />}
                      isLoading={
                        bulkOperationActive ||
                        (cancellingEvalId === evaluation.id &&
                          cancelEvaluationMutation.isPending)
                      }
                      disabled={
                        bulkOperationActive ||
                        (cancellingEvalId === evaluation.id &&
                          cancelEvaluationMutation.isPending)
                      }
                      onClick={(e) => {
                        e.stopPropagation()
                        if (bulkOperationActive) return
                        cancelEvaluationMutation.mutate(evaluation.id)
                      }}
                      className="text-amber-700 hover:text-amber-800 hover:bg-amber-50"
                      title={
                        bulkOperationActive
                          ? 'Wait for the current bulk operation to finish'
                          : 'Abort this evaluation run'
                      }
                    >
                      Abort
                    </Button>
                  )}
                </td>
              </tr>
            )
          })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

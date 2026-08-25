import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { apiClient } from '../../../lib/api'
import type { EvaluatorResultRow, ListEvaluatorResultsParams } from '../../../types/api'
import ResultsHierarchyNav, { type HierarchyCrumb } from './ResultsHierarchyNav'
import ResultsCountCards from './ResultsCountCards'
import Button from '../../../components/Button'
import {
  Clock,
  Eye,
  RefreshCw,
  RotateCcw,
  Trash2,
} from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  displayEvaluatorResultStatus,
  isEvaluatorResultInProgress,
} from './evaluatorResultStatus'
import { formatDuration, formatTimestamp, getStatusConfig } from './resultsFormatting'

const PAGE_SIZE = 50

type StatusFilter = 'all' | 'completed' | 'failed' | 'in_progress'

interface ResultsRunsListProps {
  title: string
  subtitle?: string
  crumbs?: HierarchyCrumb[]
  embedded?: boolean
  listParams: Omit<ListEvaluatorResultsParams, 'skip' | 'limit' | 'status'>
  counts?: { total: number; completed: number; failed: number; in_progress: number }
  showAgentColumn?: boolean
  showPersonaColumn?: boolean
  showScenarioColumn?: boolean
  /** Opens result in agent workspace when set; otherwise navigates to /results/:id */
  onResultClick?: (resultId: string) => void
}

export default function ResultsRunsList({
  title,
  subtitle,
  crumbs = [],
  embedded = false,
  listParams,
  counts,
  showAgentColumn = false,
  showPersonaColumn = false,
  showScenarioColumn = false,
  onResultClick,
}: ResultsRunsListProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(0)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [selectedResults, setSelectedResults] = useState<Set<string>>(new Set())
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [reEvaluatingIds, setReEvaluatingIds] = useState<Set<string>>(new Set())

  const apiStatus =
    statusFilter === 'all'
      ? undefined
      : statusFilter === 'in_progress'
        ? 'in_progress'
        : statusFilter

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['evaluator-results', listParams, page, apiStatus],
    queryFn: () =>
      apiClient.listEvaluatorResults({
        ...listParams,
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        status: apiStatus,
      }),
    refetchInterval: (query) => {
      const items = query.state.data?.items
      if (items?.some((r) => isEvaluatorResultInProgress(displayEvaluatorResultStatus(r)))) {
        return 3000
      }
      return false
    },
  })

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const deleteBulkMutation = useMutation({
    mutationFn: (ids: string[]) => apiClient.deleteEvaluatorResultsBulk(ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })
      queryClient.invalidateQueries({ queryKey: ['evaluator-results-overview'] })
      setSelectedResults(new Set())
    },
  })

  const reEvaluateMutation = useMutation({
    mutationFn: (id: string) => apiClient.reEvaluateResult(id),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })
      setReEvaluatingIds((prev) => {
        const s = new Set(prev)
        s.delete(id)
        return s
      })
    },
  })

  const openResult = (resultId: string) => {
    if (onResultClick) {
      onResultClick(resultId)
      return
    }
    navigate(`/results/${resultId}`)
  }

  return (
    <div className={embedded ? 'space-y-4' : 'space-y-6'}>
      {!embedded && crumbs.length > 0 && <ResultsHierarchyNav crumbs={crumbs} />}
      <div className="flex items-center justify-between gap-4">
        <div>
          {embedded ? (
            <h2 className="text-xl font-bold text-gray-900">{title}</h2>
          ) : (
            <h1 className="text-2xl font-bold text-gray-900">{title}</h1>
          )}
          {subtitle && <p className="text-sm text-gray-600 mt-1">{subtitle}</p>}
        </div>
        <Button
          variant="outline"
          onClick={() => queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })}
          disabled={isFetching}
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${isFetching ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {counts && (
        <ResultsCountCards
          counts={{
            ...counts,
            last_run_at: undefined,
          }}
        />
      )}

      <div className="bg-white shadow rounded-lg overflow-hidden border border-gray-200">
        <div className="px-6 py-4 border-b flex flex-wrap items-center gap-3">
          <div className="flex gap-1">
            {(
              [
                ['all', 'All'],
                ['completed', 'Completed'],
                ['failed', 'Failed'],
                ['in_progress', 'In progress'],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => {
                  setStatusFilter(key)
                  setPage(0)
                }}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg ${
                  statusFilter === key
                    ? 'bg-primary-100 text-primary-800 border border-primary-300'
                    : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {selectedResults.size > 0 && (
            <Button variant="danger" size="sm" onClick={() => setShowDeleteModal(true)}>
              <Trash2 className="w-4 h-4 mr-1" />
              Delete ({selectedResults.size})
            </Button>
          )}
        </div>

        {isLoading ? (
          <p className="p-8 text-center text-gray-500">Loading runs…</p>
        ) : items.length === 0 ? (
          <p className="p-8 text-center text-gray-500">No runs match this view.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 w-10" />
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Result ID</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                  {showAgentColumn && (
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Agent</th>
                  )}
                  {showPersonaColumn && (
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Persona</th>
                  )}
                  {showScenarioColumn && (
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Scenario</th>
                  )}
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">When</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Duration</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {items.map((result: EvaluatorResultRow) => {
                  const displayStatus = displayEvaluatorResultStatus(result)
                  const statusConfig = getStatusConfig(displayStatus)
                  return (
                    <tr
                      key={result.id}
                      className="hover:bg-gray-50 cursor-pointer"
                      onClick={() => openResult(result.result_id)}
                    >
                      <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={selectedResults.has(result.id)}
                          onChange={(e) => {
                            const next = new Set(selectedResults)
                            if (e.target.checked) next.add(result.id)
                            else next.delete(result.id)
                            setSelectedResults(next)
                          }}
                          className="rounded border-gray-300"
                        />
                      </td>
                      <td className="px-4 py-3 font-mono text-sm text-primary-600">{result.result_id}</td>
                      <td className="px-4 py-3 text-sm text-gray-900">{result.name}</td>
                      {showAgentColumn && (
                        <td className="px-4 py-3 text-sm text-gray-600">{result.agent?.name ?? '—'}</td>
                      )}
                      {showPersonaColumn && (
                        <td className="px-4 py-3 text-sm text-gray-600">{result.persona?.name ?? '—'}</td>
                      )}
                      {showScenarioColumn && (
                        <td className="px-4 py-3 text-sm text-gray-600">{result.scenario?.name ?? '—'}</td>
                      )}
                      <td className="px-4 py-3 text-sm text-gray-500">{formatTimestamp(result.timestamp)}</td>
                      <td className="px-4 py-3 text-sm text-gray-500">
                        <Clock className="w-3 h-3 inline mr-1" />
                        {formatDuration(result.duration_seconds)}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs border ${statusConfig.bg} ${statusConfig.text} ${statusConfig.border}`}
                        >
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${statusConfig.dot} ${statusConfig.animate ? 'animate-pulse' : ''}`}
                          />
                          {statusConfig.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                        <div className="flex justify-end gap-1">
                          {(displayStatus === 'completed' || result.status === 'failed') &&
                            result.evaluator_id && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => {
                                  setReEvaluatingIds((p) => new Set(p).add(result.id))
                                  reEvaluateMutation.mutate(result.id)
                                }}
                                disabled={reEvaluatingIds.has(result.id)}
                              >
                                <RotateCcw
                                  className={`w-3.5 h-3.5 ${reEvaluatingIds.has(result.id) ? 'animate-spin' : ''}`}
                                />
                              </Button>
                            )}
                          <Button variant="ghost" size="sm" onClick={() => openResult(result.result_id)}>
                            <Eye className="w-4 h-4" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {total > PAGE_SIZE && (
          <div className="px-6 py-3 border-t flex items-center justify-between text-sm text-gray-600">
            <span>
              Page {page + 1} of {totalPages} · {total} total
            </span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page + 1 >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </div>

      <AnimatePresence>
        {showDeleteModal && (
          <motion.div className="fixed inset-0 z-50 flex items-center justify-center" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <div className="absolute inset-0 bg-gray-500/75" onClick={() => setShowDeleteModal(false)} />
            <div className="relative bg-white rounded-xl p-6 max-w-md mx-4 shadow-xl">
              <p className="text-gray-900 font-medium">Delete {selectedResults.size} result(s)?</p>
              <div className="mt-4 flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setShowDeleteModal(false)}>
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  isLoading={deleteBulkMutation.isPending}
                  onClick={() =>
                    deleteBulkMutation.mutate(Array.from(selectedResults), {
                      onSuccess: () => setShowDeleteModal(false),
                    })
                  }
                >
                  Delete
                </Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

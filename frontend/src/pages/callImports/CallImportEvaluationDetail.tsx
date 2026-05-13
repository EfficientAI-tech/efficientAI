import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  BarChart3,
  Check,
  Download,
  Edit3,
  RefreshCw,
  Table,
  Trash2,
  X,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { apiClient } from '../../lib/api'
import type {
  CallImportEvaluation,
  CallImportEvaluationRow,
  CallImportMetricAggregate,
} from '../../types/api'
import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import StatusBadge from '../../components/shared/StatusBadge'

const PIE_COLORS = ['#10b981', '#ef4444', '#6366f1', '#f59e0b', '#a855f7']

const ROWS_PAGE_SIZE = 50

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

export default function CallImportEvaluationDetail() {
  const { id, evalId } = useParams<{ id: string; evalId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [page, setPage] = useState(1)
  const [editingName, setEditingName] = useState(false)
  const [draftName, setDraftName] = useState('')
  const [renameError, setRenameError] = useState<string | null>(null)
  const [pendingDeleteRow, setPendingDeleteRow] =
    useState<CallImportEvaluationRow | null>(null)
  const [deleteEvalOpen, setDeleteEvalOpen] = useState(false)
  const [rowDeleteError, setRowDeleteError] = useState<string | null>(null)
  const [resultsTab, setResultsTab] = useState<'table' | 'visualizations'>(
    'table',
  )

  const callImportQuery = useQuery({
    queryKey: ['call-import', id],
    queryFn: () => apiClient.getCallImport(id!, { row_limit: 0, row_offset: 0 }),
    enabled: !!id,
  })

  const evaluationQuery = useQuery({
    queryKey: ['call-import-evaluation', id, evalId],
    queryFn: () => apiClient.getCallImportEvaluation(id!, evalId!),
    enabled: !!id && !!evalId,
    refetchInterval: (q) => {
      const status = q.state.data?.status
      return status === 'pending' || status === 'running' ? 3000 : false
    },
  })

  const rowsQuery = useQuery({
    queryKey: ['call-import-evaluation-rows', id, evalId, page],
    queryFn: () =>
      apiClient.listCallImportEvaluationRows(id!, evalId!, {
        page,
        page_size: ROWS_PAGE_SIZE,
      }),
    enabled: !!id && !!evalId,
    refetchInterval: () => {
      const status = evaluationQuery.data?.status
      return status === 'pending' || status === 'running' ? 3000 : false
    },
  })

  // Lazy: only fetch aggregates when the user lands on the
  // visualizations tab. Refetches while the run is still in flight so
  // the chart fills in as workers complete rows.
  const aggregateQuery = useQuery({
    queryKey: ['call-import-evaluation-aggregate', id, evalId],
    queryFn: () =>
      apiClient.getCallImportEvaluationAggregate(id!, evalId!),
    enabled:
      !!id && !!evalId && resultsTab === 'visualizations',
    refetchInterval: () => {
      const status = evaluationQuery.data?.status
      return status === 'pending' || status === 'running' ? 5000 : false
    },
  })

  const renameMutation = useMutation({
    mutationFn: (newName: string | null) =>
      apiClient.updateCallImportEvaluation(id!, evalId!, { name: newName }),
    onSuccess: (updated) => {
      queryClient.setQueryData(
        ['call-import-evaluation', id, evalId],
        updated,
      )
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluations', id],
      })
      setEditingName(false)
      setRenameError(null)
    },
    onError: (err: any) => {
      setRenameError(
        err?.response?.data?.detail || err?.message || 'Failed to rename run.',
      )
    },
  })

  const deleteRowMutation = useMutation({
    mutationFn: (rowId: string) =>
      apiClient.deleteCallImportEvaluationRow(id!, evalId!, rowId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation-rows', id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation', id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluations', id],
      })
      setPendingDeleteRow(null)
      setRowDeleteError(null)
    },
    onError: (err: any) => {
      setRowDeleteError(
        err?.response?.data?.detail || err?.message || 'Failed to delete row.',
      )
    },
  })

  const deleteEvalMutation = useMutation({
    mutationFn: () => apiClient.deleteCallImportEvaluation(id!, evalId!),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluations', id],
      })
      navigate(`/call-imports/${id}`)
    },
  })

  const callImport = callImportQuery.data
  const evaluation = evaluationQuery.data

  // Derive the metric column list the same way CallImportDetail does so the
  // table stays consistent with what was actually scored, even if the
  // `metrics` summary on the evaluation drifts from `metric_scores` keys.
  const displayMetrics = useMemo(() => {
    const byId = new Map<string, { id: string; name: string }>()
    for (const m of evaluation?.metrics ?? []) {
      if (m && m.id) {
        byId.set(m.id, {
          id: m.id,
          name: m.name || `Metric ${m.id.slice(0, 8)}`,
        })
      }
    }
    for (const mid of evaluation?.selected_metric_ids ?? []) {
      if (typeof mid === 'string' && !byId.has(mid)) {
        byId.set(mid, { id: mid, name: `Metric ${mid.slice(0, 8)}` })
      }
    }
    for (const row of rowsQuery.data?.items ?? []) {
      const scores = row.metric_scores
      if (!scores || typeof scores !== 'object') continue
      for (const [metricId, entry] of Object.entries(scores)) {
        if (!metricId) continue
        const existing = byId.get(metricId)
        const fallbackName =
          entry && typeof entry === 'object' && 'metric_name' in entry
            ? (entry as { metric_name?: unknown }).metric_name
            : undefined
        const nameFromScore =
          typeof fallbackName === 'string' && fallbackName.trim()
            ? fallbackName
            : undefined
        if (!existing) {
          byId.set(metricId, {
            id: metricId,
            name: nameFromScore || `Metric ${metricId.slice(0, 8)}`,
          })
        } else if (
          nameFromScore &&
          existing.name.startsWith('Metric ') &&
          existing.name.length <= 'Metric '.length + 8
        ) {
          byId.set(metricId, { id: metricId, name: nameFromScore })
        }
      }
    }
    return Array.from(byId.values())
  }, [
    evaluation?.metrics,
    evaluation?.selected_metric_ids,
    rowsQuery.data?.items,
  ])

  // Build the "Imported columns" panel from the parent CallImport's mapping
  // metadata, so users can see which CSV columns were used to drive this
  // particular evaluation run (Transcript, Recording URL, External Call ID,
  // and any user-named custom mappings).
  const importedColumns = useMemo(() => {
    if (!callImport) return []
    const rows: { label: string; value: string }[] = []
    const mapping = callImport.column_mapping || {}
    if (mapping.external_call_id) {
      rows.push({
        label: 'External Call ID',
        value: mapping.external_call_id,
      })
    }
    if (mapping.transcript) {
      rows.push({ label: 'Transcript', value: mapping.transcript })
    }
    if (mapping.recording_url) {
      rows.push({ label: 'Recording URL', value: mapping.recording_url })
    }
    for (const extra of callImport.extra_columns || []) {
      rows.push({ label: extra, value: extra })
    }
    const custom = callImport.custom_column_mapping || {}
    for (const [name, csvHeader] of Object.entries(custom)) {
      rows.push({ label: name, value: csvHeader })
    }
    return rows
  }, [callImport])

  const handleExport = async () => {
    if (!id || !evalId) return
    try {
      const blob = await apiClient.exportCallImportEvaluation(id, evalId)
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `call-import-${id}-evaluation-${evalId}.csv`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (e) {
      console.error('Failed to export evaluation', e)
      alert('Failed to export evaluation CSV')
    }
  }

  if (!id || !evalId) {
    return <div className="text-sm text-red-600">Missing identifiers.</div>
  }

  if (evaluationQuery.isLoading || callImportQuery.isLoading) {
    return (
      <div className="text-center py-12 text-gray-500">
        <RefreshCw className="h-8 w-8 mx-auto mb-2 animate-spin" />
        <p>Loading evaluation…</p>
      </div>
    )
  }

  if (evaluationQuery.error || !evaluation) {
    const status = (evaluationQuery.error as any)?.response?.status
    return (
      <div className="space-y-4">
        <Link
          to={`/call-imports/${id}`}
          className="inline-flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to call import
        </Link>
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-start gap-2">
            <AlertCircle className="h-5 w-5 text-red-600 mt-0.5" />
            <p className="text-sm text-red-800">
              {status === 404
                ? 'Evaluation not found for this import.'
                : (evaluationQuery.error as any)?.response?.data?.detail ||
                  'Failed to load evaluation.'}
            </p>
          </div>
        </div>
      </div>
    )
  }

  const headerLabel = evaluation.name?.trim()
    ? evaluation.name
    : `Evaluation ${evaluation.id.slice(0, 8)}`

  const totalPages = rowsQuery.data
    ? Math.max(1, Math.ceil(rowsQuery.data.total / rowsQuery.data.page_size))
    : 1

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Link
          to={`/call-imports/${id}`}
          className="inline-flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to call import
        </Link>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            leftIcon={<Download className="h-4 w-4" />}
            onClick={handleExport}
            disabled={!rowsQuery.data?.items?.length}
          >
            Download CSV
          </Button>
          <Button
            variant="ghost"
            size="sm"
            leftIcon={<Trash2 className="h-4 w-4" />}
            onClick={() => setDeleteEvalOpen(true)}
            className="text-red-600 hover:text-red-700 hover:bg-red-50"
          >
            Delete run
          </Button>
        </div>
      </div>

      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0 flex-1">
            {!editingName ? (
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold text-gray-900 truncate">
                  {headerLabel}
                </h1>
                <button
                  type="button"
                  className="p-1.5 rounded text-gray-400 hover:text-primary-600 hover:bg-primary-50 transition-colors"
                  onClick={() => {
                    setDraftName(evaluation.name || '')
                    setRenameError(null)
                    setEditingName(true)
                  }}
                  title="Rename"
                  aria-label="Rename evaluation"
                >
                  <Edit3 className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <div className="flex flex-col gap-2 max-w-md">
                <div className="flex items-center gap-2">
                  <input
                    autoFocus
                    type="text"
                    value={draftName}
                    onChange={(e) => setDraftName(e.target.value)}
                    placeholder="e.g. March QA pass"
                    maxLength={255}
                    className="flex-1 px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  />
                  <Button
                    variant="primary"
                    size="sm"
                    leftIcon={<Check className="h-4 w-4" />}
                    isLoading={renameMutation.isPending}
                    onClick={() =>
                      renameMutation.mutate(
                        draftName.trim() ? draftName.trim() : null,
                      )
                    }
                  >
                    Save
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      if (renameMutation.isPending) return
                      setEditingName(false)
                      setRenameError(null)
                    }}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
                {renameError && (
                  <p className="text-xs text-red-600">{renameError}</p>
                )}
              </div>
            )}
            <div className="mt-1 text-xs text-gray-500 font-mono">
              {evaluation.id}
            </div>
            <div className="mt-3 flex items-center gap-3 flex-wrap">
              <StatusBadge status={evaluation.status} />
              <span className="text-sm text-gray-600">
                Created: {formatDateTime(evaluation.created_at)}
              </span>
              {evaluation.started_at && (
                <span className="text-sm text-gray-600">
                  Started: {formatDateTime(evaluation.started_at)}
                </span>
              )}
              {evaluation.finished_at && (
                <span className="text-sm text-gray-600">
                  Finished: {formatDateTime(evaluation.finished_at)}
                </span>
              )}
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <div className="bg-gray-50 rounded p-2 min-w-[72px]">
              <div className="text-gray-500">Total</div>
              <div className="font-semibold text-gray-900">
                {evaluation.total_rows}
              </div>
            </div>
            <div className="bg-green-50 rounded p-2 min-w-[72px]">
              <div className="text-green-700">Completed</div>
              <div className="font-semibold text-green-800">
                {evaluation.completed_rows}
              </div>
            </div>
            <div className="bg-red-50 rounded p-2 min-w-[72px]">
              <div className="text-red-700">Failed</div>
              <div className="font-semibold text-red-800">
                {evaluation.failed_rows}
              </div>
            </div>
          </div>
        </div>

        {evaluation.error_message && (
          <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-3">
            <div className="flex items-start gap-2">
              <AlertCircle className="h-4 w-4 text-red-600 mt-0.5" />
              <p className="text-sm text-red-800">
                {evaluation.error_message}
              </p>
            </div>
          </div>
        )}

        <div className="mt-5 grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
              Metrics in this run ({displayMetrics.length})
            </h3>
            {displayMetrics.length ? (
              <div className="flex flex-wrap gap-1.5">
                {displayMetrics.map((m) => (
                  <span
                    key={m.id}
                    className="inline-flex items-center text-xs rounded-full px-2 py-0.5 bg-primary-50 text-primary-700 border border-primary-200"
                    title={m.id}
                  >
                    {m.name}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-xs text-gray-500 italic">
                No metrics recorded for this run.
              </p>
            )}
          </div>
          <div>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
              Imported columns ({importedColumns.length})
            </h3>
            {importedColumns.length ? (
              <dl className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 text-xs">
                {importedColumns.map((col) => (
                  <div
                    key={`${col.label}::${col.value}`}
                    className="bg-gray-50 border border-gray-200 rounded px-2 py-1"
                  >
                    <dt className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider truncate">
                      {col.label}
                    </dt>
                    <dd className="text-gray-800 truncate" title={col.value}>
                      {col.value}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="text-xs text-gray-500 italic">
                No column mapping recorded on the parent import.
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Row results</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {rowsQuery.data?.total ?? 0} row
              {(rowsQuery.data?.total ?? 0) === 1 ? '' : 's'} scored against{' '}
              {displayMetrics.length} metric
              {displayMetrics.length === 1 ? '' : 's'}.
            </p>
          </div>
          <div className="inline-flex border border-gray-200 rounded-lg p-1 bg-gray-50">
            <button
              type="button"
              onClick={() => setResultsTab('table')}
              className={`px-3 py-1.5 text-xs font-medium rounded transition ${
                resultsTab === 'table'
                  ? 'bg-white text-primary-700 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              <Table className="h-3.5 w-3.5 inline mr-1 -mt-0.5" />
              Table
            </button>
            <button
              type="button"
              onClick={() => setResultsTab('visualizations')}
              className={`px-3 py-1.5 text-xs font-medium rounded transition ${
                resultsTab === 'visualizations'
                  ? 'bg-white text-primary-700 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              <BarChart3 className="h-3.5 w-3.5 inline mr-1 -mt-0.5" />
              Visualizations
            </button>
          </div>
        </div>

        {resultsTab === 'visualizations' ? (
          aggregateQuery.isLoading || !aggregateQuery.data ? (
            <div className="text-center py-12 text-gray-500">
              <RefreshCw className="h-6 w-6 mx-auto mb-2 animate-spin" />
              <p>Loading visualizations…</p>
            </div>
          ) : aggregateQuery.data.metrics.length === 0 ? (
            <p className="text-sm text-gray-500">
              No metric data yet. Charts populate as rows finish scoring.
            </p>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {aggregateQuery.data.metrics.map((m) => (
                <MetricVisualization key={m.metric_id} metric={m} />
              ))}
            </div>
          )
        ) : rowsQuery.isLoading ? (
          <p className="text-sm text-gray-500">Loading rows…</p>
        ) : !rowsQuery.data?.items?.length ? (
          <p className="text-sm text-gray-500">
            No row results yet. Rows will appear as workers complete them.
          </p>
        ) : (
          <>
            {displayMetrics.length > 3 && (
              <p className="mb-2 text-[11px] text-gray-500">
                Scroll the table horizontally to see all{' '}
                {displayMetrics.length} metric columns.
              </p>
            )}
            <div className="overflow-x-auto border border-gray-100 rounded">
              <table className="min-w-max w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="sticky left-0 z-10 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">
                      #
                    </th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">
                      CallID
                    </th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">
                      Status
                    </th>
                    {displayMetrics.map((metric) => (
                      <th
                        key={metric.id}
                        className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap"
                        title={metric.name}
                      >
                        {metric.name}
                      </th>
                    ))}
                    <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase whitespace-nowrap">
                      &nbsp;
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {rowsQuery.data.items.map(
                    (row: CallImportEvaluationRow) => (
                      <tr key={row.id} className="hover:bg-gray-50">
                        <td className="sticky left-0 z-10 bg-inherit px-3 py-2 text-sm text-gray-600 whitespace-nowrap">
                          {(row.row_index ?? 0) + 1}
                        </td>
                        <td className="px-3 py-2 text-sm font-mono text-gray-900 whitespace-nowrap">
                          {row.external_call_id || '-'}
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          <StatusBadge status={row.status} size="sm" />
                        </td>
                        {displayMetrics.map((metric) => {
                          const score = row.metric_scores?.[metric.id]
                          const value =
                            score && typeof score === 'object'
                              ? score.value
                              : undefined
                          const scoreType =
                            score &&
                            typeof score === 'object' &&
                            typeof score.type === 'string'
                              ? score.type.toLowerCase()
                              : undefined
                          const isEmpty =
                            value === undefined ||
                            value === null ||
                            value === ''
                          const valueStr = isEmpty ? '' : String(value)
                          const isLongText =
                            scoreType === 'text' && valueStr.length > 80
                          const errorText =
                            score &&
                            typeof score === 'object' &&
                            score.error
                              ? String(score.error)
                              : undefined
                          return (
                            <td
                              key={metric.id}
                              className={
                                scoreType === 'text'
                                  ? 'px-3 py-2 text-sm text-gray-700 align-top max-w-xs'
                                  : 'px-3 py-2 text-sm text-gray-700 whitespace-nowrap'
                              }
                              title={
                                errorText ||
                                (isLongText ? valueStr : undefined)
                              }
                            >
                              {isEmpty ? (
                                '-'
                              ) : scoreType === 'text' ? (
                                <span className="block whitespace-pre-wrap break-words leading-snug line-clamp-3">
                                  {valueStr}
                                </span>
                              ) : (
                                valueStr
                              )}
                            </td>
                          )
                        })}
                        <td className="px-3 py-2 text-right whitespace-nowrap">
                          <button
                            type="button"
                            onClick={() => {
                              setRowDeleteError(null)
                              setPendingDeleteRow(row)
                            }}
                            disabled={
                              deleteRowMutation.isPending &&
                              pendingDeleteRow?.id === row.id
                            }
                            className="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-40"
                            title="Delete row from this evaluation"
                            aria-label="Delete evaluation row"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </div>

            {totalPages > 1 && (
              <div className="mt-3 flex items-center justify-between">
                <p className="text-sm text-gray-500">
                  Page {rowsQuery.data.page} of {totalPages}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={rowsQuery.data.page <= 1}
                  >
                    Prev
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setPage((p) => p + 1)}
                    disabled={
                      rowsQuery.data.page * rowsQuery.data.page_size >=
                      rowsQuery.data.total
                    }
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <ConfirmModal
        isOpen={pendingDeleteRow !== null}
        title="Delete this evaluation row?"
        description={(() => {
          if (!pendingDeleteRow) return ''
          const callId = pendingDeleteRow.external_call_id || '(no callid)'
          const lines = [
            `Row for CallID ${callId} will be removed from this evaluation only.`,
            'The underlying CSV row and its recording stay untouched on the parent import, so you can re-evaluate later.',
            'This cannot be undone.',
            rowDeleteError ? `Error: ${rowDeleteError}` : '',
          ]
          return lines.filter(Boolean).join('\n\n')
        })()}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        isLoading={deleteRowMutation.isPending}
        onConfirm={() => {
          if (pendingDeleteRow) {
            deleteRowMutation.mutate(pendingDeleteRow.id)
          }
        }}
        onCancel={() => {
          if (deleteRowMutation.isPending) return
          setPendingDeleteRow(null)
          setRowDeleteError(null)
        }}
      />

      <ConfirmModal
        isOpen={deleteEvalOpen}
        title="Delete this evaluation run?"
        description={(() => {
          const lines = [
            `“${headerLabel}” will be permanently deleted, along with all ${evaluation.total_rows} per-row score records.`,
            evaluation.status === 'pending' || evaluation.status === 'running'
              ? 'This run is still in flight — pending tasks will be revoked before deletion.'
              : '',
            'The underlying CSV import stays intact; you can re-run the evaluation later.',
            'This cannot be undone.',
          ]
          return lines.filter(Boolean).join('\n\n')
        })()}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        isLoading={deleteEvalMutation.isPending}
        onConfirm={() => {
          if (!deleteEvalMutation.isPending) deleteEvalMutation.mutate()
        }}
        onCancel={() => {
          if (deleteEvalMutation.isPending) return
          setDeleteEvalOpen(false)
        }}
      />
    </div>
  )
}

/**
 * Single-metric chart card used inside the Visualizations tab. Picks
 * the chart shape from the aggregate payload: numeric histograms beat
 * categorical pie/bar charts when both are present, since numeric
 * distributions tell a richer story than the top-N category tally.
 */
function MetricVisualization({
  metric,
}: {
  metric: CallImportMetricAggregate
}) {
  const histogram = metric.histogram_buckets
  const valueCounts = metric.value_counts
  const hasNumeric = histogram.length > 0 || metric.mean != null
  const hasCategorical = valueCounts.length > 0

  // Render mode: numeric histogram, categorical pie/bar, or empty state.
  // The Pie chart is reserved for low-cardinality categorical metrics
  // (<= 5 values) so it stays readable; otherwise we fall back to a
  // horizontal bar chart for the top categories.
  let chart: ReactNodeLike = null
  if (histogram.length > 0) {
    const data = histogram.map((b) => ({
      label: `${b.x0.toFixed(2)}-${b.x1.toFixed(2)}`,
      count: b.count,
    }))
    chart = (
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip />
          <Bar dataKey="count" fill="#6366f1" />
        </BarChart>
      </ResponsiveContainer>
    )
  } else if (valueCounts.length && valueCounts.length <= 5) {
    chart = (
      <ResponsiveContainer width="100%" height={180}>
        <PieChart>
          <Tooltip />
          <Pie
            data={valueCounts}
            dataKey="count"
            nameKey="label"
            outerRadius={70}
            label={(entry) => entry.label}
          >
            {valueCounts.map((_, i) => (
              <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    )
  } else if (valueCounts.length) {
    chart = (
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={valueCounts} layout="vertical">
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" tick={{ fontSize: 10 }} />
          <YAxis
            type="category"
            dataKey="label"
            tick={{ fontSize: 10 }}
            width={80}
          />
          <Tooltip />
          <Bar dataKey="count" fill="#10b981" />
        </BarChart>
      </ResponsiveContainer>
    )
  }

  return (
    <div className="border border-gray-200 rounded-lg p-3 space-y-2">
      <div className="flex items-baseline justify-between">
        <p className="text-sm font-medium text-gray-900 truncate">
          {metric.metric_name}
        </p>
        <p className="text-[11px] text-gray-500">
          n={metric.count}
          {metric.skipped_count > 0
            ? ` · skipped ${metric.skipped_count}`
            : ''}
          {metric.error_count > 0 ? ` · errors ${metric.error_count}` : ''}
        </p>
      </div>
      {hasNumeric && (
        <div className="grid grid-cols-4 text-[11px] text-gray-600 gap-2">
          <span>μ {metric.mean?.toFixed(2) ?? '—'}</span>
          <span>p50 {metric.median?.toFixed(2) ?? '—'}</span>
          <span>p95 {metric.p95?.toFixed(2) ?? '—'}</span>
          <span>σ {metric.stddev?.toFixed(2) ?? '—'}</span>
        </div>
      )}
      {chart ?? (
        <p className="text-xs text-gray-400 italic py-6 text-center">
          No values recorded yet.
        </p>
      )}
      {!hasNumeric && hasCategorical && metric.value_counts.length > 5 && (
        <p className="text-[11px] text-gray-400">
          Showing top {metric.value_counts.length} categories.
        </p>
      )}
    </div>
  )
}

// Lightweight ReactNode alias keeps the chart variable typed without
// pulling React's full ReactNode through the function signature
// (prevents a "type-only import" tangle on tsx/lint).
type ReactNodeLike = React.ReactNode

export type { CallImportEvaluation as _ }

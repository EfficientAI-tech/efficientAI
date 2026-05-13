import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  BarChart3,
  Check,
  Download,
  Edit3,
  ExternalLink,
  Filter,
  RefreshCw,
  Search,
  Sparkles,
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

  // --- Filters / search / drilldown state -------------------------------
  // Search input is debounced (250 ms) before becoming the actual query
  // parameter so we don't refire the rows endpoint on every keystroke.
  const [searchInput, setSearchInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | null>(null)
  // ``metricFilter`` is applied via /rows?metric_id=...&metric_value=...
  // and is set by clicking a chart segment in the Visualizations tab.
  const [metricFilter, setMetricFilter] = useState<{
    metricId: string
    metricName: string
    value: string
  } | null>(null)
  // Row-detail side panel: full CSV row + transcript + per-metric scores
  // for the currently-selected row.
  const [detailRow, setDetailRow] =
    useState<CallImportEvaluationRow | null>(null)

  useEffect(() => {
    const t = setTimeout(() => setSearchQuery(searchInput.trim()), 250)
    return () => clearTimeout(t)
  }, [searchInput])

  // Reset to first page whenever any active filter changes — otherwise we'd
  // be paging through a filtered result set that may be smaller than ``page``.
  useEffect(() => {
    setPage(1)
  }, [searchQuery, statusFilter, metricFilter?.metricId, metricFilter?.value])

  const hasActiveFilters =
    !!searchQuery || !!statusFilter || !!metricFilter

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
    queryKey: [
      'call-import-evaluation-rows',
      id,
      evalId,
      page,
      searchQuery,
      statusFilter,
      metricFilter?.metricId,
      metricFilter?.value,
    ],
    queryFn: () =>
      apiClient.listCallImportEvaluationRows(id!, evalId!, {
        page,
        page_size: ROWS_PAGE_SIZE,
        q: searchQuery || undefined,
        status: statusFilter || undefined,
        metric_id: metricFilter?.metricId,
        metric_value: metricFilter?.value,
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
  //
  // For each metric we also flag ``hasRationale``: true when ANY row has a
  // non-empty ``rationale`` string for that metric (i.e. it was scored
  // with ``capture_rationale=true``). The table then renders an extra
  // "<Name> - Rationale" column right after the value column for those
  // metrics, mirroring the CSV export layout.
  type DisplayMetric = { id: string; name: string; hasRationale: boolean }
  const displayMetrics = useMemo<DisplayMetric[]>(() => {
    const byId = new Map<string, DisplayMetric>()
    const upsert = (id: string, patch: Partial<DisplayMetric>) => {
      const prev = byId.get(id)
      byId.set(id, {
        id,
        name: patch.name || prev?.name || `Metric ${id.slice(0, 8)}`,
        hasRationale: prev?.hasRationale || patch.hasRationale || false,
      })
    }

    for (const m of evaluation?.metrics ?? []) {
      if (m && m.id) {
        upsert(m.id, { name: m.name || `Metric ${m.id.slice(0, 8)}` })
      }
    }
    for (const mid of evaluation?.selected_metric_ids ?? []) {
      if (typeof mid === 'string' && !byId.has(mid)) {
        upsert(mid, {})
      }
    }
    for (const row of rowsQuery.data?.items ?? []) {
      const scores = row.metric_scores
      if (!scores || typeof scores !== 'object') continue
      for (const [metricId, entry] of Object.entries(scores)) {
        if (!metricId) continue
        const fallbackName =
          entry && typeof entry === 'object' && 'metric_name' in entry
            ? (entry as { metric_name?: unknown }).metric_name
            : undefined
        const nameFromScore =
          typeof fallbackName === 'string' && fallbackName.trim()
            ? fallbackName
            : undefined
        const existing = byId.get(metricId)
        const isStubName =
          !!existing &&
          existing.name.startsWith('Metric ') &&
          existing.name.length <= 'Metric '.length + 8
        const rationaleStr =
          entry &&
          typeof entry === 'object' &&
          typeof (entry as { rationale?: unknown }).rationale === 'string'
            ? (entry as { rationale?: string }).rationale
            : undefined
        upsert(metricId, {
          name:
            !existing || isStubName
              ? nameFromScore || existing?.name
              : existing.name,
          hasRationale: !!(rationaleStr && rationaleStr.trim()),
        })
      }
    }
    return Array.from(byId.values())
  }, [
    evaluation?.metrics,
    evaluation?.selected_metric_ids,
    rowsQuery.data?.items,
  ])

  // Total visible metric-related columns (value + optional rationale per
  // metric). Used for the "scroll horizontally" hint.
  const totalMetricColumnCount = useMemo(
    () =>
      displayMetrics.reduce(
        (sum, m) => sum + 1 + (m.hasRationale ? 1 : 0),
        0,
      ),
    [displayMetrics],
  )

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
              {(rowsQuery.data?.total ?? 0) === 1 ? '' : 's'}
              {hasActiveFilters ? ' (filtered)' : ''} scored against{' '}
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

        {resultsTab === 'table' && (
          <>
            <div className="mb-3 flex items-stretch gap-2 flex-wrap">
              <div className="relative flex-1 min-w-[260px]">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
                <input
                  type="text"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  placeholder="Search by Call ID or transcript…"
                  className="w-full pl-9 pr-9 py-2 text-sm border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-500"
                />
                {searchInput && (
                  <button
                    type="button"
                    onClick={() => setSearchInput('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100"
                    aria-label="Clear search"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              <select
                value={statusFilter ?? ''}
                onChange={(e) => setStatusFilter(e.target.value || null)}
                className="px-3 py-2 text-sm border border-gray-300 rounded-md shadow-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-500"
              >
                <option value="">All statuses</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
                <option value="pending">Pending</option>
                <option value="running">Running</option>
                <option value="skipped">Skipped</option>
              </select>
            </div>

            {hasActiveFilters && (
              <div className="mb-3 flex items-center gap-1.5 flex-wrap text-xs">
                <span className="inline-flex items-center gap-1 text-gray-500">
                  <Filter className="h-3.5 w-3.5" />
                  Active filters:
                </span>
                {searchQuery && (
                  <FilterChip
                    label={`Search: "${searchQuery}"`}
                    onClear={() => {
                      setSearchInput('')
                      setSearchQuery('')
                    }}
                  />
                )}
                {statusFilter && (
                  <FilterChip
                    label={`Status: ${statusFilter}`}
                    onClear={() => setStatusFilter(null)}
                  />
                )}
                {metricFilter && (
                  <FilterChip
                    label={`${metricFilter.metricName} = ${metricFilter.value}`}
                    onClear={() => setMetricFilter(null)}
                  />
                )}
                <button
                  type="button"
                  onClick={() => {
                    setSearchInput('')
                    setSearchQuery('')
                    setStatusFilter(null)
                    setMetricFilter(null)
                  }}
                  className="ml-1 text-gray-500 underline underline-offset-2 hover:text-gray-700"
                >
                  Clear all
                </button>
              </div>
            )}
          </>
        )}

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
            <>
              <p className="mb-3 text-xs text-gray-500 inline-flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-primary-500" />
                Click any bar or slice to filter the row table by that value.
              </p>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {aggregateQuery.data.metrics.map((m) => (
                  <MetricVisualization
                    key={m.metric_id}
                    metric={m}
                    isActive={metricFilter?.metricId === m.metric_id}
                    activeValue={
                      metricFilter?.metricId === m.metric_id
                        ? metricFilter.value
                        : null
                    }
                    onValueClick={(value) => {
                      setMetricFilter({
                        metricId: m.metric_id,
                        metricName: m.metric_name,
                        value,
                      })
                      setResultsTab('table')
                    }}
                  />
                ))}
              </div>
            </>
          )
        ) : rowsQuery.isLoading ? (
          <p className="text-sm text-gray-500">Loading rows…</p>
        ) : !rowsQuery.data?.items?.length ? (
          hasActiveFilters ? (
            <div className="text-sm text-gray-500 border border-dashed border-gray-300 rounded-md p-6 text-center">
              No rows match the current filters.{' '}
              <button
                type="button"
                onClick={() => {
                  setSearchInput('')
                  setSearchQuery('')
                  setStatusFilter(null)
                  setMetricFilter(null)
                }}
                className="text-primary-600 hover:text-primary-700 underline underline-offset-2"
              >
                Clear filters
              </button>
            </div>
          ) : (
            <p className="text-sm text-gray-500">
              No row results yet. Rows will appear as workers complete them.
            </p>
          )
        ) : (
          <>
            {totalMetricColumnCount > 3 && (
              <p className="mb-2 text-[11px] text-gray-500">
                Scroll the table horizontally to see all{' '}
                {totalMetricColumnCount} metric columns.
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
                    {displayMetrics.flatMap((metric) => {
                      const headers = [
                        <th
                          key={metric.id}
                          className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap"
                          title={metric.name}
                        >
                          {metric.name}
                        </th>,
                      ]
                      if (metric.hasRationale) {
                        headers.push(
                          <th
                            key={`${metric.id}__rationale`}
                            className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap"
                            title={`${metric.name} - LLM Rationale`}
                          >
                            {metric.name} <span className="text-gray-400">- Rationale</span>
                          </th>,
                        )
                      }
                      return headers
                    })}
                    <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase whitespace-nowrap">
                      &nbsp;
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {rowsQuery.data.items.map(
                    (row: CallImportEvaluationRow) => (
                      <tr
                        key={row.id}
                        onClick={() => setDetailRow(row)}
                        className={`hover:bg-primary-50/40 cursor-pointer transition ${
                          detailRow?.id === row.id ? 'bg-primary-50/60' : ''
                        }`}
                      >
                        <td className="sticky left-0 z-10 bg-inherit px-3 py-2 text-sm text-gray-600 whitespace-nowrap">
                          {(row.row_index ?? 0) + 1}
                        </td>
                        <td className="px-3 py-2 text-sm font-mono text-primary-700 whitespace-nowrap">
                          {row.external_call_id || '-'}
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          <StatusBadge status={row.status} size="sm" />
                        </td>
                        {displayMetrics.flatMap((metric) => {
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
                          // ``rationale`` is only populated for metrics that
                          // were scored with capture_rationale=true. When
                          // ``metric.hasRationale`` is true we render the
                          // rationale in its own adjacent column (mirroring
                          // the CSV export), otherwise we omit the column
                          // entirely so other metrics stay compact.
                          const rationale =
                            score &&
                            typeof score === 'object' &&
                            typeof (score as { rationale?: unknown })
                              .rationale === 'string' &&
                            (score as { rationale?: string }).rationale
                              ? String(
                                  (score as { rationale: string }).rationale,
                                )
                              : undefined
                          const valueTooltip =
                            errorText || (isLongText ? valueStr : undefined)
                          const valueCellClassName =
                            scoreType === 'text'
                              ? 'px-3 py-2 text-sm text-gray-700 align-top max-w-xs'
                              : 'px-3 py-2 text-sm text-gray-700 whitespace-nowrap'
                          const cells = [
                            <td
                              key={metric.id}
                              className={valueCellClassName}
                              title={valueTooltip}
                            >
                              {isEmpty ? (
                                '-'
                              ) : scoreType === 'text' ? (
                                <span className="block whitespace-pre-wrap break-words leading-snug line-clamp-3">
                                  {valueStr}
                                </span>
                              ) : (
                                <span className="font-medium">{valueStr}</span>
                              )}
                            </td>,
                          ]
                          if (metric.hasRationale) {
                            cells.push(
                              <td
                                key={`${metric.id}__rationale`}
                                className="px-3 py-2 text-sm text-gray-600 align-top max-w-xs"
                                title={rationale || undefined}
                              >
                                {rationale ? (
                                  <span className="block whitespace-pre-wrap break-words leading-snug line-clamp-3">
                                    {rationale}
                                  </span>
                                ) : (
                                  <span className="text-gray-300">-</span>
                                )}
                              </td>,
                            )
                          }
                          return cells
                        })}
                        <td className="px-3 py-2 text-right whitespace-nowrap">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
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

      <RowDetailPanel
        row={detailRow}
        displayMetrics={displayMetrics}
        onClose={() => setDetailRow(null)}
      />

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

/** Tiny removable filter chip used above the rows table. */
function FilterChip({
  label,
  onClear,
}: {
  label: string
  onClear: () => void
}) {
  return (
    <span className="inline-flex items-center gap-1 pl-2 pr-1 py-0.5 rounded-full bg-primary-50 text-primary-700 border border-primary-200">
      <span className="font-medium">{label}</span>
      <button
        type="button"
        onClick={onClear}
        className="rounded-full p-0.5 hover:bg-primary-100"
        aria-label={`Clear filter ${label}`}
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  )
}

/** Pretty-print a metric score value for the side panel. */
function formatScoreValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toString() : value.toFixed(2)
  }
  return String(value)
}

/**
 * Slide-in panel that shows everything we know about a single
 * evaluation row: the original CSV row (``raw_columns``), the
 * transcript, every metric score (with rationale where available),
 * and the recording link/audio. Triggered by clicking a table row.
 */
function RowDetailPanel({
  row,
  displayMetrics,
  onClose,
}: {
  row: CallImportEvaluationRow | null
  displayMetrics: { id: string; name: string; hasRationale: boolean }[]
  onClose: () => void
}) {
  // Close on Escape so the panel feels like a proper drawer.
  useEffect(() => {
    if (!row) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [row, onClose])

  if (!row) return null

  const callId = row.external_call_id || `Row ${(row.row_index ?? 0) + 1}`

  return (
    <div className="fixed inset-0 z-50 flex" role="dialog" aria-modal="true">
      <div
        className="flex-1 bg-gray-900/40 backdrop-blur-[1px]"
        onClick={onClose}
      />
      <aside className="w-full max-w-xl bg-white shadow-2xl overflow-y-auto border-l border-gray-200">
        <div className="sticky top-0 z-10 bg-white border-b border-gray-200 px-5 py-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-wider text-gray-500">
              Call Details
            </p>
            <p
              className="text-base font-semibold text-gray-900 font-mono truncate"
              title={callId}
            >
              {callId}
            </p>
            <div className="mt-1 flex items-center gap-2 flex-wrap text-xs text-gray-500">
              <StatusBadge status={row.status} size="sm" />
              {row.row_index !== null && (
                <span>Row #{(row.row_index ?? 0) + 1}</span>
              )}
              {row.finished_at && (
                <span>· Finished {formatDateTime(row.finished_at)}</span>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-md text-gray-400 hover:text-gray-700 hover:bg-gray-100"
            aria-label="Close panel"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-5">
          {row.error_message && (
            <div className="bg-red-50 border border-red-200 rounded-md p-3 text-sm text-red-800 flex items-start gap-2">
              <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
              <span>{row.error_message}</span>
            </div>
          )}

          {/* Recording */}
          {row.recording_url && (
            <section>
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                Recording
              </h3>
              <audio controls src={row.recording_url} className="w-full" />
              <a
                href={row.recording_url}
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-flex items-center gap-1 text-[11px] text-primary-600 hover:text-primary-700"
              >
                Open in new tab
                <ExternalLink className="h-3 w-3" />
              </a>
            </section>
          )}

          {/* Metric scores */}
          <section>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
              Scores ({displayMetrics.length})
            </h3>
            {displayMetrics.length === 0 ? (
              <p className="text-xs text-gray-400 italic">
                No metric scores recorded.
              </p>
            ) : (
              <div className="space-y-2">
                {displayMetrics.map((metric) => {
                  const score = (row.metric_scores || {})[metric.id]
                  const hasScore =
                    score !== undefined && score !== null && score !== ''
                  const value =
                    hasScore && typeof score === 'object'
                      ? (score as any).value
                      : score
                  const rationale =
                    hasScore &&
                    typeof score === 'object' &&
                    typeof (score as any).rationale === 'string'
                      ? String((score as any).rationale)
                      : undefined
                  const errorText =
                    hasScore &&
                    typeof score === 'object' &&
                    (score as any).error
                      ? String((score as any).error)
                      : undefined
                  return (
                    <div
                      key={metric.id}
                      className="border border-gray-200 rounded-md p-3"
                    >
                      <div className="flex items-baseline justify-between gap-3">
                        <p className="text-sm font-medium text-gray-700 truncate">
                          {metric.name}
                        </p>
                        <span
                          className={`text-sm font-semibold ${
                            hasScore ? 'text-gray-900' : 'text-gray-400'
                          }`}
                        >
                          {hasScore ? formatScoreValue(value) : '—'}
                        </span>
                      </div>
                      {rationale && (
                        <p className="mt-1.5 text-xs text-gray-600 whitespace-pre-wrap leading-snug">
                          {rationale}
                        </p>
                      )}
                      {errorText && (
                        <p className="mt-1.5 text-xs text-red-700 whitespace-pre-wrap leading-snug">
                          {errorText}
                        </p>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </section>

          {/* Transcript */}
          {row.transcript && (
            <section>
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                Transcript
              </h3>
              <div className="bg-gray-50 border border-gray-200 rounded-md p-3 text-xs text-gray-800 whitespace-pre-wrap leading-relaxed max-h-72 overflow-y-auto">
                {row.transcript}
              </div>
            </section>
          )}

          {/* Raw CSV columns */}
          {row.raw_columns &&
            Object.keys(row.raw_columns).length > 0 && (
              <section>
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                  CSV Row ({Object.keys(row.raw_columns).length} columns)
                </h3>
                <dl className="border border-gray-200 rounded-md divide-y divide-gray-200 overflow-hidden">
                  {Object.entries(row.raw_columns).map(([key, value]) => (
                    <div
                      key={key}
                      className="grid grid-cols-[140px_1fr] text-xs"
                    >
                      <dt className="bg-gray-50 px-3 py-1.5 font-medium text-gray-600 truncate border-r border-gray-200">
                        {key}
                      </dt>
                      <dd className="px-3 py-1.5 text-gray-800 break-words">
                        {value === null || value === undefined || value === ''
                          ? '—'
                          : String(value)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}
        </div>
      </aside>
    </div>
  )
}

/**
 * Single-metric chart card used inside the Visualizations tab. Picks
 * the chart shape from the aggregate payload: numeric histograms beat
 * categorical pie/bar charts when both are present, since numeric
 * distributions tell a richer story than the top-N category tally.
 *
 * Categorical bars and pie slices are clickable: clicking one calls
 * ``onValueClick(label)`` with the value the user wants to drill into
 * — the parent uses that to apply a row-table filter.
 */
function MetricVisualization({
  metric,
  isActive,
  activeValue,
  onValueClick,
}: {
  metric: CallImportMetricAggregate
  isActive: boolean
  activeValue: string | null
  onValueClick: (value: string) => void
}) {
  const histogram = metric.histogram_buckets
  const valueCounts = metric.value_counts
  const hasNumeric = histogram.length > 0 || metric.mean != null
  const hasCategorical = valueCounts.length > 0
  const totalCategorical = valueCounts.reduce((sum, v) => sum + v.count, 0)

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
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 4 }}>
          <defs>
            <linearGradient id={`bar-num-${metric.metric_id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#6366f1" stopOpacity={0.95} />
              <stop offset="100%" stopColor="#6366f1" stopOpacity={0.55} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 10, fill: '#64748b' }}
            axisLine={{ stroke: '#e2e8f0' }}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 10, fill: '#64748b' }}
            axisLine={false}
            tickLine={false}
            allowDecimals={false}
          />
          <Tooltip
            contentStyle={{
              background: '#0f172a',
              border: 'none',
              borderRadius: 6,
              fontSize: 11,
              color: '#f8fafc',
            }}
            cursor={{ fill: 'rgba(99,102,241,0.08)' }}
          />
          <Bar
            dataKey="count"
            fill={`url(#bar-num-${metric.metric_id})`}
            radius={[4, 4, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    )
  } else if (valueCounts.length && valueCounts.length <= 5) {
    chart = (
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Tooltip
            contentStyle={{
              background: '#0f172a',
              border: 'none',
              borderRadius: 6,
              fontSize: 11,
              color: '#f8fafc',
            }}
          />
          <Pie
            data={valueCounts}
            dataKey="count"
            nameKey="label"
            innerRadius={42}
            outerRadius={75}
            paddingAngle={2}
            stroke="#fff"
            strokeWidth={2}
            onClick={(slice: any) => {
              const label = slice?.payload?.label ?? slice?.name
              if (typeof label === 'string') onValueClick(label)
            }}
            label={(entry) => entry.label}
            labelLine={false}
          >
            {valueCounts.map((vc, i) => (
              <Cell
                key={vc.label}
                fill={PIE_COLORS[i % PIE_COLORS.length]}
                cursor="pointer"
                opacity={
                  activeValue && activeValue !== vc.label ? 0.35 : 1
                }
              />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    )
  } else if (valueCounts.length) {
    chart = (
      <ResponsiveContainer width="100%" height={Math.min(260, 32 + valueCounts.length * 26)}>
        <BarChart
          data={valueCounts}
          layout="vertical"
          margin={{ top: 4, right: 16, left: 0, bottom: 4 }}
        >
          <defs>
            <linearGradient id={`bar-cat-${metric.metric_id}`} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#10b981" stopOpacity={0.55} />
              <stop offset="100%" stopColor="#10b981" stopOpacity={0.95} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
          <XAxis
            type="number"
            tick={{ fontSize: 10, fill: '#64748b' }}
            axisLine={false}
            tickLine={false}
            allowDecimals={false}
          />
          <YAxis
            type="category"
            dataKey="label"
            tick={{ fontSize: 11, fill: '#334155' }}
            axisLine={false}
            tickLine={false}
            width={120}
          />
          <Tooltip
            contentStyle={{
              background: '#0f172a',
              border: 'none',
              borderRadius: 6,
              fontSize: 11,
              color: '#f8fafc',
            }}
            cursor={{ fill: 'rgba(16,185,129,0.08)' }}
            formatter={(value: any) => [`${value} rows`, 'Count']}
          />
          <Bar
            dataKey="count"
            fill={`url(#bar-cat-${metric.metric_id})`}
            radius={[0, 4, 4, 0]}
            onClick={(bar: any) => {
              const label = bar?.label ?? bar?.payload?.label
              if (typeof label === 'string') onValueClick(label)
            }}
          >
            {valueCounts.map((vc) => (
              <Cell
                key={vc.label}
                cursor="pointer"
                opacity={
                  activeValue && activeValue !== vc.label ? 0.35 : 1
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    )
  }

  return (
    <div
      className={`group relative rounded-xl border bg-white p-4 transition-shadow ${
        isActive
          ? 'border-primary-300 ring-2 ring-primary-100 shadow-sm'
          : 'border-gray-200 hover:shadow-md hover:border-gray-300'
      }`}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <p
            className="text-sm font-semibold text-gray-900 truncate"
            title={metric.metric_name}
          >
            {metric.metric_name}
          </p>
          <div className="mt-1 flex items-center gap-1.5 flex-wrap">
            <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-gray-100 text-gray-700">
              n = {metric.count}
            </span>
            {metric.skipped_count > 0 && (
              <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-amber-50 text-amber-700">
                {metric.skipped_count} skipped
              </span>
            )}
            {metric.error_count > 0 && (
              <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-red-50 text-red-700">
                {metric.error_count} errors
              </span>
            )}
            {metric.metric_type && (
              <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-primary-50 text-primary-700 capitalize">
                {metric.metric_type}
              </span>
            )}
          </div>
        </div>
        {isActive && (
          <span className="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full bg-primary-100 text-primary-800 shrink-0">
            <Filter className="h-3 w-3" />
            Filtering
          </span>
        )}
      </div>

      {hasNumeric && (
        <div className="mb-3 grid grid-cols-4 gap-2">
          {[
            { label: 'Mean', value: metric.mean },
            { label: 'Median', value: metric.median },
            { label: 'p95', value: metric.p95 },
            { label: 'σ', value: metric.stddev },
          ].map((stat) => (
            <div
              key={stat.label}
              className="rounded-md bg-gradient-to-br from-gray-50 to-gray-100/60 border border-gray-100 px-2 py-1.5 text-center"
            >
              <p className="text-[9px] uppercase tracking-wider text-gray-500">
                {stat.label}
              </p>
              <p className="text-xs font-semibold text-gray-900">
                {stat.value != null ? stat.value.toFixed(2) : '—'}
              </p>
            </div>
          ))}
        </div>
      )}

      {chart ?? (
        <p className="text-xs text-gray-400 italic py-8 text-center">
          No values recorded yet.
        </p>
      )}

      {hasCategorical && totalCategorical > 0 && (
        <ul className="mt-3 space-y-1 text-[11px]">
          {valueCounts.slice(0, 4).map((vc, i) => {
            const pct = (vc.count / totalCategorical) * 100
            const isFiltered = activeValue === vc.label
            return (
              <li key={vc.label}>
                <button
                  type="button"
                  onClick={() => onValueClick(vc.label)}
                  className={`group/row w-full flex items-center gap-2 rounded px-1.5 py-1 transition ${
                    isFiltered
                      ? 'bg-primary-50 text-primary-800'
                      : 'hover:bg-gray-50 text-gray-700'
                  }`}
                >
                  <span
                    className="h-2 w-2 rounded-full shrink-0"
                    style={{ background: PIE_COLORS[i % PIE_COLORS.length] }}
                  />
                  <span className="truncate text-left flex-1" title={vc.label}>
                    {vc.label}
                  </span>
                  <span className="font-medium text-gray-900">{vc.count}</span>
                  <span className="text-gray-400 w-10 text-right">
                    {pct.toFixed(0)}%
                  </span>
                </button>
              </li>
            )
          })}
          {valueCounts.length > 4 && (
            <li className="text-[10px] text-gray-400 px-1.5">
              +{valueCounts.length - 4} more
            </li>
          )}
        </ul>
      )}
    </div>
  )
}

// Lightweight ReactNode alias keeps the chart variable typed without
// pulling React's full ReactNode through the function signature
// (prevents a "type-only import" tangle on tsx/lint).
type ReactNodeLike = React.ReactNode

export type { CallImportEvaluation as _ }

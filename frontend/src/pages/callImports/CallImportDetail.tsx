import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  Edit3,
  FileText,
  Pause,
  Play,
  RefreshCw,
  Trash2,
  Volume2,
  X,
  XCircle,
} from 'lucide-react'
import { apiClient } from '../../lib/api'
import type {
  CallImportEvaluation,
  CallImportEvaluationRow,
  CallImportRow,
  CallImportTag,
} from '../../types/api'
import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import StatusBadge from '../../components/shared/StatusBadge'
import CallImportProgressBar from './components/CallImportProgressBar'

const ROW_PAGE_SIZE = 100

function renderModal(content: ReactNode) {
  if (typeof document === 'undefined') return null
  return createPortal(content, document.body)
}

function formatBytes(bytes: number | null): string {
  if (!bytes || bytes <= 0) return '\u2014'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`
}

function isNonRetryableError(message: string | null | undefined): boolean {
  if (!message) return false
  return /(401|403|404|forbidden|unauthor|not found|exceeds|too large|invalid content)/i.test(message)
}

export default function CallImportDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [rowOffset, setRowOffset] = useState(0)
  const [transcriptRow, setTranscriptRow] = useState<CallImportRow | null>(null)

  const [playingRowId, setPlayingRowId] = useState<string | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [loadingRowId, setLoadingRowId] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)

  const [showDeleteImport, setShowDeleteImport] = useState(false)
  const [pendingDeleteRow, setPendingDeleteRow] = useState<CallImportRow | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [showRunEval, setShowRunEval] = useState(false)
  const [selectedMetricIds, setSelectedMetricIds] = useState<string[]>([])
  const [activeEvalId, setActiveEvalId] = useState<string | null>(null)
  const [evalRowsPage, setEvalRowsPage] = useState(1)
  const [activeTab, setActiveTab] = useState<'rows' | 'evaluations'>('rows')

  const [editingMeta, setEditingMeta] = useState(false)
  const [draftDataset, setDraftDataset] = useState('')
  const [draftTagIds, setDraftTagIds] = useState<string[]>([])

  const { data: existingDatasets = [] } = useQuery({
    queryKey: ['call-import-datasets'],
    queryFn: () => apiClient.listCallImportDatasets(),
    enabled: editingMeta,
  })

  const { data: allTags = [] } = useQuery({
    queryKey: ['call-import-tags'],
    queryFn: () => apiClient.listCallImportTags(),
  })

  const updateMetaMutation = useMutation({
    mutationFn: (payload: { dataset?: string | null; tag_ids?: string[] }) =>
      apiClient.updateCallImport(id!, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-import', id] })
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      queryClient.invalidateQueries({ queryKey: ['call-import-datasets'] })
      setEditingMeta(false)
    },
  })

  const deleteImportMutation = useMutation({
    mutationFn: (importId: string) => apiClient.deleteCallImport(importId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      navigate('/call-imports')
    },
    onError: (err: any) => {
      setDeleteError(
        err?.response?.data?.detail || err?.message || 'Failed to delete import.',
      )
    },
  })

  const deleteRowMutation = useMutation({
    mutationFn: ({ importId, rowId }: { importId: string; rowId: string }) =>
      apiClient.deleteCallImportRow(importId, rowId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-import', id] })
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      setPendingDeleteRow(null)
      setDeleteError(null)
    },
    onError: (err: any) => {
      setDeleteError(
        err?.response?.data?.detail || err?.message || 'Failed to delete row.',
      )
    },
  })

  const queryParams = useMemo(
    () => ({ row_limit: ROW_PAGE_SIZE, row_offset: rowOffset }),
    [rowOffset],
  )

  const { data, isLoading, isFetching, refetch, error } = useQuery({
    queryKey: ['call-import', id, queryParams],
    queryFn: () => apiClient.getCallImport(id!, queryParams),
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'pending' || status === 'processing' ? 5000 : false
    },
  })

  const { data: metrics = [] } = useQuery({
    queryKey: ['metrics', 'agent'],
    queryFn: () => apiClient.listMetrics('agent'),
    enabled: !!id,
  })

  const { data: evaluationsData } = useQuery({
    queryKey: ['call-import-evaluations', id],
    queryFn: () => apiClient.listCallImportEvaluations(id!),
    enabled: !!id,
    refetchInterval: (query) => {
      const rows = query.state.data?.items || []
      return rows.some((row) => row.status === 'pending' || row.status === 'running')
        ? 3000
        : false
    },
  })

  const activeEvaluation = useMemo(
    () => evaluationsData?.items.find((row) => row.id === activeEvalId) || null,
    [evaluationsData?.items, activeEvalId],
  )

  const { data: activeEvalRows } = useQuery({
    queryKey: ['call-import-evaluation-rows', id, activeEvalId, evalRowsPage],
    queryFn: () =>
      apiClient.listCallImportEvaluationRows(id!, activeEvalId!, {
        page: evalRowsPage,
        page_size: 50,
      }),
    enabled: !!id && !!activeEvalId,
    refetchInterval: () => {
      if (!activeEvaluation) return false
      return activeEvaluation.status === 'pending' || activeEvaluation.status === 'running'
        ? 3000
        : false
    },
  })

  // Columns to render in the per-row results table.
  //
  // We intentionally union three sources rather than only trusting
  // `activeEvaluation.metrics` so the UI stays in sync with the actual
  // scored data even if the server metrics list is stale or filtered:
  //   1. `activeEvaluation.metrics`      -- server-known metrics, in selected
  //                                         order. Source of truth for ordering.
  //   2. `selected_metric_ids`           -- in case the server dropped a row
  //                                         from (1) but the id is still
  //                                         recorded on the evaluation.
  //   3. keys observed in `metric_scores` -- catches anything that was actually
  //                                         scored (what the CSV export
  //                                         iterates), with `metric_name`
  //                                         falling back from the score payload
  //                                         itself.
  const displayMetrics = useMemo(() => {
    const byId = new Map<string, { id: string; name: string }>()

    for (const m of activeEvaluation?.metrics ?? []) {
      if (m && m.id) {
        byId.set(m.id, { id: m.id, name: m.name || `Metric ${m.id.slice(0, 8)}` })
      }
    }

    for (const mid of activeEvaluation?.selected_metric_ids ?? []) {
      if (typeof mid === 'string' && !byId.has(mid)) {
        byId.set(mid, { id: mid, name: `Metric ${mid.slice(0, 8)}` })
      }
    }

    for (const row of activeEvalRows?.items ?? []) {
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
          // Upgrade placeholder name with the real one from the score payload.
          byId.set(metricId, { id: metricId, name: nameFromScore })
        }
      }
    }

    return Array.from(byId.values())
  }, [
    activeEvaluation?.metrics,
    activeEvaluation?.selected_metric_ids,
    activeEvalRows?.items,
  ])

  const runEvaluationMutation = useMutation({
    mutationFn: (metricIds: string[]) =>
      apiClient.createCallImportEvaluation(id!, { metric_ids: metricIds }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['call-import-evaluations', id] })
      setShowRunEval(false)
      setSelectedMetricIds([])
      setActiveEvalId(created.id)
      setEvalRowsPage(1)
      setActiveTab('evaluations')
    },
  })

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause()
      }
    }
  }, [])

  useEffect(() => {
    const firstEval = evaluationsData?.items?.[0]
    if (!activeEvalId && firstEval) {
      setActiveEvalId(firstEval.id)
    }
  }, [evaluationsData?.items, activeEvalId])

  const totalRows = data?.total_rows ?? 0
  const rowPage = Math.floor(rowOffset / ROW_PAGE_SIZE) + 1
  const rowTotalPages = Math.max(1, Math.ceil(totalRows / ROW_PAGE_SIZE))

  const handlePlay = async (row: CallImportRow) => {
    if (!row.recording_s3_key) return

    if (playingRowId === row.id && audioUrl) {
      if (isPlaying) {
        audioRef.current?.pause()
        setIsPlaying(false)
      } else {
        audioRef.current?.play()
        setIsPlaying(true)
      }
      return
    }

    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
    }

    setLoadingRowId(row.id)
    try {
      const { url } = await apiClient.getS3PresignedUrl(row.recording_s3_key)
      setAudioUrl(url)
      setPlayingRowId(row.id)
      setIsPlaying(true)
      setLoadingRowId(null)
      setTimeout(() => audioRef.current?.play(), 100)
    } catch (e) {
      console.error('Failed to load recording', e)
      setLoadingRowId(null)
      alert('Failed to load recording')
    }
  }

  const handleStopAudio = () => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
    }
    setIsPlaying(false)
    setPlayingRowId(null)
    setAudioUrl(null)
  }

  const handleDownload = async (row: CallImportRow) => {
    if (!row.recording_s3_key) return
    try {
      const { url } = await apiClient.getS3PresignedUrl(row.recording_s3_key)
      const link = document.createElement('a')
      link.href = url
      link.setAttribute(
        'download',
        row.recording_s3_key.split('/').pop() || `${row.external_call_id}.mp3`,
      )
      document.body.appendChild(link)
      link.click()
      link.remove()
    } catch (e) {
      console.error('Failed to download recording', e)
      alert('Failed to download recording')
    }
  }

  const handleExportEvaluation = async (evaluationId: string) => {
    if (!id) return
    try {
      const blob = await apiClient.exportCallImportEvaluation(id, evaluationId)
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `call-import-${id}-evaluation-${evaluationId}.csv`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (e) {
      console.error('Failed to export evaluation', e)
      alert('Failed to export evaluation CSV')
    }
  }

  const toggleMetric = (metricId: string) => {
    setSelectedMetricIds((prev) =>
      prev.includes(metricId)
        ? prev.filter((id) => id !== metricId)
        : [...prev, metricId],
    )
  }

  if (!id) {
    return <div className="text-sm text-red-600">Missing import id.</div>
  }

  if (isLoading) {
    return (
      <div className="text-center py-12 text-gray-500">
        <RefreshCw className="h-8 w-8 mx-auto mb-2 animate-spin" />
        <p>Loading import...</p>
      </div>
    )
  }

  if (error || !data) {
    const status = (error as any)?.response?.status
    return (
      <div className="space-y-4">
        <Link
          to="/call-imports"
          className="inline-flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Call Imports
        </Link>
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-start gap-2">
            <AlertCircle className="h-5 w-5 text-red-600 mt-0.5" />
            <p className="text-sm text-red-800">
              {status === 404
                ? 'Call import not found.'
                : (error as any)?.response?.data?.detail || 'Failed to load import.'}
            </p>
          </div>
        </div>
      </div>
    )
  }

  const rows = data.rows ?? []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Link
          to="/call-imports"
          className="inline-flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Call Imports
        </Link>
        <div className="flex items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              setSelectedMetricIds([])
              setShowRunEval(true)
            }}
            disabled={!rows.length}
            title={!rows.length ? 'No rows to evaluate yet' : 'Run an evaluation on this import'}
          >
            Run Evaluation
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => refetch()}
            isLoading={isFetching && !isLoading}
            leftIcon={!(isFetching && !isLoading) ? <RefreshCw className="h-4 w-4" /> : undefined}
          >
            Refresh
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setDeleteError(null)
              setShowDeleteImport(true)
            }}
            leftIcon={<Trash2 className="h-4 w-4" />}
            className="text-red-600 hover:text-red-700 hover:bg-red-50"
          >
            Delete Import
          </Button>
        </div>
      </div>

      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold text-gray-900 truncate">
              {data.original_filename || '(unnamed import)'}
            </h1>
            <div className="mt-1 text-xs text-gray-500 font-mono">{data.id}</div>
            <div className="mt-3 flex items-center gap-3 flex-wrap">
              <StatusBadge status={data.status} />
              <span className="text-sm text-gray-600 capitalize">
                Provider: <span className="font-medium">{data.provider}</span>
              </span>
              <span className="text-sm text-gray-600">
                Created: {new Date(data.created_at).toLocaleString()}
              </span>
              <span className="text-sm text-gray-600">
                Updated: {new Date(data.updated_at).toLocaleString()}
              </span>
            </div>
          </div>
          <div className="w-72 flex-shrink-0">
            <CallImportProgressBar
              total={data.total_rows}
              completed={data.completed_rows}
              failed={data.failed_rows}
            />
            <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
              <div className="bg-gray-50 rounded p-2">
                <div className="text-gray-500">Total</div>
                <div className="font-semibold text-gray-900">{data.total_rows}</div>
              </div>
              <div className="bg-green-50 rounded p-2">
                <div className="text-green-700">Completed</div>
                <div className="font-semibold text-green-800">{data.completed_rows}</div>
              </div>
              <div className="bg-red-50 rounded p-2">
                <div className="text-red-700">Failed</div>
                <div className="font-semibold text-red-800">{data.failed_rows}</div>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-4 border-t border-gray-100 pt-4">
          {!editingMeta ? (
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Dataset:
                  </span>
                  {data.dataset ? (
                    <span className="inline-flex items-center text-sm font-medium text-gray-800 bg-gray-100 rounded px-2 py-0.5">
                      {data.dataset}
                    </span>
                  ) : (
                    <span className="text-sm text-gray-400 italic">none</span>
                  )}
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Tags:
                  </span>
                  {data.tags.length > 0 ? (
                    data.tags.map((tag) => (
                      <span
                        key={tag.id}
                        className="inline-flex items-center text-xs uppercase tracking-wide rounded-full px-2 py-0.5 border"
                        style={{
                          borderColor: tag.color || '#d1d5db',
                          color: tag.color || '#4b5563',
                        }}
                      >
                        {tag.name}
                      </span>
                    ))
                  ) : (
                    <span className="text-sm text-gray-400 italic">none</span>
                  )}
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<Edit3 className="h-4 w-4" />}
                onClick={() => {
                  setDraftDataset(data.dataset || '')
                  setDraftTagIds(data.tags.map((t) => t.id))
                  setEditingMeta(true)
                }}
              >
                Edit dataset / tags
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              <div>
                <label
                  htmlFor="dataset-edit"
                  className="block text-xs font-medium text-gray-600 uppercase tracking-wide mb-1"
                >
                  Dataset
                </label>
                <input
                  id="dataset-edit"
                  type="text"
                  list="dataset-edit-suggestions"
                  value={draftDataset}
                  onChange={(e) => setDraftDataset(e.target.value)}
                  placeholder="Leave blank to clear"
                  className="w-full max-w-sm px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                />
                <datalist id="dataset-edit-suggestions">
                  {existingDatasets.map((d) => (
                    <option key={d} value={d} />
                  ))}
                </datalist>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 uppercase tracking-wide mb-1">
                  Tags
                </label>
                {allTags.length === 0 ? (
                  <p className="text-xs text-gray-500">
                    No tags created yet.{' '}
                    <Link
                      to="/call-imports/tags"
                      className="text-primary-600 hover:text-primary-700 underline"
                    >
                      Create tags
                    </Link>
                    .
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {allTags.map((tag: CallImportTag) => {
                      const active = draftTagIds.includes(tag.id)
                      return (
                        <button
                          key={tag.id}
                          type="button"
                          onClick={() =>
                            setDraftTagIds((prev) =>
                              prev.includes(tag.id)
                                ? prev.filter((t) => t !== tag.id)
                                : [...prev, tag.id],
                            )
                          }
                          className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                            active
                              ? 'bg-primary-600 border-primary-600 text-white'
                              : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
                          }`}
                          style={
                            !active && tag.color
                              ? { borderColor: tag.color, color: tag.color }
                              : undefined
                          }
                        >
                          {tag.name}
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
              <div className="flex gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  leftIcon={<Check className="h-4 w-4" />}
                  isLoading={updateMetaMutation.isPending}
                  onClick={() =>
                    updateMetaMutation.mutate({
                      dataset: draftDataset.trim() ? draftDataset.trim() : null,
                      tag_ids: draftTagIds,
                    })
                  }
                >
                  Save
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setEditingMeta(false)}
                  disabled={updateMetaMutation.isPending}
                >
                  Cancel
                </Button>
              </div>
              {updateMetaMutation.isError && (
                <p className="text-xs text-red-600">
                  {(updateMetaMutation.error as any)?.response?.data?.detail ||
                    'Failed to update.'}
                </p>
              )}
            </div>
          )}
        </div>

        {data.error_message && (
          <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-3">
            <div className="flex items-start gap-2">
              <AlertCircle className="h-4 w-4 text-red-600 mt-0.5" />
              <p className="text-sm text-red-800">{data.error_message}</p>
            </div>
          </div>
        )}
      </div>

      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-6" aria-label="Call import sections">
          <button
            type="button"
            onClick={() => setActiveTab('rows')}
            className={`whitespace-nowrap py-3 px-1 border-b-2 text-sm font-medium transition ${
              activeTab === 'rows'
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
            aria-current={activeTab === 'rows' ? 'page' : undefined}
          >
            Rows
            <span className="ml-2 inline-flex items-center justify-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">
              {totalRows}
            </span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('evaluations')}
            className={`whitespace-nowrap py-3 px-1 border-b-2 text-sm font-medium transition ${
              activeTab === 'evaluations'
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
            aria-current={activeTab === 'evaluations' ? 'page' : undefined}
          >
            Evaluations
            <span className="ml-2 inline-flex items-center justify-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">
              {evaluationsData?.items?.length ?? 0}
            </span>
          </button>
        </nav>
      </div>

      {activeTab === 'rows' && (
      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">Rows</h2>
          <p className="text-sm text-gray-500">
            Showing {rows.length === 0 ? 0 : rowOffset + 1}&ndash;
            {rowOffset + rows.length} of {totalRows}
          </p>
        </div>

        {rows.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            <FileText className="h-12 w-12 mx-auto mb-3 text-gray-300" />
            <p>No rows in this slice.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-12">
                    #
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    CallID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Attempts
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Recording
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Transcript
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider w-12">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {rows.map((row) => {
                  const hasRecording = !!row.recording_s3_key
                  const isThisPlaying = playingRowId === row.id && isPlaying
                  return (
                    <Fragment key={row.id}>
                      <tr className="hover:bg-gray-50 align-top">
                        <td className="px-4 py-3 text-sm text-gray-500">
                          {row.row_index + 1}
                        </td>
                        <td className="px-4 py-3 text-sm font-mono text-gray-900 break-all">
                          {row.external_call_id}
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge status={row.status} size="sm" />
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600">{row.attempts}</td>
                        <td className="px-4 py-3 text-sm">
                          {hasRecording ? (
                            <div className="flex items-center gap-2 flex-wrap">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handlePlay(row)}
                                isLoading={loadingRowId === row.id}
                                leftIcon={
                                  loadingRowId === row.id
                                    ? undefined
                                    : isThisPlaying
                                      ? <Pause className="h-4 w-4" />
                                      : <Play className="h-4 w-4" />
                                }
                                className={
                                  isThisPlaying
                                    ? 'text-green-600 hover:text-green-700 bg-green-50'
                                    : 'text-blue-600 hover:text-blue-700'
                                }
                                title={isThisPlaying ? 'Pause' : 'Play'}
                              >
                                {isThisPlaying ? 'Pause' : 'Play'}
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleDownload(row)}
                                leftIcon={<Download className="h-4 w-4" />}
                                className="text-primary-600 hover:text-primary-700"
                              >
                                Download
                              </Button>
                              <span className="text-xs text-gray-400">
                                {formatBytes(row.recording_size_bytes)}
                              </span>
                            </div>
                          ) : (
                            <span className="text-xs text-gray-400">
                              {row.status === 'failed' ? '\u2014' : 'Pending...'}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-sm">
                          {row.transcript ? (
                            <button
                              onClick={() => setTranscriptRow(row)}
                              className="text-left text-gray-700 hover:text-primary-700 underline-offset-2 hover:underline line-clamp-2 max-w-md"
                              title="View transcript"
                            >
                              {row.transcript.length > 120
                                ? `${row.transcript.slice(0, 120)}...`
                                : row.transcript}
                            </button>
                          ) : (
                            <span className="text-xs text-gray-400">No transcript</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            aria-label={`Delete recording for ${row.external_call_id}`}
                            title="Delete recording"
                            onClick={() => {
                              setDeleteError(null)
                              setPendingDeleteRow(row)
                            }}
                            disabled={
                              deleteRowMutation.isPending &&
                              pendingDeleteRow?.id === row.id
                            }
                            className="text-gray-400 hover:text-red-600 transition-colors disabled:opacity-40"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </td>
                      </tr>
                      {row.status === 'failed' && row.error_message && (
                        <tr className="bg-red-50">
                          <td />
                          <td colSpan={6} className="px-4 py-2 text-xs text-red-800">
                            <div className="flex items-start gap-2">
                              <AlertCircle className="h-3.5 w-3.5 text-red-600 mt-0.5 flex-shrink-0" />
                              <div className="flex-1">
                                <span className="font-medium">Error:</span> {row.error_message}
                                {isNonRetryableError(row.error_message) && (
                                  <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-100 text-red-700">
                                    no retry
                                  </span>
                                )}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>

            {rowTotalPages > 1 && (
              <div className="px-4 py-3 bg-gray-50 border-t border-gray-200 flex items-center justify-between mt-2 rounded-b-lg">
                <p className="text-sm text-gray-600">
                  Page {rowPage} of {rowTotalPages}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setRowOffset((o) => Math.max(0, o - ROW_PAGE_SIZE))}
                    disabled={rowOffset <= 0}
                    leftIcon={<ChevronLeft className="h-4 w-4" />}
                  >
                    Prev
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      setRowOffset((o) =>
                        o + ROW_PAGE_SIZE >= totalRows ? o : o + ROW_PAGE_SIZE,
                      )
                    }
                    disabled={rowOffset + ROW_PAGE_SIZE >= totalRows}
                    rightIcon={<ChevronRight className="h-4 w-4" />}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {playingRowId && audioUrl && (
          <div className="mt-4 bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-lg p-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Volume2 className="h-5 w-5 text-blue-600" />
                <span className="text-sm font-medium text-gray-700">Now Playing:</span>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-900 truncate">
                  {rows.find((r) => r.id === playingRowId)?.external_call_id}
                </p>
              </div>
              <button
                onClick={handleStopAudio}
                className="p-2 rounded-full bg-gray-200 text-gray-600 hover:bg-gray-300 transition-colors"
                title="Stop"
              >
                <XCircle className="h-4 w-4" />
              </button>
              <audio
                ref={audioRef}
                src={audioUrl}
                onEnded={() => setIsPlaying(false)}
                onPause={() => setIsPlaying(false)}
                onPlay={() => setIsPlaying(true)}
                controls
                className="h-8 flex-shrink-0"
              />
            </div>
          </div>
        )}
      </div>
      )}

      {activeTab === 'evaluations' && (
      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Evaluations</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Use the Run Evaluation button at the top to start a new evaluation.
            </p>
          </div>
        </div>

        {(evaluationsData?.items?.length || 0) === 0 ? (
          <p className="text-sm text-gray-500">No evaluations have been run for this dataset yet.</p>
        ) : (
          <div className="space-y-3">
            {evaluationsData?.items.map((evaluation: CallImportEvaluation) => (
              <button
                key={evaluation.id}
                type="button"
                onClick={() => {
                  setActiveEvalId(evaluation.id)
                  setEvalRowsPage(1)
                }}
                className={`w-full text-left border rounded-lg px-4 py-3 transition ${
                  activeEvalId === evaluation.id
                    ? 'border-primary-500 bg-primary-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-gray-900">
                      Evaluation {evaluation.id.slice(0, 8)}
                    </p>
                    <p className="text-xs text-gray-600">
                      {evaluation.metrics.map((metric) => metric.name).join(', ') || 'No metrics'}
                    </p>
                  </div>
                  <div className="text-right">
                    <StatusBadge status={evaluation.status} size="sm" />
                    <p className="text-xs text-gray-500 mt-1">
                      {evaluation.completed_rows}/{evaluation.total_rows} rows
                    </p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        {activeEvaluation && (
          <div className="mt-6 border-t border-gray-100 pt-4">
            <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-900">
                  Rows for evaluation {activeEvaluation.id.slice(0, 8)}
                </p>
                <p className="text-xs text-gray-500">
                  Metrics ({displayMetrics.length}):{' '}
                  {displayMetrics.map((m) => m.name).join(', ') || 'none'}
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                leftIcon={<Download className="h-4 w-4" />}
                onClick={() => handleExportEvaluation(activeEvaluation.id)}
              >
                Download CSV
              </Button>
            </div>

            {activeEvalRows?.items?.length ? (
              <>
                {displayMetrics.length > 3 && (
                  <p className="mb-2 text-[11px] text-gray-500">
                    Scroll the table horizontally to see all {displayMetrics.length}{' '}
                    metric columns.
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
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {activeEvalRows.items.map((row: CallImportEvaluationRow) => (
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
                              score && typeof score === 'object' ? score.value : undefined
                            const scoreType =
                              score && typeof score === 'object' && typeof score.type === 'string'
                                ? score.type.toLowerCase()
                                : undefined
                            const isEmpty =
                              value === undefined || value === null || value === ''
                            const valueStr = isEmpty ? '' : String(value)
                            const isLongText = scoreType === 'text' && valueStr.length > 80
                            const errorText =
                              score && typeof score === 'object' && score.error
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
                                title={errorText || (isLongText ? valueStr : undefined)}
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
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <p className="text-sm text-gray-500">No row results yet.</p>
            )}

            {activeEvalRows && activeEvalRows.total > activeEvalRows.page_size && (
              <div className="mt-3 flex items-center justify-between">
                <p className="text-sm text-gray-500">
                  Page {activeEvalRows.page} of {Math.max(1, Math.ceil(activeEvalRows.total / activeEvalRows.page_size))}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setEvalRowsPage((p) => Math.max(1, p - 1))}
                    disabled={activeEvalRows.page <= 1}
                  >
                    Prev
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setEvalRowsPage((p) => p + 1)}
                    disabled={activeEvalRows.page * activeEvalRows.page_size >= activeEvalRows.total}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
      )}

      {transcriptRow &&
        renderModal(
          <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
            <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col">
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                <div className="min-w-0">
                  <h3 className="text-lg font-semibold">Transcript</h3>
                  <p className="text-xs text-gray-500 font-mono truncate">
                    {transcriptRow.external_call_id}
                  </p>
                </div>
                <button
                  onClick={() => setTranscriptRow(null)}
                  className="text-gray-400 hover:text-gray-600 flex-shrink-0"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-6 overflow-y-auto whitespace-pre-wrap text-sm text-gray-800 leading-relaxed">
                {transcriptRow.transcript || '(no transcript)'}
              </div>
            </div>
          </div>,
        )}

      {showRunEval &&
        renderModal(
          (() => {
            const enabledMetrics = metrics.filter((m: any) => m.enabled)
            const disabledMetrics = metrics.filter((m: any) => !m.enabled)
            const runError = runEvaluationMutation.isError
              ? (runEvaluationMutation.error as any)?.response?.data?.detail ||
                'Failed to start evaluation.'
              : null
            return (
              <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
                <div className="bg-white rounded-lg shadow-xl max-w-lg w-full mx-4">
                  <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                    <h3 className="text-lg font-semibold">Run Evaluation</h3>
                    <button
                      onClick={() => {
                        if (runEvaluationMutation.isPending) return
                        setShowRunEval(false)
                      }}
                      className="text-gray-400 hover:text-gray-600"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>
                  <div className="p-6 space-y-3 max-h-[70vh] overflow-y-auto">
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-sm text-gray-600">
                        Pick the metrics to run against every completed row in this batch.
                      </p>
                      <Link
                        to="/metrics"
                        className="text-xs font-medium text-primary-700 hover:text-primary-900 whitespace-nowrap"
                      >
                        Manage metrics →
                      </Link>
                    </div>

                    {enabledMetrics.length === 0 ? (
                      <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 space-y-2">
                        <p className="font-medium">No enabled agent metrics yet.</p>
                        <p>
                          Evaluations only run against metrics that are <strong>enabled</strong> on
                          your organization and support the <strong>agent</strong> surface.
                        </p>
                        {disabledMetrics.length > 0 ? (
                          <p>
                            You have {disabledMetrics.length} disabled metric
                            {disabledMetrics.length === 1 ? '' : 's'} (
                            {disabledMetrics
                              .slice(0, 3)
                              .map((m: any) => m.name)
                              .join(', ')}
                            {disabledMetrics.length > 3 ? ', …' : ''}). Open Metrics to enable
                            them.
                          </p>
                        ) : (
                          <p>You don't have any metrics yet — create one in Metrics first.</p>
                        )}
                        <Link
                          to="/metrics"
                          className="inline-block font-medium text-amber-900 underline hover:text-amber-700"
                        >
                          Open Metrics →
                        </Link>
                      </div>
                    ) : (
                      <>
                        <div className="space-y-2">
                          <p className="text-xs uppercase tracking-wide font-semibold text-gray-500">
                            Enabled metrics ({enabledMetrics.length})
                          </p>
                          {enabledMetrics.map((metric: any) => (
                            <label
                              key={metric.id}
                              className="flex items-start gap-2 text-sm cursor-pointer"
                            >
                              <input
                                type="checkbox"
                                checked={selectedMetricIds.includes(metric.id)}
                                onChange={() => toggleMetric(metric.id)}
                                className="mt-1"
                              />
                              <span>
                                <span className="font-medium text-gray-900">{metric.name}</span>
                                {metric.description ? (
                                  <span className="block text-xs text-gray-500">
                                    {metric.description}
                                  </span>
                                ) : null}
                              </span>
                            </label>
                          ))}
                        </div>

                        {disabledMetrics.length > 0 && (
                          <details className="rounded-md border border-gray-200 bg-gray-50 p-3 text-sm">
                            <summary className="cursor-pointer font-medium text-gray-700">
                              {disabledMetrics.length} disabled metric
                              {disabledMetrics.length === 1 ? '' : 's'} hidden
                            </summary>
                            <ul className="mt-2 space-y-1 text-xs text-gray-600">
                              {disabledMetrics.map((metric: any) => (
                                <li key={metric.id} className="flex items-baseline gap-2">
                                  <span className="line-through">{metric.name}</span>
                                  <span className="text-gray-400">— disabled</span>
                                </li>
                              ))}
                            </ul>
                            <Link
                              to="/metrics"
                              className="mt-2 inline-block text-xs font-medium text-primary-700 hover:text-primary-900"
                            >
                              Enable them in Metrics →
                            </Link>
                          </details>
                        )}
                      </>
                    )}

                    {runError ? (
                      <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 space-y-1">
                        <p>{runError}</p>
                        {/metric/i.test(runError) ? (
                          <Link
                            to="/metrics"
                            className="font-medium text-red-700 underline hover:text-red-900"
                          >
                            Check your metrics setup →
                          </Link>
                        ) : null}
                      </div>
                    ) : null}

                    <div className="flex gap-2 pt-2">
                      <Button
                        variant="outline"
                        onClick={() => setShowRunEval(false)}
                        disabled={runEvaluationMutation.isPending}
                        className="flex-1"
                      >
                        Cancel
                      </Button>
                      <Button
                        variant="primary"
                        isLoading={runEvaluationMutation.isPending}
                        disabled={
                          selectedMetricIds.length === 0 ||
                          enabledMetrics.length === 0 ||
                          runEvaluationMutation.isPending
                        }
                        onClick={() => runEvaluationMutation.mutate(selectedMetricIds)}
                        className="flex-1"
                      >
                        Start
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            )
          })(),
        )}

      <ConfirmModal
        isOpen={showDeleteImport}
        title="Delete call import?"
        description={(() => {
          const name = data.original_filename || '(unnamed)'
          const inFlight = data.status === 'pending' || data.status === 'processing'
          const lines = [
            `“${name}” will be permanently deleted, along with all ${data.total_rows} row record${data.total_rows === 1 ? '' : 's'} and ${data.completed_rows} stored recording${data.completed_rows === 1 ? '' : 's'} in S3.`,
            inFlight
              ? 'This batch is still processing — pending tasks will be revoked before deletion.'
              : '',
            'This cannot be undone.',
            deleteError ? `Error: ${deleteError}` : '',
          ]
          return lines.filter(Boolean).join('\n\n')
        })()}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        isLoading={deleteImportMutation.isPending}
        onConfirm={() => deleteImportMutation.mutate(data.id)}
        onCancel={() => {
          if (deleteImportMutation.isPending) return
          setShowDeleteImport(false)
          setDeleteError(null)
        }}
      />

      <ConfirmModal
        isOpen={pendingDeleteRow !== null}
        title="Delete this recording?"
        description={(() => {
          if (!pendingDeleteRow) return ''
          const callId = pendingDeleteRow.external_call_id
          const hasS3 = !!pendingDeleteRow.recording_s3_key
          const lines = [
            `The row for CallID ${callId} will be removed from this import.`,
            hasS3
              ? 'The associated recording will also be deleted from S3.'
              : 'No recording is stored for this row yet, so only the row record will be removed.',
            'This cannot be undone.',
            deleteError ? `Error: ${deleteError}` : '',
          ]
          return lines.filter(Boolean).join('\n\n')
        })()}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        isLoading={deleteRowMutation.isPending}
        onConfirm={() => {
          if (pendingDeleteRow && id) {
            deleteRowMutation.mutate({ importId: id, rowId: pendingDeleteRow.id })
          }
        }}
        onCancel={() => {
          if (deleteRowMutation.isPending) return
          setPendingDeleteRow(null)
          setDeleteError(null)
        }}
      />
    </div>
  )
}

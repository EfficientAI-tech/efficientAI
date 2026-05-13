import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
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
  ListTree,
  MessageSquare,
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
  CallImportRow,
  CallImportTag,
} from '../../types/api'
import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import StatusBadge from '../../components/shared/StatusBadge'
import CallImportProgressBar from './components/CallImportProgressBar'
import TranscriptView from './components/TranscriptView'

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
  const [expandedRowIds, setExpandedRowIds] = useState<Set<string>>(new Set())

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
  const [runDraftName, setRunDraftName] = useState('')
  const [activeTab, setActiveTab] = useState<'rows' | 'evaluations'>('rows')
  const [selectedEvalIds, setSelectedEvalIds] = useState<Set<string>>(new Set())
  const [showBulkDeleteEvals, setShowBulkDeleteEvals] = useState(false)
  const [bulkDeleteEvalsError, setBulkDeleteEvalsError] = useState<string | null>(null)

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

  const runEvaluationMutation = useMutation({
    mutationFn: (payload: { metric_ids: string[]; name?: string | null }) =>
      apiClient.createCallImportEvaluation(id!, payload),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['call-import-evaluations', id] })
      setShowRunEval(false)
      setSelectedMetricIds([])
      setRunDraftName('')
      setActiveTab('evaluations')
      // Land directly on the dedicated detail page for the new run.
      navigate(`/call-imports/${id}/evaluations/${created.id}`)
    },
  })

  const bulkDeleteEvalsMutation = useMutation({
    mutationFn: (ids: string[]) =>
      apiClient.bulkDeleteCallImportEvaluations(id!, ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-import-evaluations', id] })
      setSelectedEvalIds(new Set())
      setShowBulkDeleteEvals(false)
      setBulkDeleteEvalsError(null)
    },
    onError: (err: any) => {
      setBulkDeleteEvalsError(
        err?.response?.data?.detail ||
          err?.message ||
          'Failed to delete evaluation runs.',
      )
    },
  })

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause()
      }
    }
  }, [])

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
        <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
          <h2 className="text-lg font-semibold text-gray-900">Rows</h2>
          <div className="flex items-center gap-3 flex-wrap">
            {rows.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<ListTree className="h-4 w-4" />}
                onClick={() => {
                  const everyExpanded = rows.every((r) => expandedRowIds.has(r.id))
                  setExpandedRowIds(
                    everyExpanded
                      ? new Set()
                      : new Set(rows.map((r) => r.id)),
                  )
                }}
              >
                {rows.every((r) => expandedRowIds.has(r.id)) && rows.length > 0
                  ? 'Collapse all'
                  : 'Expand all'}
              </Button>
            )}
            <p className="text-sm text-gray-500">
              Showing {rows.length === 0 ? 0 : rowOffset + 1}&ndash;
              {rowOffset + rows.length} of {totalRows}
            </p>
          </div>
        </div>

        {rows.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            <FileText className="h-12 w-12 mx-auto mb-3 text-gray-300" />
            <p>No rows in this slice.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {rows.map((row) => {
              const hasRecording = !!row.recording_s3_key
              const isThisPlaying = playingRowId === row.id && isPlaying
              const isLoadingThis = loadingRowId === row.id
              const isExpanded = expandedRowIds.has(row.id)
              // Hide raw_columns entries that just duplicate fields we
              // already render in dedicated UI (Conversation, Recording
              // section, summary line). The backend always preserves the
              // mapped CSV columns into raw_columns under their original
              // header, so without this filter the user sees, e.g. a
              // "transcript" cell containing the exact same conversation
              // they're already reading as chat bubbles.
              const transcriptValue = (row.transcript || '').trim()
              const recordingUrlValue = (row.recording_url || '').trim()
              const externalCallIdValue = (row.external_call_id || '').trim()
              const rawColumnEntries = Object.entries(row.raw_columns || {}).filter(
                ([key, value]) => {
                  if (!key.trim()) return false
                  const trimmedValue = (value || '').trim()
                  if (!trimmedValue) return true
                  if (transcriptValue && trimmedValue === transcriptValue) return false
                  if (recordingUrlValue && trimmedValue === recordingUrlValue) return false
                  if (externalCallIdValue && trimmedValue === externalCallIdValue) {
                    return false
                  }
                  return true
                },
              )
              return (
                <div
                  key={row.id}
                  className="border border-gray-200 rounded-lg bg-white overflow-hidden transition-shadow hover:shadow-sm"
                >
                  <div className="flex items-center gap-2 px-3 py-2.5">
                    <button
                      type="button"
                      onClick={() =>
                        setExpandedRowIds((prev) => {
                          const next = new Set(prev)
                          if (next.has(row.id)) next.delete(row.id)
                          else next.add(row.id)
                          return next
                        })
                      }
                      aria-expanded={isExpanded}
                      aria-label={isExpanded ? 'Collapse row' : 'Expand row'}
                      className="flex items-center gap-3 flex-1 min-w-0 text-left rounded hover:bg-gray-50 -mx-1 px-1 py-1 transition-colors"
                    >
                      <ChevronRight
                        className={`h-4 w-4 flex-shrink-0 text-gray-400 transition-transform duration-150 ${
                          isExpanded ? 'rotate-90' : ''
                        }`}
                      />
                      <span className="text-xs text-gray-400 w-10 tabular-nums flex-shrink-0">
                        #{row.row_index + 1}
                      </span>
                      <span
                        className="font-mono text-sm text-gray-900 truncate flex-1 min-w-0"
                        title={row.external_call_id}
                      >
                        {row.external_call_id}
                      </span>
                      <StatusBadge status={row.status} size="sm" />
                    </button>

                    <div className="flex items-center gap-1 flex-shrink-0">
                      {hasRecording ? (
                        <>
                          <button
                            type="button"
                            onClick={() => handlePlay(row)}
                            disabled={isLoadingThis}
                            title={isThisPlaying ? 'Pause' : 'Play recording'}
                            className={`p-1.5 rounded transition-colors disabled:opacity-50 ${
                              isThisPlaying
                                ? 'text-green-600 bg-green-50 hover:bg-green-100'
                                : 'text-blue-600 hover:bg-blue-50'
                            }`}
                          >
                            {isLoadingThis ? (
                              <RefreshCw className="h-4 w-4 animate-spin" />
                            ) : isThisPlaying ? (
                              <Pause className="h-4 w-4" />
                            ) : (
                              <Play className="h-4 w-4" />
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDownload(row)}
                            title="Download recording"
                            className="p-1.5 rounded text-gray-500 hover:text-primary-600 hover:bg-primary-50 transition-colors"
                          >
                            <Download className="h-4 w-4" />
                          </button>
                        </>
                      ) : (
                        <span className="text-[11px] text-gray-400 px-2">
                          {row.status === 'failed' ? 'no audio' : 'pending'}
                        </span>
                      )}
                      <button
                        type="button"
                        aria-label={`Delete recording for ${row.external_call_id}`}
                        title="Delete row"
                        onClick={() => {
                          setDeleteError(null)
                          setPendingDeleteRow(row)
                        }}
                        disabled={
                          deleteRowMutation.isPending &&
                          pendingDeleteRow?.id === row.id
                        }
                        className="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-40"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>

                  {row.status === 'failed' && row.error_message && (
                    <div className="border-t border-red-100 bg-red-50 px-3 py-2 text-xs text-red-800 flex items-start gap-2">
                      <AlertCircle className="h-3.5 w-3.5 text-red-600 flex-shrink-0 mt-0.5" />
                      <div className="min-w-0 flex-1 break-words">
                        <span className="font-medium">Error:</span> {row.error_message}
                        {isNonRetryableError(row.error_message) && (
                          <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-100 text-red-700">
                            no retry
                          </span>
                        )}
                      </div>
                    </div>
                  )}

                  {isExpanded && (
                    <div className="border-t border-gray-200 px-4 py-4 bg-gray-100 space-y-3">
                      <div className="grid grid-cols-1 lg:grid-cols-5 gap-3">
                        <section className="lg:col-span-3 min-w-0 bg-white border border-gray-200 rounded-lg shadow-sm">
                          <header className="px-3 py-2 border-b border-gray-100 flex items-center gap-1.5">
                            <MessageSquare className="h-3.5 w-3.5 text-gray-400" />
                            <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
                              Conversation
                            </h4>
                          </header>
                          <div className="p-3">
                            <TranscriptView transcript={row.transcript} compact />
                          </div>
                        </section>

                        <div className="lg:col-span-2 min-w-0 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-1 gap-3">
                          <section className="bg-white border border-gray-200 rounded-lg shadow-sm">
                            <header className="px-3 py-2 border-b border-gray-100 flex items-center gap-1.5">
                              <Volume2 className="h-3.5 w-3.5 text-gray-400" />
                              <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
                                Recording
                              </h4>
                            </header>
                            <dl className="p-3 space-y-1.5 text-xs">
                              <div className="flex justify-between gap-2">
                                <dt className="text-gray-500">Size</dt>
                                <dd className="text-gray-800 tabular-nums">
                                  {formatBytes(row.recording_size_bytes)}
                                </dd>
                              </div>
                              <div className="flex justify-between gap-2">
                                <dt className="text-gray-500">Type</dt>
                                <dd className="text-gray-800 truncate text-right">
                                  {row.recording_content_type || '—'}
                                </dd>
                              </div>
                              {row.recording_url && (
                                <div className="flex flex-col gap-0.5 pt-1 border-t border-gray-50">
                                  <dt className="text-gray-500">Source URL</dt>
                                  <dd className="min-w-0">
                                    <a
                                      href={row.recording_url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="text-blue-700 hover:text-blue-800 underline break-all"
                                      title={row.recording_url}
                                    >
                                      {row.recording_url}
                                    </a>
                                  </dd>
                                </div>
                              )}
                            </dl>
                          </section>

                          <section className="bg-white border border-gray-200 rounded-lg shadow-sm">
                            <header className="px-3 py-2 border-b border-gray-100 flex items-center gap-1.5">
                              <RefreshCw className="h-3.5 w-3.5 text-gray-400" />
                              <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
                                Run
                              </h4>
                            </header>
                            <dl className="p-3 space-y-1.5 text-xs">
                              <div className="flex justify-between gap-2">
                                <dt className="text-gray-500">Attempts</dt>
                                <dd className="text-gray-800 tabular-nums">
                                  {row.attempts}
                                </dd>
                              </div>
                              <div className="flex justify-between gap-2">
                                <dt className="text-gray-500">Created</dt>
                                <dd className="text-gray-800 text-right">
                                  {new Date(row.created_at).toLocaleString()}
                                </dd>
                              </div>
                              <div className="flex justify-between gap-2">
                                <dt className="text-gray-500">Updated</dt>
                                <dd className="text-gray-800 text-right">
                                  {new Date(row.updated_at).toLocaleString()}
                                </dd>
                              </div>
                            </dl>
                          </section>
                        </div>
                      </div>

                      {rawColumnEntries.length > 0 && (
                        <section className="bg-white border border-gray-200 rounded-lg shadow-sm">
                          <header className="px-3 py-2 border-b border-gray-100 flex items-center gap-1.5">
                            <FileText className="h-3.5 w-3.5 text-gray-400" />
                            <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
                              Imported columns
                            </h4>
                            <span className="ml-1 inline-flex items-center justify-center rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-600">
                              {rawColumnEntries.length}
                            </span>
                          </header>
                          <dl className="p-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 text-xs">
                            {rawColumnEntries.map(([key, value]) => (
                              <div
                                key={key}
                                className="bg-gray-50 border border-gray-200 rounded px-2.5 py-1.5"
                              >
                                <dt className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider truncate">
                                  {key}
                                </dt>
                                <dd className="text-gray-800 break-words mt-0.5 whitespace-pre-wrap">
                                  {value && value.trim() ? (
                                    value
                                  ) : (
                                    <span className="italic text-gray-400">empty</span>
                                  )}
                                </dd>
                              </div>
                            ))}
                          </dl>
                        </section>
                      )}
                    </div>
                  )}
                </div>
              )
            })}

            {rowTotalPages > 1 && (
              <div className="px-4 py-3 bg-gray-50 border border-gray-200 flex items-center justify-between mt-3 rounded-lg">
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
        <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Evaluations</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Click a run to view its results in detail. Use the Run Evaluation
              button at the top to start a new run.
            </p>
          </div>
          {selectedEvalIds.size > 0 && (
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
          )}
        </div>

        {(evaluationsData?.items?.length || 0) === 0 ? (
          <p className="text-sm text-gray-500">
            No evaluations have been run for this dataset yet.
          </p>
        ) : (
          <div className="space-y-2">
            {(() => {
              const items = evaluationsData?.items ?? []
              const allSelected =
                items.length > 0 &&
                items.every((row) => selectedEvalIds.has(row.id))
              return (
                <div className="flex items-center gap-2 px-3 py-2 border border-gray-200 rounded-lg bg-gray-50">
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
                  <span className="text-xs text-gray-600">
                    Select all ({items.length})
                  </span>
                </div>
              )
            })()}
            {evaluationsData?.items.map((evaluation: CallImportEvaluation) => {
              const isSelected = selectedEvalIds.has(evaluation.id)
              const headerLabel = evaluation.name?.trim()
                ? evaluation.name
                : `Evaluation ${evaluation.id.slice(0, 8)}`
              return (
                <div
                  key={evaluation.id}
                  className={`flex items-center gap-3 border rounded-lg px-3 py-2.5 bg-white transition ${
                    isSelected
                      ? 'border-primary-400 bg-primary-50/40'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
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
                  />
                  <Link
                    to={`/call-imports/${id}/evaluations/${evaluation.id}`}
                    className="flex-1 min-w-0 flex items-center justify-between gap-3"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">
                        {headerLabel}
                      </p>
                      <p className="text-xs text-gray-600 truncate">
                        {evaluation.metrics.map((metric) => metric.name).join(', ') ||
                          'No metrics'}
                      </p>
                      <p className="text-[11px] text-gray-400 mt-0.5">
                        Created {new Date(evaluation.created_at).toLocaleString()}
                      </p>
                    </div>
                    <div className="text-right flex-shrink-0">
                      <StatusBadge status={evaluation.status} size="sm" />
                      <p className="text-xs text-gray-500 mt-1">
                        {evaluation.completed_rows}/{evaluation.total_rows} rows
                      </p>
                    </div>
                  </Link>
                </div>
              )
            })}
          </div>
        )}
      </div>
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

                    <div>
                      <label
                        htmlFor="run-eval-name"
                        className="block text-xs font-medium text-gray-700 mb-1"
                      >
                        Name this run{' '}
                        <span className="text-gray-400 font-normal">(optional)</span>
                      </label>
                      <input
                        id="run-eval-name"
                        type="text"
                        value={runDraftName}
                        onChange={(e) => setRunDraftName(e.target.value)}
                        placeholder="e.g. March QA pass"
                        maxLength={255}
                        disabled={runEvaluationMutation.isPending}
                        className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent disabled:opacity-60"
                      />
                      <p className="mt-1 text-[11px] text-gray-500">
                        Leave blank to fall back to the run's UUID prefix.
                      </p>
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
                        onClick={() =>
                          runEvaluationMutation.mutate({
                            metric_ids: selectedMetricIds,
                            name: runDraftName.trim() || null,
                          })
                        }
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
        isOpen={showBulkDeleteEvals}
        title={
          selectedEvalIds.size === 1
            ? 'Delete this evaluation run?'
            : `Delete ${selectedEvalIds.size} evaluation runs?`
        }
        description={(() => {
          const lines = [
            selectedEvalIds.size === 1
              ? 'This run and all of its per-row score records will be permanently removed.'
              : `These ${selectedEvalIds.size} runs and all of their per-row score records will be permanently removed.`,
            'In-flight runs will have their pending tasks revoked before deletion.',
            'The underlying CSV import stays intact, so you can re-run later.',
            'This cannot be undone.',
            bulkDeleteEvalsError ? `Error: ${bulkDeleteEvalsError}` : '',
          ]
          return lines.filter(Boolean).join('\n\n')
        })()}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        isLoading={bulkDeleteEvalsMutation.isPending}
        onConfirm={() => {
          bulkDeleteEvalsMutation.mutate(Array.from(selectedEvalIds))
        }}
        onCancel={() => {
          if (bulkDeleteEvalsMutation.isPending) return
          setShowBulkDeleteEvals(false)
          setBulkDeleteEvalsError(null)
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

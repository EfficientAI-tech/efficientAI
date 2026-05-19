import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  AudioLines,
  BarChart3,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  Edit3,
  FileText,
  ListTree,
  Mic,
  MessageSquare,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Volume2,
  X,
  XCircle,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { apiClient } from '../../lib/api'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type {
  CallImportEvaluation,
  CallImportEvaluationLLMOverride,
  CallImportRow,
  CallImportTag,
} from '../../types/api'
import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import StatusBadge from '../../components/shared/StatusBadge'
import ProviderModelPicker, {
  type ProviderModelValue,
} from '../../components/providers/ProviderModelPicker'
import CallImportProgressBar from './components/CallImportProgressBar'
import TranscriptView from './components/TranscriptView'

// Providers we know `TranscriptionService.transcribe()` already supports
// for the full diarization-enabled path. Local Whisper is omitted since
// it's an unconditional fallback inside the service rather than
// something the user explicitly picks.
const STT_PROVIDER_ALLOWLIST = [
  'deepgram',
  'openai',
  'elevenlabs',
  'sarvam',
  'smallest',
]

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
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const [rowOffset, setRowOffset] = useState(0)
  const [expandedRowIds, setExpandedRowIds] = useState<Set<string>>(new Set())
  // Row search: debounce keystrokes so we don't refire the rows fetch on
  // every character — the backend filters by external_call_id ILIKE %q%
  // and reports the post-filter total in ``filtered_total_rows``.
  const [rowSearchInput, setRowSearchInput] = useState('')
  const [rowSearchQuery, setRowSearchQuery] = useState('')
  // Multi-select state for the row list — drives the bulk-action
  // toolbar (delete / transcribe). The header checkbox toggles every
  // row currently visible on the page; selection is intentionally
  // scoped to the current page so cross-page operations stay explicit.
  const [selectedRowIds, setSelectedRowIds] = useState<Set<string>>(new Set())
  const [showBulkDeleteRows, setShowBulkDeleteRows] = useState(false)
  const [bulkDeleteRowsError, setBulkDeleteRowsError] = useState<string | null>(
    null,
  )

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
  // Run-level LLM picker for the eval modal. Empty provider keeps the
  // legacy OpenAI/gpt-4o default; any non-empty provider+model becomes
  // the new run-level default that propagates to every selected metric
  // unless overridden in the Advanced section.
  const [runLLM, setRunLLM] = useState<ProviderModelValue>({
    provider: null,
    model: null,
    credential_id: null,
  })
  // Per-metric LLM overrides keyed by metric id. Only metrics with a
  // non-null provider+model end up in the request payload; everything
  // else inherits the run-level default.
  const [metricLLMOverrides, setMetricLLMOverrides] = useState<
    Record<string, ProviderModelValue>
  >({})
  const [showAdvancedLLM, setShowAdvancedLLM] = useState(false)
  // Auto-transcribe toggles for the eval modal: when on, the backend
  // chains a transcribe -> evaluate per row so the user doesn't have
  // to run two flows back-to-back when the CSV is missing transcripts.
  const [autoTranscribe, setAutoTranscribe] = useState(false)
  const [transcribeOverwrite, setTranscribeOverwrite] = useState(false)
  // Which transcript(s) to score against. Ticking both creates two
  // evaluation runs (one per source) so the user can compare scores
  // side-by-side. At least one must stay checked.
  const [evalUseProduction, setEvalUseProduction] = useState(true)
  const [evalUseDiarised, setEvalUseDiarised] = useState(false)
  const [evalSTT, setEvalSTT] = useState<ProviderModelValue>({
    provider: null,
    model: null,
    credential_id: null,
  })
  const [evalSTTLanguage, setEvalSTTLanguage] = useState('')
  const [activeTab, setActiveTab] = useState<
    'rows' | 'evaluations' | 'insights'
  >('rows')
  const [selectedEvalIds, setSelectedEvalIds] = useState<Set<string>>(new Set())
  const [showBulkDeleteEvals, setShowBulkDeleteEvals] = useState(false)
  const [bulkDeleteEvalsError, setBulkDeleteEvalsError] = useState<string | null>(null)
  // Standalone "Transcribe row" modal (separate from the eval flow).
  const [showTranscribeModal, setShowTranscribeModal] = useState(false)
  const [transcribeTargetRows, setTranscribeTargetRows] = useState<
    CallImportRow[] | null
  >(null)
  const [transcribeSTT, setTranscribeSTT] = useState<ProviderModelValue>({
    provider: null,
    model: null,
    credential_id: null,
  })
  const [transcribeOverwriteStandalone, setTranscribeOverwriteStandalone] =
    useState(false)
  const [transcribeLanguage, setTranscribeLanguage] = useState('')
  const [transcribeError, setTranscribeError] = useState<string | null>(null)

  const [editingMeta, setEditingMeta] = useState(false)
  const [draftDataset, setDraftDataset] = useState('')
  const [draftTagIds, setDraftTagIds] = useState<string[]>([])

  const { data: existingDatasets = [] } = useQuery({
    queryKey: ['call-import-datasets', activeWorkspaceId],
    queryFn: () => apiClient.listCallImportDatasets(),
    enabled: editingMeta,
  })

  const { data: allTags = [] } = useQuery({
    queryKey: ['call-import-tags', activeWorkspaceId],
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

  const bulkDeleteRowsMutation = useMutation({
    mutationFn: (rowIds: string[]) =>
      apiClient.bulkDeleteCallImportRows(id!, rowIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-import', id] })
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      setSelectedRowIds(new Set())
      setShowBulkDeleteRows(false)
      setBulkDeleteRowsError(null)
    },
    onError: (err: any) => {
      setBulkDeleteRowsError(
        err?.response?.data?.detail ||
          err?.message ||
          'Failed to delete selected rows.',
      )
    },
  })

  // Debounce the row-search input so we don't requery on every keystroke.
  useEffect(() => {
    const handle = setTimeout(() => {
      setRowSearchQuery(rowSearchInput.trim())
    }, 250)
    return () => clearTimeout(handle)
  }, [rowSearchInput])

  // Snap back to the first page whenever the active query changes —
  // otherwise the user could be sitting on page 3 of a filtered set
  // that only has one page of results.
  useEffect(() => {
    setRowOffset(0)
  }, [rowSearchQuery])

  // Clear any active row selection when the visible slice changes
  // (search / pagination). Selection is scoped to the current page so
  // keeping stale ids around just leads to confusing "X selected"
  // counters that don't match what's on screen.
  useEffect(() => {
    setSelectedRowIds(new Set())
  }, [rowSearchQuery, rowOffset])

  const queryParams = useMemo(
    () => ({
      row_limit: ROW_PAGE_SIZE,
      row_offset: rowOffset,
      q: rowSearchQuery || undefined,
    }),
    [rowOffset, rowSearchQuery],
  )

  const { data, isLoading, isFetching, refetch, error } = useQuery({
    queryKey: ['call-import', id, queryParams],
    queryFn: () => apiClient.getCallImport(id!, queryParams),
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      // Keep polling while the CSV import itself is in flight, or
      // while any row has an active (pending/running) transcription —
      // otherwise the user has to manually refresh to see whether
      // the transcribe worker finished or failed.
      if (status === 'pending' || status === 'processing') return 5000
      const rows = query.state.data?.rows ?? []
      const hasActiveTranscript = rows.some(
        (r: {
          transcript_status?: string | null
          diarised_transcript_status?: string | null
        }) =>
          r.transcript_status === 'pending' ||
          r.transcript_status === 'running' ||
          r.diarised_transcript_status === 'pending' ||
          r.diarised_transcript_status === 'running',
      )
      return hasActiveTranscript ? 4000 : false
    },
  })

  const { data: metrics = [] } = useQuery({
    queryKey: ['metrics', activeWorkspaceId, 'agent'],
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

  // Insights tab: fetched lazily so we don't pay for the cross-run
  // aggregation on first page load. Refetches on a 30s cadence while
  // any evaluation is still running so the trend chart fills in as
  // data arrives.
  const { data: insightsData, isLoading: insightsLoading } = useQuery({
    queryKey: ['call-import-insights', id],
    queryFn: () => apiClient.getCallImportInsights(id!),
    enabled: !!id && activeTab === 'insights',
    refetchInterval: () => {
      const rows = evaluationsData?.items || []
      return rows.some(
        (row) => row.status === 'pending' || row.status === 'running',
      )
        ? 15000
        : false
    },
  })

  const runEvaluationMutation = useMutation({
    mutationFn: (payload: Parameters<typeof apiClient.createCallImportEvaluation>[1]) =>
      apiClient.createCallImportEvaluation(id!, payload),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['call-import-evaluations', id] })
      queryClient.invalidateQueries({ queryKey: ['call-import', id] })
      setShowRunEval(false)
      setSelectedMetricIds([])
      setRunDraftName('')
      setRunLLM({ provider: null, model: null, credential_id: null })
      setMetricLLMOverrides({})
      setShowAdvancedLLM(false)
      setAutoTranscribe(false)
      setTranscribeOverwrite(false)
      setEvalUseProduction(true)
      setEvalUseDiarised(false)
      setEvalSTT({ provider: null, model: null, credential_id: null })
      setEvalSTTLanguage('')
      setActiveTab('evaluations')
      // When the user picked both Production and Diarised the backend
      // creates two runs and returns the primary one; the second eval
      // id is in ``sibling_evaluation_ids``. Drop the user on the
      // evaluations tab so both runs are visible side-by-side instead
      // of deep-linking into just one.
      const siblings = created.sibling_evaluation_ids ?? []
      if (siblings.length > 0) {
        return
      }
      // Land directly on the dedicated detail page for the new run.
      navigate(`/call-imports/${id}/evaluations/${created.id}`)
    },
  })

  const transcribeRowsMutation = useMutation({
    mutationFn: ({
      rowIds,
      stt,
      language,
      overwrite,
    }: {
      rowIds: string[] | null
      stt: ProviderModelValue
      language: string
      overwrite: boolean
    }) => {
      const trimmedLang = language.trim() || null
      // Single-row endpoint vs batch endpoint: prefer the single-row
      // endpoint when the modal targets exactly one row so the API
      // surface stays self-documenting.
      if (rowIds && rowIds.length === 1) {
        return apiClient.transcribeCallImportRow(id!, rowIds[0], {
          stt_provider: stt.provider as string,
          stt_model: stt.model as string,
          credential_id: stt.credential_id ?? null,
          language: trimmedLang,
          only_missing: !overwrite,
          overwrite_existing: overwrite,
        })
      }
      return apiClient.transcribeCallImport(id!, {
        stt_provider: stt.provider as string,
        stt_model: stt.model as string,
        credential_id: stt.credential_id ?? null,
        language: trimmedLang,
        only_missing: !overwrite,
        overwrite_existing: overwrite,
        row_ids: rowIds ?? undefined,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-import', id] })
      setShowTranscribeModal(false)
      setTranscribeTargetRows(null)
      setTranscribeError(null)
      // Drop the bulk selection too — those rows are now in-flight so
      // keeping them "selected" would invite repeat clicks while the
      // transcribe worker is still doing its first pass.
      setSelectedRowIds(new Set())
    },
    onError: (err: any) => {
      setTranscribeError(
        err?.response?.data?.detail || err?.message || 'Failed to enqueue transcription.',
      )
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
  // ``filtered_total_rows`` is only set when ``q`` is on; pagination
  // should always page against whatever slice the user is actually
  // looking at (filtered or otherwise).
  const filteredTotalRows = rowSearchQuery
    ? data?.filtered_total_rows ?? 0
    : totalRows
  const rowPage = Math.floor(rowOffset / ROW_PAGE_SIZE) + 1
  const rowTotalPages = Math.max(1, Math.ceil(filteredTotalRows / ROW_PAGE_SIZE))

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

  // Toggle a parent metric in the 2-level picker. Selecting a parent
  // implicitly selects all of its enabled children (the backend
  // re-expands a bare parent id to its children, but we mirror that
  // here so the per-metric override UI surfaces the right rows). When
  // the parent has no children we treat it like a regular leaf toggle.
  const toggleParentMetric = (parent: any) => {
    const childIds: string[] = Array.isArray(parent.children)
      ? parent.children.filter((c: any) => c.enabled).map((c: any) => c.id)
      : []
    setSelectedMetricIds((prev) => {
      const set = new Set(prev)
      const parentSelected = set.has(parent.id)
      const someChildren = childIds.some((cid) => set.has(cid))
      if (parentSelected || someChildren) {
        set.delete(parent.id)
        for (const cid of childIds) set.delete(cid)
      } else {
        set.add(parent.id)
        for (const cid of childIds) set.add(cid)
      }
      return Array.from(set)
    })
  }

  // Toggle one child while keeping the parent reference in sync: if a
  // child is the only remaining selected member of its group we drop
  // the parent id; if every child is selected we add the parent id so
  // the run modal can show a single chip for the whole group.
  const toggleChildMetric = (parent: any, childId: string) => {
    const childIds: string[] = Array.isArray(parent.children)
      ? parent.children.filter((c: any) => c.enabled).map((c: any) => c.id)
      : []
    setSelectedMetricIds((prev) => {
      const set = new Set(prev)
      if (set.has(childId)) {
        set.delete(childId)
      } else {
        set.add(childId)
      }
      const allSelected =
        childIds.length > 0 && childIds.every((cid) => set.has(cid))
      if (allSelected) {
        set.add(parent.id)
      } else {
        set.delete(parent.id)
      }
      return Array.from(set)
    })
  }

  const openTranscribeModal = (rows: CallImportRow[]) => {
    setTranscribeTargetRows(rows)
    setTranscribeError(null)
    setTranscribeOverwriteStandalone(false)
    // Default to deepgram/nova-2 since it's the most common diarization
    // setup; the user can change it before submitting.
    if (!transcribeSTT.provider) {
      setTranscribeSTT({
        provider: 'deepgram',
        model: 'nova-2',
        credential_id: null,
      })
    }
    setShowTranscribeModal(true)
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

  // Selection state derived from the current page's row list. We
  // intentionally scope selection to the current page so a "Select all"
  // tick on screen always matches the rows the user can see.
  const selectedOnPage = rows.filter((r) => selectedRowIds.has(r.id))
  const selectedCount = selectedOnPage.length
  const allOnPageSelected = rows.length > 0 && selectedCount === rows.length
  const transcribeReadySelection = selectedOnPage.filter(
    (r) =>
      !!r.recording_s3_key &&
      r.diarised_transcript_status !== 'pending' &&
      r.diarised_transcript_status !== 'running',
  )

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
          <button
            type="button"
            onClick={() => setActiveTab('insights')}
            className={`whitespace-nowrap py-3 px-1 border-b-2 text-sm font-medium transition ${
              activeTab === 'insights'
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
            aria-current={activeTab === 'insights' ? 'page' : undefined}
          >
            <BarChart3 className="h-3.5 w-3.5 inline mr-1 -mt-0.5" />
            Insights
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
              {rowOffset + rows.length} of {filteredTotalRows}
              {rowSearchQuery ? ` (filtered from ${totalRows})` : ''}
            </p>
          </div>
        </div>

        <div className="mb-4 flex items-stretch gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[260px] max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
            <input
              type="text"
              value={rowSearchInput}
              onChange={(e) => setRowSearchInput(e.target.value)}
              placeholder="Search by Call ID…"
              aria-label="Search rows by Call ID"
              className="w-full pl-9 pr-9 py-2 text-sm border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-500"
            />
            {rowSearchInput && (
              <button
                type="button"
                onClick={() => setRowSearchInput('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100"
                aria-label="Clear search"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          {selectedCount > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs text-gray-600">
                {selectedCount} selected
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSelectedRowIds(new Set())}
              >
                Clear
              </Button>
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<Mic className="h-4 w-4" />}
                disabled={transcribeReadySelection.length === 0}
                title={
                  transcribeReadySelection.length === 0
                    ? 'Selected rows have no downloaded recording or are already transcribing'
                    : `Transcribe ${transcribeReadySelection.length} row${
                        transcribeReadySelection.length === 1 ? '' : 's'
                      }`
                }
                onClick={() => openTranscribeModal(transcribeReadySelection)}
                className="text-purple-600 hover:text-purple-700 hover:bg-purple-50"
              >
                Transcribe selected
              </Button>
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<Trash2 className="h-4 w-4" />}
                onClick={() => {
                  setBulkDeleteRowsError(null)
                  setShowBulkDeleteRows(true)
                }}
                className="text-red-600 hover:text-red-700 hover:bg-red-50"
              >
                Delete selected
              </Button>
            </div>
          )}
        </div>

        {rows.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            <FileText className="h-12 w-12 mx-auto mb-3 text-gray-300" />
            {rowSearchQuery ? (
              <p>
                No rows match{' '}
                <span className="font-mono text-gray-700">
                  &quot;{rowSearchQuery}&quot;
                </span>
                .
              </p>
            ) : (
              <p>No rows in this slice.</p>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            <div className="flex items-center gap-2 px-3 py-2 border border-gray-200 rounded-lg bg-gray-50">
              <input
                type="checkbox"
                aria-label="Select all rows on this page"
                checked={allOnPageSelected}
                ref={(el) => {
                  if (el) el.indeterminate = selectedCount > 0 && !allOnPageSelected
                }}
                onChange={(e) => {
                  if (e.target.checked) {
                    setSelectedRowIds(new Set(rows.map((r) => r.id)))
                  } else {
                    setSelectedRowIds(new Set())
                  }
                }}
              />
              <span className="text-xs text-gray-600">
                {allOnPageSelected
                  ? `All ${rows.length} on this page selected`
                  : selectedCount > 0
                  ? `${selectedCount} of ${rows.length} on this page selected`
                  : `Select all on this page (${rows.length})`}
              </span>
            </div>
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
              const isSelected = selectedRowIds.has(row.id)
              return (
                <div
                  key={row.id}
                  className={`border rounded-lg bg-white overflow-hidden transition-shadow hover:shadow-sm ${
                    isSelected
                      ? 'border-primary-400 bg-primary-50/30'
                      : 'border-gray-200'
                  }`}
                >
                  <div className="flex items-center gap-2 px-3 py-2.5">
                    <input
                      type="checkbox"
                      aria-label={`Select row ${row.external_call_id}`}
                      checked={isSelected}
                      onChange={(e) => {
                        setSelectedRowIds((prev) => {
                          const next = new Set(prev)
                          if (e.target.checked) next.add(row.id)
                          else next.delete(row.id)
                          return next
                        })
                      }}
                      onClick={(e) => e.stopPropagation()}
                    />
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
                          <button
                            type="button"
                            onClick={() => openTranscribeModal([row])}
                            disabled={
                              row.diarised_transcript_status === 'pending' ||
                              row.diarised_transcript_status === 'running'
                            }
                            title={
                              row.diarised_transcript_status === 'pending' ||
                              row.diarised_transcript_status === 'running'
                                ? 'Diarisation in progress'
                                : 'Diarise this row'
                            }
                            className="p-1.5 rounded text-gray-500 hover:text-purple-600 hover:bg-purple-50 transition-colors disabled:opacity-40"
                          >
                            {row.diarised_transcript_status === 'pending' ||
                            row.diarised_transcript_status === 'running' ? (
                              <RefreshCw className="h-4 w-4 animate-spin" />
                            ) : (
                              <Mic className="h-4 w-4" />
                            )}
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
                        <section className="lg:col-span-3 min-w-0 space-y-3">
                          {/* Production transcript (from CSV upload). */}
                          <div className="bg-white border border-gray-200 rounded-lg shadow-sm">
                            <header className="px-3 py-2 border-b border-gray-100 flex items-center justify-between gap-2">
                              <div className="flex items-center gap-1.5 min-w-0">
                                <MessageSquare className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
                                <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
                                  Production Transcript
                                </h4>
                                {row.transcript ? (
                                  <span className="ml-1 inline-flex items-center rounded-full bg-gray-100 text-gray-700 px-2 py-0.5 text-[10px] font-medium">
                                    From CSV
                                  </span>
                                ) : (
                                  <span className="ml-1 inline-flex items-center rounded-full bg-gray-50 text-gray-500 px-2 py-0.5 text-[10px] font-medium">
                                    Not provided
                                  </span>
                                )}
                              </div>
                            </header>
                            <div className="p-3">
                              {row.transcript ? (
                                <TranscriptView
                                  transcript={row.transcript}
                                  compact
                                />
                              ) : (
                                <p className="text-xs text-gray-500 italic">
                                  No production transcript was uploaded for
                                  this row. Map a CSV column to "Transcript"
                                  next time, or run diarisation below.
                                </p>
                              )}
                            </div>
                          </div>

                          {/* Diarised transcript (from the diarisation worker). */}
                          <div className="bg-white border border-gray-200 rounded-lg shadow-sm">
                            <header className="px-3 py-2 border-b border-gray-100 flex items-center justify-between gap-2">
                              <div className="flex items-center gap-1.5 min-w-0">
                                <AudioLines className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
                                <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
                                  Diarised Transcript
                                </h4>
                                {row.diarised_transcript && (
                                  <span className="ml-1 inline-flex items-center gap-1 rounded-full bg-purple-50 text-purple-700 px-2 py-0.5 text-[10px] font-medium">
                                    <AudioLines className="h-3 w-3" />
                                    Diarised
                                    {row.diarised_transcript_provider && (
                                      <span className="font-mono">
                                        · {row.diarised_transcript_provider}
                                        {row.diarised_transcript_model
                                          ? `/${row.diarised_transcript_model}`
                                          : ''}
                                      </span>
                                    )}
                                  </span>
                                )}
                                {(row.diarised_transcript_status ===
                                  'pending' ||
                                  row.diarised_transcript_status ===
                                    'running') && (
                                  <span className="ml-1 inline-flex items-center gap-1 rounded-full bg-blue-50 text-blue-700 px-2 py-0.5 text-[10px] font-medium">
                                    <RefreshCw className="h-3 w-3 animate-spin" />
                                    Diarising…
                                  </span>
                                )}
                                {row.diarised_transcript_status ===
                                  'failed' && (
                                  <span
                                    className="ml-1 inline-flex items-center gap-1 rounded-full bg-red-50 text-red-700 px-2 py-0.5 text-[10px] font-medium"
                                    title={
                                      row.diarised_transcript_error || ''
                                    }
                                  >
                                    <AlertCircle className="h-3 w-3" />
                                    Diarisation failed
                                  </span>
                                )}
                              </div>
                              {hasRecording && (
                                <button
                                  type="button"
                                  onClick={() => openTranscribeModal([row])}
                                  disabled={
                                    row.diarised_transcript_status ===
                                      'pending' ||
                                    row.diarised_transcript_status ===
                                      'running'
                                  }
                                  className="text-[11px] font-medium text-purple-700 hover:text-purple-900 disabled:opacity-50"
                                >
                                  {row.diarised_transcript
                                    ? 'Re-diarise'
                                    : 'Diarise'}
                                </button>
                              )}
                            </header>
                            {row.diarised_transcript_status === 'failed' &&
                              row.diarised_transcript_error && (
                                <div className="border-b border-red-100 bg-red-50 px-3 py-2 text-xs text-red-800 flex items-start gap-2">
                                  <AlertCircle className="h-3.5 w-3.5 text-red-600 flex-shrink-0 mt-0.5" />
                                  <div className="min-w-0 flex-1 break-words">
                                    <span className="font-medium">
                                      Diarisation failed:
                                    </span>{' '}
                                    {row.diarised_transcript_error}
                                    {row.diarised_transcript_provider && (
                                      <span className="ml-1 text-[10px] text-red-700/80 font-mono">
                                        ({row.diarised_transcript_provider}
                                        {row.diarised_transcript_model
                                          ? `/${row.diarised_transcript_model}`
                                          : ''}
                                        )
                                      </span>
                                    )}
                                  </div>
                                </div>
                              )}
                            <div className="p-3">
                              {row.diarised_transcript ? (
                                <TranscriptView
                                  transcript={row.diarised_transcript}
                                  compact
                                />
                              ) : (
                                <p className="text-xs text-gray-500 italic">
                                  {hasRecording
                                    ? 'No diarised transcript yet. Click Diarise to run STT on this recording.'
                                    : 'No recording available for this row, so diarisation cannot run.'}
                                </p>
                              )}
                            </div>
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
                            <button
                              type="button"
                              onClick={() => {
                                // Hand the column header names to the
                                // metric editor through router state.
                                // The user can prune unwanted ones in
                                // the resulting modal before saving.
                                navigate('/metrics-management', {
                                  state: {
                                    prefillInputColumns: rawColumnEntries.map(
                                      ([key]) => key,
                                    ),
                                  },
                                })
                              }}
                              className="ml-auto inline-flex items-center gap-1 text-[11px] font-medium text-primary-700 hover:text-primary-900"
                              title="Open the metric editor with these column headers pre-filled. The next evaluation run will judge those columns and add a new column to the results."
                            >
                              <Plus className="h-3 w-3" />
                              Create metric from columns
                            </button>
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
                        o + ROW_PAGE_SIZE >= filteredTotalRows ? o : o + ROW_PAGE_SIZE,
                      )
                    }
                    disabled={rowOffset + ROW_PAGE_SIZE >= filteredTotalRows}
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

      {activeTab === 'insights' && (
        <div className="bg-white shadow rounded-lg p-6 space-y-6">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Insights</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Cross-run signals for this call import. Trend lines show the
              mean of each metric across every evaluation; transcript
              coverage helps you spot rows that still need diarization.
            </p>
          </div>

          {insightsLoading || !insightsData ? (
            <div className="text-center py-12 text-gray-500">
              <RefreshCw className="h-6 w-6 mx-auto mb-2 animate-spin" />
              <p>Loading insights…</p>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="border border-gray-200 rounded-lg px-3 py-2">
                  <p className="text-[11px] text-gray-500 uppercase tracking-wide">
                    Total rows
                  </p>
                  <p className="text-2xl font-semibold text-gray-900">
                    {insightsData.total_rows}
                  </p>
                </div>
                <div className="border border-gray-200 rounded-lg px-3 py-2">
                  <p className="text-[11px] text-gray-500 uppercase tracking-wide">
                    With transcript
                  </p>
                  <p className="text-2xl font-semibold text-gray-900">
                    {insightsData.rows_with_transcript}
                  </p>
                </div>
                <div className="border border-gray-200 rounded-lg px-3 py-2">
                  <p className="text-[11px] text-gray-500 uppercase tracking-wide">
                    Missing transcript
                  </p>
                  <p className="text-2xl font-semibold text-gray-900">
                    {insightsData.rows_without_transcript}
                  </p>
                </div>
                <div className="border border-gray-200 rounded-lg px-3 py-2">
                  <p className="text-[11px] text-gray-500 uppercase tracking-wide">
                    Eval runs
                  </p>
                  <p className="text-2xl font-semibold text-gray-900">
                    {insightsData.evaluation_count}
                  </p>
                </div>
              </div>

              {Object.keys(insightsData.transcript_source_counts).length >
                0 && (
                <div>
                  <h3 className="text-sm font-semibold text-gray-800 mb-2">
                    Transcript source mix
                  </h3>
                  <div className="flex gap-2 flex-wrap">
                    {Object.entries(
                      insightsData.transcript_source_counts,
                    ).map(([source, count]) => (
                      <span
                        key={source}
                        className="inline-flex items-center gap-1 rounded-full bg-gray-100 text-gray-800 px-3 py-1 text-xs"
                      >
                        <span className="font-medium capitalize">{source}</span>
                        <span className="tabular-nums">· {count}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {insightsData.metrics.length === 0 ? (
                <p className="text-sm text-gray-500">
                  Run at least one evaluation to populate metric trends.
                </p>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {insightsData.metrics.map((m) => {
                    const trend = m.trend
                      .filter((p) => p.mean !== null)
                      .map((p) => ({
                        x: new Date(p.created_at).toLocaleDateString(),
                        mean: p.mean as number,
                        name: p.name,
                      }))
                    const latest = m.latest
                    return (
                      <div
                        key={m.metric_id}
                        className="border border-gray-200 rounded-lg p-3 space-y-2"
                      >
                        <div className="flex items-center justify-between">
                          <p className="text-sm font-medium text-gray-900">
                            {m.metric_name}
                          </p>
                          {latest?.mean != null && (
                            <span className="text-sm font-semibold text-primary-700 tabular-nums">
                              μ {latest.mean.toFixed(2)}
                            </span>
                          )}
                        </div>
                        {trend.length > 1 ? (
                          <ResponsiveContainer width="100%" height={120}>
                            <LineChart data={trend}>
                              <CartesianGrid strokeDasharray="3 3" />
                              <XAxis dataKey="x" tick={{ fontSize: 10 }} />
                              <YAxis tick={{ fontSize: 10 }} />
                              <Tooltip />
                              <Line
                                type="monotone"
                                dataKey="mean"
                                strokeWidth={2}
                                stroke="#6366f1"
                                dot={{ r: 3 }}
                              />
                            </LineChart>
                          </ResponsiveContainer>
                        ) : latest && latest.value_counts.length ? (
                          <ResponsiveContainer width="100%" height={120}>
                            <BarChart data={latest.value_counts}>
                              <CartesianGrid strokeDasharray="3 3" />
                              <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                              <YAxis tick={{ fontSize: 10 }} />
                              <Tooltip />
                              <Bar dataKey="count" fill="#10b981" />
                            </BarChart>
                          </ResponsiveContainer>
                        ) : (
                          <p className="text-xs text-gray-400 italic">
                            Need at least two runs to plot a trend.
                          </p>
                        )}
                        {latest && (
                          <div className="grid grid-cols-3 text-[11px] text-gray-500 gap-1">
                            <span>n={latest.count}</span>
                            <span>p50={latest.median?.toFixed(2) ?? '—'}</span>
                            <span>p95={latest.p95?.toFixed(2) ?? '—'}</span>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {showTranscribeModal &&
        renderModal(
          (() => {
            const targets = transcribeTargetRows ?? []
            const headerLabel =
              targets.length === 1
                ? `Transcribe row #${(targets[0]?.row_index ?? 0) + 1}`
                : `Transcribe ${targets.length} rows`
            const canSubmit =
              !!transcribeSTT.provider &&
              !!transcribeSTT.model &&
              targets.length > 0 &&
              !transcribeRowsMutation.isPending
            return (
              <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
                <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
                  <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                    <h3 className="text-lg font-semibold">{headerLabel}</h3>
                    <button
                      onClick={() => {
                        if (transcribeRowsMutation.isPending) return
                        setShowTranscribeModal(false)
                        setTranscribeTargetRows(null)
                      }}
                      className="text-gray-400 hover:text-gray-600"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>
                  <div className="p-6 space-y-3">
                    <p className="text-sm text-gray-600">
                      Pick the STT provider and model. Diarization is enabled
                      automatically — the transcript is stored in
                      <code className="mx-1 px-1 bg-gray-100 rounded text-[11px]">
                        Speaker N:
                      </code>
                      format that the conversation viewer renders as bubbles.
                    </p>
                    <ProviderModelPicker
                      kind="stt"
                      value={transcribeSTT}
                      onChange={setTranscribeSTT}
                      providerAllowList={STT_PROVIDER_ALLOWLIST}
                      defaultLabel="Pick an STT provider"
                      allowCredentialPick
                    />
                    <input
                      type="text"
                      value={transcribeLanguage}
                      onChange={(e) => setTranscribeLanguage(e.target.value)}
                      placeholder="Language hint (e.g. en, hi)"
                      className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                    />
                    <label className="flex items-start gap-2 text-xs">
                      <input
                        type="checkbox"
                        checked={transcribeOverwriteStandalone}
                        onChange={(e) =>
                          setTranscribeOverwriteStandalone(e.target.checked)
                        }
                      />
                      <span>
                        Overwrite existing transcripts (otherwise rows with
                        a transcript are skipped).
                      </span>
                    </label>
                    {transcribeError && (
                      <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                        {transcribeError}
                      </div>
                    )}
                    <div className="flex gap-2 pt-2">
                      <Button
                        variant="outline"
                        onClick={() => {
                          if (transcribeRowsMutation.isPending) return
                          setShowTranscribeModal(false)
                          setTranscribeTargetRows(null)
                        }}
                        disabled={transcribeRowsMutation.isPending}
                        className="flex-1"
                      >
                        Cancel
                      </Button>
                      <Button
                        variant="primary"
                        isLoading={transcribeRowsMutation.isPending}
                        disabled={!canSubmit}
                        onClick={() =>
                          transcribeRowsMutation.mutate({
                            rowIds: targets.map((r) => r.id),
                            stt: transcribeSTT,
                            language: transcribeLanguage,
                            overwrite: transcribeOverwriteStandalone,
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
                <div className="bg-white rounded-lg shadow-xl max-w-5xl w-full mx-4">
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
                  <div className="p-6 space-y-4 max-h-[80vh] overflow-y-auto">
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-sm text-gray-600">
                        Pick the metrics to run against every completed row in this batch.
                      </p>
                      <Link
                        to="/metrics-management"
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
                          to="/metrics-management"
                          className="inline-block font-medium text-amber-900 underline hover:text-amber-700"
                        >
                          Open Metrics →
                        </Link>
                      </div>
                    ) : (
                      <>
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
                        <div className="space-y-3">
                        <div className="space-y-2">
                          <p className="text-xs uppercase tracking-wide font-semibold text-gray-500">
                            Enabled metrics ({enabledMetrics.length})
                          </p>
                          {enabledMetrics.map((metric: any) => {
                            const children: any[] = Array.isArray(metric.children)
                              ? metric.children.filter((c: any) => c.enabled)
                              : []
                            const isParent =
                              !!metric.selection_mode && children.length > 0
                            if (!isParent) {
                              return (
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
                              )
                            }
                            const childIds = children.map((c) => c.id)
                            const selectedChildCount = childIds.filter((cid) =>
                              selectedMetricIds.includes(cid),
                            ).length
                            const allSelected =
                              selectedChildCount === childIds.length &&
                              childIds.length > 0
                            const someSelected =
                              selectedChildCount > 0 && !allSelected
                            return (
                              <div
                                key={metric.id}
                                className="rounded-md border border-gray-200 bg-gray-50 p-2 space-y-1"
                              >
                                <label className="flex items-start gap-2 text-sm cursor-pointer">
                                  <input
                                    type="checkbox"
                                    ref={(el) => {
                                      if (el) el.indeterminate = someSelected
                                    }}
                                    checked={allSelected}
                                    onChange={() => toggleParentMetric(metric)}
                                    className="mt-1"
                                  />
                                  <span className="flex-1">
                                    <span className="font-medium text-gray-900">
                                      {metric.name}
                                    </span>
                                    <span className="ml-2 inline-flex items-center rounded-full bg-primary-100 px-2 py-0.5 text-[10px] font-medium text-primary-700">
                                      {metric.selection_mode === 'single_choice'
                                        ? 'pick one'
                                        : 'multi-label'}
                                    </span>
                                    <span className="ml-2 text-[11px] text-gray-500">
                                      {selectedChildCount}/{childIds.length} selected
                                    </span>
                                    {metric.description ? (
                                      <span className="block text-xs text-gray-500">
                                        {metric.description}
                                      </span>
                                    ) : null}
                                  </span>
                                </label>
                                <div className="ml-6 space-y-1 border-l border-gray-200 pl-3">
                                  {children.map((child: any) => (
                                    <label
                                      key={child.id}
                                      className="flex items-start gap-2 text-xs cursor-pointer"
                                    >
                                      <input
                                        type="checkbox"
                                        checked={selectedMetricIds.includes(child.id)}
                                        onChange={() =>
                                          toggleChildMetric(metric, child.id)
                                        }
                                        className="mt-0.5"
                                      />
                                      <span>
                                        <span className="font-medium text-gray-800">
                                          {child.name}
                                        </span>
                                        {child.description ? (
                                          <span className="block text-[11px] text-gray-500">
                                            {child.description}
                                          </span>
                                        ) : null}
                                      </span>
                                    </label>
                                  ))}
                                </div>
                              </div>
                            )
                          })}
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
                              to="/metrics-management"
                              className="mt-2 inline-block text-xs font-medium text-primary-700 hover:text-primary-900"
                            >
                              Enable them in Metrics →
                            </Link>
                          </details>
                        )}
                        </div>

                        <div className="space-y-3">
                        {/* Run-level LLM config */}
                        <div className="rounded-md border border-gray-200 bg-gray-50 p-3 space-y-2">
                          <p className="text-xs uppercase tracking-wide font-semibold text-gray-500">
                            Evaluation LLM
                          </p>
                          <p className="text-[11px] text-gray-500">
                            Pick the LLM that scores every selected metric.
                            Leave empty to keep the default (OpenAI · gpt-4o).
                          </p>
                          <ProviderModelPicker
                            kind="llm"
                            value={runLLM}
                            onChange={setRunLLM}
                            defaultLabel="Default (OpenAI · gpt-4o)"
                            allowCredentialPick
                          />

                          {selectedMetricIds.length > 0 && (
                            <div className="pt-2 border-t border-gray-200">
                              <button
                                type="button"
                                onClick={() => setShowAdvancedLLM((s) => !s)}
                                className="text-[11px] font-medium text-primary-700 hover:text-primary-900"
                              >
                                {showAdvancedLLM ? 'Hide' : 'Show'} per-metric overrides
                                ({selectedMetricIds.length} metric
                                {selectedMetricIds.length === 1 ? '' : 's'})
                              </button>
                              {showAdvancedLLM && (
                                <div className="mt-2 space-y-3">
                                  {selectedMetricIds.map((metricId) => {
                                    const metric =
                                      enabledMetrics.find(
                                        (m: any) => m.id === metricId,
                                      ) ||
                                      enabledMetrics
                                        .flatMap((m: any) =>
                                          Array.isArray(m.children)
                                            ? m.children
                                            : [],
                                        )
                                        .find((c: any) => c.id === metricId)
                                    if (!metric) return null
                                    const override = metricLLMOverrides[
                                      metricId
                                    ] || {
                                      provider: null,
                                      model: null,
                                      credential_id: null,
                                    }
                                    return (
                                      <div
                                        key={metricId}
                                        className="rounded border border-gray-200 bg-white p-2"
                                      >
                                        <p className="text-xs font-medium text-gray-800 mb-1">
                                          {metric.name}
                                        </p>
                                        <ProviderModelPicker
                                          kind="llm"
                                          value={override}
                                          onChange={(next) => {
                                            setMetricLLMOverrides((prev) => {
                                              const copy = { ...prev }
                                              if (!next.provider && !next.model) {
                                                delete copy[metricId]
                                              } else {
                                                copy[metricId] = next
                                              }
                                              return copy
                                            })
                                          }}
                                          defaultLabel="Use run default"
                                        />
                                      </div>
                                    )
                                  })}
                                </div>
                              )}
                            </div>
                          )}
                        </div>

                        {/* Transcript source selector — ticking both
                            creates two evaluation runs (one per source). */}
                        <div className="rounded-md border border-gray-200 bg-gray-50 p-3 space-y-2">
                          <p className="text-sm font-medium text-gray-900">
                            Run evaluation on
                          </p>
                          <p className="text-[11px] text-gray-500 -mt-1">
                            Tick both to run the evaluation twice — once
                            per transcript — so the two scorings can be
                            compared side-by-side. At least one is required.
                          </p>
                          <label className="flex items-start gap-2 text-sm cursor-pointer">
                            <input
                              type="checkbox"
                              checked={evalUseProduction}
                              onChange={(e) =>
                                setEvalUseProduction(e.target.checked)
                              }
                              className="mt-0.5"
                            />
                            <span>
                              <span className="font-medium text-gray-900">
                                Production transcript
                              </span>
                              <span className="block text-[11px] text-gray-500">
                                The transcript supplied via the CSV upload.
                              </span>
                            </span>
                          </label>
                          <label className="flex items-start gap-2 text-sm cursor-pointer">
                            <input
                              type="checkbox"
                              checked={evalUseDiarised}
                              onChange={(e) =>
                                setEvalUseDiarised(e.target.checked)
                              }
                              className="mt-0.5"
                            />
                            <span>
                              <span className="font-medium text-gray-900">
                                Diarised transcript
                              </span>
                              <span className="block text-[11px] text-gray-500">
                                The transcript produced by running
                                diarisation on the recording.
                              </span>
                            </span>
                          </label>
                          {!evalUseProduction && !evalUseDiarised && (
                            <p className="text-[11px] text-red-600">
                              Select at least one transcript to evaluate.
                            </p>
                          )}
                        </div>

                        {/* Auto-transcribe hook */}
                        <div className="rounded-md border border-gray-200 bg-gray-50 p-3 space-y-2">
                          <label className="flex items-start gap-2 text-sm cursor-pointer">
                            <input
                              type="checkbox"
                              checked={autoTranscribe}
                              onChange={(e) =>
                                setAutoTranscribe(e.target.checked)
                              }
                              className="mt-0.5"
                            />
                            <span>
                              <span className="font-medium text-gray-900">
                                Auto-diarise rows missing a diarised transcript
                              </span>
                              <span className="block text-[11px] text-gray-500">
                                Runs the STT/diarisation worker first, then
                                evaluates. Only applies to the Diarised
                                transcript source — rows that already have a
                                diarised transcript are reused unless overwrite
                                is enabled.
                              </span>
                            </span>
                          </label>
                          {autoTranscribe && (
                            <div className="pl-6 space-y-2">
                              <ProviderModelPicker
                                kind="stt"
                                value={evalSTT}
                                onChange={setEvalSTT}
                                providerAllowList={STT_PROVIDER_ALLOWLIST}
                                defaultLabel="Pick an STT provider"
                                allowCredentialPick
                              />
                              <input
                                type="text"
                                value={evalSTTLanguage}
                                onChange={(e) =>
                                  setEvalSTTLanguage(e.target.value)
                                }
                                placeholder="Language hint (e.g. en, hi)"
                                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                              />
                              <label className="flex items-start gap-2 text-xs">
                                <input
                                  type="checkbox"
                                  checked={transcribeOverwrite}
                                  onChange={(e) =>
                                    setTranscribeOverwrite(e.target.checked)
                                  }
                                />
                                <span>Overwrite existing transcripts</span>
                              </label>
                            </div>
                          )}
                        </div>
                        </div>
                        </div>
                      </>
                    )}

                    {runError ? (
                      <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 space-y-1">
                        <p>{runError}</p>
                        {/metric/i.test(runError) ? (
                          <Link
                            to="/metrics-management"
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
                          runEvaluationMutation.isPending ||
                          (autoTranscribe &&
                            (!evalSTT.provider || !evalSTT.model)) ||
                          (Boolean(runLLM.provider) !==
                            Boolean(runLLM.model)) ||
                          (!evalUseProduction && !evalUseDiarised)
                        }
                        onClick={() => {
                          // Build a clean overrides payload — drop any
                          // entries that didn't end up with both a
                          // provider and a model set so the API doesn't
                          // 400 on partial fills.
                          const overrides: Record<
                            string,
                            CallImportEvaluationLLMOverride
                          > = {}
                          for (const [mid, val] of Object.entries(
                            metricLLMOverrides,
                          )) {
                            if (val.provider && val.model) {
                              overrides[mid] = {
                                provider: val.provider,
                                model: val.model,
                                credential_id: val.credential_id || null,
                              }
                            }
                          }
                          const transcriptSources: Array<
                            'production' | 'diarised'
                          > = []
                          if (evalUseProduction)
                            transcriptSources.push('production')
                          if (evalUseDiarised)
                            transcriptSources.push('diarised')
                          runEvaluationMutation.mutate({
                            metric_ids: selectedMetricIds,
                            name: runDraftName.trim() || null,
                            transcript_sources: transcriptSources,
                            llm_provider: runLLM.provider || null,
                            llm_model: runLLM.model || null,
                            llm_credential_id: runLLM.credential_id || null,
                            metric_llm_overrides: Object.keys(overrides).length
                              ? overrides
                              : null,
                            auto_transcribe: autoTranscribe,
                            transcribe_overwrite:
                              autoTranscribe && transcribeOverwrite,
                            stt_provider: autoTranscribe
                              ? evalSTT.provider
                              : null,
                            stt_model: autoTranscribe ? evalSTT.model : null,
                            stt_credential_id: autoTranscribe
                              ? evalSTT.credential_id || null
                              : null,
                            stt_language: autoTranscribe
                              ? evalSTTLanguage.trim() || null
                              : null,
                          })
                        }}
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

      <ConfirmModal
        isOpen={showBulkDeleteRows}
        title={
          selectedRowIds.size === 1
            ? 'Delete this row?'
            : `Delete ${selectedRowIds.size} rows?`
        }
        description={(() => {
          const lines = [
            selectedRowIds.size === 1
              ? 'The selected row will be removed from this import, along with its stored recording in S3.'
              : `${selectedRowIds.size} rows will be removed from this import, along with their stored recordings in S3.`,
            'In-flight transcribe / download tasks for these rows will be revoked.',
            'This cannot be undone.',
            bulkDeleteRowsError ? `Error: ${bulkDeleteRowsError}` : '',
          ]
          return lines.filter(Boolean).join('\n\n')
        })()}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        isLoading={bulkDeleteRowsMutation.isPending}
        onConfirm={() => {
          if (selectedRowIds.size === 0) return
          bulkDeleteRowsMutation.mutate(Array.from(selectedRowIds))
        }}
        onCancel={() => {
          if (bulkDeleteRowsMutation.isPending) return
          setShowBulkDeleteRows(false)
          setBulkDeleteRowsError(null)
        }}
      />
    </div>
  )
}

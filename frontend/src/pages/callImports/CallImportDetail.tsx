import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  ArrowLeftRight,
  AudioLines,
  BarChart3,
  Check,
  ChevronRight,
  Copy,
  Download,
  Edit3,
  FileText,
  ListTree,
  Mic,
  MessageSquare,
  Pause,
  Play,
  RefreshCw,
  Search,
  Square,
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
import Pagination from '../../components/Pagination'
import StatusBadge from '../../components/shared/StatusBadge'
import ProviderModelPicker, {
  type ProviderModelValue,
} from '../../components/providers/ProviderModelPicker'
import CallImportProgressBar from './components/CallImportProgressBar'
import ImportPanel from './components/ImportPanel'
import MappingPanel from './components/MappingPanel'
import StageTracker from './components/StageTracker'
import TranscriptView from './components/TranscriptView'

// Providers we know `TranscriptionService.transcribe()` already supports
// for the full diarization-enabled path. Local Whisper is omitted since
// it's an unconditional fallback inside the service rather than
// something the user explicitly picks. Google is wired up via Gemini
// multimodal completions through LiteLLM (see
// `app/services/ai/stt_clients/google.py`) — the picker exposes the
// `gemini-*-stt` model entries from `app/config/models.json`.
const STT_PROVIDER_ALLOWLIST = [
  'deepgram',
  'openai',
  'elevenlabs',
  'sarvam',
  'smallest',
  'google',
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
  // Transient "✓ Copied" feedback on the per-row Copy button next to
  // the conversation_id. Keyed by row.id so the badge can flip on the
  // exact button that was clicked without affecting the rest of the
  // table. Auto-clears after 1.5s via a setTimeout inside the handler.
  const [copiedRowId, setCopiedRowId] = useState<string | null>(null)
  const handleCopyConversationId = (
    row: CallImportRow,
    event: React.MouseEvent,
  ) => {
    // Stop the synthetic click from bubbling up to the expand button
    // that wraps the row header — otherwise copying would also toggle
    // the row open/closed.
    event.preventDefault()
    event.stopPropagation()
    const text = row.conversation_id || ''
    if (!text) return
    const finalize = () => {
      setCopiedRowId(row.id)
      window.setTimeout(() => {
        // Only clear if THIS row is still the active one — a quick
        // double-click on two different rows shouldn't prematurely
        // wipe the badge on the second.
        setCopiedRowId((prev) => (prev === row.id ? null : prev))
      }, 1500)
    }
    // ``navigator.clipboard`` is async + requires a secure context.
    // Fall back to the legacy ``execCommand`` path so localhost-over-
    // http (e.g. ``http://10.x.x.x:5173`` LAN dev) still works.
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(finalize).catch(() => {
        // Best-effort fallback if the async API rejects (permission /
        // not focused / unsupported MIME, …).
        try {
          const ta = document.createElement('textarea')
          ta.value = text
          ta.style.position = 'fixed'
          ta.style.opacity = '0'
          document.body.appendChild(ta)
          ta.select()
          document.execCommand('copy')
          document.body.removeChild(ta)
          finalize()
        } catch {
          // Swallow — user can still drag-select the visible text.
        }
      })
    } else {
      try {
        const ta = document.createElement('textarea')
        ta.value = text
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
        finalize()
      } catch {
        // Swallow — drag-select still works.
      }
    }
  }
  // Row search: debounce keystrokes so we don't refire the rows fetch on
  // every character — the backend filters by conversation_id ILIKE %q%
  // and reports the post-filter total in ``filtered_total_rows``.
  const [rowSearchInput, setRowSearchInput] = useState('')
  const [rowSearchQuery, setRowSearchQuery] = useState('')
  // Optional filter on per-row diarised transcript status. Lets the
  // user find rows where diarisation failed (or is still running)
  // without having to expand each row. Backed by the new
  // ``diarised_status`` query param on ``GET /call-imports/{id}``.
  type DiarisedStatusFilter =
    | 'all'
    | 'pending'
    | 'running'
    | 'completed'
    | 'failed'
  const [diarisedStatusFilter, setDiarisedStatusFilter] =
    useState<DiarisedStatusFilter>('all')
  // Multi-select state for the row list — drives the bulk-action
  // toolbar (delete / transcribe). The header checkbox toggles every
  // row currently visible on the page; an explicit "Select all in
  // import" affordance extends the selection across pages by harvesting
  // ids from ``GET /call-imports/{id}/row-ids``.
  const [selectedRowIds, setSelectedRowIds] = useState<Set<string>>(new Set())
  // Loading flag for the cross-page select-all click; surfaces a tiny
  // spinner on the affordance button so the user knows the harvest is
  // in flight.
  const [isSelectingAllInImport, setIsSelectingAllInImport] = useState(false)
  const [selectAllError, setSelectAllError] = useState<string | null>(null)
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
  // Auto-transcribe is now ALWAYS on for every eval run — every run
  // scores the diarised transcript, and missing diarised transcripts
  // are auto-produced by the STT worker before scoring. The flag is
  // no longer user-editable so we don't track it as state; the request
  // payload below hardcodes ``auto_transcribe: true``.
  const [transcribeOverwrite, setTranscribeOverwrite] = useState(false)
  // Same toggle as the standalone Transcribe modal: ``stt_llm`` (the
  // legacy two-stage path) vs ``llm_only`` (multimodal audio→LLM in
  // one pass). The Run-Evaluation modal carries an independent copy
  // so flipping the standalone modal doesn't quietly mutate the eval
  // run's transcribe step.
  //
  // Default is ``llm_only`` because a single audio-in multimodal call
  // is faster, cheaper, and produces a tighter transcript than the
  // two-stage STT+LLM dance in the vast majority of real-world rows.
  // Operators who explicitly want the legacy pipeline (e.g. to reuse
  // an existing STT contract) flip the segmented control over to
  // "STT + LLM diariser" which is presented as the advanced fallback.
  const [evalTranscribeMode, setEvalTranscribeMode] = useState<
    'stt_llm' | 'llm_only'
  >('llm_only')
  const [evalSTT, setEvalSTT] = useState<ProviderModelValue>({
    provider: null,
    model: null,
    credential_id: null,
  })
  const [evalSTTLanguage, setEvalSTTLanguage] = useState('')
  // LLM diariser config for the auto-diarise step. Mirrors the
  // standalone Transcribe modal; required by the backend.
  const [evalDiariserLLM, setEvalDiariserLLM] = useState<ProviderModelValue>({
    provider: null,
    model: null,
    credential_id: null,
  })
  const [evalDiarisationPrompt, setEvalDiarisationPrompt] = useState('')
  // Opt into LLM-driven discovery of brand-new top-level metrics for
  // this run. Defaults to off so existing users get the same behaviour
  // as before; flipping it on adds a single instruction block to the
  // first LLM call per row asking the model to surface candidate
  // metrics that aren't already in the selected list.
  const [discoverNewMetrics, setDiscoverNewMetrics] = useState(false)
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
  // Which diarisation pipeline the operator has selected for THIS
  // modal instance. ``stt_llm`` is the legacy two-stage path (STT
  // then LLM diariser); ``llm_only`` hides the STT picker and feeds
  // the audio straight to a multimodal chat model. Persists across
  // modal opens within a session so power-users don't have to re-
  // toggle every time. ``llm_only`` is the default — see the
  // matching note on ``evalTranscribeMode`` above.
  const [transcribeMode, setTranscribeMode] = useState<
    'stt_llm' | 'llm_only'
  >('llm_only')
  const [transcribeSTT, setTranscribeSTT] = useState<ProviderModelValue>({
    provider: null,
    model: null,
    credential_id: null,
  })
  // LLM that diarises the STT plain-text into agent/user turns.
  // Pyannote has been removed — this picker is required to start a
  // run. We default to OpenAI/gpt-4o-mini because it's the cheapest
  // chat model on the curated list; the user can override it.
  const [transcribeDiariserLLM, setTranscribeDiariserLLM] =
    useState<ProviderModelValue>({
      provider: null,
      model: null,
      credential_id: null,
    })
  const [transcribeDiarisationPrompt, setTranscribeDiarisationPrompt] =
    useState('')
  // Defaults to ON: when the user clicks the Diarize button they almost
  // always want to re-run on top of any existing diarised transcript;
  // the safe-off default forced an extra click for every re-run. The
  // user can still untick it before submitting if they explicitly want
  // to skip rows that already have a transcript.
  const [transcribeOverwriteStandalone, setTranscribeOverwriteStandalone] =
    useState(true)
  const [transcribeLanguage, setTranscribeLanguage] = useState('')
  const [transcribeError, setTranscribeError] = useState<string | null>(null)

  // Prompt-partial import sub-modal. ``target`` decides which
  // diarisation prompt textarea the chosen partial's ``content``
  // replaces — ``standalone`` is the Diarize-modal textarea,
  // ``eval`` is the Run-Evaluation modal's. ``null`` keeps the
  // sub-modal hidden.
  const [partialsImportTarget, setPartialsImportTarget] = useState<
    'standalone' | 'eval' | null
  >(null)
  const [partialsSearchInput, setPartialsSearchInput] = useState('')
  const [partialsSearchQuery, setPartialsSearchQuery] = useState('')
  const [selectedPartialId, setSelectedPartialId] = useState<string>('')
  const [partialsImportError, setPartialsImportError] = useState<string | null>(
    null,
  )

  // The canonical default diariser prompt. Fetched once when the
  // modal opens so the textarea can pre-fill with the *actual*
  // server-side default rather than a duplicated hardcoded copy.
  const { data: defaultDiarisationPrompt } = useQuery({
    queryKey: ['call-import-diarisation-prompt-default'],
    queryFn: () => apiClient.getCallImportDiarisationPromptDefault(),
    staleTime: Infinity,
  })

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

  // Debounce the partials-search input so we don't refire the list
  // query on every character while the import sub-modal is open.
  useEffect(() => {
    const handle = setTimeout(() => {
      setPartialsSearchQuery(partialsSearchInput.trim())
    }, 250)
    return () => clearTimeout(handle)
  }, [partialsSearchInput])

  const { data: promptPartials = [], isLoading: isLoadingPartials } = useQuery<
    Array<{ id: string; name: string; description?: string | null }>
  >({
    queryKey: ['call-import-prompt-partials', partialsSearchQuery],
    queryFn: () =>
      apiClient.listPromptPartials(
        0,
        100,
        partialsSearchQuery ? partialsSearchQuery : undefined,
      ),
    enabled: partialsImportTarget !== null,
  })

  const importPartialMutation = useMutation({
    mutationFn: (partialId: string) => apiClient.getPromptPartial(partialId),
    onSuccess: (partial) => {
      const content = ((partial?.content as string | undefined) || '').trim()
      if (!content) {
        setPartialsImportError('Selected prompt partial has no content.')
        return
      }
      if (partialsImportTarget === 'standalone') {
        setTranscribeDiarisationPrompt(content)
      } else if (partialsImportTarget === 'eval') {
        setEvalDiarisationPrompt(content)
      }
      setPartialsImportTarget(null)
      setPartialsSearchInput('')
      setPartialsSearchQuery('')
      setSelectedPartialId('')
      setPartialsImportError(null)
    },
    onError: (err: any) => {
      setPartialsImportError(
        err?.response?.data?.detail ||
          err?.message ||
          'Failed to load prompt partial.',
      )
    },
  })

  const closePartialsImportModal = () => {
    if (importPartialMutation.isPending) return
    setPartialsImportTarget(null)
    setPartialsSearchInput('')
    setPartialsSearchQuery('')
    setSelectedPartialId('')
    setPartialsImportError(null)
  }

  // Snap back to the first page whenever the active query changes —
  // otherwise the user could be sitting on page 3 of a filtered set
  // that only has one page of results.
  useEffect(() => {
    setRowOffset(0)
  }, [rowSearchQuery, diarisedStatusFilter])

  // Clear any active row selection when the filter set changes — the
  // ids the user picked may no longer match the new slice. Pagination
  // alone no longer resets the selection so users can still pick rows
  // across pages (the "Select all in import" affordance relies on this).
  useEffect(() => {
    setSelectedRowIds(new Set())
    setSelectAllError(null)
  }, [rowSearchQuery, diarisedStatusFilter])

  const queryParams = useMemo(
    () => ({
      row_limit: ROW_PAGE_SIZE,
      row_offset: rowOffset,
      q: rowSearchQuery || undefined,
      diarised_status:
        diarisedStatusFilter === 'all' ? undefined : diarisedStatusFilter,
    }),
    [rowOffset, rowSearchQuery, diarisedStatusFilter],
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
    // Pre-import staged batches don't have a meaningful "still working"
    // signal that needs polling — they only change in response to user
    // actions on this page, which already invalidate the query.
    staleTime: 0,
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
      setTranscribeOverwrite(false)
      setEvalSTT({ provider: null, model: null, credential_id: null })
      setEvalSTTLanguage('')
      setEvalDiariserLLM({
        provider: null,
        model: null,
        credential_id: null,
      })
      setEvalDiarisationPrompt('')
      setDiscoverNewMetrics(false)
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
      mode,
      stt,
      diariserLLM,
      diarisationPrompt,
      language,
      overwrite,
    }: {
      rowIds: string[] | null
      mode: 'stt_llm' | 'llm_only'
      stt: ProviderModelValue
      diariserLLM: ProviderModelValue
      diarisationPrompt: string
      language: string
      overwrite: boolean
    }) => {
      const trimmedLang = language.trim() || null
      const trimmedPrompt = diarisationPrompt.trim() || null
      // STT fields are conditionally present: required when the
      // operator picked the legacy STT+LLM path, omitted (sent as
      // null) when they picked LLM-only so the backend's validator
      // accepts the request. We always send `mode` explicitly so the
      // server never has to guess from the absence of stt_*.
      const base = {
        mode,
        stt_provider: mode === 'stt_llm' ? (stt.provider as string) : null,
        stt_model: mode === 'stt_llm' ? (stt.model as string) : null,
        credential_id: mode === 'stt_llm' ? (stt.credential_id ?? null) : null,
        language: trimmedLang,
        only_missing: !overwrite,
        overwrite_existing: overwrite,
        diarization_llm_provider: diariserLLM.provider as string,
        diarization_llm_model: diariserLLM.model as string,
        diarization_llm_credential_id: diariserLLM.credential_id ?? null,
        diarization_prompt: trimmedPrompt,
      }
      // Single-row endpoint vs batch endpoint: prefer the single-row
      // endpoint when the modal targets exactly one row so the API
      // surface stays self-documenting.
      if (rowIds && rowIds.length === 1) {
        return apiClient.transcribeCallImportRow(id!, rowIds[0], base)
      }
      return apiClient.transcribeCallImport(id!, {
        ...base,
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

  // Tracks which row's diarisation we're currently asking the backend
  // to cancel. Used to inline-spinner the Stop button on the row
  // without blocking the rest of the row's controls. Cleared in
  // ``onSettled`` so a transient 5xx still releases the spinner.
  const [cancellingRowId, setCancellingRowId] = useState<string | null>(null)

  const cancelDiarisationMutation = useMutation({
    mutationFn: ({ rowId }: { rowId: string }) =>
      apiClient.cancelCallImportRowDiarisation(id!, rowId),
    onMutate: ({ rowId }) => {
      setCancellingRowId(rowId)
    },
    onSuccess: () => {
      // The backend has already flipped the row to ``failed`` with the
      // "cancelled by user" sentinel; refetch so the diarisation pill
      // and error message in the row drawer pick up the new state
      // immediately instead of waiting for the next poll tick.
      queryClient.invalidateQueries({ queryKey: ['call-import', id] })
    },
    onError: (err: any) => {
      // Cancel is idempotent on the server — the most likely failure
      // is a 404 because the row was just deleted, in which case the
      // refetch below will reconcile state. Surface a console.error
      // so the failure isn't completely silent for an operator with
      // dev-tools open, but skip the inline banner: the row strip
      // itself reflects truth on the next poll.
      // eslint-disable-next-line no-console
      console.error('cancelDiarisationMutation failed:', err)
    },
    onSettled: () => {
      setCancellingRowId(null)
    },
  })

  // Consolidated "Bulk actions" modal. The toolbar used to have one
  // button per action (Transcribe / Delete) which crowded the strip;
  // now there's a single entry point that opens a modal listing every
  // action with its own per-action count + execute button. This also
  // makes the new "Stop diarisation (selected)" affordance a natural
  // fit without growing the toolbar further.
  const [showBulkActionsModal, setShowBulkActionsModal] = useState(false)
  const [bulkActionResult, setBulkActionResult] = useState<string | null>(
    null,
  )
  const [bulkActionError, setBulkActionError] = useState<string | null>(null)

  const bulkCancelDiarisationMutation = useMutation({
    mutationFn: (rowIds: string[]) =>
      apiClient.cancelCallImportDiarisation(id!, rowIds),
    onMutate: () => {
      setBulkActionError(null)
      setBulkActionResult(null)
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['call-import', id] })
      // The endpoint returns a typed ``{cancelled, skipped}`` summary;
      // surface it inline in the modal so the operator sees the
      // breakdown without having to scan the rows table for green
      // diarise pills.
      const cancelled = data?.cancelled ?? 0
      const skipped = data?.skipped ?? 0
      const parts = [
        `Cancelled ${cancelled} row${cancelled === 1 ? '' : 's'}`,
      ]
      if (skipped > 0) {
        parts.push(
          `skipped ${skipped} (not in a cancellable state — typically already completed or never queued)`,
        )
      }
      setBulkActionResult(parts.join(' · '))
    },
    onError: (err: any) => {
      setBulkActionError(
        err?.response?.data?.detail ||
          err?.message ||
          'Failed to cancel diarisation for the selected rows.',
      )
    },
  })

  // Tracks which row is currently being swapped so we can show a tiny
  // spinner inline on its toggle button without blocking the rest of
  // the row UI. Cleared on success or error.
  const [swappingRowId, setSwappingRowId] = useState<string | null>(null)
  const [swapError, setSwapError] = useState<string | null>(null)

  const swapSpeakersMutation = useMutation({
    mutationFn: ({ rowId }: { rowId: string }) =>
      apiClient.toggleCallImportRowSpeakerSwap(id!, rowId),
    onMutate: ({ rowId }) => {
      setSwappingRowId(rowId)
      setSwapError(null)
    },
    onSuccess: () => {
      // The PATCH already returns the updated row, but we still want
      // the parent ``call-import`` query to refetch so the row list /
      // pagination / search index stay in sync (the row object is
      // embedded inside a much larger response).
      queryClient.invalidateQueries({ queryKey: ['call-import', id] })
    },
    onError: (err: any) => {
      setSwapError(
        err?.response?.data?.detail ||
          err?.message ||
          'Failed to swap speaker labels.',
      )
    },
    onSettled: () => {
      setSwappingRowId(null)
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
  // ``filtered_total_rows`` is set whenever any filter (search OR
  // diarisation-status) is active; pagination should always page
  // against whatever slice the user is actually looking at.
  const hasActiveFilter =
    !!rowSearchQuery || diarisedStatusFilter !== 'all'
  const filteredTotalRows = hasActiveFilter
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
        row.recording_s3_key.split('/').pop() || `${row.conversation_id}.mp3`,
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
    setTranscribeOverwriteStandalone(true)
    // Default to deepgram/nova-2 since it's the most common diarization
    // setup; the user can change it before submitting.
    if (!transcribeSTT.provider) {
      setTranscribeSTT({
        provider: 'deepgram',
        model: 'nova-2',
        credential_id: null,
      })
    }
    // Default diariser LLM: openai/gpt-4o-mini is cheap and good
    // enough for two-speaker call diarisation. The user can change
    // it before submitting.
    if (!transcribeDiariserLLM.provider) {
      setTranscribeDiariserLLM({
        provider: 'openai',
        model: 'gpt-4o-mini',
        credential_id: null,
      })
    }
    // Seed the prompt textarea with the canonical default the first
    // time the modal opens; preserve any local edits across re-opens.
    if (!transcribeDiarisationPrompt && defaultDiarisationPrompt) {
      setTranscribeDiarisationPrompt(defaultDiarisationPrompt)
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

  // The staged-flow batch isn't ready to render rows / evaluations
  // until the user finishes the MAP + IMPORT steps. We swap out the
  // bottom of the page for the stage panels while the batch is still
  // pre-import so the user has a single linear next-action.
  const preImport = data.status === 'uploaded' || data.status === 'mapped'

  // Selection state — ``selectedRowIds`` can now span pages (we no
  // longer wipe it on pagination), so distinguish "how many of the
  // currently-visible rows are ticked" from "how many rows are
  // selected in total". The header checkbox toggles only the on-page
  // rows; a separate affordance appears once every on-page row is
  // selected to let the user extend the selection across every page.
  const selectedOnPage = rows.filter((r) => selectedRowIds.has(r.id))
  const selectedOnPageCount = selectedOnPage.length
  const selectedCount = selectedRowIds.size
  const allOnPageSelected =
    rows.length > 0 && selectedOnPageCount === rows.length
  const allMatchingSelected =
    filteredTotalRows > 0 && selectedCount >= filteredTotalRows
  // ``transcribeReadySelection`` previously gated the Transcribe
  // button on the on-page filter; with cross-page selection we can't
  // cheaply check every off-page row's status from here, so we trust
  // the worker's own ``_select_rows_for_transcription`` filter to
  // skip rows lacking audio / in-flight. We still surface an on-page
  // optimistic count for the button label.
  const transcribeReadySelection = selectedOnPage.filter(
    (r) =>
      !!r.recording_s3_key &&
      r.diarised_transcript_status !== 'pending' &&
      r.diarised_transcript_status !== 'running',
  )
  // Rows in the selection (on-page slice we can see) whose diarisation
  // is actually cancellable (queued OR currently running). The same
  // cross-page caveat as ``transcribeReadySelection`` applies — if the
  // user has selected rows on pages we don't have loaded, this counter
  // undercounts and we surface that ambiguity in the modal copy. The
  // backend filters again server-side so a hopeful click on a stale
  // count just reports back ``cancelled / skipped`` in the toast.
  const cancellableSelection = selectedOnPage.filter(
    (r) =>
      r.diarised_transcript_status === 'pending' ||
      r.diarised_transcript_status === 'running',
  )
  // True when the user's selection covers rows we don't have loaded on
  // the current page (cross-page selection). In that case any
  // per-action count is on-page-only, so the modal degrades to "we'll
  // act on N selected rows; the server filters the rest".
  const selectionSpansPages = selectedCount > selectedOnPageCount

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
          {!preImport && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                setSelectedMetricIds([])
                // Seed sensible diariser defaults; the user can
                // override before submitting. Same defaults as the
                // standalone Transcribe modal so the two paths feel
                // consistent.
                if (!evalDiariserLLM.provider) {
                  setEvalDiariserLLM({
                    provider: 'openai',
                    model: 'gpt-4o-mini',
                    credential_id: null,
                  })
                }
                if (!evalDiarisationPrompt && defaultDiarisationPrompt) {
                  setEvalDiarisationPrompt(defaultDiarisationPrompt)
                }
                setShowRunEval(true)
              }}
              disabled={!rows.length}
              title={
                !rows.length
                  ? 'No rows to evaluate yet'
                  : 'Open the run dialog — you must pick metrics and an STT provider/model before starting'
              }
            >
              Run Evaluation
            </Button>
          )}
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
                Provider:{' '}
                <span className="font-medium">
                  {data.provider || (
                    <span className="text-gray-400 italic normal-case">
                      not selected yet
                    </span>
                  )}
                </span>
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
            <div className="text-xs font-medium text-gray-600 mb-1">
              Recording import
            </div>
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

            {/*
              Transcription + diarisation progress, surfaced only once
              the worker has actually been kicked off on at least one
              row (otherwise every fresh batch would show a permanent
              0% bar that means nothing). The ``pending`` + ``running``
              counter is shown next to the bar so the user can see
              "still working on N" while the bar fills with completed
              + failed.
            */}
            {(() => {
              const diariseInFlight =
                (data.diarised_pending_rows ?? 0) +
                (data.diarised_running_rows ?? 0)
              const diariseDone =
                (data.diarised_completed_rows ?? 0) +
                (data.diarised_failed_rows ?? 0)
              const hasActivity = diariseInFlight + diariseDone > 0
              if (!hasActivity) return null
              return (
                <div className="mt-4 pt-4 border-t border-gray-100">
                  <div className="flex items-center justify-between mb-1">
                    <div className="text-xs font-medium text-gray-600">
                      Transcription &amp; diarisation
                    </div>
                    {diariseInFlight > 0 && (
                      <div className="flex items-center gap-1 text-[11px] text-primary-700">
                        <RefreshCw className="h-3 w-3 animate-spin" />
                        {diariseInFlight} in progress
                      </div>
                    )}
                  </div>
                  <CallImportProgressBar
                    total={data.total_rows}
                    completed={data.diarised_completed_rows ?? 0}
                    failed={data.diarised_failed_rows ?? 0}
                  />
                </div>
              )
            })()}
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

      {/* Stage tracker: only meaningful for batches that came through
          the staged flow (i.e. have ``source_s3_key`` set). Legacy
          one-shot uploads start at status='processing' so they would
          render the tracker stuck on the final step, which is
          confusing — skip it entirely for those. */}
      {data.source_s3_key && <StageTracker status={data.status} />}

      {preImport && data.source_s3_key && (
        <>
          {data.status === 'uploaded' && <MappingPanel callImport={data} />}
          {data.status === 'mapped' && (
            <>
              <MappingPanel callImport={data} />
              <ImportPanel callImport={data} />
            </>
          )}
        </>
      )}

      {preImport ? null : (
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
      )}

      {!preImport && activeTab === 'rows' && (
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
              {hasActiveFilter ? ` (filtered from ${totalRows})` : ''}
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
              placeholder="Search by Conversation ID…"
              aria-label="Search rows by Conversation ID"
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
          {/* Diarisation status filter chips — finally lets the user
              find rows where diarisation failed without expanding every
              row in turn. The active chip drives ``diarised_status`` on
              the rows query and updates ``filtered_total_rows``. */}
          <div
            className="flex items-center gap-1 flex-wrap"
            role="group"
            aria-label="Filter rows by diarisation status"
          >
            <span className="text-[11px] uppercase tracking-wide text-gray-500 mr-1">
              Diarisation:
            </span>
            {(
              [
                { id: 'all', label: 'All' },
                { id: 'pending', label: 'Pending' },
                { id: 'running', label: 'Running' },
                { id: 'completed', label: 'Completed' },
                { id: 'failed', label: 'Failed' },
              ] as Array<{ id: DiarisedStatusFilter; label: string }>
            ).map((chip) => {
              const active = diarisedStatusFilter === chip.id
              return (
                <button
                  key={chip.id}
                  type="button"
                  onClick={() => setDiarisedStatusFilter(chip.id)}
                  className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                    active
                      ? chip.id === 'failed'
                        ? 'bg-red-600 border-red-600 text-white'
                        : 'bg-primary-600 border-primary-600 text-white'
                      : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
                  }`}
                  aria-pressed={active}
                >
                  {chip.label}
                </button>
              )
            })}
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
              {/* Single entry point for every multi-row operation:
                  Diarise, Stop diarisation, Delete. The modal
                  surfaces per-action counts and explicit confirm
                  affordances, so the toolbar can stay uncluttered
                  even as we keep adding bulk verbs. */}
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<ListTree className="h-4 w-4" />}
                onClick={() => {
                  setBulkActionError(null)
                  setBulkActionResult(null)
                  setShowBulkActionsModal(true)
                }}
                className="text-primary-700 hover:text-primary-800 hover:bg-primary-50"
              >
                Bulk actions
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
                {diarisedStatusFilter !== 'all'
                  ? ` with diarisation status ${diarisedStatusFilter}.`
                  : '.'}
              </p>
            ) : diarisedStatusFilter !== 'all' ? (
              <p>
                No rows with diarisation status{' '}
                <span className="font-medium text-gray-700">
                  {diarisedStatusFilter}
                </span>
                .
              </p>
            ) : (
              <p>No rows in this slice.</p>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            <div className="flex items-center gap-3 px-3 py-2 border border-gray-200 rounded-lg bg-gray-50 flex-wrap">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  aria-label="Select all rows on this page"
                  checked={allOnPageSelected}
                  ref={(el) => {
                    if (el)
                      el.indeterminate =
                        selectedOnPageCount > 0 && !allOnPageSelected
                  }}
                  onChange={(e) => {
                    if (e.target.checked) {
                      // Add every on-page row to the selection without
                      // disturbing rows the user already ticked on
                      // other pages.
                      setSelectedRowIds((prev) => {
                        const next = new Set(prev)
                        for (const r of rows) next.add(r.id)
                        return next
                      })
                    } else {
                      // Drop only the on-page rows from the selection
                      // so the user can unselect this page without
                      // wiping cross-page picks.
                      setSelectedRowIds((prev) => {
                        const next = new Set(prev)
                        for (const r of rows) next.delete(r.id)
                        return next
                      })
                    }
                  }}
                />
                <span className="text-xs text-gray-600">
                  {allOnPageSelected
                    ? `All ${rows.length} on this page selected`
                    : selectedOnPageCount > 0
                    ? `${selectedOnPageCount} of ${rows.length} on this page selected`
                    : `Select all on this page (${rows.length})`}
                </span>
              </div>
              {/* "Select all in import" affordance — only shown once
                  the on-page checkbox is satisfied AND there are off-page
                  rows that the user could still benefit from selecting.
                  Clicking it hits the lightweight ``/row-ids`` endpoint
                  with the active filters so the selection respects the
                  search / status chips. */}
              {allOnPageSelected &&
                filteredTotalRows > rows.length &&
                !allMatchingSelected && (
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-400">·</span>
                    <Button
                      variant="ghost"
                      size="sm"
                      isLoading={isSelectingAllInImport}
                      onClick={async () => {
                        if (isSelectingAllInImport) return
                        setSelectAllError(null)
                        setIsSelectingAllInImport(true)
                        try {
                          const { ids } =
                            await apiClient.listCallImportRowIds(id!, {
                              q: rowSearchQuery || undefined,
                              diarised_status:
                                diarisedStatusFilter === 'all'
                                  ? undefined
                                  : diarisedStatusFilter,
                            })
                          setSelectedRowIds(new Set(ids))
                        } catch (err: any) {
                          setSelectAllError(
                            err?.response?.data?.detail ||
                              err?.message ||
                              'Failed to select all rows.',
                          )
                        } finally {
                          setIsSelectingAllInImport(false)
                        }
                      }}
                    >
                      {`Select all ${filteredTotalRows} rows in this import${
                        hasActiveFilter ? ' (matching filters)' : ''
                      }`}
                    </Button>
                  </div>
                )}
              {allMatchingSelected &&
                filteredTotalRows > rows.length && (
                  <span className="text-xs text-primary-700">
                    All {filteredTotalRows} matching rows selected.
                  </span>
                )}
            </div>
            {selectAllError && (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
                {selectAllError}
              </div>
            )}
            {/* Top pagination — mirrors the bottom bar so users don't
                have to scroll past hundreds of rows to flip pages.
                Renders nothing when there's only one page of results. */}
            <Pagination
              page={rowPage}
              pageCount={rowTotalPages}
              total={filteredTotalRows}
              pageSize={ROW_PAGE_SIZE}
              variant="card"
              className="mb-2"
              onPrev={() =>
                setRowOffset((o) => Math.max(0, o - ROW_PAGE_SIZE))
              }
              onNext={() =>
                setRowOffset((o) =>
                  o + ROW_PAGE_SIZE >= filteredTotalRows
                    ? o
                    : o + ROW_PAGE_SIZE,
                )
              }
            />
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
              const conversationIdValue = (row.conversation_id || '').trim()
              // ``raw_columns`` cell values can be strings, numbers,
              // booleans, or null after the staged flow's type
              // coercion (legacy uploads were always strings). Coerce
              // to a string before any string ops so non-string cells
              // don't blow up ``.trim()``.
              const rawColumnEntries = Object.entries(row.raw_columns || {}).filter(
                ([key, value]) => {
                  if (!key.trim()) return false
                  const stringValue =
                    value === null || value === undefined ? '' : String(value)
                  const trimmedValue = stringValue.trim()
                  if (!trimmedValue) return true
                  if (transcriptValue && trimmedValue === transcriptValue) return false
                  if (recordingUrlValue && trimmedValue === recordingUrlValue) return false
                  if (conversationIdValue && trimmedValue === conversationIdValue) {
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
                      aria-label={`Select row ${row.conversation_id}`}
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
                      {/*
                        ``conversation_id`` is the user-visible row
                        identifier. It used to sit inside the expand
                        button untouched, which meant:
                          (a) browsers default ``user-select: none`` on
                              ``<button>`` contents, so drag-select
                              didn't work, and
                          (b) any mouse-up on the text triggered the
                              expand toggle, swallowing accidental
                              clicks that the user intended as a
                              double-click-to-select-word.
                        We now stop click + mousedown propagation on
                        the span so the button's onClick never fires
                        from interactions with the text, force
                        ``user-select: text`` to re-enable drag-select,
                        and expose a one-click Copy affordance next to
                        it for the common case.
                       */}
                      <span
                        className="font-mono text-sm text-gray-900 truncate flex-1 min-w-0 select-text cursor-text"
                        title={row.conversation_id}
                        onClick={(e) => e.stopPropagation()}
                        onMouseDown={(e) => e.stopPropagation()}
                        onDoubleClick={(e) => e.stopPropagation()}
                      >
                        {row.conversation_id}
                      </span>
                      <span
                        role="button"
                        tabIndex={0}
                        aria-label={
                          copiedRowId === row.id
                            ? `Copied ${row.conversation_id}`
                            : `Copy ${row.conversation_id}`
                        }
                        title={
                          copiedRowId === row.id
                            ? 'Copied!'
                            : 'Copy conversation ID'
                        }
                        onClick={(e) => handleCopyConversationId(row, e)}
                        onMouseDown={(e) => e.stopPropagation()}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            handleCopyConversationId(
                              row,
                              e as unknown as React.MouseEvent,
                            )
                          }
                        }}
                        className={`flex-shrink-0 inline-flex items-center justify-center w-6 h-6 rounded transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 cursor-pointer ${
                          copiedRowId === row.id
                            ? 'text-green-600 bg-green-50'
                            : 'text-gray-400 hover:text-primary-600 hover:bg-primary-50'
                        }`}
                      >
                        {copiedRowId === row.id ? (
                          <Check className="h-3.5 w-3.5" />
                        ) : (
                          <Copy className="h-3.5 w-3.5" />
                        )}
                      </span>
                      <StatusBadge status={row.status} size="sm" />
                      {/* Diarisation status pill: only surfaced once
                          the diarise/transcribe worker has touched
                          this row. Lets the user spot failed rows
                          inline without expanding the row, and makes
                          the new diarisation status filter chip set
                          self-evident. */}
                      {(() => {
                        const ds = row.diarised_transcript_status
                        if (!ds || ds === 'idle') return null
                        const tone =
                          ds === 'failed'
                            ? 'bg-red-100 text-red-700 border-red-200'
                            : ds === 'completed'
                            ? 'bg-green-100 text-green-700 border-green-200'
                            : ds === 'running'
                            ? 'bg-blue-100 text-blue-700 border-blue-200'
                            : 'bg-gray-100 text-gray-700 border-gray-200'
                        return (
                          <span
                            className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border ${tone}`}
                            title={`Diarisation: ${ds}`}
                          >
                            Diarise: {ds}
                          </span>
                        )
                      })()}
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
                          {/*
                            Stop / abort button. Only visible while
                            the diarisation pipeline is actually in
                            flight (``pending`` queued OR ``running``
                            inside the worker). Calls the cancel
                            endpoint which revokes the Celery task
                            (SIGTERM) and stamps the row with a
                            "Cancelled by user" failure so the UI
                            immediately reflects the abort. Disabled
                            while we already have an in-flight cancel
                            request for THIS row so a double-click
                            doesn't fire two revokes (it's idempotent
                            on the server, but the spinner state would
                            flicker).
                           */}
                          {(row.diarised_transcript_status === 'pending' ||
                            row.diarised_transcript_status === 'running') && (
                            <button
                              type="button"
                              onClick={() =>
                                cancelDiarisationMutation.mutate({
                                  rowId: row.id,
                                })
                              }
                              disabled={cancellingRowId === row.id}
                              title="Stop diarisation"
                              aria-label={`Stop diarisation for ${row.conversation_id}`}
                              className="p-1.5 rounded text-gray-500 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-40"
                            >
                              {cancellingRowId === row.id ? (
                                <RefreshCw className="h-4 w-4 animate-spin" />
                              ) : (
                                <Square className="h-4 w-4" />
                              )}
                            </button>
                          )}
                        </>
                      ) : (
                        <span className="text-[11px] text-gray-400 px-2">
                          {row.status === 'failed' ? 'no audio' : 'pending'}
                        </span>
                      )}
                      <button
                        type="button"
                        aria-label={`Delete recording for ${row.conversation_id}`}
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

                  {/* Surface diarisation-specific failures even when
                      the row's recording download itself succeeded.
                      Previously these only showed inside the expanded
                      panel, so the new "Failed" filter chip would land
                      the user on rows with no inline indication of why
                      they failed. */}
                  {row.diarised_transcript_status === 'failed' &&
                    row.diarised_transcript_error && (
                      <div className="border-t border-red-100 bg-red-50 px-3 py-2 text-xs text-red-800 flex items-start gap-2">
                        <AlertCircle className="h-3.5 w-3.5 text-red-600 flex-shrink-0 mt-0.5" />
                        <div className="min-w-0 flex-1 break-words">
                          <span className="font-medium">
                            Diarisation error:
                          </span>{' '}
                          {row.diarised_transcript_error}
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
                              <div className="flex items-center gap-3">
                                {Array.isArray(row.diarised_segments) &&
                                  row.diarised_segments.length > 0 && (
                                    <button
                                      type="button"
                                      onClick={() =>
                                        swapSpeakersMutation.mutate({
                                          rowId: row.id,
                                        })
                                      }
                                      disabled={
                                        swappingRowId === row.id ||
                                        row.diarised_transcript_status ===
                                          'pending' ||
                                        row.diarised_transcript_status ===
                                          'running'
                                      }
                                      title={
                                        row.diarised_speaker_swap
                                          ? 'Speaker labels have been swapped. Click to revert to the diarisation default.'
                                          : 'Swap user and agent labels on this row.'
                                      }
                                      className="inline-flex items-center gap-1 text-[11px] font-medium text-purple-700 hover:text-purple-900 disabled:opacity-50"
                                    >
                                      {swappingRowId === row.id ? (
                                        <RefreshCw className="h-3 w-3 animate-spin" />
                                      ) : (
                                        <ArrowLeftRight className="h-3 w-3" />
                                      )}
                                      Swap user/agent
                                      {row.diarised_speaker_swap && (
                                        <span className="text-[9px] uppercase tracking-wider text-purple-500">
                                          (swapped)
                                        </span>
                                      )}
                                    </button>
                                  )}
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
                              </div>
                            </header>
                            {swapError && swappingRowId === null && (
                              <div className="border-b border-red-100 bg-red-50 px-3 py-2 text-xs text-red-800 flex items-start gap-2">
                                <AlertCircle className="h-3.5 w-3.5 text-red-600 flex-shrink-0 mt-0.5" />
                                <div className="min-w-0 flex-1 break-words">
                                  {swapError}
                                </div>
                                <button
                                  type="button"
                                  onClick={() => setSwapError(null)}
                                  className="text-red-600 hover:text-red-800 flex-shrink-0"
                                >
                                  <X className="h-3.5 w-3.5" />
                                </button>
                              </div>
                            )}
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
                          </header>
                          <dl className="p-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 text-xs">
                            {rawColumnEntries.map(([key, value]) => {
                              // Typed raw_columns cells (numbers /
                              // booleans / nulls) need to be stringified
                              // before any string ops or JSX render or
                              // React throws on the non-string child.
                              const stringValue =
                                value === null || value === undefined
                                  ? ''
                                  : String(value)
                              return (
                                <div
                                  key={key}
                                  className="bg-gray-50 border border-gray-200 rounded px-2.5 py-1.5"
                                >
                                  <dt className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider truncate">
                                    {key}
                                  </dt>
                                  <dd className="text-gray-800 break-words mt-0.5 whitespace-pre-wrap">
                                    {stringValue.trim() ? (
                                      stringValue
                                    ) : (
                                      <span className="italic text-gray-400">empty</span>
                                    )}
                                  </dd>
                                </div>
                              )
                            })}
                          </dl>
                        </section>
                      )}
                    </div>
                  )}
                </div>
              )
            })}

            <Pagination
              page={rowPage}
              pageCount={rowTotalPages}
              total={filteredTotalRows}
              pageSize={ROW_PAGE_SIZE}
              variant="card"
              className="mt-3"
              onPrev={() =>
                setRowOffset((o) => Math.max(0, o - ROW_PAGE_SIZE))
              }
              onNext={() =>
                setRowOffset((o) =>
                  o + ROW_PAGE_SIZE >= filteredTotalRows
                    ? o
                    : o + ROW_PAGE_SIZE,
                )
              }
            />
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
                  {rows.find((r) => r.id === playingRowId)?.conversation_id}
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

      {!preImport && activeTab === 'evaluations' && (
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

      {!preImport && activeTab === 'insights' && (
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

      {partialsImportTarget !== null &&
        renderModal(
          <div
            className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[10000]"
            onClick={closePartialsImportModal}
          >
            <div
              className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[85vh] overflow-hidden flex flex-col"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                <h3 className="text-lg font-semibold text-gray-900">
                  Import diarisation prompt from saved partials
                </h3>
                <button
                  onClick={closePartialsImportModal}
                  className="text-gray-400 hover:text-gray-600"
                  aria-label="Close prompt partials modal"
                  disabled={importPartialMutation.isPending}
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-6 space-y-4 overflow-y-auto flex-1">
                <p className="text-xs text-gray-500">
                  Pick a saved Prompt Partial; its content will replace
                  the current diarisation prompt textarea.
                </p>
                <input
                  type="text"
                  value={partialsSearchInput}
                  onChange={(e) => setPartialsSearchInput(e.target.value)}
                  placeholder="Search saved prompts..."
                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                />

                {isLoadingPartials ? (
                  <div className="flex items-center justify-center py-8 text-sm text-gray-500">
                    <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                    Loading saved prompts...
                  </div>
                ) : promptPartials.length === 0 ? (
                  <div className="rounded-lg border border-gray-200 p-8 text-center text-sm text-gray-500">
                    {partialsSearchQuery
                      ? `No saved prompt partials match “${partialsSearchQuery}”.`
                      : 'No saved prompt partials yet.'}
                  </div>
                ) : (
                  <div className="space-y-2 max-h-[45vh] overflow-y-auto">
                    {promptPartials.map((partial) => {
                      const isSelected = selectedPartialId === partial.id
                      return (
                        <label
                          key={partial.id}
                          className={`block cursor-pointer rounded-lg border p-3 transition-colors ${
                            isSelected
                              ? 'border-primary-300 bg-primary-50'
                              : 'border-gray-200 hover:bg-gray-50'
                          }`}
                        >
                          <div className="flex items-start gap-3">
                            <input
                              type="radio"
                              name="call-import-prompt-partial"
                              checked={isSelected}
                              onChange={() =>
                                setSelectedPartialId(partial.id)
                              }
                              className="mt-1 h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-500"
                            />
                            <div className="min-w-0 flex-1">
                              <p className="text-sm font-semibold text-gray-900">
                                {partial.name}
                              </p>
                              {partial.description ? (
                                <p className="mt-0.5 text-xs text-gray-500">
                                  {partial.description}
                                </p>
                              ) : null}
                            </div>
                          </div>
                        </label>
                      )
                    })}
                  </div>
                )}

                {partialsImportError && (
                  <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                    {partialsImportError}
                  </div>
                )}
              </div>
              <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-2 bg-gray-50 rounded-b-lg">
                <Button
                  variant="outline"
                  onClick={closePartialsImportModal}
                  disabled={importPartialMutation.isPending}
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  onClick={() =>
                    importPartialMutation.mutate(selectedPartialId)
                  }
                  isLoading={importPartialMutation.isPending}
                  disabled={!selectedPartialId}
                >
                  Use Selected Prompt
                </Button>
              </div>
            </div>
          </div>,
        )}

      {showTranscribeModal &&
        renderModal(
          (() => {
            const targets = transcribeTargetRows ?? []
            const headerLabel =
              targets.length === 1
                ? `Transcribe row #${(targets[0]?.row_index ?? 0) + 1}`
                : `Transcribe ${targets.length} rows`
            // The STT picker is only required in the legacy two-stage
            // path; the new ``llm_only`` path skips STT entirely so we
            // drop the STT-validity check from ``canSubmit`` when that
            // mode is active. The diariser LLM picker is required in
            // both modes (it's the model that produces the turns).
            const canSubmit =
              (transcribeMode === 'llm_only'
                ? true
                : !!transcribeSTT.provider && !!transcribeSTT.model) &&
              !!transcribeDiariserLLM.provider &&
              !!transcribeDiariserLLM.model &&
              targets.length > 0 &&
              !transcribeRowsMutation.isPending
            return (
              <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
                <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] flex flex-col">
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
                  <div className="p-6 space-y-4 overflow-y-auto">
                    {/* Mode toggle: STT+LLM vs LLM only. Rendered as a
                        segmented control so the active path is
                        unambiguous at a glance and the user can flip
                        between the two without scrolling. */}
                    <div className="space-y-2">
                      <p className="text-xs uppercase tracking-wide text-gray-500 font-semibold">
                        Diarisation mode
                      </p>
                      {/* Order intentionally puts LLM-only on the LEFT
                          (the recommended default) and STT+LLM on the
                          RIGHT, badged as "Advanced". This matches the
                          product direction: audio-in multimodal is the
                          first-class path and the two-stage STT pipeline
                          is the escape hatch for orgs that need a
                          specific STT contract or transcript artefact. */}
                      <div
                        role="tablist"
                        aria-label="Diarisation mode"
                        className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-0.5"
                      >
                        <button
                          type="button"
                          role="tab"
                          aria-pressed={transcribeMode === 'llm_only'}
                          onClick={() => setTranscribeMode('llm_only')}
                          className={`px-3 py-1.5 text-xs font-medium rounded-md transition ${
                            transcribeMode === 'llm_only'
                              ? 'bg-white text-gray-900 shadow-sm'
                              : 'text-gray-600 hover:text-gray-900'
                          }`}
                        >
                          LLM only (audio in)
                        </button>
                        <button
                          type="button"
                          role="tab"
                          aria-pressed={transcribeMode === 'stt_llm'}
                          onClick={() => setTranscribeMode('stt_llm')}
                          className={`px-3 py-1.5 text-xs font-medium rounded-md transition inline-flex items-center gap-1.5 ${
                            transcribeMode === 'stt_llm'
                              ? 'bg-white text-gray-900 shadow-sm'
                              : 'text-gray-600 hover:text-gray-900'
                          }`}
                        >
                          STT + LLM diariser
                          <span className="rounded-full bg-gray-200 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-gray-600">
                            Advanced
                          </span>
                        </button>
                      </div>
                      <p className="text-[11px] text-gray-500">
                        {transcribeMode === 'llm_only'
                          ? 'Recommended. Single-stage pipeline: the audio is fed directly to a multimodal LLM along with your prompt; the model both transcribes and diarises in one call. Pick a model that accepts audio input (e.g. Gemini 1.5/2.0, GPT-4o audio-preview).'
                          : 'Advanced fallback. Two-stage pipeline: STT transcribes the audio, then an LLM splits it into agent / user turns using your prompt. Use this when you need a specific STT contract or to reuse an existing transcript artefact.'}
                      </p>
                    </div>
                    {transcribeMode === 'stt_llm' && (
                      <div className="space-y-2">
                        <p className="text-xs uppercase tracking-wide text-gray-500 font-semibold">
                          1. Speech-to-text
                        </p>
                        <p className="text-sm text-gray-600">
                          The STT step produces plain text only; the LLM
                          below splits it into agent / user turns.
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
                          onChange={(e) =>
                            setTranscribeLanguage(e.target.value)
                          }
                          placeholder="Language hint (e.g. en, hi)"
                          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                        />
                      </div>
                    )}
                    <div className="space-y-2 pt-1 border-t border-gray-100">
                      <p className="text-xs uppercase tracking-wide text-gray-500 font-semibold pt-3">
                        {transcribeMode === 'stt_llm'
                          ? '2. LLM diariser'
                          : 'Multimodal diariser LLM'}
                      </p>
                      <p className="text-sm text-gray-600">
                        {transcribeMode === 'stt_llm' ? (
                          <>
                            Pick a chat model and tweak the prompt below.
                            The model receives the STT plain text and the
                            prompt and must return a JSON array of{' '}
                            <code className="px-1 bg-gray-100 rounded text-[11px]">
                              {'{ speaker, text }'}
                            </code>{' '}
                            turns.
                          </>
                        ) : (
                          <>
                            Pick a chat model that accepts audio input
                            (e.g. <code className="px-1 bg-gray-100 rounded text-[11px]">gemini-1.5-pro</code>,{' '}
                            <code className="px-1 bg-gray-100 rounded text-[11px]">gpt-4o-audio-preview</code>).
                            The model receives the recording bytes and
                            the prompt and must return a JSON array of{' '}
                            <code className="px-1 bg-gray-100 rounded text-[11px]">
                              {'{ speaker, text }'}
                            </code>{' '}
                            turns.
                          </>
                        )}
                      </p>
                      <ProviderModelPicker
                        kind="llm"
                        value={transcribeDiariserLLM}
                        onChange={setTranscribeDiariserLLM}
                        defaultLabel="Pick an LLM for diarisation"
                        allowCredentialPick
                        audioCapableOnly={transcribeMode === 'llm_only'}
                      />
                      <div className="flex items-center justify-between pt-1">
                        <label className="text-xs font-medium text-gray-700">
                          Diarisation prompt
                        </label>
                        <div className="flex items-center gap-3">
                          <button
                            type="button"
                            onClick={() => {
                              setPartialsImportError(null)
                              setSelectedPartialId('')
                              setPartialsSearchInput('')
                              setPartialsSearchQuery('')
                              setPartialsImportTarget('standalone')
                            }}
                            className="text-[11px] text-primary-600 hover:text-primary-700"
                          >
                            Import from saved partials
                          </button>
                          {defaultDiarisationPrompt && (
                            <button
                              type="button"
                              onClick={() =>
                                setTranscribeDiarisationPrompt(
                                  defaultDiarisationPrompt,
                                )
                              }
                              className="text-[11px] text-primary-600 hover:text-primary-700"
                            >
                              Reset to default
                            </button>
                          )}
                        </div>
                      </div>
                      <textarea
                        value={transcribeDiarisationPrompt}
                        onChange={(e) =>
                          setTranscribeDiarisationPrompt(e.target.value)
                        }
                        rows={10}
                        placeholder={
                          defaultDiarisationPrompt ||
                          'Describe how the LLM should split the transcript into agent / user turns…'
                        }
                        className="w-full px-3 py-2 text-xs font-mono border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                      />
                      <p className="text-[11px] text-gray-500">
                        Leave blank to fall back to the canonical default
                        prompt the worker ships with.
                      </p>
                    </div>
                    <label className="flex items-start gap-2 text-xs pt-2 border-t border-gray-100">
                      <input
                        type="checkbox"
                        className="mt-0.5"
                        checked={transcribeOverwriteStandalone}
                        onChange={(e) =>
                          setTranscribeOverwriteStandalone(e.target.checked)
                        }
                      />
                      <span>
                        Overwrite existing transcripts (otherwise rows
                        with a transcript are skipped).
                      </span>
                    </label>
                    {transcribeError && (
                      <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                        {transcribeError}
                      </div>
                    )}
                  </div>
                  <div className="px-6 py-4 border-t border-gray-200 flex gap-2 bg-gray-50 rounded-b-lg">
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
                          mode: transcribeMode,
                          stt: transcribeSTT,
                          diariserLLM: transcribeDiariserLLM,
                          diarisationPrompt: transcribeDiarisationPrompt,
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
            )
          })(),
        )}

      {showRunEval &&
        renderModal(
          (() => {
            const enabledMetrics = metrics.filter((m: any) => m.enabled)
            const disabledMetrics = metrics.filter((m: any) => !m.enabled)
            // Group the user's selection into "override targets" — one
            // entry per parent categorization metric (regardless of how
            // many of its labels are picked) and one entry per standalone
            // metric. This drives the per-metric LLM override UI: we
            // surface ONE picker per chosen metric, never one per label.
            // The picker keys overrides by parent id for hierarchical
            // metrics; the backend already accepts parent ids and
            // expands them to every child of that parent.
            type OverrideTarget = {
              id: string
              name: string
              isHierarchical: boolean
              selectedChildCount: number
            }
            const selectedSet = new Set(selectedMetricIds)
            const overrideTargets: OverrideTarget[] = []
            for (const metric of enabledMetrics as any[]) {
              const children: any[] = Array.isArray(metric.children)
                ? metric.children.filter((c: any) => c.enabled)
                : []
              const isHierarchical =
                !!metric.selection_mode && children.length > 0
              if (isHierarchical) {
                const selectedChildCount = children.filter((c: any) =>
                  selectedSet.has(c.id),
                ).length
                if (selectedChildCount > 0) {
                  overrideTargets.push({
                    id: metric.id,
                    name: metric.name,
                    isHierarchical: true,
                    selectedChildCount,
                  })
                }
              } else if (selectedSet.has(metric.id)) {
                overrideTargets.push({
                  id: metric.id,
                  name: metric.name,
                  isHierarchical: false,
                  selectedChildCount: 0,
                })
              }
            }
            const overrideTargetIds = new Set(
              overrideTargets.map((t) => t.id),
            )
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
                          <div className="flex items-center justify-between gap-2">
                            <p className="text-xs uppercase tracking-wide font-semibold text-gray-500">
                              Enabled metrics ({enabledMetrics.length})
                              <span
                                className="ml-1 text-red-600 normal-case"
                                aria-label="required"
                                title="At least one metric is required"
                              >
                                *
                              </span>
                            </p>
                            {selectedMetricIds.length === 0 ? (
                              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700 ring-1 ring-inset ring-amber-200">
                                <AlertCircle className="h-3 w-3" />
                                Pick at least one
                              </span>
                            ) : (
                              <span className="text-[10px] font-medium text-gray-500">
                                {selectedMetricIds.length} selected
                              </span>
                            )}
                          </div>
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
                        {(() => {
                          const llmPartial =
                            Boolean(runLLM.provider) !==
                            Boolean(runLLM.model)
                          return (
                            <div
                              className={`rounded-md border p-3 space-y-2 ${
                                llmPartial
                                  ? 'border-red-300 bg-red-50/40'
                                  : 'border-gray-200 bg-gray-50'
                              }`}
                            >
                              <p className="text-xs uppercase tracking-wide font-semibold text-gray-500">
                                Evaluation LLM
                              </p>
                              <p className="text-[11px] text-gray-500">
                                Pick the LLM that scores every selected
                                metric. Leave empty to keep the default
                                (OpenAI · gpt-4o).
                              </p>
                              <ProviderModelPicker
                                kind="llm"
                                value={runLLM}
                                onChange={setRunLLM}
                                defaultLabel="Default (OpenAI · gpt-4o)"
                                allowCredentialPick
                              />
                              {llmPartial && (
                                <p className="flex items-start gap-1 text-[11px] font-medium text-red-700">
                                  <AlertCircle className="h-3 w-3 mt-0.5 flex-shrink-0" />
                                  <span>
                                    {runLLM.provider
                                      ? 'Pick a model for this provider, or clear the provider to use the default.'
                                      : 'Pick a provider for this model, or clear the model to use the default.'}
                                  </span>
                                </p>
                              )}

                          {overrideTargets.length > 0 && (
                            <div className="pt-2 border-t border-gray-200">
                              <button
                                type="button"
                                onClick={() => setShowAdvancedLLM((s) => !s)}
                                className="text-[11px] font-medium text-primary-700 hover:text-primary-900"
                              >
                                {showAdvancedLLM ? 'Hide' : 'Show'} per-metric overrides
                                ({overrideTargets.length} metric
                                {overrideTargets.length === 1 ? '' : 's'})
                              </button>
                              {showAdvancedLLM && (
                                <div className="mt-2 space-y-3">
                                  {overrideTargets.map((target) => {
                                    const override = metricLLMOverrides[
                                      target.id
                                    ] || {
                                      provider: null,
                                      model: null,
                                      credential_id: null,
                                    }
                                    return (
                                      <div
                                        key={target.id}
                                        className="rounded border border-gray-200 bg-white p-2"
                                      >
                                        <p className="text-xs font-medium text-gray-800 mb-1">
                                          {target.name}
                                          {target.isHierarchical && (
                                            <span className="ml-2 text-[10px] font-normal text-gray-500">
                                              ({target.selectedChildCount} label
                                              {target.selectedChildCount === 1
                                                ? ''
                                                : 's'}{' '}
                                              selected)
                                            </span>
                                          )}
                                        </p>
                                        <ProviderModelPicker
                                          kind="llm"
                                          value={override}
                                          onChange={(next) => {
                                            setMetricLLMOverrides((prev) => {
                                              const copy = { ...prev }
                                              if (!next.provider && !next.model) {
                                                delete copy[target.id]
                                              } else {
                                                copy[target.id] = next
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
                          )
                        })()}

                        {/* Diarisation is now mandatory for every eval
                            run — the checkbox is shown as always-on
                            (matching the spec) so the user knows the
                            STT picker below is required. The legacy
                            "Production vs Diarised" transcript-source
                            selector has been removed: runs always
                            score the diarised transcript. */}
                        {(() => {
                          // In ``llm_only`` mode there is no STT —
                          // the diariser LLM consumes the audio
                          // directly. We adapt the "is the auto-
                          // diarise step ready?" check to reflect
                          // that so the banner doesn't yell about a
                          // missing STT picker that's intentionally
                          // hidden.
                          const sttMissing =
                            evalTranscribeMode === 'stt_llm' &&
                            (!evalSTT.provider || !evalSTT.model)
                          const diariserMissing =
                            !evalDiariserLLM.provider || !evalDiariserLLM.model
                          const sectionIncomplete = sttMissing || (
                            evalTranscribeMode === 'llm_only' && diariserMissing
                          )
                          return (
                            <div
                              className={`rounded-md border p-3 space-y-2 ${
                                sectionIncomplete
                                  ? 'border-red-300 bg-red-50/40 ring-1 ring-red-200'
                                  : 'border-gray-200 bg-gray-50'
                              }`}
                            >
                              <label className="flex items-start gap-2 text-sm">
                                <input
                                  type="checkbox"
                                  checked
                                  disabled
                                  readOnly
                                  className="mt-0.5"
                                  aria-label="Auto-diarise rows missing a diarised transcript (always on)"
                                />
                                <span className="flex-1">
                                  <span className="flex items-center gap-2 flex-wrap">
                                    <span className="font-medium text-gray-900">
                                      Auto-diarise rows missing a diarised
                                      transcript
                                    </span>
                                    <span
                                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${
                                        sectionIncomplete
                                          ? 'bg-red-100 text-red-700 ring-1 ring-inset ring-red-200'
                                          : 'bg-green-50 text-green-700 ring-1 ring-inset ring-green-200'
                                      }`}
                                    >
                                      {sectionIncomplete ? 'Required' : 'Set'}
                                    </span>
                                  </span>
                                  <span className="block text-[11px] text-gray-500">
                                    {evalTranscribeMode === 'stt_llm'
                                      ? "Every evaluation scores the diarised transcript. Rows that don't already have one are diarised first via the STT provider you pick below."
                                      : "Every evaluation scores the diarised transcript. Rows that don't already have one are diarised by feeding the audio directly to the multimodal LLM you pick below."}
                                  </span>
                                </span>
                              </label>
                              <div className="pl-6 space-y-2">
                                {/* Mode toggle. Hidden behind the
                                    "Auto-diarise" checkbox row so the
                                    flow reads top-to-bottom: enable
                                    auto-diarise → pick pipeline → pick
                                    models. */}
                                {/* Same ordering rationale as the
                                    standalone Transcribe modal:
                                    LLM-only is the recommended default
                                    and STT+LLM is the advanced
                                    fallback. */}
                                <div
                                  role="tablist"
                                  aria-label="Auto-diarise pipeline"
                                  className="inline-flex rounded-lg border border-gray-200 bg-white p-0.5"
                                >
                                  <button
                                    type="button"
                                    role="tab"
                                    aria-pressed={evalTranscribeMode === 'llm_only'}
                                    onClick={() =>
                                      setEvalTranscribeMode('llm_only')
                                    }
                                    className={`px-3 py-1 text-[11px] font-medium rounded-md transition ${
                                      evalTranscribeMode === 'llm_only'
                                        ? 'bg-primary-50 text-primary-700 ring-1 ring-inset ring-primary-200'
                                        : 'text-gray-600 hover:text-gray-900'
                                    }`}
                                  >
                                    LLM only (audio in)
                                  </button>
                                  <button
                                    type="button"
                                    role="tab"
                                    aria-pressed={evalTranscribeMode === 'stt_llm'}
                                    onClick={() =>
                                      setEvalTranscribeMode('stt_llm')
                                    }
                                    className={`px-3 py-1 text-[11px] font-medium rounded-md transition inline-flex items-center gap-1.5 ${
                                      evalTranscribeMode === 'stt_llm'
                                        ? 'bg-primary-50 text-primary-700 ring-1 ring-inset ring-primary-200'
                                        : 'text-gray-600 hover:text-gray-900'
                                    }`}
                                  >
                                    STT + LLM diariser
                                    <span className="rounded-full bg-gray-200 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-gray-600">
                                      Advanced
                                    </span>
                                  </button>
                                </div>
                                {evalTranscribeMode === 'stt_llm' && (
                                  <>
                                    <ProviderModelPicker
                                      kind="stt"
                                      value={evalSTT}
                                      onChange={setEvalSTT}
                                      providerAllowList={STT_PROVIDER_ALLOWLIST}
                                      defaultLabel="Pick an STT provider"
                                      allowCredentialPick
                                    />
                                    {sttMissing && (
                                      <p className="flex items-start gap-1 text-[11px] font-medium text-red-700">
                                        <AlertCircle className="h-3 w-3 mt-0.5 flex-shrink-0" />
                                        <span>
                                          {!evalSTT.provider
                                            ? 'Pick an STT provider — auto-diarisation is mandatory for every run.'
                                            : 'Pick a model for this STT provider to enable the run.'}
                                        </span>
                                      </p>
                                    )}
                                    <input
                                      type="text"
                                      value={evalSTTLanguage}
                                      onChange={(e) =>
                                        setEvalSTTLanguage(e.target.value)
                                      }
                                      placeholder="Language hint (e.g. en, hi)"
                                      className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                                    />
                                  </>
                                )}
                                <label className="flex items-start gap-2 text-xs">
                                  <input
                                    type="checkbox"
                                    checked={transcribeOverwrite}
                                    onChange={(e) =>
                                      setTranscribeOverwrite(e.target.checked)
                                    }
                                  />
                                  <span>
                                    Overwrite existing diarised transcripts
                                    (otherwise rows with a stored transcript
                                    are reused).
                                  </span>
                                </label>
                                <div className="pt-3 border-t border-gray-200 space-y-2">
                                  <p className="text-xs font-medium text-gray-700">
                                    {evalTranscribeMode === 'stt_llm'
                                      ? 'Diariser LLM'
                                      : 'Multimodal diariser LLM'}
                                  </p>
                                  <p className="text-[11px] text-gray-500">
                                    {evalTranscribeMode === 'stt_llm'
                                      ? 'After the STT step, this chat model splits the plain transcript into agent / user turns using the prompt below.'
                                      : 'This chat model receives the audio bytes and the prompt and produces structured agent / user turns in one call. Pick a model that accepts audio input (e.g. Gemini 1.5/2.0 or GPT-4o audio-preview).'}
                                  </p>
                                  <ProviderModelPicker
                                    kind="llm"
                                    value={evalDiariserLLM}
                                    onChange={setEvalDiariserLLM}
                                    defaultLabel="Pick an LLM for diarisation"
                                    allowCredentialPick
                                    audioCapableOnly={evalTranscribeMode === 'llm_only'}
                                  />
                                  <div className="flex items-center justify-between pt-1">
                                    <label className="text-[11px] font-medium text-gray-700">
                                      Diarisation prompt
                                    </label>
                                    <div className="flex items-center gap-3">
                                      <button
                                        type="button"
                                        onClick={() => {
                                          setPartialsImportError(null)
                                          setSelectedPartialId('')
                                          setPartialsSearchInput('')
                                          setPartialsSearchQuery('')
                                          setPartialsImportTarget('eval')
                                        }}
                                        className="text-[11px] text-primary-600 hover:text-primary-700"
                                      >
                                        Import from saved partials
                                      </button>
                                      {defaultDiarisationPrompt && (
                                        <button
                                          type="button"
                                          onClick={() =>
                                            setEvalDiarisationPrompt(
                                              defaultDiarisationPrompt,
                                            )
                                          }
                                          className="text-[11px] text-primary-600 hover:text-primary-700"
                                        >
                                          Reset to default
                                        </button>
                                      )}
                                    </div>
                                  </div>
                                  <textarea
                                    value={evalDiarisationPrompt}
                                    onChange={(e) =>
                                      setEvalDiarisationPrompt(e.target.value)
                                    }
                                    rows={6}
                                    placeholder={
                                      defaultDiarisationPrompt ||
                                      'Describe how the LLM should split the transcript into agent / user turns…'
                                    }
                                    className="w-full px-3 py-2 text-[11px] font-mono border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                                  />
                                  <p className="text-[11px] text-gray-500">
                                    Leave blank to fall back to the
                                    canonical default prompt.
                                  </p>
                                </div>
                              </div>
                            </div>
                          )
                        })()}

                        {/* Metric discovery (opt-in per run). When
                            enabled, the LLM is asked once per row to
                            surface candidate top-level metrics
                            beyond the ones selected above; the
                            results show up in the Discovered metrics
                            panel on the evaluation detail Flow tab
                            where they can be promoted into real
                            Metric rows. */}
                        <div className="rounded-md border border-amber-200 bg-amber-50/40 p-3 space-y-2">
                          <label className="flex items-start gap-2 text-sm">
                            <input
                              type="checkbox"
                              checked={discoverNewMetrics}
                              onChange={(e) =>
                                setDiscoverNewMetrics(e.target.checked)
                              }
                              className="mt-0.5 h-4 w-4 text-amber-600 focus:ring-amber-500 border-gray-300 rounded"
                            />
                            <span>
                              <span className="font-medium text-gray-900">
                                Discover new metrics
                              </span>
                              <span className="block text-[11px] text-gray-600 mt-0.5">
                                Asks the LLM to propose brand-new
                                top-level metrics it noticed in each
                                transcript (boolean / rating /
                                category). Candidates appear in the
                                Discovered metrics panel on the Flow
                                tab and can be promoted into real
                                Metric rows.
                              </span>
                            </span>
                          </label>
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

                    {(() => {
                      const disabledReasons: string[] = []
                      if (enabledMetrics.length === 0) {
                        disabledReasons.push(
                          'Enable at least one agent metric in Metrics.',
                        )
                      } else if (selectedMetricIds.length === 0) {
                        disabledReasons.push('Select at least one metric to score.')
                      }
                      // STT is only required in the legacy two-stage
                      // mode. ``llm_only`` mode feeds the audio
                      // straight to the diariser LLM, so the STT
                      // checks are gated on the active mode.
                      if (evalTranscribeMode === 'stt_llm') {
                        if (!evalSTT.provider) {
                          disabledReasons.push(
                            'Pick an STT provider (auto-diarisation is required).',
                          )
                        } else if (!evalSTT.model) {
                          disabledReasons.push(
                            'Pick an STT model for the selected provider.',
                          )
                        }
                      }
                      if (!evalDiariserLLM.provider) {
                        disabledReasons.push(
                          evalTranscribeMode === 'llm_only'
                            ? 'Pick a multimodal LLM provider — the recording is fed to it directly in LLM-only mode.'
                            : 'Pick a diariser LLM provider — the STT output is split into agent / user turns by an LLM.',
                        )
                      } else if (!evalDiariserLLM.model) {
                        disabledReasons.push(
                          'Pick a diariser LLM model for the selected provider.',
                        )
                      }
                      if (
                        Boolean(runLLM.provider) !== Boolean(runLLM.model)
                      ) {
                        disabledReasons.push(
                          'Finish the Evaluation LLM selection (pick both a provider and a model, or clear both).',
                        )
                      }
                      const isDisabled =
                        disabledReasons.length > 0 ||
                        runEvaluationMutation.isPending
                      return (
                        <>
                          {disabledReasons.length > 0 && (
                            <div
                              role="status"
                              className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
                            >
                              <p className="flex items-center gap-1.5 font-medium">
                                <AlertCircle className="h-4 w-4" />
                                Finish the required fields to start this run
                              </p>
                              <ul className="mt-1 list-disc pl-7 space-y-0.5 text-[12px]">
                                {disabledReasons.map((reason) => (
                                  <li key={reason}>{reason}</li>
                                ))}
                              </ul>
                            </div>
                          )}

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
                              disabled={isDisabled}
                              title={
                                disabledReasons.length > 0
                                  ? `Can't start yet:\n• ${disabledReasons.join('\n• ')}`
                                  : 'Start this evaluation run'
                              }
                        onClick={() => {
                          // Build a clean overrides payload — drop any
                          // entries that didn't end up with both a
                          // provider and a model set so the API doesn't
                          // 400 on partial fills. We also discard
                          // entries for ids that are no longer in
                          // ``overrideTargets`` (e.g., the user set an
                          // override for a parent then deselected every
                          // one of its labels) so stale state doesn't
                          // trip backend validation.
                          const overrides: Record<
                            string,
                            CallImportEvaluationLLMOverride
                          > = {}
                          for (const [mid, val] of Object.entries(
                            metricLLMOverrides,
                          )) {
                            if (!overrideTargetIds.has(mid)) continue
                            if (val.provider && val.model) {
                              overrides[mid] = {
                                provider: val.provider,
                                model: val.model,
                                credential_id: val.credential_id || null,
                              }
                            }
                          }
                          runEvaluationMutation.mutate({
                            metric_ids: selectedMetricIds,
                            name: runDraftName.trim() || null,
                            // Diarised is the only supported source
                            // now; the backend rejects anything else.
                            transcript_sources: ['diarised'],
                            llm_provider: runLLM.provider || null,
                            llm_model: runLLM.model || null,
                            llm_credential_id: runLLM.credential_id || null,
                            metric_llm_overrides: Object.keys(overrides).length
                              ? overrides
                              : null,
                            // Auto-diarise is always on; ``transcribe_mode``
                            // decides whether the STT step actually runs
                            // (and therefore whether the STT fields are
                            // sent or nulled out for the backend's
                            // validator).
                            auto_transcribe: true,
                            transcribe_overwrite: transcribeOverwrite,
                            transcribe_mode: evalTranscribeMode,
                            stt_provider:
                              evalTranscribeMode === 'stt_llm'
                                ? evalSTT.provider
                                : null,
                            stt_model:
                              evalTranscribeMode === 'stt_llm'
                                ? evalSTT.model
                                : null,
                            stt_credential_id:
                              evalTranscribeMode === 'stt_llm'
                                ? evalSTT.credential_id || null
                                : null,
                            stt_language:
                              evalTranscribeMode === 'stt_llm'
                                ? evalSTTLanguage.trim() || null
                                : null,
                            diarization_llm_provider:
                              evalDiariserLLM.provider,
                            diarization_llm_model: evalDiariserLLM.model,
                            diarization_llm_credential_id:
                              evalDiariserLLM.credential_id || null,
                            diarization_prompt:
                              evalDiarisationPrompt.trim() || null,
                            discover_new_metrics: discoverNewMetrics,
                          })
                        }}
                              className="flex-1"
                            >
                              Start
                            </Button>
                          </div>
                        </>
                      )
                    })()}
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
          const callId = pendingDeleteRow.conversation_id
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

      {/*
        Consolidated bulk-actions modal.

        Rationale: instead of growing the toolbar with one button per
        verb (Transcribe / Stop / Delete / …), the toolbar exposes a
        single "Bulk actions" entry point that opens this modal. Each
        action lives in its own card, shows the count of rows it'll
        actually affect (with a "selection spans pages" disclaimer
        when we can only see the on-page slice), and either fires
        immediately (Stop) or hands off to the existing dedicated
        modal (Transcribe → Diarise modal, Delete → ConfirmModal) so
        all the per-flow validation / config UI is preserved.
       */}
      {showBulkActionsModal &&
        selectedCount > 0 &&
        renderModal(
          <div
            className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-50"
            onClick={() => {
              if (bulkCancelDiarisationMutation.isPending) return
              setShowBulkActionsModal(false)
              setBulkActionError(null)
              setBulkActionResult(null)
            }}
          >
            <div
              className="bg-white rounded-lg shadow-xl max-w-xl w-full mx-4 max-h-[85vh] overflow-hidden flex flex-col"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-start gap-3">
                <div className="min-w-0">
                  <h3 className="text-lg font-semibold text-gray-900">
                    Bulk actions
                  </h3>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {selectedCount} row{selectedCount === 1 ? '' : 's'}{' '}
                    selected
                    {selectionSpansPages
                      ? ' · selection spans pages (per-action counts below are for on-page rows only; the backend filters the rest)'
                      : ''}
                    .
                  </p>
                </div>
                <button
                  onClick={() => {
                    if (bulkCancelDiarisationMutation.isPending) return
                    setShowBulkActionsModal(false)
                    setBulkActionError(null)
                    setBulkActionResult(null)
                  }}
                  className="text-gray-400 hover:text-gray-600 flex-shrink-0"
                  aria-label="Close bulk actions modal"
                  disabled={bulkCancelDiarisationMutation.isPending}
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="p-5 space-y-3 overflow-y-auto flex-1">
                {/*
                  Action card 1 — Diarise / re-diarise.

                  ``transcribeReadySelection`` counts on-page rows that
                  have a recording AND aren't already in-flight. With
                  cross-page selections we hand off the full
                  ``selectedRowIds`` set and rely on the worker's
                  server-side filter to skip rows that don't qualify.
                 */}
                <div className="rounded-lg border border-gray-200 p-4 hover:border-purple-300 hover:bg-purple-50/40 transition-colors">
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-purple-100 text-purple-700 flex items-center justify-center">
                      <Mic className="h-5 w-5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-semibold text-gray-900">
                        Diarise / re-diarise
                      </h4>
                      <p className="text-xs text-gray-600 mt-1">
                        {selectionSpansPages
                          ? `Run diarisation on the ${selectedCount} selected rows. Rows without a recording or already in flight are skipped server-side.`
                          : transcribeReadySelection.length === 0
                          ? 'No rows in this selection are ready to diarise (each is either missing a recording or already in flight).'
                          : `${transcribeReadySelection.length} of ${selectedCount} selected row${
                              selectedCount === 1 ? '' : 's'
                            } can be diarised right now. The rest will be skipped.`}
                      </p>
                    </div>
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={
                        !selectionSpansPages &&
                        transcribeReadySelection.length === 0
                      }
                      onClick={() => {
                        setShowBulkActionsModal(false)
                        setBulkActionError(null)
                        setBulkActionResult(null)
                        if (selectionSpansPages) {
                          // Cross-page selection: forward synthetic
                          // rows (id-only) so the modal targets the
                          // batch endpoint without inventing fake
                          // row_index values for the header label.
                          openTranscribeModal(
                            Array.from(selectedRowIds).map(
                              (rowId) =>
                                ({
                                  id: rowId,
                                  row_index: 0,
                                } as unknown as CallImportRow),
                            ),
                          )
                        } else {
                          openTranscribeModal(transcribeReadySelection)
                        }
                      }}
                      className="flex-shrink-0"
                    >
                      Diarise
                    </Button>
                  </div>
                </div>

                {/*
                  Action card 2 — Stop diarisation.

                  The button is disabled when there's nothing in flight
                  on the visible page; for cross-page selections we
                  allow the click and let the server's
                  ``cancelled / skipped`` summary do the talking.
                 */}
                <div className="rounded-lg border border-gray-200 p-4 hover:border-amber-300 hover:bg-amber-50/40 transition-colors">
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center">
                      <Square className="h-5 w-5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-semibold text-gray-900">
                        Stop diarisation
                      </h4>
                      <p className="text-xs text-gray-600 mt-1">
                        {selectionSpansPages
                          ? `Revoke any in-flight or queued diarisation across the ${selectedCount} selected rows. Rows that finished already are skipped.`
                          : cancellableSelection.length === 0
                          ? 'No rows in this selection are currently queued or running. Nothing to stop.'
                          : `Stop diarisation for ${cancellableSelection.length} pending / running row${
                              cancellableSelection.length === 1 ? '' : 's'
                            }. Each row is flipped to "failed" with a "Cancelled by user" message.`}
                      </p>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      isLoading={bulkCancelDiarisationMutation.isPending}
                      disabled={
                        bulkCancelDiarisationMutation.isPending ||
                        (!selectionSpansPages &&
                          cancellableSelection.length === 0)
                      }
                      onClick={() => {
                        if (bulkCancelDiarisationMutation.isPending) return
                        // For on-page selections we narrow to the
                        // cancellable subset so the server doesn't
                        // need to discover skips; for cross-page we
                        // send everything and let the server filter.
                        const ids = selectionSpansPages
                          ? Array.from(selectedRowIds)
                          : cancellableSelection.map((r) => r.id)
                        if (ids.length === 0) return
                        bulkCancelDiarisationMutation.mutate(ids)
                      }}
                      className="flex-shrink-0 text-amber-700 border-amber-300 hover:bg-amber-50"
                    >
                      Stop
                    </Button>
                  </div>
                </div>

                {/*
                  Action card 3 — Delete rows.

                  We close THIS modal and hand off to the existing
                  ConfirmModal so the destructive flow keeps its
                  "type-aware confirm" behaviour. No duplication of
                  the irreversible-action copy here.
                 */}
                <div className="rounded-lg border border-gray-200 p-4 hover:border-red-300 hover:bg-red-50/40 transition-colors">
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-red-100 text-red-700 flex items-center justify-center">
                      <Trash2 className="h-5 w-5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-semibold text-gray-900">
                        Delete rows
                      </h4>
                      <p className="text-xs text-gray-600 mt-1">
                        Permanently remove {selectedCount} selected row
                        {selectedCount === 1 ? '' : 's'} from this import,
                        along with their stored recordings in S3. In-flight
                        tasks for these rows will be revoked. This cannot
                        be undone.
                      </p>
                    </div>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => {
                        setShowBulkActionsModal(false)
                        setBulkActionError(null)
                        setBulkActionResult(null)
                        setBulkDeleteRowsError(null)
                        setShowBulkDeleteRows(true)
                      }}
                      className="flex-shrink-0"
                    >
                      Delete
                    </Button>
                  </div>
                </div>

                {bulkActionResult && (
                  <div className="rounded-md border border-green-200 bg-green-50 p-3 text-xs text-green-800 flex items-start gap-2">
                    <Check className="h-4 w-4 text-green-600 flex-shrink-0 mt-0.5" />
                    <div className="min-w-0 flex-1">{bulkActionResult}</div>
                    <button
                      type="button"
                      onClick={() => setBulkActionResult(null)}
                      className="text-green-700 hover:text-green-900 flex-shrink-0"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}

                {bulkActionError && (
                  <div className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-800 flex items-start gap-2">
                    <AlertCircle className="h-4 w-4 text-red-600 flex-shrink-0 mt-0.5" />
                    <div className="min-w-0 flex-1">{bulkActionError}</div>
                    <button
                      type="button"
                      onClick={() => setBulkActionError(null)}
                      className="text-red-700 hover:text-red-900 flex-shrink-0"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
              </div>

              <div className="px-6 py-3 border-t border-gray-200 bg-gray-50 flex justify-end">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={bulkCancelDiarisationMutation.isPending}
                  onClick={() => {
                    if (bulkCancelDiarisationMutation.isPending) return
                    setShowBulkActionsModal(false)
                    setBulkActionError(null)
                    setBulkActionResult(null)
                  }}
                >
                  Close
                </Button>
              </div>
            </div>
          </div>,
        )}
    </div>
  )
}

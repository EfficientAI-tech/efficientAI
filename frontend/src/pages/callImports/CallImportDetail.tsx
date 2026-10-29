import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ArrowLeft, RefreshCw } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { itemsOf } from '../../lib/safeData'
import { getApiErrorMessage } from '../../lib/apiErrors'
import { useToast } from '../../hooks/useToast'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { CallImportEvaluation, CallImportRow } from '../../types/api'
import { type ProviderModelValue } from '../../components/providers/ProviderModelPicker'
import { resolveLLMModelForSubmit } from '../../lib/llmModelOptions'
import PlatformImportProgressDock from './components/PlatformImportProgressDock'
import { usePlatformImportProgressStore } from '../../store/platformImportProgressStore'
import RetryFailedImportModal from './components/RetryFailedImportModal'
import UploadAudioModal from './components/UploadAudioModal'
import MappingPanel from './components/MappingPanel'
import RunEvaluationStep from './components/RunEvaluationStep'
import StageTracker from './components/StageTracker'
import ImportRowsTab from './components/ImportRowsTab'
import ImportEvaluationsTab from './components/ImportEvaluationsTab'
import ImportInsightsTab from './components/ImportInsightsTab'
import { useImportDetailRows } from './hooks/useImportDetailRows'
import { isImportCredentialError } from './components/importDetail/isImportCredentialError'
import { ImportDetailHeader } from './components/importDetail/ImportDetailHeader'
import { ImportTranscribeModals } from './components/importDetail/ImportTranscribeModals'
import { ImportDeleteConfirmModals } from './components/importDetail/ImportDeleteConfirmModals'
import { ImportRunEvaluationModal } from './components/importDetail/ImportRunEvaluationModal'
import { useImportEvaluationsTab } from './hooks/useImportEvaluationsTab'
import { evaluationListPollMs } from './evaluationBulkOperation'




export default function CallImportDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)


  const {
    data,
    isLoading,
    isFetching: headerFetching,
    refetch: refetchHeader,
    error,
  } = useQuery({
    queryKey: ['call-import', activeWorkspaceId, id],
    queryFn: () => apiClient.callImports.getCallImport(id!, { row_limit: 0, row_offset: 0 }),
    enabled: !!id,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const d = query.state.data
      if (!d) return false
      if (d.status === 'deleting') return 4000
      const platform = (d.source_format || '').toLowerCase() === 'platform'
      if (
        platform &&
        (d.status === 'pending' ||
          d.status === 'processing' ||
          d.platform_progress?.is_active)
      ) {
        return 4000
      }
      if (d.status === 'pending' || d.status === 'processing') return 5000
      const diariseInFlight =
        (d.diarised_pending_rows ?? 0) + (d.diarised_running_rows ?? 0)
      if (diariseInFlight > 0) return 4000
      if (
        d.status === 'completed' ||
        d.status === 'failed' ||
        d.status === 'mapped'
      ) {
        return false
      }
      return false
    },
  })

  const {
    rowOffset,
    setRowOffset,
    selectedRowId,
    setSelectedRowId,
    rowPanelTab,
    setRowPanelTab,
    copiedRowId,
    copiedTranscriptField,
    handleCopyConversationId,
    handleCopyTranscript,
    rowSearchInput,
    setRowSearchInput,
    rowSearchQuery,
    diarisedStatusFilter,
    setDiarisedStatusFilter,
    selectedRowIds,
    setSelectedRowIds,
    bulkSelectionFilter,
    setBulkSelectionFilter,
    selectAllError,
    setSelectAllError,
    rowsPage,
    rowsLoading,
    rowsFetching,
    refetchRows,
    rows,
    selectedRow,
    selectedRowDetail,
    filteredTotalRows,
    hasActiveFilter,
    rowPage,
    rowTotalPages,
    listRowFilter,
    selectedCount,
    selectedOnPageCount,
    allOnPageSelected,
    allMatchingSelected,
    transcribeReadySelection,
    cancellableSelection,
    selectionSpansPages,
  } = useImportDetailRows(id ?? '', activeWorkspaceId, data)


  const [showBulkDeleteRows, setShowBulkDeleteRows] = useState(false)
  const [bulkDeleteRowsError, setBulkDeleteRowsError] = useState<string | null>(
    null,
  )

  const reportDeleteError = (
    err: unknown,
    fallback: string,
    setError: (message: string) => void,
  ) => {
    const message = getApiErrorMessage(err, fallback)
    setError(message)
    showToast(message, 'error')
  }
  const [showDeleteImport, setShowDeleteImport] = useState(false)
  const [showAppendAudioModal, setShowAppendAudioModal] = useState(false)
  const [showRetryFailedImportConfirm, setShowRetryFailedImportConfirm] =
    useState(false)
  const [retryFailedImportError, setRetryFailedImportError] = useState<string | null>(
    null,
  )
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
  // System 1 (Jev) model used for classification metrics in the run.
  const [classificationLLM, setClassificationLLM] = useState<ProviderModelValue>({
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
  const [evalTranscriptSource, setEvalTranscriptSource] = useState<
    'production' | 'diarised'
  >('diarised')
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
  const [evalTelephonyProvider, setEvalTelephonyProvider] = useState('')
  const [evalTelephonyIntegrationId, setEvalTelephonyIntegrationId] = useState('')
  const [activeTab, setActiveTab] = useState<
    'rows' | 'evaluations' | 'insights'
  >('rows')

  const {
    evaluationsData,
    evaluationsWithBulkOperation,
    selectedEvalIds,
    setSelectedEvalIds,
    showBulkDeleteEvals,
    setShowBulkDeleteEvals,
    bulkDeleteEvalsError,
    setBulkDeleteEvalsError,
    bulkDeleteEvalsMutation,
    cancellingEvalId,
    cancelEvaluationMutation,
    bulkCancelEvalsMutation,
  } = useImportEvaluationsTab(id, activeWorkspaceId, activeTab, reportDeleteError)

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

  // Prompt-partial *save* sub-modal. Mirrors the import sub-modal but
  // pushes the current textarea content back into the Prompt Partials
  // library. ``target`` decides which textarea sources the content;
  // ``mode`` chooses between creating a brand-new partial and updating
  // an existing one (which appends a new version under the hood).
  const [savePartialTarget, setSavePartialTarget] = useState<
    'standalone' | 'eval' | null
  >(null)
  const [savePartialMode, setSavePartialMode] = useState<'new' | 'existing'>(
    'new',
  )
  const [savePartialName, setSavePartialName] = useState('')
  const [savePartialDescription, setSavePartialDescription] = useState('')
  const [savePartialChangeSummary, setSavePartialChangeSummary] = useState('')
  const [savePartialExistingId, setSavePartialExistingId] = useState<string>('')
  const [savePartialError, setSavePartialError] = useState<string | null>(null)
  const [savePartialSuccess, setSavePartialSuccess] = useState<string | null>(
    null,
  )

  // The canonical default diariser prompt. Fetched once when the
  // modal opens so the textarea can pre-fill with the *actual*
  // server-side default rather than a duplicated hardcoded copy.
  const { data: defaultDiarisationPrompt } = useQuery({
    queryKey: ['call-import-diarisation-prompt-default'],
    queryFn: () => apiClient.callImports.getCallImportDiarisationPromptDefault(),
    staleTime: Infinity,
  })

  const openRunEvaluationModal = useCallback(() => {
    setSelectedMetricIds([])
    setRunLLM({ provider: null, model: null, credential_id: null })
    setClassificationLLM({ provider: null, model: null, credential_id: null })
    void queryClient.invalidateQueries({ queryKey: ['ai-providers'] })
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
  }, [
    defaultDiarisationPrompt,
    evalDiariserLLM.provider,
    evalDiarisationPrompt,
    queryClient,
  ])

  const runEvaluationStepRef = useRef<HTMLDivElement>(null)
  const [highlightRunEvaluation, setHighlightRunEvaluation] = useState(false)
  const [pendingScrollToEvaluation, setPendingScrollToEvaluation] = useState(false)

  const handleMappingSaved = useCallback(() => {
    showToast('Mapping saved. Continue with Run Evaluation below.', 'success')
    setHighlightRunEvaluation(true)
    setPendingScrollToEvaluation(true)
    window.setTimeout(() => setHighlightRunEvaluation(false), 4000)
  }, [showToast])

  const { data: aiProviders = [] } = useQuery({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const [editingMeta, setEditingMeta] = useState(false)
  const [draftImportName, setDraftImportName] = useState('')
  const [draftDataset, setDraftDataset] = useState('')
  const [draftTagIds, setDraftTagIds] = useState<string[]>([])

  const { data: existingDatasets = [] } = useQuery({
    queryKey: ['call-import-datasets', activeWorkspaceId],
    queryFn: () => apiClient.callImports.listCallImportDatasets(),
    enabled: editingMeta,
  })

  const { data: allTags = [] } = useQuery({
    queryKey: ['call-import-tags', activeWorkspaceId],
    queryFn: () => apiClient.callImports.listCallImportTags(),
  })

  const updateMetaMutation = useMutation({
    mutationFn: (payload: {
      original_filename?: string | null
      dataset?: string | null
      tag_ids?: string[]
    }) => apiClient.callImports.updateCallImport(id!, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-import', activeWorkspaceId, id] })
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      queryClient.invalidateQueries({ queryKey: ['call-import-datasets'] })
      setEditingMeta(false)
    },
  })

  const deleteImportMutation = useMutation({
    mutationFn: (importId: string) => apiClient.callImports.deleteCallImport(importId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      queryClient.invalidateQueries({ queryKey: ['call-import', activeWorkspaceId, id] })
      if (result.status === 'accepted') {
        showToast(
          'Deletion started — large imports may take a minute.',
          'success',
        )
      }
      navigate('/call-imports')
    },
    onError: (err: unknown) => {
      reportDeleteError(err, 'Failed to delete import.', setDeleteError)
    },
  })

  const retryFailedImportMutation = useMutation({
    mutationFn: (selection: {
      provider: string | null
      telephonyIntegrationId: string | null
    }) =>
      apiClient.callImports.retryFailedCallImportRows(id!, selection),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['call-import', activeWorkspaceId, id] })
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      setShowRetryFailedImportConfirm(false)
      const parts = [`Re-queued ${result.requeued} failed row${result.requeued === 1 ? '' : 's'}`]
      if (result.enqueue_failed > 0) {
        parts.push(`enqueue failed for ${result.enqueue_failed}`)
      }
      if (result.skipped > 0) {
        parts.push(`skipped ${result.skipped}`)
      }
      setRetryFailedImportError(null)
      setBulkActionResult(parts.join(' · '))
    },
    onError: (err: any) => {
      setRetryFailedImportError(
        err?.response?.data?.detail ||
          err?.message ||
          'Failed to retry failed import rows.',
      )
    },
  })

  const deleteRowMutation = useMutation({
    mutationFn: ({ importId, rowId }: { importId: string; rowId: string }) =>
      apiClient.callImports.deleteCallImportRow(importId, rowId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-import', activeWorkspaceId, id] })
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      setPendingDeleteRow(null)
      setDeleteError(null)
    },
    onError: (err: unknown) => {
      reportDeleteError(err, 'Failed to delete row.', setDeleteError)
    },
  })

  const bulkDeleteRowsMutation = useMutation({
    mutationFn: (target: { rowIds?: string[]; rowFilter?: { q?: string; diarised_status?: string } }) =>
      target.rowFilter
        ? apiClient.callImports.bulkDeleteCallImportRows(id!, { rowFilter: target.rowFilter })
        : apiClient.callImports.bulkDeleteCallImportRows(id!, { rowIds: target.rowIds ?? [] }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-import', activeWorkspaceId, id] })
      queryClient.invalidateQueries({ queryKey: ['call-imports'] })
      setSelectedRowIds(new Set())
      setShowBulkDeleteRows(false)
      setBulkDeleteRowsError(null)
    },
    onError: (err: unknown) => {
      reportDeleteError(
        err,
        'Failed to delete selected rows.',
        setBulkDeleteRowsError,
      )
    },
  })


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
    enabled:
      partialsImportTarget !== null ||
      (savePartialTarget !== null && savePartialMode === 'existing'),
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

  // Mutation backing the "Save as partial" sub-modal. The body shape
  // depends on ``savePartialMode``: ``new`` calls ``createPromptPartial``
  // with a fresh name/description, ``existing`` calls
  // ``updatePromptPartial`` against the selected partial which appends
  // a new version to its history.
  const savePartialMutation = useMutation({
    mutationFn: async (input: {
      content: string
      mode: 'new' | 'existing'
      name?: string
      description?: string
      partialId?: string
      changeSummary?: string
    }) => {
      if (input.mode === 'new') {
        return apiClient.createPromptPartial({
          name: input.name || 'Untitled diarisation prompt',
          description: input.description || undefined,
          content: input.content,
        })
      }
      return apiClient.updatePromptPartial(input.partialId!, {
        content: input.content,
        change_summary: input.changeSummary || undefined,
      })
    },
    onSuccess: (partial: any) => {
      queryClient.invalidateQueries({
        queryKey: ['call-import-prompt-partials'],
      })
      const label =
        partial?.name || (savePartialMode === 'new' ? 'new partial' : 'partial')
      setSavePartialSuccess(
        savePartialMode === 'new'
          ? `Saved as new prompt partial “${label}”.`
          : `Updated prompt partial “${label}” (new version saved).`,
      )
      setSavePartialError(null)
      // Auto-close shortly after so the user sees the confirmation.
      setTimeout(() => {
        setSavePartialTarget(null)
        setSavePartialMode('new')
        setSavePartialName('')
        setSavePartialDescription('')
        setSavePartialChangeSummary('')
        setSavePartialExistingId('')
        setSavePartialError(null)
        setSavePartialSuccess(null)
        setPartialsSearchInput('')
        setPartialsSearchQuery('')
      }, 1200)
    },
    onError: (err: any) => {
      setSavePartialError(
        err?.response?.data?.detail ||
          err?.message ||
          'Failed to save prompt partial.',
      )
    },
  })

  const closeSavePartialModal = () => {
    if (savePartialMutation.isPending) return
    setSavePartialTarget(null)
    setSavePartialMode('new')
    setSavePartialName('')
    setSavePartialDescription('')
    setSavePartialChangeSummary('')
    setSavePartialExistingId('')
    setSavePartialError(null)
    setSavePartialSuccess(null)
    setPartialsSearchInput('')
    setPartialsSearchQuery('')
  }

  const openSavePartialModal = (target: 'standalone' | 'eval') => {
    setSavePartialTarget(target)
    setSavePartialMode('new')
    setSavePartialName('')
    setSavePartialDescription('')
    setSavePartialChangeSummary('')
    setSavePartialExistingId('')
    setSavePartialError(null)
    setSavePartialSuccess(null)
    setPartialsSearchInput('')
    setPartialsSearchQuery('')
  }

  const isFetching = headerFetching || rowsFetching
  const refetch = () => {
    void refetchHeader()
    void refetchRows()
  }

  useEffect(() => {
    if (!data?.id || (data.source_format || '').toLowerCase() !== 'platform') return
    if (data.status === 'deleting') {
      usePlatformImportProgressStore.getState().unpin(data.id)
    }
  }, [data?.id, data?.source_format, data?.status])

  useEffect(() => {
    if (!data?.id || !data.platform_progress || !activeWorkspaceId) return
    queryClient.setQueryData(
      ['platform-import-progress', activeWorkspaceId, data.id],
      data.platform_progress,
    )
  }, [data?.id, data?.platform_progress, activeWorkspaceId, queryClient])

  useEffect(() => {
    if (!pendingScrollToEvaluation || data?.status !== 'mapped') return
    setPendingScrollToEvaluation(false)
    window.setTimeout(() => {
      runEvaluationStepRef.current?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      })
    }, 100)
  }, [pendingScrollToEvaluation, data?.status])

  const { data: metrics = [] } = useQuery({
    queryKey: ['metrics', activeWorkspaceId, 'agent'],
    queryFn: () => apiClient.listMetrics('agent'),
    enabled: !!id,
  })


  // Insights tab: fetched lazily so we don't pay for the cross-run
  // aggregation on first page load. Refetches on a 30s cadence while
  // any evaluation is still running so the trend chart fills in as
  // data arrives.
  const { data: insightsData, isLoading: insightsLoading } = useQuery({
    queryKey: ['call-import-insights', activeWorkspaceId, id],
    queryFn: () => apiClient.callImports.getCallImportInsights(id!),
    enabled: !!id && activeTab === 'insights',
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    refetchInterval: () =>
      evaluationListPollMs(itemsOf<CallImportEvaluation>(evaluationsData), {
        slowCadenceMs: 15000,
      }),
  })

  const runEvaluationMutation = useMutation({
    mutationFn: (payload: Parameters<typeof apiClient.callImports.createCallImportEvaluation>[1]) =>
      apiClient.callImports.createCallImportEvaluation(id!, payload),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['call-import-evaluations', activeWorkspaceId, id] })
      queryClient.invalidateQueries({ queryKey: ['call-import', activeWorkspaceId, id] })
      void queryClient.refetchQueries({
        queryKey: ['call-import-evaluations', activeWorkspaceId, id],
      })
      void queryClient.refetchQueries({
        queryKey: ['call-import', activeWorkspaceId, id],
      })
      setShowRunEval(false)
      setSelectedMetricIds([])
      setRunDraftName('')
      setRunLLM({ provider: null, model: null, credential_id: null })
      setClassificationLLM({ provider: null, model: null, credential_id: null })
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
      void queryClient.refetchQueries({
        queryKey: ['call-import-evaluation', activeWorkspaceId, id, created.id],
      })
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
        diarization_llm_model:
          resolveLLMModelForSubmit(diariserLLM, aiProviders) ??
          (diariserLLM.model as string),
        diarization_llm_credential_id: diariserLLM.credential_id ?? null,
        diarization_prompt: trimmedPrompt,
      }
      // Single-row endpoint vs batch endpoint: prefer the single-row
      // endpoint when the modal targets exactly one row so the API
      // surface stays self-documenting.
      if (rowIds && rowIds.length === 1) {
        return apiClient.callImports.transcribeCallImportRow(id!, rowIds[0], base)
      }
      if (bulkSelectionFilter) {
        return apiClient.callImports.transcribeCallImport(id!, {
          ...base,
          row_filter: bulkSelectionFilter,
        })
      }
      return apiClient.callImports.transcribeCallImport(id!, {
        ...base,
        row_ids: rowIds ?? undefined,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['call-import', activeWorkspaceId, id] })
      setShowTranscribeModal(false)
      setTranscribeTargetRows(null)
      setTranscribeError(null)
      // Drop the bulk selection too — those rows are now in-flight so
      // keeping them "selected" would invite repeat clicks while the
      // transcribe worker is still doing its first pass.
      setSelectedRowIds(new Set())
      setBulkSelectionFilter(null)
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
      apiClient.callImports.cancelCallImportRowDiarisation(id!, rowId),
    onMutate: ({ rowId }) => {
      setCancellingRowId(rowId)
    },
    onSuccess: () => {
      // The backend has already flipped the row to ``failed`` with the
      // "cancelled by user" sentinel; refetch so the diarisation pill
      // and error message in the row drawer pick up the new state
      // immediately instead of waiting for the next poll tick.
      queryClient.invalidateQueries({ queryKey: ['call-import', activeWorkspaceId, id] })
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
    mutationFn: (target: { rowIds?: string[]; rowFilter?: { q?: string; diarised_status?: string } }) =>
      target.rowFilter
        ? apiClient.callImports.cancelCallImportDiarisation(id!, { rowFilter: target.rowFilter })
        : apiClient.callImports.cancelCallImportDiarisation(id!, { rowIds: target.rowIds ?? null }),
    onMutate: () => {
      setBulkActionError(null)
      setBulkActionResult(null)
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['call-import', activeWorkspaceId, id] })
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
      apiClient.callImports.toggleCallImportRowSpeakerSwap(id!, rowId),
    onMutate: ({ rowId }) => {
      setSwappingRowId(rowId)
      setSwapError(null)
    },
    onSuccess: () => {
      // The PATCH already returns the updated row, but we still want
      // the parent ``call-import`` query to refetch so the row list /
      // pagination / search index stay in sync (the row object is
      // embedded inside a much larger response).
      queryClient.invalidateQueries({ queryKey: ['call-import', activeWorkspaceId, id] })
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


  const totalRows = data?.total_rows ?? 0
  const failedImportRowsCount = data?.failed_rows ?? 0
  const diarisationInFlightCount =
    (data?.diarised_pending_rows ?? 0) + (data?.diarised_running_rows ?? 0)
  const diarisedCompletedRows = data?.diarised_completed_rows ?? 0
  const diarisedFailedRows = data?.diarised_failed_rows ?? 0
  // ``filtered_total_rows`` is set whenever any filter (search OR
  // diarisation-status) is active; pagination should always page
  // against whatever slice the user is actually looking at.
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

  if (isLoading || (rowsLoading && !rowsPage)) {
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
          Back to Imports
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

  const pendingCredentialErrorCount = rows.filter(
    (row) =>
      row.status === 'pending' &&
      !!row.error_message &&
      isImportCredentialError(row.error_message),
  ).length
  const showCredentialImportWarning =
    data.status === 'processing' && pendingCredentialErrorCount > 0

  // The staged-flow batch isn't ready to render rows / evaluations
  // until the user finishes the MAP + IMPORT steps. We swap out the
  // bottom of the page for the stage panels while the batch is still
  // pre-import so the user has a single linear next-action.
  const isPlatformImport = (data.source_format || '').toLowerCase() === 'platform'
  const liveProgress = isPlatformImport ? data.platform_progress : undefined
  const recordingTotal = liveProgress?.recordings.total ?? data.total_rows
  const recordingCompleted = liveProgress?.recordings.completed ?? data.completed_rows
  const recordingFailed = liveProgress?.recordings.failed ?? data.failed_rows
  const needsMapping =
    !isPlatformImport &&
    (data.status === 'uploaded' || data.status === 'mapped')
  const showWorkflowTabs = !needsMapping
  const isDeleting = data.status === 'deleting'
  const isManualAudioImport = (data.source_format || '').toLowerCase() === 'audio'
  const canAppendManualAudio =
    isManualAudioImport && data.status === 'completed' && !isDeleting
  const canRunEvaluation = data.status === 'mapped' || showWorkflowTabs

  return (
    <div className="space-y-6">
      <ToastContainer />
      <ImportDetailHeader
        data={data}
        isDeleting={isDeleting}
        canRunEvaluation={canRunEvaluation}
        showWorkflowTabs={showWorkflowTabs}
        openRunEvaluationModal={openRunEvaluationModal}
        rows={rows}
        canAppendManualAudio={canAppendManualAudio}
        onAppendAudio={() => setShowAppendAudioModal(true)}
        refetch={refetch}
        isFetching={isFetching}
        isLoading={isLoading}
        failedImportRowsCount={failedImportRowsCount}
        onRetryFailedImport={() => {
          setRetryFailedImportError(null)
          setShowRetryFailedImportConfirm(true)
        }}
        onDeleteImport={() => {
          setDeleteError(null)
          setShowDeleteImport(true)
        }}
        isPlatformImport={isPlatformImport}
        liveProgress={liveProgress}
        recordingTotal={recordingTotal}
        recordingCompleted={recordingCompleted}
        recordingFailed={recordingFailed}
        diarisationInFlightCount={diarisationInFlightCount}
        diarisedCompletedRows={diarisedCompletedRows}
        diarisedFailedRows={diarisedFailedRows}
        showCredentialImportWarning={showCredentialImportWarning}
        pendingCredentialErrorCount={pendingCredentialErrorCount}
        editingMeta={editingMeta}
        setEditingMeta={setEditingMeta}
        draftImportName={draftImportName}
        setDraftImportName={setDraftImportName}
        draftDataset={draftDataset}
        setDraftDataset={setDraftDataset}
        draftTagIds={draftTagIds}
        setDraftTagIds={setDraftTagIds}
        existingDatasets={existingDatasets}
        allTags={allTags}
        updateMetaMutation={updateMetaMutation}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        totalRows={totalRows}
        evaluationsCount={evaluationsData?.items?.length ?? 0}
      />

      {data.source_s3_key && <StageTracker status={data.status} />}

      {needsMapping && data.source_s3_key && (
        <>
          {(data.status === 'uploaded' || data.status === 'mapped') && (
            <MappingPanel
              callImport={data}
              onMappingSaved={handleMappingSaved}
            />
          )}
          {data.status === 'mapped' && !isDeleting && (
            <div ref={runEvaluationStepRef}>
              <RunEvaluationStep
                onRunEvaluation={openRunEvaluationModal}
                highlighted={highlightRunEvaluation}
              />
            </div>
          )}
        </>
      )}

      {showWorkflowTabs && activeTab === 'rows' && (
        <ImportRowsTab
          data={data}
          totalRows={totalRows}
          rows={rows}
          rowOffset={rowOffset}
          setRowOffset={setRowOffset}
          filteredTotalRows={filteredTotalRows}
          hasActiveFilter={hasActiveFilter}
          rowSearchInput={rowSearchInput}
          setRowSearchInput={setRowSearchInput}
          rowSearchQuery={rowSearchQuery}
          diarisedStatusFilter={diarisedStatusFilter}
          setDiarisedStatusFilter={setDiarisedStatusFilter}
          selectedCount={selectedCount}
          selectedRowIds={selectedRowIds}
          setSelectedRowIds={setSelectedRowIds}
          setBulkSelectionFilter={setBulkSelectionFilter}
          setBulkActionError={setBulkActionError}
          setBulkActionResult={setBulkActionResult}
          setShowBulkActionsModal={setShowBulkActionsModal}
          allOnPageSelected={allOnPageSelected}
          selectedOnPageCount={selectedOnPageCount}
          listRowFilter={listRowFilter}
          bulkSelectionFilter={bulkSelectionFilter}
          allMatchingSelected={allMatchingSelected}
          selectAllError={selectAllError}
          setSelectAllError={setSelectAllError}
          rowPage={rowPage}
          rowTotalPages={rowTotalPages}
          selectedRowId={selectedRowId}
          setSelectedRowId={setSelectedRowId}
          selectedRow={selectedRow}
          copiedRowId={copiedRowId}
          handleCopyConversationId={handleCopyConversationId}
          handleDownload={handleDownload}
          openTranscribeModal={openTranscribeModal}
          cancelDiarisationMutation={cancelDiarisationMutation}
          cancellingRowId={cancellingRowId}
          setDeleteError={setDeleteError}
          setPendingDeleteRow={setPendingDeleteRow}
          deleteRowMutation={deleteRowMutation}
          pendingDeleteRow={pendingDeleteRow}
          selectedRowDetail={selectedRowDetail}
          rowPanelTab={rowPanelTab}
          setRowPanelTab={setRowPanelTab}
          copiedTranscriptField={copiedTranscriptField}
          handleCopyTranscript={handleCopyTranscript}
          swapSpeakersMutation={swapSpeakersMutation}
          swappingRowId={swappingRowId}
          swapError={swapError}
          setSwapError={setSwapError}
        />
      )}

      {showWorkflowTabs && activeTab === 'evaluations' && (
        <ImportEvaluationsTab
          importId={id}
          evaluationsData={evaluationsData}
          evaluationsWithBulkOperation={evaluationsWithBulkOperation}
          selectedEvalIds={selectedEvalIds}
          setSelectedEvalIds={setSelectedEvalIds}
          setBulkDeleteEvalsError={setBulkDeleteEvalsError}
          setShowBulkDeleteEvals={setShowBulkDeleteEvals}
          bulkCancelEvalsMutation={bulkCancelEvalsMutation}
          cancellingEvalId={cancellingEvalId}
          cancelEvaluationMutation={cancelEvaluationMutation}
        />
      )}

      {showWorkflowTabs && activeTab === 'insights' && (
        <ImportInsightsTab
          insightsLoading={insightsLoading}
          insightsData={insightsData}
        />
      )}

      <RetryFailedImportModal
        isOpen={showRetryFailedImportConfirm}
        failedCount={failedImportRowsCount}
        callImport={data}
        isLoading={retryFailedImportMutation.isPending}
        errorMessage={retryFailedImportError}
        onConfirm={(selection) => {
          if (retryFailedImportMutation.isPending) return
          retryFailedImportMutation.mutate(selection)
        }}
        onCancel={() => {
          if (retryFailedImportMutation.isPending) return
          setShowRetryFailedImportConfirm(false)
          setRetryFailedImportError(null)
        }}
      />

      <UploadAudioModal
        open={showAppendAudioModal}
        onClose={() => setShowAppendAudioModal(false)}
        appendToImportId={id}
        appendToImportName={data.original_filename || undefined}
        onAppendSuccess={(response) => {
          showToast(
            response.message ||
              `Added recordings (${response.total_rows} total in batch).`,
            'success',
          )
          refetch()
        }}
      />

      <ImportTranscribeModals
        partialsImportTarget={partialsImportTarget}
        closePartialsImportModal={closePartialsImportModal}
        importPartialMutation={importPartialMutation}
        partialsSearchInput={partialsSearchInput}
        setPartialsSearchInput={setPartialsSearchInput}
        isLoadingPartials={isLoadingPartials}
        promptPartials={promptPartials}
        partialsSearchQuery={partialsSearchQuery}
        selectedPartialId={selectedPartialId}
        setSelectedPartialId={setSelectedPartialId}
        partialsImportError={partialsImportError}
        savePartialTarget={savePartialTarget}
        closeSavePartialModal={closeSavePartialModal}
        savePartialMutation={savePartialMutation}
        savePartialMode={savePartialMode}
        setSavePartialMode={setSavePartialMode}
        setSavePartialError={setSavePartialError}
        transcribeDiarisationPrompt={transcribeDiarisationPrompt}
        evalDiarisationPrompt={evalDiarisationPrompt}
        savePartialName={savePartialName}
        setSavePartialName={setSavePartialName}
        savePartialDescription={savePartialDescription}
        setSavePartialDescription={setSavePartialDescription}
        savePartialExistingId={savePartialExistingId}
        setSavePartialExistingId={setSavePartialExistingId}
        savePartialChangeSummary={savePartialChangeSummary}
        setSavePartialChangeSummary={setSavePartialChangeSummary}
        savePartialError={savePartialError}
        savePartialSuccess={savePartialSuccess}
        showTranscribeModal={showTranscribeModal}
        transcribeTargetRows={transcribeTargetRows}
        bulkSelectionFilter={bulkSelectionFilter}
        selectedCount={selectedCount}
        transcribeMode={transcribeMode}
        setTranscribeMode={setTranscribeMode}
        transcribeSTT={transcribeSTT}
        setTranscribeSTT={setTranscribeSTT}
        transcribeLanguage={transcribeLanguage}
        setTranscribeLanguage={setTranscribeLanguage}
        transcribeDiariserLLM={transcribeDiariserLLM}
        setTranscribeDiariserLLM={setTranscribeDiariserLLM}
        aiProviders={aiProviders}
        defaultDiarisationPrompt={defaultDiarisationPrompt}
        openSavePartialModal={openSavePartialModal}
        setPartialsImportError={setPartialsImportError}
        setPartialsSearchQuery={setPartialsSearchQuery}
        setPartialsImportTarget={setPartialsImportTarget}
        setTranscribeDiarisationPrompt={setTranscribeDiarisationPrompt}
        transcribeOverwriteStandalone={transcribeOverwriteStandalone}
        setTranscribeOverwriteStandalone={setTranscribeOverwriteStandalone}
        transcribeError={transcribeError}
        transcribeRowsMutation={transcribeRowsMutation}
        setShowTranscribeModal={setShowTranscribeModal}
        setTranscribeTargetRows={setTranscribeTargetRows}
        showBulkActionsModal={showBulkActionsModal}
        setShowBulkActionsModal={setShowBulkActionsModal}
        bulkActionError={bulkActionError}
        setBulkActionError={setBulkActionError}
        bulkActionResult={bulkActionResult}
        setBulkActionResult={setBulkActionResult}
        selectionSpansPages={selectionSpansPages}
        transcribeReadySelection={transcribeReadySelection}
        openTranscribeModal={openTranscribeModal}
        selectedRowIds={selectedRowIds}
        bulkCancelDiarisationMutation={bulkCancelDiarisationMutation}
        cancellableSelection={cancellableSelection}
        setBulkDeleteRowsError={setBulkDeleteRowsError}
        setShowBulkDeleteRows={setShowBulkDeleteRows}
      />

      <ImportRunEvaluationModal
        open={showRunEval}
        setShowRunEval={setShowRunEval}
        data={data}
        metrics={metrics}
        selectedMetricIds={selectedMetricIds}
        setSelectedMetricIds={setSelectedMetricIds}
        toggleMetric={toggleMetric}
        toggleParentMetric={toggleParentMetric}
        runDraftName={runDraftName}
        setRunDraftName={setRunDraftName}
        runEvaluationMutation={runEvaluationMutation}
        evalTelephonyProvider={evalTelephonyProvider}
        setEvalTelephonyProvider={setEvalTelephonyProvider}
        evalTelephonyIntegrationId={evalTelephonyIntegrationId}
        setEvalTelephonyIntegrationId={setEvalTelephonyIntegrationId}
        classificationLLM={classificationLLM}
        setClassificationLLM={setClassificationLLM}
        runLLM={runLLM}
        setRunLLM={setRunLLM}
        metricLLMOverrides={metricLLMOverrides}
        setMetricLLMOverrides={setMetricLLMOverrides}
        showAdvancedLLM={showAdvancedLLM}
        setShowAdvancedLLM={setShowAdvancedLLM}
        transcribeOverwrite={transcribeOverwrite}
        setTranscribeOverwrite={setTranscribeOverwrite}
        evalTranscribeMode={evalTranscribeMode}
        setEvalTranscribeMode={setEvalTranscribeMode}
        evalTranscriptSource={evalTranscriptSource}
        setEvalTranscriptSource={setEvalTranscriptSource}
        evalSTT={evalSTT}
        setEvalSTT={setEvalSTT}
        evalSTTLanguage={evalSTTLanguage}
        setEvalSTTLanguage={setEvalSTTLanguage}
        evalDiariserLLM={evalDiariserLLM}
        setEvalDiariserLLM={setEvalDiariserLLM}
        evalDiarisationPrompt={evalDiarisationPrompt}
        setEvalDiarisationPrompt={setEvalDiarisationPrompt}
        isManualAudioImport={isManualAudioImport}
        aiProviders={aiProviders}
        defaultDiarisationPrompt={defaultDiarisationPrompt}
        setPartialsImportError={setPartialsImportError}
        setSelectedPartialId={setSelectedPartialId}
        setPartialsSearchInput={setPartialsSearchInput}
        setPartialsSearchQuery={setPartialsSearchQuery}
        setPartialsImportTarget={setPartialsImportTarget}
        openSavePartialModal={openSavePartialModal}
      />

      <ImportDeleteConfirmModals
        importId={id}
        data={data}
        showDeleteImport={showDeleteImport}
        setShowDeleteImport={setShowDeleteImport}
        deleteError={deleteError}
        setDeleteError={setDeleteError}
        deleteImportMutation={deleteImportMutation}
        showBulkDeleteEvals={showBulkDeleteEvals}
        setShowBulkDeleteEvals={setShowBulkDeleteEvals}
        selectedEvalIds={selectedEvalIds}
        bulkDeleteEvalsError={bulkDeleteEvalsError}
        setBulkDeleteEvalsError={setBulkDeleteEvalsError}
        bulkDeleteEvalsMutation={bulkDeleteEvalsMutation}
        pendingDeleteRow={pendingDeleteRow}
        setPendingDeleteRow={setPendingDeleteRow}
        deleteRowMutation={deleteRowMutation}
        showBulkDeleteRows={showBulkDeleteRows}
        setShowBulkDeleteRows={setShowBulkDeleteRows}
        selectedRowIds={selectedRowIds}
        bulkDeleteRowsError={bulkDeleteRowsError}
        setBulkDeleteRowsError={setBulkDeleteRowsError}
        bulkSelectionFilter={bulkSelectionFilter}
        bulkDeleteRowsMutation={bulkDeleteRowsMutation}
      />

      <PlatformImportProgressDock />
    </div>
  )
}

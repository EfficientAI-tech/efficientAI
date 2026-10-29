import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  Check,
  ChevronDown,
  ChevronRight,
  Edit3,
  Loader2,
  RefreshCw,
  Sparkles,
  X,
} from 'lucide-react'
import { apiClient } from '../../lib/api'
import { getApiErrorMessage } from '../../lib/apiErrors'
import { itemsOf } from '../../lib/safeData'
import { copyTextToClipboard } from '../../lib/clipboard'
import {
  isLLMSelectionComplete,
  resolveLLMModelForSubmit,
  isClassificationCapableModel,
  isClassificationMetric,
} from '../../lib/llmModelOptions'
import { useToast } from '../../hooks/useToast'
import type {
  CallImportEvaluation,
  CallImportEvaluationBulkActionResponse,
  CallImportEvaluationExportPart,
  CallImportEvaluationRow,
  CallImportMetricAggregate,
  EvaluationTldrSummary,
  EvaluationMetricClustersState,
  EvaluationPromptImprovementsState,
  EvaluationUserInsightsState,
} from '../../types/api'
import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import { type ProviderModelValue } from '../../components/providers/ProviderModelPicker'
import { useWorkspaceStore } from '../../store/workspaceStore'
import StatusBadge from '../../components/shared/StatusBadge'
import { EvaluationAuditMeta } from '../../components/callImports/AuditMetaChips'
import CallImportProgressBar from './components/CallImportProgressBar'
import { type CallImportEvaluationRowSidePanelTabId } from './components/CallImportEvaluationRowSidePanelContent'
import MetricPromptImprovementsPanel from './components/MetricPromptImprovementsPanel'
import { useCallImportEvaluationAggregate } from './hooks/useCallImportEvaluationAggregate'
import { useEvalEvaluationRows } from './hooks/useEvalEvaluationRows'
import {
  bulkCancelResponseKeepsBulkOperation,
  evaluationBulkOperationDescription,
  evaluationBulkOperationLabel,
  evaluationRunPollMs,
  type BulkEvaluationOperation,
} from './evaluationBulkOperation'
import { importHeaderPollMs } from './importPolling'
import { isReservedMetricScoreKey } from './metricScoresMeta'
import MetricVisualization from './components/evalCharts/MetricVisualization'
import {
  loadChartGlobalDefault,
  saveChartGlobalDefault,
  loadChartPerMetric,
  saveChartPerMetric,
  resolveCategoricalChart,
  type CategoricalChartChoice,
  type CategoricalChartType,
} from './components/evalCharts/chartPrefs'
import { EvaluationTLDR } from './components/evalDetail/EvaluationTLDR'
import { UserInsightsStatusBanner } from './components/evalDetail/UserInsightsStatusBanner'
import { DiscoveredMetricsTopPanel } from './components/evalDetail/DiscoveredMetricsTopPanel'
import { FlowDiagramForParent } from './components/evalDetail/FlowDiagramForParent'
import { EvaluationUserInsightsPanel } from './components/evalDetail/EvaluationUserInsightsPanel'
import { MetricClustersPanel } from './components/evalDetail/EvalMetricClustersPanel'
import { useEvalRetryMutations } from './hooks/useEvalRetryMutations'
import { useEvalPdfReports } from './hooks/useEvalPdfReports'
import { EvaluationDetailHeader } from './components/evalDetail/EvaluationDetailHeader'
import { EvaluationResultsTabSwitcher } from './components/evalDetail/EvaluationResultsTabSwitcher'
import { EvaluationRowsTable } from './components/evalDetail/EvaluationRowsTable'
import { EvaluationRetryRerunModals } from './components/evalDetail/EvaluationRetryRerunModals'
import { EvaluationPdfWizard } from './components/evalDetail/EvaluationPdfWizard'
import {
  formatDateTime,
  formatRecordingDate,
} from './components/evalDetail/evalDisplayUtils'

function isUserInsightMetricName(name: string): boolean {
  const normalized = name.toLowerCase().replace(/[-_]/g, ' ')
  return [
    'call context',
    'caller context',
    'product identification',
    'out of scope',
    'identity match',
    'user identity',
    'caller identity',
    'frustration trigger',
    'video call offer',
    'video call reception',
  ].some((phrase) => normalized.includes(phrase))
}

// Mirrors the allowlist used on `CallImportDetail` when picking STT
// providers for a new evaluation run. The retry modal exposes the same
// set so the user can't pick an STT provider that the backend's
// `TranscriptionService` doesn't actually wire up.

export default function CallImportEvaluationDetail() {
  const { id, evalId } = useParams<{ id: string; evalId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const { showToast, ToastContainer } = useToast()

  const evaluationQueryKey = [
    'call-import-evaluation',
    activeWorkspaceId,
    id,
    evalId,
  ] as const

  const setEvaluationBulkOperationOptimistic = (
    operation: BulkEvaluationOperation | null,
  ) => {
    if (!id || !evalId) return
    queryClient.setQueryData<CallImportEvaluation>(
      evaluationQueryKey,
      (prev) => (prev ? { ...prev, bulk_operation: operation } : prev),
    )
  }

  const invalidateEvaluationQueries = () => {
    queryClient.invalidateQueries({ queryKey: evaluationQueryKey })
    queryClient.invalidateQueries({
      queryKey: ['call-import-evaluation-rows', activeWorkspaceId, id, evalId],
    })
    queryClient.invalidateQueries({
      queryKey: [
        'call-import-evaluation-pending-rows-count',
        activeWorkspaceId,
        id,
        evalId,
      ],
    })
    queryClient.invalidateQueries({
      queryKey: ['call-import-evaluations', activeWorkspaceId, id],
    })
    queryClient.invalidateQueries({
      queryKey: ['call-import', activeWorkspaceId, id],
    })
  }

  const bulkOperationConflictMessage =
    'Another bulk operation is already running for this evaluation. Wait for it to finish.'

  const [searchParams] = useSearchParams()
  const deepLinkConversationId =
    searchParams.get('conversation_id')?.trim() || ''
  const deepLinkRowId = searchParams.get('row_id')?.trim() || ''

  const [page, setPage] = useState(1)
  const [editingName, setEditingName] = useState(false)
  const [draftName, setDraftName] = useState('')
  const [renameError, setRenameError] = useState<string | null>(null)
  const [pendingDeleteRow, setPendingDeleteRow] =
    useState<CallImportEvaluationRow | null>(null)
  const [deleteEvalOpen, setDeleteEvalOpen] = useState(false)
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false)
  const downloadMenuRef = useRef<HTMLDivElement>(null)
  const exportPollRef = useRef(0)
  const [exportPreparing, setExportPreparing] = useState(false)
  const [exportParts, setExportParts] = useState<CallImportEvaluationExportPart[]>([])
  const [rowDeleteError, setRowDeleteError] = useState<string | null>(null)
  const [pdfReportOpen, setPdfReportOpen] = useState(false)
  const [vizBaselineEvaluationId, setVizBaselineEvaluationId] = useState<
    string | null
  >(null)
  const [resultsTab, setResultsTab] = useState<
    'table' | 'visualizations' | 'flow'
  >('table')
  // Categorical metrics can be rendered as one of several chart
  // types. The user picks a global default (auto = let us pick the
  // best fit per-metric) and can override on a per-metric basis via
  // the small icon row in the top-right of each chart card. Both
  // settings persist in localStorage so reloading the page keeps the
  // user's chart layout intact. Numeric metrics always use a
  // histogram regardless of these settings.
  const [chartGlobalDefault, setChartGlobalDefault] =
    useState<CategoricalChartChoice>(() => loadChartGlobalDefault())
  const [chartPerMetric, setChartPerMetric] = useState<
    Record<string, CategoricalChartType>
  >(() => loadChartPerMetric())
  const [visualizationSubtab, setVisualizationSubtab] = useState<
    'quality' | 'aiInsights' | 'clusters' | 'improvements'
  >('quality')
  const [qualityPanelCollapsed, setQualityPanelCollapsed] = useState(false)
  const [userInsightsPanelCollapsed, setUserInsightsPanelCollapsed] =
    useState(false)
  useEffect(() => {
    saveChartGlobalDefault(chartGlobalDefault)
  }, [chartGlobalDefault])
  useEffect(() => {
    saveChartPerMetric(chartPerMetric)
  }, [chartPerMetric])
  const setMetricChartType = (
    metricId: string,
    type: CategoricalChartType | null,
  ) => {
    setChartPerMetric((prev) => {
      const next = { ...prev }
      if (type == null) delete next[metricId]
      else next[metricId] = type
      return next
    })
  }

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
  const [tableFilterMetricId, setTableFilterMetricId] = useState('')
  const [tableFilterMetricValue, setTableFilterMetricValue] = useState('')
  const [classificationTableYesNo, setClassificationTableYesNo] = useState('')
  const [classificationTableChoice, setClassificationTableChoice] = useState('')
  const [classificationTableLevel, setClassificationTableLevel] = useState('')
  const [classificationMetricFilter, setClassificationMetricFilter] = useState<{
    metricId: string
    metricName: string
    yesNo?: string | null
    choice?: string | null
    level?: string | null
  } | null>(null)
  // ``flowFilter`` is set by clicking a node / edge in the Flow tab.
  // ``targetNodeId`` (and label) are populated only for edge clicks —
  // the backend then restricts to rows whose sequence has the
  // ``nodeId -> targetNodeId`` directed transition (immediately
  // adjacent). For node clicks ``targetNodeId`` stays null.
  const [flowFilter, setFlowFilter] = useState<{
    parentId: string
    parentName: string
    nodeId: string
    nodeLabel: string
    targetNodeId?: string | null
    targetNodeLabel?: string | null
  } | null>(null)
  // ``discoveredFilter`` is set by the "View calls" buttons on the
  // Discovered Labels panel. Either a specific candidate slug or a
  // catch-all "any discovered for this parent".
  const [discoveredFilter, setDiscoveredFilter] = useState<
    | {
        parentId: string
        parentName: string
        labelKey?: string
        labelName?: string
        anyDiscovered?: boolean
      }
    | null
  >(null)
  // Row-detail side panel: full CSV row + transcript + per-metric scores
  // for the currently-selected row.
  const [detailRow, setDetailRow] =
    useState<CallImportEvaluationRow | null>(null)
  const [evalPanelTab, setEvalPanelTab] =
    useState<CallImportEvaluationRowSidePanelTabId>('scores')

  // Transient "✓ Copied" feedback on the per-row Copy button next to
  // the ``conversation_id`` cell. Same UX as the upstream rows table
  // on ``CallImportDetail`` — keyed by eval-row id so we can flip
  // exactly one button at a time.
  const [copiedRowId, setCopiedRowId] = useState<string | null>(null)
  const handleCopyConversationId = (
    row: CallImportEvaluationRow,
    event: React.MouseEvent | React.KeyboardEvent,
  ) => {
    // The ``<tr>`` wrapping each row has an onClick that opens the
    // detail drawer; without this guard, copying would also open the
    // drawer for the row whose ID was just copied.
    event.preventDefault()
    event.stopPropagation()
    const text = row.conversation_id || ''
    if (!text) return
    const finalize = () => {
      setCopiedRowId(row.id)
      window.setTimeout(() => {
        setCopiedRowId((prev) => (prev === row.id ? null : prev))
      }, 1500)
    }
    copyTextToClipboard(text, finalize)
  }

  // Column-click sort state. ``sortBy`` is one of the built-in column
  // keys (``row_index`` / ``conversation_id`` / ``status``) or
  // ``metric:<metric_uuid>``; ``null`` means "no sort" (server falls
  // back to row_index asc, the original behaviour). The header cycles
  // null → asc → desc → null per column, so power users can flip
  // direction with two clicks and clear with a third without reaching
  // for a separate UI.
  const [sortBy, setSortBy] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  // Inline status-filter popover anchored on the Status column header.
  // The toolbar above keeps its full dropdown — this just gives users a
  // one-click affordance from the column they're already looking at.
  const [statusFilterMenuOpen, setStatusFilterMenuOpen] = useState(false)
  const statusFilterMenuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const t = setTimeout(() => setSearchQuery(searchInput.trim()), 250)
    return () => clearTimeout(t)
  }, [searchInput])

  // Reset to first page whenever any active filter or sort changes —
  // otherwise we'd be paging through a filtered / re-ordered result
  // set that may be smaller than ``page`` or whose row at the current
  // page index has changed.
  useEffect(() => {
    setPage(1)
  }, [
    searchQuery,
    statusFilter,
    metricFilter?.metricId,
    metricFilter?.value,
    classificationMetricFilter?.metricId,
    classificationMetricFilter?.yesNo,
    classificationMetricFilter?.choice,
    classificationMetricFilter?.level,
    flowFilter?.parentId,
    flowFilter?.nodeId,
    flowFilter?.targetNodeId,
    discoveredFilter?.parentId,
    discoveredFilter?.labelKey,
    discoveredFilter?.anyDiscovered,
    sortBy,
    sortDir,
  ])

  // Close the inline status-filter popover when the user clicks outside it.
  useEffect(() => {
    if (!statusFilterMenuOpen) return
    const handleClickOutside = (event: MouseEvent) => {
      if (
        statusFilterMenuRef.current &&
        !statusFilterMenuRef.current.contains(event.target as Node)
      ) {
        setStatusFilterMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [statusFilterMenuOpen])

  // Three-state cycle when the user clicks a sortable column header.
  // Same key + same direction is the "I already see this view" hint
  // and we move forward in the cycle:
  //   1st click  → ascending on this column
  //   2nd click  → descending on the same column
  //   3rd click  → clear sort (server reverts to row_index asc)
  const handleColumnSort = (key: string) => {
    if (sortBy !== key) {
      setSortBy(key)
      setSortDir('asc')
      return
    }
    if (sortDir === 'asc') {
      setSortDir('desc')
      return
    }
    setSortBy(null)
    setSortDir('asc')
  }

  const hasActiveFilters =
    !!searchQuery ||
    !!statusFilter ||
    !!metricFilter ||
    !!classificationMetricFilter ||
    !!flowFilter ||
    !!discoveredFilter

  const callImportQuery = useQuery({
    queryKey: ['call-import', activeWorkspaceId, id],
    queryFn: () => apiClient.callImports.getCallImport(id!, { row_limit: 0, row_offset: 0 }),
    enabled: !!id,
    refetchOnWindowFocus: false,
    // Poll while import, diarisation, or the linked evaluation is in flight
    // so all three summary bars update without a hard refresh. Mirrors the
    // broader conditions on CallImportDetail plus active eval-run status.
    refetchInterval: (q) => {
      const ci = q.state.data
      const evaluation = queryClient.getQueryData(evaluationQueryKey) as
        | CallImportEvaluation
        | undefined
      const headerMs = importHeaderPollMs(ci)
      const evalMs = evaluationRunPollMs(evaluation)
      if (headerMs && evalMs) {
        return Math.min(
          typeof headerMs === 'number' ? headerMs : 5000,
          typeof evalMs === 'number' ? evalMs : 5000,
        )
      }
      return headerMs || evalMs || false
    },
  })

  const evaluationQuery = useQuery({
    queryKey: evaluationQueryKey,
    queryFn: () => apiClient.callImports.getCallImportEvaluation(id!, evalId!),
    enabled: !!id && !!evalId,
    staleTime: 0,
    refetchOnWindowFocus: false,
    refetchInterval: (q) => evaluationRunPollMs(q.state.data),
  })

  const evalDetailPollInterval = () =>
    evaluationRunPollMs(evaluationQuery.data) || false

  const { data: aiProviders = [] } = useQuery({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  // Metric definitions, used to tell classification metrics apart from
  // standard ones. Same query key as the Run Evaluation modal (shared cache).
  const { data: metricDefinitions = [] } = useQuery({
    queryKey: ['metrics', activeWorkspaceId, 'agent'],
    queryFn: () => apiClient.listMetrics('agent'),
    enabled: !!evalId,
  })
  const classificationMetricIdSet = useMemo(() => {
    const ids = new Set<string>()
    const visit = (metric: { id: string; custom_data_type?: string | null; children?: unknown }) => {
      if (isClassificationMetric(metric)) ids.add(metric.id)
      if (Array.isArray(metric.children)) metric.children.forEach(visit)
    }
    metricDefinitions.forEach(visit)
    return ids
  }, [metricDefinitions])

  const { rowsQuery, detailRowFull } = useEvalEvaluationRows({
    callImportId: id,
    evaluationId: evalId,
    activeWorkspaceId,
    page,
    searchQuery,
    statusFilter,
    metricFilter,
    classificationMetricFilter,
    flowFilter,
    discoveredFilter,
    sortBy,
    sortDir,
    resultsTab,
    evaluation: evaluationQuery.data,
    detailRow,
    setDetailRow,
    deepLinkConversationId,
    deepLinkRowId,
    setSearchQuery,
    setPage,
  })


  // Lazy: only fetch aggregates when the user lands on the
  // visualizations tab. Refetches while the run is still in flight so
  // the chart fills in as workers complete rows.
  const aggregateQuery = useCallImportEvaluationAggregate({
    callImportId: id,
    evaluationId: evalId,
    workspaceId: activeWorkspaceId,
    baselineEvaluationId: vizBaselineEvaluationId,
    enabled: !!id && !!evalId && resultsTab === 'visualizations',
    evaluation: evaluationQuery.data,
  })

  const visualizationInsightsQuery = useQuery<EvaluationTldrSummary | null>({
    queryKey: ['call-import-evaluation-insights', activeWorkspaceId, id, evalId],
    queryFn: () => apiClient.callImports.getCallImportEvaluationInsights(id!, evalId!),
    enabled: !!id && !!evalId && resultsTab === 'visualizations',
    refetchOnWindowFocus: false,
    refetchInterval: false,
  })

  const userInsightsQuery = useQuery<EvaluationUserInsightsState | null>({
    queryKey: ['call-import-evaluation-user-insights', activeWorkspaceId, id, evalId],
    queryFn: () =>
      apiClient.callImports.getCallImportEvaluationUserInsights(id!, evalId!),
    enabled:
      !!id &&
      !!evalId &&
      (resultsTab === 'visualizations' || pdfReportOpen),
    refetchOnWindowFocus: false,
    refetchInterval: () => evalDetailPollInterval(),
  })

  const metricClustersQuery = useQuery<EvaluationMetricClustersState | null>({
    queryKey: ['call-import-evaluation-metric-clusters', activeWorkspaceId, id, evalId],
    queryFn: () =>
      apiClient.callImports.getCallImportEvaluationMetricClusters(id!, evalId!),
    enabled:
      !!id &&
      !!evalId &&
      (resultsTab === 'visualizations' || pdfReportOpen),
    refetchOnWindowFocus: false,
    refetchInterval: () => evalDetailPollInterval(),
  })

  const promptImprovementsQuery = useQuery<EvaluationPromptImprovementsState | null>({
    queryKey: ['call-import-evaluation-prompt-improvements', activeWorkspaceId, id, evalId],
    queryFn: () =>
      apiClient.callImports.getCallImportEvaluationPromptImprovements(id!, evalId!),
    enabled:
      !!id &&
      !!evalId &&
      (resultsTab === 'visualizations' || pdfReportOpen),
    refetchOnWindowFocus: false,
    refetchInterval: () => evalDetailPollInterval(),
  })

  const retry = useEvalRetryMutations({
    callImportId: id,
    evaluationId: evalId,
    activeWorkspaceId,
    evaluation: evaluationQuery.data,
    callImport: callImportQuery.data,
    searchQuery,
    aiProviders,
    classificationMetricIdSet,
    setEvaluationBulkOperationOptimistic,
    invalidateEvaluationQueries,
    bulkOperationConflictMessage,
  })

  const {
    retryError,
    setRetryError,
    rerunMetricIds,
    retryClassificationLLM,
    rerunClassificationLLM,
  } = retry

  const renameMutation = useMutation({
    mutationFn: (newName: string | null) =>
      apiClient.callImports.updateCallImportEvaluation(id!, evalId!, { name: newName }),
    onSuccess: (updated) => {
      queryClient.setQueryData(
        ['call-import-evaluation', activeWorkspaceId, id, evalId],
        updated,
      )
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluations', activeWorkspaceId, id],
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
      apiClient.callImports.deleteCallImportEvaluationRow(id!, evalId!, rowId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation-rows', activeWorkspaceId, id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation', activeWorkspaceId, id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluations', activeWorkspaceId, id],
      })
      setPendingDeleteRow(null)
      setRowDeleteError(null)
    },
    onError: (err: unknown) => {
      const message = getApiErrorMessage(err, 'Failed to delete row.')
      setRowDeleteError(message)
      showToast(message, 'error')
    },
  })

  const deleteEvalMutation = useMutation({
    mutationFn: () => apiClient.callImports.deleteCallImportEvaluation(id!, evalId!),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluations', activeWorkspaceId, id],
      })
      navigate(`/call-imports/${id}`)
    },
    onError: (err: unknown) => {
      showToast(getApiErrorMessage(err, 'Failed to delete evaluation run.'), 'error')
    },
  })


  // Inline error banner shown above the run header when an Abort call
  // fails. Cancel is idempotent on the server so the most likely cause
  // is a network blip; we still surface the message so the operator
  // knows the click didn't take effect rather than silently swallowing.
  const [cancelError, setCancelError] = useState<string | null>(null)
  // Tracks which single row is currently mid-cancel so we can render
  // a spinner on the row's Stop button without blocking the others.
  const [cancellingRowId, setCancellingRowId] = useState<string | null>(null)

  // Run-level cancel: marks rows cancelled in DB (background worker for large
  // batches), revokes Celery tasks without terminate on worker-imports, rolls
  // up the parent. Pollers pick up state; invalidate for a quick refetch.
  const cancelEvaluationMutation = useMutation({
    mutationFn: () => apiClient.callImports.cancelCallImportEvaluation(id!, evalId!),
    onMutate: () => {
      setCancelError(null)
      setEvaluationBulkOperationOptimistic('abort')
      invalidateEvaluationQueries()
    },
    onSuccess: (data: CallImportEvaluationBulkActionResponse) => {
      if (bulkCancelResponseKeepsBulkOperation(data)) {
        setEvaluationBulkOperationOptimistic('abort')
      } else {
        setEvaluationBulkOperationOptimistic(null)
      }
      invalidateEvaluationQueries()
    },
    onError: (err: any) => {
      setEvaluationBulkOperationOptimistic(null)
      setCancelError(
        err?.response?.status === 409
          ? err?.response?.data?.detail || bulkOperationConflictMessage
          : err?.response?.data?.detail ||
              err?.message ||
              'Failed to abort this evaluation run.',
      )
    },
  })

  // Row-level cancel: same shape as the run-level mutation but
  // scoped to a single row so the operator can stop one wedged row
  // without aborting siblings that are progressing fine.
  const cancelRowMutation = useMutation({
    mutationFn: (rowId: string) =>
      apiClient.callImports.cancelCallImportEvaluationRow(id!, evalId!, rowId),
    onMutate: (rowId) => {
      setCancellingRowId(rowId)
      setCancelError(null)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation', activeWorkspaceId, id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation-rows', activeWorkspaceId, id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluations', activeWorkspaceId, id],
      })
    },
    onError: (err: any) => {
      setCancelError(
        err?.response?.status === 409
          ? err?.response?.data?.detail || bulkOperationConflictMessage
          : err?.response?.data?.detail ||
              err?.message ||
              'Failed to abort this row.',
      )
    },
    onSettled: () => {
      setCancellingRowId(null)
    },
  })

  const callImport = callImportQuery.data
  const evaluation = evaluationQuery.data
  const platformAgentLabel =
    (callImport?.source_format || '').toLowerCase() === 'platform'
      ? (callImport?.platform_agents || []).length === 0
        ? 'All agents'
        : (callImport?.platform_agents || []).map((agent) => agent.name).join(', ')
      : null

  const runMetricIds: string[] = evaluation?.selected_metric_ids ?? []
  const retryClassificationIds = runMetricIds.filter((mid) =>
    classificationMetricIdSet.has(mid),
  )
  const retryHasStandard = runMetricIds.some(
    (mid) => !classificationMetricIdSet.has(mid),
  )
  const rerunSelectedIds = Array.from(rerunMetricIds)
  const rerunClassificationIds = rerunSelectedIds.filter((mid) =>
    classificationMetricIdSet.has(mid),
  )
  const rerunHasStandard = rerunSelectedIds.some(
    (mid) => !classificationMetricIdSet.has(mid),
  )
  const isClassificationSelectionReady = (value: ProviderModelValue) =>
    aiProviders.length > 0 &&
    isLLMSelectionComplete(value, aiProviders) &&
    isClassificationCapableModel(
      resolveLLMModelForSubmit(value, aiProviders) ?? value.model ?? '',
    )
  const retryClassificationReady =
    retryClassificationIds.length === 0 ||
    isClassificationSelectionReady(retryClassificationLLM)
  const rerunClassificationReady =
    rerunClassificationIds.length === 0 ||
    isClassificationSelectionReady(rerunClassificationLLM)
  const metricNameById = useMemo(() => {
    const names = new Map<string, string>()
    const visit = (metric: { id: string; name?: string; children?: unknown }) => {
      names.set(metric.id, metric.name ?? metric.id)
      if (Array.isArray(metric.children)) metric.children.forEach(visit)
    }
    metricDefinitions.forEach(visit)
    return names
  }, [metricDefinitions])
  const hasClassificationCredential = aiProviders.some(
    (p) =>
      p.is_active &&
      (p.enabled_models?.some((m: string) => isClassificationCapableModel(m)) ||
        isClassificationCapableModel(p.gateway_model ?? '') ||
        ['openrouter', 'typesafe'].includes(String(p.provider).toLowerCase())),
  )
  const diarisationInFlightCount = callImport
    ? (callImport.diarised_pending_rows ?? 0) +
      (callImport.diarised_running_rows ?? 0)
    : 0
  const diarisedCompletedRows = callImport?.diarised_completed_rows ?? 0
  const diarisedFailedRows = callImport?.diarised_failed_rows ?? 0

  // Derive the metric column list the same way CallImportDetail does so the
  // table stays consistent with what was actually scored, even if the
  // `metrics` summary on the evaluation drifts from `metric_scores` keys.
  //
  // For each metric we also flag ``hasRationale``: true when ANY row has a
  // non-empty ``rationale`` string for that metric (i.e. it was scored
  // with ``capture_rationale=true``). The table then renders an extra
  // "<Name> - LLM Rationale" column right after the value column for those
  // metrics, mirroring the CSV export layout.
  //
  // Category parents collapse to a single value column (chosen child label)
  // plus the rationale column. Any child whose parent is part of this
  // run (via ``selected_metric_groups``) is suppressed so the user only
  // sees the parent column — matching the CSV export.
  type DisplayMetric = {
    id: string
    name: string
    hasRationale: boolean
    metricCategory: string
  }
  const childrenInGroups = useMemo<Set<string>>(() => {
    const set = new Set<string>()
    const groups = evaluation?.selected_metric_groups
    if (groups && typeof groups === 'object') {
      for (const childIds of Object.values(groups)) {
        if (Array.isArray(childIds)) {
          for (const cid of childIds) {
            if (typeof cid === 'string') set.add(cid)
          }
        }
      }
    }
    return set
  }, [evaluation?.selected_metric_groups])

  const displayMetrics = useMemo<DisplayMetric[]>(() => {
    const byId = new Map<string, DisplayMetric>()
    const upsert = (id: string, patch: Partial<DisplayMetric>) => {
      if (childrenInGroups.has(id)) return
      const prev = byId.get(id)
      byId.set(id, {
        id,
        name: patch.name || prev?.name || `Metric ${id.slice(0, 8)}`,
        hasRationale: prev?.hasRationale || patch.hasRationale || false,
        metricCategory:
          patch.metricCategory || prev?.metricCategory || 'quality',
      })
    }

    for (const m of evaluation?.metrics ?? []) {
      if (m && m.id) {
        upsert(m.id, {
          name: m.name || `Metric ${m.id.slice(0, 8)}`,
          metricCategory:
            (m as any).metric_category === 'user_insight' ||
            isUserInsightMetricName(m.name || '')
              ? 'user_insight'
              : 'quality',
        })
      }
    }
    for (const mid of evaluation?.selected_metric_ids ?? []) {
      if (typeof mid === 'string' && !byId.has(mid)) {
        upsert(mid, {})
      }
    }
    for (const row of itemsOf<CallImportEvaluationRow>(rowsQuery.data)) {
      const scores = row.metric_scores
      if (!scores || typeof scores !== 'object') continue
      for (const [metricId, entry] of Object.entries(scores)) {
        if (!metricId || isReservedMetricScoreKey(metricId)) continue
        if (childrenInGroups.has(metricId)) continue
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
    childrenInGroups,
  ])

  const tableFilterMetricAggregate = useMemo(() => {
    if (!tableFilterMetricId || !aggregateQuery.data) return undefined
    return aggregateQuery.data.metrics.find(
      (m) => m.metric_id === tableFilterMetricId,
    )
  }, [aggregateQuery.data, tableFilterMetricId])

  const tableMetricIsClassification = Boolean(
    tableFilterMetricAggregate?.classification_facets,
  )

  const tableMetricFilterValueOptions = useMemo(() => {
    if (!tableFilterMetricId || !tableFilterMetricAggregate) return []
    if (tableMetricIsClassification) return []
    if (!tableFilterMetricAggregate.value_counts?.length) return []
    return [...tableFilterMetricAggregate.value_counts]
      .sort((a, b) => b.count - a.count)
      .map((vc) => ({
        value: String(vc.label),
        count: vc.count,
      }))
  }, [tableFilterMetricAggregate, tableFilterMetricId, tableMetricIsClassification])

  const applyClassificationTableFilter = (
    metricId: string,
    yesNo: string,
    choice: string,
    level: string,
  ) => {
    const hasAny = !!(yesNo || choice || level)
    if (!metricId || !hasAny) {
      setClassificationMetricFilter(null)
      return
    }
    const metricName =
      displayMetrics.find((m) => m.id === metricId)?.name ??
      `Metric ${metricId.slice(0, 8)}`
    setClassificationMetricFilter({
      metricId,
      metricName,
      yesNo: yesNo || null,
      choice: choice || null,
      level: level || null,
    })
    setMetricFilter(null)
    setFlowFilter(null)
  }

  const filteredRowsSummary = useMemo(() => {
    const shown = rowsQuery.data?.total ?? 0
    const evalTotal = evaluation?.total_rows
    if (hasActiveFilters) {
      if (evalTotal != null) {
        return `Showing ${shown} matching row${shown === 1 ? '' : 's'} (of ${evalTotal} in this evaluation)`
      }
      return `Showing ${shown} matching row${shown === 1 ? '' : 's'}`
    }
    return `${shown} row${shown === 1 ? '' : 's'} in this evaluation`
  }, [rowsQuery.data?.total, evaluation?.total_rows, hasActiveFilters])

  const applyTableMetricFilter = (metricId: string, value: string) => {
    const trimmed = value.trim()
    if (!metricId || !trimmed) {
      setMetricFilter(null)
      setFlowFilter(null)
      return
    }
    const metricName =
      displayMetrics.find((m) => m.id === metricId)?.name ??
      `Metric ${metricId.slice(0, 8)}`
    const agg = aggregateQuery.data?.metrics.find(
      (m) => m.metric_id === metricId,
    )
    if (agg?.is_multi_label_parent) {
      setFlowFilter({
        parentId: metricId,
        parentName: metricName,
        nodeId: trimmed,
        nodeLabel: trimmed,
        targetNodeId: null,
        targetNodeLabel: null,
      })
      setMetricFilter(null)
    } else {
      setMetricFilter({
        metricId,
        metricName,
        value: trimmed,
      })
      setFlowFilter(null)
    }
  }

  useEffect(() => {
    if (metricFilter) {
      setTableFilterMetricId(metricFilter.metricId)
      setTableFilterMetricValue(metricFilter.value)
      return
    }
    if (flowFilter && !flowFilter.targetNodeId) {
      setTableFilterMetricId(flowFilter.parentId)
      setTableFilterMetricValue(flowFilter.nodeLabel)
      return
    }
    if (classificationMetricFilter) {
      setTableFilterMetricId(classificationMetricFilter.metricId)
      return
    }
    if (!metricFilter && !flowFilter && !classificationMetricFilter) {
      setTableFilterMetricId('')
      setTableFilterMetricValue('')
    }
  }, [metricFilter, flowFilter, classificationMetricFilter])

  // Parent metrics (selection_mode != null) and their enabled children
  // pulled straight from the run's metric summaries. The Flow tab uses
  // these to render one diagram per parent and to translate per-row
  // ``sequence`` arrays back into child IDs/names for the row drawer.
  type FlowParentMetric = {
    id: string
    name: string
    selection_mode: 'single_choice' | 'multi_label' | null
    allow_discovery: boolean
    children: { id: string; name: string }[]
  }
  const parentMetrics = useMemo<FlowParentMetric[]>(() => {
    const all = evaluation?.metrics ?? []
    const childrenByParent = new Map<string, { id: string; name: string }[]>()
    for (const m of all) {
      const pid = (m as any).parent_metric_id as string | null | undefined
      if (pid) {
        const list = childrenByParent.get(pid) || []
        list.push({ id: m.id, name: m.name })
        childrenByParent.set(pid, list)
      }
    }
    const parents: FlowParentMetric[] = []
    for (const m of all) {
      const mode = (m as any).selection_mode as
        | 'single_choice'
        | 'multi_label'
        | null
        | undefined
      const parentId = (m as any).parent_metric_id as string | null | undefined
      if (mode && !parentId) {
        parents.push({
          id: m.id,
          name: m.name,
          selection_mode: mode ?? null,
          allow_discovery: Boolean((m as any).allow_discovery),
          children: childrenByParent.get(m.id) || [],
        })
      }
    }
    return parents
  }, [evaluation?.metrics])

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

  const reportQualityMetrics = useMemo(
    () => displayMetrics.filter((metric) => metric.metricCategory !== 'user_insight'),
    [displayMetrics],
  )
  const reportInsightMetrics = useMemo(
    () => displayMetrics.filter((metric) => metric.metricCategory === 'user_insight'),
    [displayMetrics],
  )

  const pdf = useEvalPdfReports({
    callImportId: id,
    evaluationId: evalId,
    activeWorkspaceId,
    evalId,
    pdfReportOpen,
    setPdfReportOpen,
    resultsTab,
    reportQualityMetrics,
    reportInsightMetrics,
    userInsightsQuery,
    metricClustersQuery,
    promptImprovementsQuery,
  })

  const handleExport = async (format: 'csv' | 'xlsx') => {
    if (!id || !evalId) return
    setDownloadMenuOpen(false)
    const pollId = exportPollRef.current + 1
    exportPollRef.current = pollId
    setExportPreparing(true)
    setExportParts([])
    try {
      let job = await apiClient.callImports.startCallImportEvaluationExport(
        id,
        evalId,
        format,
        true,
      )
      while (job.status === 'pending' || job.status === 'running') {
        if (exportPollRef.current !== pollId) return
        await new Promise((resolve) => setTimeout(resolve, 2000))
        if (exportPollRef.current !== pollId) return
        job = await apiClient.callImports.getCallImportEvaluationExport(id, evalId, job.id)
      }
      if (exportPollRef.current !== pollId) return
      if (job.status === 'failed') {
        alert(job.error_message || 'Export failed')
        return
      }
      const ready = (job.parts || []).filter((part) => part.download_url)
      if (ready.length === 1 && ready[0].download_url) {
        window.location.assign(ready[0].download_url)
      } else if (ready.length > 1) {
        setExportParts(ready)
      } else {
        alert(job.error_message || 'Export finished without a download link')
      }
    } catch (e: any) {
      console.error('Failed to export evaluation', e)
      const detail = e?.response?.data?.detail
      alert(typeof detail === 'string' ? detail : `Failed to export evaluation ${format.toUpperCase()}`)
    } finally {
      if (exportPollRef.current === pollId) setExportPreparing(false)
    }
  }

  useEffect(() => {
    if (resultsTab !== 'visualizations' || !id || !evalId) return
    let cancelled = false
    apiClient.callImports
      .listCallImportEvaluationBaselineCandidates(id, evalId)
      .then((response) => {
        if (cancelled) return
        const defaultId =
          response.default_evaluation_id ||
          response.items.find((item) => item.is_default)?.evaluation_id ||
          response.items[0]?.evaluation_id ||
          null
        setVizBaselineEvaluationId(defaultId)
      })
      .catch(() => {
        if (!cancelled) setVizBaselineEvaluationId(null)
      })
    return () => {
      cancelled = true
    }
  }, [resultsTab, id, evalId])

  useEffect(() => {
    if (!downloadMenuOpen) return
    const handleClickOutside = (event: MouseEvent) => {
      if (
        downloadMenuRef.current &&
        !downloadMenuRef.current.contains(event.target as Node)
      ) {
        setDownloadMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [downloadMenuOpen])

  useEffect(() => {
    return () => {
      exportPollRef.current += 1
    }
  }, [])

  // Build the "Imported columns" panel from the parent CallImport's mapping
  // metadata, so users can see which CSV columns were used to drive this
  // particular evaluation run. Schema-driven batches (``schema_id`` set)
  // surface every Input Parameter from ``parameter_mapping``; legacy
  // batches still render via the free-form ``column_mapping`` /
  // ``extra_columns`` / ``custom_column_mapping`` fields.
  const importedColumns = useMemo(() => {
    if (!callImport) return []
    const rows: { label: string; value: string }[] = []
    if (callImport.schema_id) {
      const paramMapping = callImport.parameter_mapping || {}
      for (const [name, csvHeader] of Object.entries(paramMapping)) {
        rows.push({ label: name, value: csvHeader })
      }
      return rows
    }
    const mapping = callImport.column_mapping || {}
    if (mapping.external_call_id) {
      rows.push({
        label: 'Conversation ID',
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
  const bulkOperation = evaluation.bulk_operation ?? null
  const bulkOperationActive = bulkOperation !== null
  const getMetricLlmLabel = (metricId: string): string => {
    const override = evaluation.metric_llm_overrides?.[metricId]
    const overrideProvider = override?.provider?.trim()
    const overrideModel = override?.model?.trim()
    if (overrideProvider && overrideModel) {
      return `${overrideProvider} / ${overrideModel}`
    }
    const runProvider = evaluation.llm_provider?.trim()
    const runModel = evaluation.llm_model?.trim()
    return `${runProvider || 'openai'} / ${runModel || 'gpt-4o'}`
  }

  const totalPages = rowsQuery.data
    ? Math.max(1, Math.ceil(rowsQuery.data.total / rowsQuery.data.page_size))
    : 1

  return (
    <div className="space-y-6">
      <ToastContainer />
      <EvaluationDetailHeader
        id={id}
        evalId={evalId}
        evaluation={evaluation}
        rowsQuery={rowsQuery}
        bulkOperationActive={bulkOperationActive}
        bulkOperation={bulkOperation}
        cancelEvaluationMutation={cancelEvaluationMutation}
        retry={retry}
        pdf={pdf}
        downloadMenuOpen={downloadMenuOpen}
        setDownloadMenuOpen={setDownloadMenuOpen}
        downloadMenuRef={downloadMenuRef}
        exportPreparing={exportPreparing}
        exportParts={exportParts}
        handleExport={handleExport}
        setDeleteEvalOpen={setDeleteEvalOpen}
      />

      <div className="bg-white shadow rounded-lg p-6">
        <div className="space-y-4">
          <div className="min-w-0">
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
            <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 min-w-0 max-w-full text-sm text-gray-600">
              <StatusBadge status={evaluation.status} />
              <span
                className={
                  'inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ' +
                  (evaluation.transcript_source === 'diarised'
                    ? 'bg-purple-50 text-purple-700'
                    : 'bg-gray-100 text-gray-700')
                }
                title={
                  evaluation.transcript_source === 'diarised'
                    ? 'Scored against the worker-produced diarised transcript.'
                    : 'Scored against the CSV-supplied production transcript.'
                }
              >
                {evaluation.transcript_source === 'diarised'
                  ? 'Evaluated on Diarised transcript'
                  : 'Evaluated on Production transcript'}
              </span>
              {platformAgentLabel && (
                <span className="shrink-0">
                  Agent:{' '}
                  <span className="font-medium text-gray-800">{platformAgentLabel}</span>
                </span>
              )}
              <EvaluationAuditMeta
                inline
                showTimestamps={false}
                startedAt={evaluation.started_at}
                finishedAt={evaluation.finished_at}
                runByEmail={evaluation.created_by_email}
                lastUpdatedByEmail={evaluation.last_updated_by_email}
                formatDate={formatDateTime}
              />
            </div>
          </div>

          <div
            className={
              evaluation.transcript_source === 'diarised'
                ? 'grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3'
                : 'grid grid-cols-1 gap-3 max-w-md'
            }
          >
            {callImport && evaluation.transcript_source === 'diarised' && (
              <div className="rounded-lg border border-slate-200 bg-slate-50/80 p-3 shadow-sm min-w-0">
                <h3 className="text-sm font-semibold text-slate-900 mb-2.5 pb-2 border-b border-slate-200">
                  Recording import
                </h3>
                <CallImportProgressBar
                  total={callImport.total_rows}
                  completed={callImport.completed_rows}
                  failed={callImport.failed_rows}
                />
                <div className="mt-2.5 grid grid-cols-3 gap-2 text-center text-xs">
                  <div className="bg-white rounded-md border border-slate-100 p-2">
                    <div className="text-gray-500">Total</div>
                    <div className="font-semibold text-gray-900">
                      {callImport.total_rows}
                    </div>
                  </div>
                  <div className="bg-white rounded-md border border-green-100 p-2">
                    <div className="text-green-700">Completed</div>
                    <div className="font-semibold text-green-800">
                      {callImport.completed_rows}
                    </div>
                  </div>
                  <div className="bg-white rounded-md border border-red-100 p-2">
                    <div className="text-red-700">Failed</div>
                    <div className="font-semibold text-red-800">
                      {callImport.failed_rows}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {callImport && evaluation.transcript_source === 'diarised' && (
              <div className="rounded-lg border border-violet-200 bg-violet-50/50 p-3 shadow-sm min-w-0">
                <div className="flex items-center justify-between gap-2 mb-2.5 pb-2 border-b border-violet-200">
                  <h3 className="text-sm font-semibold text-violet-950">
                    Transcription &amp; diarisation
                  </h3>
                  {diarisationInFlightCount > 0 && (
                    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-violet-700 whitespace-nowrap">
                      <RefreshCw className="h-3 w-3 animate-spin" />
                      {diarisationInFlightCount} in progress
                    </span>
                  )}
                </div>
                <CallImportProgressBar
                  total={callImport.total_rows}
                  completed={diarisedCompletedRows}
                  failed={diarisedFailedRows}
                />
                <div className="mt-2.5 grid grid-cols-3 gap-2 text-center text-xs">
                  <div className="bg-white rounded-md border border-violet-100 p-2">
                    <div className="text-gray-500">Total</div>
                    <div className="font-semibold text-gray-900">
                      {callImport.total_rows}
                    </div>
                  </div>
                  <div className="bg-white rounded-md border border-green-100 p-2">
                    <div className="text-green-700">Completed</div>
                    <div className="font-semibold text-green-800">
                      {diarisedCompletedRows}
                    </div>
                  </div>
                  <div className="bg-white rounded-md border border-red-100 p-2">
                    <div className="text-red-700">Failed</div>
                    <div className="font-semibold text-red-800">
                      {diarisedFailedRows}
                    </div>
                  </div>
                </div>
              </div>
            )}

            <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-3 shadow-sm min-w-0">
              <h3 className="text-sm font-semibold text-emerald-950 mb-2.5 pb-2 border-b border-emerald-200">
                Evaluation progress
              </h3>
              <CallImportProgressBar
                total={evaluation.total_rows}
                completed={evaluation.completed_rows}
                failed={evaluation.failed_rows}
              />
              <div className="mt-2.5 grid grid-cols-3 gap-2 text-center text-xs">
                <div className="bg-white rounded-md border border-emerald-100 p-2">
                  <div className="text-gray-500">Total</div>
                  <div className="font-semibold text-gray-900">
                    {evaluation.total_rows}
                  </div>
                </div>
                <div className="bg-white rounded-md border border-green-100 p-2">
                  <div className="text-green-700">Completed</div>
                  <div className="font-semibold text-green-800">
                    {evaluation.completed_rows}
                  </div>
                </div>
                <div className="bg-white rounded-md border border-red-100 p-2">
                  <div className="text-red-700">Failed</div>
                  <div className="font-semibold text-red-800">
                    {evaluation.failed_rows}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {bulkOperation && (
          <div className="mt-4 bg-amber-50 border border-amber-200 rounded-lg p-3">
            <div className="flex items-start gap-2">
              <Loader2 className="h-4 w-4 text-amber-600 mt-0.5 animate-spin shrink-0" />
              <div className="flex-1">
                <p className="text-sm font-medium text-amber-900">
                  {evaluationBulkOperationLabel(bulkOperation)}
                </p>
                <p className="text-xs text-amber-800 mt-0.5">
                  {evaluationBulkOperationDescription(bulkOperation)}
                </p>
              </div>
            </div>
          </div>
        )}

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

        {retryError && (
          <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-3">
            <div className="flex items-start gap-2">
              <AlertCircle className="h-4 w-4 text-red-600 mt-0.5" />
              <div className="flex-1">
                <p className="text-sm text-red-800">{retryError}</p>
              </div>
              <button
                type="button"
                onClick={() => setRetryError(null)}
                className="p-1 rounded text-red-400 hover:text-red-600 hover:bg-red-100"
                aria-label="Dismiss retry error"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}

        {cancelError && (
          <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-3">
            <div className="flex items-start gap-2">
              <AlertCircle className="h-4 w-4 text-red-600 mt-0.5" />
              <div className="flex-1">
                <p className="text-sm text-red-800">{cancelError}</p>
              </div>
              <button
                type="button"
                onClick={() => setCancelError(null)}
                className="p-1 rounded text-red-400 hover:text-red-600 hover:bg-red-100"
                aria-label="Dismiss abort error"
              >
                <X className="h-3.5 w-3.5" />
              </button>
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
        <div className="flex items-start justify-between mb-3 gap-3 flex-wrap">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Row results</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {filteredRowsSummary}. Scored against {displayMetrics.length}{' '}
              metric{displayMetrics.length === 1 ? '' : 's'}.
            </p>
          </div>
          <EvaluationResultsTabSwitcher
            resultsTab={resultsTab}
            setResultsTab={setResultsTab}
          />
        </div>

        {resultsTab === 'flow' ? (
          <div className="space-y-6">
            {/* Top-level metric discovery panel. Rendered above the
                per-parent diagrams so the user sees newly-suggested
                metrics first, regardless of whether the run included
                any parent category metrics. Gated on the per-run opt-in
                flag so legacy / non-discovery runs keep their
                existing Flow tab layout. */}
            {evaluationQuery.data?.discover_new_metrics ? (
              <DiscoveredMetricsTopPanel
                callImportId={id!}
                evalId={evalId!}
              />
            ) : null}

            {parentMetrics.length === 0 ? (
              <div className="text-sm text-gray-500 border border-dashed border-gray-300 rounded-md p-6 text-center space-y-1">
                <p>
                  No category metrics in this run. Flow diagrams are
                  only rendered for parent metrics with sub-labels.
                </p>
                <p className="text-xs">
                  Standalone <strong>boolean</strong> and{' '}
                  <strong>rating</strong> metrics (including ones
                  promoted from the Discovered metrics panel) are
                  scored per call and shown in the{' '}
                  <button
                    type="button"
                    className="underline text-primary-600 hover:text-primary-700"
                    onClick={() => setResultsTab('table')}
                  >
                    Table
                  </button>{' '}
                  and{' '}
                  <button
                    type="button"
                    className="underline text-primary-600 hover:text-primary-700"
                    onClick={() => setResultsTab('visualizations')}
                  >
                    Visualizations
                  </button>{' '}
                  tabs.
                </p>
              </div>
            ) : (
              <>
              <p className="text-xs text-gray-500 inline-flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-primary-500" />
                One diagram per category metric. Edge thickness scales
                with how many calls flowed between each pair of labels;
                terminal labels are outlined.
              </p>
              {parentMetrics.map((pm) => (
                <FlowDiagramForParent
                  key={pm.id}
                  callImportId={id!}
                  evalId={evalId!}
                  parent={pm}
                  onNodeClick={(node) => {
                    setFlowFilter({
                      parentId: pm.id,
                      parentName: pm.name,
                      nodeId: node.id,
                      nodeLabel: node.label,
                      targetNodeId: null,
                      targetNodeLabel: null,
                    })
                    setMetricFilter(null)
                    setDiscoveredFilter(null)
                    setResultsTab('table')
                  }}
                  onEdgeClick={(edge) => {
                    setFlowFilter({
                      parentId: pm.id,
                      parentName: pm.name,
                      nodeId: edge.source.id,
                      nodeLabel: edge.source.label,
                      targetNodeId: edge.target.id,
                      targetNodeLabel: edge.target.label,
                    })
                    setMetricFilter(null)
                    setDiscoveredFilter(null)
                    setResultsTab('table')
                  }}
                  onViewDiscoveredCalls={(item) => {
                    setDiscoveredFilter({
                      parentId: pm.id,
                      parentName: pm.name,
                      labelKey: item.key,
                      labelName: item.name,
                    })
                    setFlowFilter(null)
                    setMetricFilter(null)
                    setResultsTab('table')
                  }}
                  onViewAnyDiscoveredCalls={() => {
                    setDiscoveredFilter({
                      parentId: pm.id,
                      parentName: pm.name,
                      anyDiscovered: true,
                    })
                    setFlowFilter(null)
                    setMetricFilter(null)
                    setResultsTab('table')
                  }}
                />
              ))}
              </>
            )}
          </div>
        ) : resultsTab === 'visualizations' ? (
          aggregateQuery.isLoading || !aggregateQuery.data ? (
            <div className="text-center py-12 text-gray-500">
              <RefreshCw className="h-6 w-6 mx-auto mb-2 animate-spin" />
              <p>Loading visualizations…</p>
            </div>
          ) : (aggregateQuery.data.metrics?.length ?? 0) === 0 ? (
            <p className="text-sm text-gray-500">
              No metric data yet. Charts populate as rows finish scoring.
            </p>
          ) : (
            <>
              <EvaluationTLDR
                callImportId={id!}
                evaluation={evaluation}
                aggregate={aggregateQuery.data}
              />
              <div className="mt-4 mb-3 flex items-center justify-between gap-3 flex-wrap">
                <p className="text-xs text-gray-500 inline-flex items-center gap-1.5">
                  <Sparkles className="h-3.5 w-3.5 text-primary-500" />
                  Click any bar, tile, or slice to filter the row table.
                  Use the icon row on each card to change its chart.
                </p>
                <div className="inline-flex items-center gap-2">
                  <span className="text-[11px] text-gray-500">
                    Default chart:
                  </span>
                  <select
                    value={chartGlobalDefault}
                    onChange={(e) =>
                      setChartGlobalDefault(
                        e.target.value as CategoricalChartChoice,
                      )
                    }
                    className="text-[11px] border border-gray-200 rounded-md bg-white px-2 py-1 text-gray-700 focus:outline-none focus:ring-1 focus:ring-primary-300"
                    title="Default chart type for categorical metrics. Per-metric overrides win."
                  >
                    <option value="auto">Auto (smart pick)</option>
                    <option value="pie">Pie / donut</option>
                    <option value="bar">Bar</option>
                    <option value="lollipop">Lollipop</option>
                    <option value="radial">Radial</option>
                    <option value="treemap">Treemap</option>
                    <option value="waffle">Waffle (10×10)</option>
                  </select>
                </div>
              </div>
              {(() => {
                // Suppress category sub-label children so each logical
                // metric gets one chart card — same rule as the table.
                const visibleAggregates = aggregateQuery.data.metrics.filter(
                  (m) => !childrenInGroups.has(m.metric_id),
                )
                const qualityAggregates = visibleAggregates.filter(
                  (m) => (m.metric_category || 'quality') !== 'user_insight',
                )
                const insightAggregates = visibleAggregates.filter(
                  (m) => m.metric_category === 'user_insight',
                )
                const renderAggregate = (m: CallImportMetricAggregate) => {
                  // For multi-label parents, the visualization "active"
                  // state is driven by the flowFilter (we route bar
                  // clicks through it because the parent's stored
                  // ``value`` is a comma-joined string and never
                  // matches a single bar label). For single-value
                  // metrics it stays driven by metricFilter.
                  const isMultiLabelActive =
                    m.is_multi_label_parent === true &&
                    flowFilter?.parentId === m.metric_id &&
                    !flowFilter?.targetNodeId
                  const isActive = isMultiLabelActive
                    ? true
                    : metricFilter?.metricId === m.metric_id
                  const activeValue = isMultiLabelActive
                    ? flowFilter?.nodeLabel ?? null
                    : metricFilter?.metricId === m.metric_id
                      ? metricFilter.value
                      : null
                  return (
                    <div
                      key={m.metric_id}
                      // Multi-label parents pack a tall horizontal bar
                      // chart with long labels; spanning the full row
                      // keeps the y-axis labels readable instead of
                      // clipping inside a half-column.
                      className={
                        m.is_multi_label_parent ? 'lg:col-span-2' : ''
                      }
                    >
                      <MetricVisualization
                        metric={m}
                        chartType={resolveCategoricalChart(
                          m,
                          chartPerMetric,
                          chartGlobalDefault,
                        )}
                        chartOverridden={chartPerMetric[m.metric_id] != null}
                        onChangeChartType={(t) =>
                          setMetricChartType(m.metric_id, t)
                        }
                        isActive={isActive}
                        activeValue={activeValue}
                        businessInsight={
                          visualizationInsightsQuery.data?.metric_insights?.[
                            m.metric_id
                          ] || null
                        }
                        periodDelta={
                          aggregateQuery.data?.period_deltas?.[m.metric_id] ??
                          null
                        }
                        failurePoliciesSource={
                          aggregateQuery.data?.failure_policies_source ?? null
                        }
                        onValueClick={(value) => {
                          if (m.is_multi_label_parent) {
                            // Re-use the Flow tab's drilldown filter so
                            // the SQL path (``metric_scores[parent]
                            // .sequence`` contains slug(label)) handles
                            // both promoted children AND LLM-discovered
                            // labels uniformly. A plain metric_id +
                            // metric_value filter would never match
                            // here because the parent stores a
                            // comma-joined value, not the clicked
                            // label.
                            setFlowFilter({
                              parentId: m.metric_id,
                              parentName: m.metric_name,
                              nodeId: value,
                              nodeLabel: value,
                              targetNodeId: null,
                              targetNodeLabel: null,
                            })
                            setMetricFilter(null)
                            setDiscoveredFilter(null)
                          } else {
                            setMetricFilter({
                              metricId: m.metric_id,
                              metricName: m.metric_name,
                              value,
                            })
                            setFlowFilter(null)
                            setDiscoveredFilter(null)
                          }
                          setResultsTab('table')
                        }}
                      />
                    </div>
                  )
                }
                return (
                  <div className="space-y-6">
                    <div
                      className="inline-flex w-fit rounded-md border border-amber-300 bg-amber-50/80 p-0.5"
                      role="tablist"
                      aria-label="Visualization sections"
                    >
                      <button
                        type="button"
                        role="tab"
                        aria-selected={visualizationSubtab === 'quality'}
                        onClick={() => setVisualizationSubtab('quality')}
                        className={`rounded px-2.5 py-1 text-[13px] font-medium transition ${
                          visualizationSubtab === 'quality'
                            ? 'bg-white text-amber-950 shadow-sm'
                            : 'text-gray-600 hover:text-gray-900'
                        }`}
                      >
                        Quality Metrics
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected={visualizationSubtab === 'aiInsights'}
                        onClick={() => setVisualizationSubtab('aiInsights')}
                        className={`rounded px-2.5 py-1 text-[13px] font-medium transition ${
                          visualizationSubtab === 'aiInsights'
                            ? 'bg-white text-amber-950 shadow-sm'
                            : 'text-gray-600 hover:text-gray-900'
                        }`}
                      >
                        AI User Insights
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected={visualizationSubtab === 'clusters'}
                        onClick={() => setVisualizationSubtab('clusters')}
                        className={`rounded px-2.5 py-1 text-[13px] font-medium transition ${
                          visualizationSubtab === 'clusters'
                            ? 'bg-white text-amber-950 shadow-sm'
                            : 'text-gray-600 hover:text-gray-900'
                        }`}
                      >
                        Clusters
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected={visualizationSubtab === 'improvements'}
                        onClick={() => setVisualizationSubtab('improvements')}
                        className={`rounded px-2.5 py-1 text-[13px] font-medium transition ${
                          visualizationSubtab === 'improvements'
                            ? 'bg-white text-amber-950 shadow-sm'
                            : 'text-gray-600 hover:text-gray-900'
                        }`}
                      >
                        Prompt / Agent Improvements
                      </button>
                    </div>

                    {visualizationSubtab === 'quality' ? (
                      qualityAggregates.length ? (
                        <section>
                          <header className="flex items-center justify-between gap-2 mb-3">
                            <button
                              type="button"
                              onClick={() =>
                                setQualityPanelCollapsed((collapsed) => !collapsed)
                              }
                              className="text-sm font-semibold text-gray-900 inline-flex items-center gap-1 hover:text-gray-700"
                              aria-expanded={!qualityPanelCollapsed}
                              title={
                                qualityPanelCollapsed
                                  ? 'Expand quality metric panel'
                                  : 'Collapse quality metric panel'
                              }
                            >
                              {qualityPanelCollapsed ? (
                                <ChevronRight className="h-3.5 w-3.5" />
                              ) : (
                                <ChevronDown className="h-3.5 w-3.5" />
                              )}
                              Quality Metric Panel
                            </button>
                            <span className="text-[10px] text-gray-500 tabular-nums">
                              {qualityAggregates.length}{' '}
                              {qualityAggregates.length === 1
                                ? 'metric'
                                : 'metrics'}
                            </span>
                          </header>
                          {qualityPanelCollapsed ? null : (
                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                              {qualityAggregates.map(renderAggregate)}
                            </div>
                          )}
                        </section>
                      ) : (
                        <p className="text-sm text-gray-500">
                          No quality metrics available yet.
                        </p>
                      )
                    ) : visualizationSubtab === 'aiInsights' ? (
                      <div className="space-y-6">
                        <section>
                          <UserInsightsStatusBanner
                            state={userInsightsQuery.data ?? null}
                            isLoading={userInsightsQuery.isLoading}
                          />
                          <header className="flex items-center justify-between gap-2 mb-3 mt-4">
                            <button
                              type="button"
                              onClick={() =>
                                setUserInsightsPanelCollapsed((collapsed) => !collapsed)
                              }
                              className="text-sm font-semibold text-gray-900 inline-flex items-center gap-1 hover:text-gray-700"
                              aria-expanded={!userInsightsPanelCollapsed}
                              title={
                                userInsightsPanelCollapsed
                                  ? 'Expand AI user insights panel'
                                  : 'Collapse AI user insights panel'
                              }
                            >
                              {userInsightsPanelCollapsed ? (
                                <ChevronRight className="h-3.5 w-3.5" />
                              ) : (
                                <ChevronDown className="h-3.5 w-3.5" />
                              )}
                              AI User Insights (External Audit)
                            </button>
                          </header>
                          {userInsightsPanelCollapsed ? null : (
                            <EvaluationUserInsightsPanel
                              state={userInsightsQuery.data ?? null}
                              isLoading={userInsightsQuery.isLoading}
                            />
                          )}
                        </section>
                        {insightAggregates.length ? (
                          <section>
                            <h3 className="text-sm font-semibold text-gray-900 mb-1">
                              User Insights
                            </h3>
                            <p className="text-xs text-gray-500 mb-3">
                              Distribution classifiers derived from the same
                              per-call evaluation pass.
                            </p>
                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                              {insightAggregates.map(renderAggregate)}
                            </div>
                          </section>
                        ) : (
                          <p className="text-sm text-gray-500">
                            No user insight metrics available yet.
                          </p>
                        )}
                      </div>
                    ) : visualizationSubtab === 'clusters' ? (
                      <MetricClustersPanel
                        callImportId={id!}
                        evaluationId={evalId!}
                        defaultProvider={evaluation?.llm_provider ?? ''}
                        defaultModel={evaluation?.llm_model ?? ''}
                        state={metricClustersQuery.data ?? null}
                        isLoading={metricClustersQuery.isLoading}
                        onGenerated={() => {
                          queryClient.invalidateQueries({
                            queryKey: [
                              'call-import-evaluation-metric-clusters',
                              activeWorkspaceId,
                              id,
                              evalId,
                            ],
                          })
                        }}
                      />
                    ) : (
                      <MetricPromptImprovementsPanel
                        callImportId={id!}
                        evaluationId={evalId!}
                        clustersState={metricClustersQuery.data ?? null}
                        improvementsState={promptImprovementsQuery.data ?? null}
                        isLoading={promptImprovementsQuery.isLoading}
                        linkedImportedAgentPartialId={
                          callImport?.imported_agent_partial_id ?? null
                        }
                        platformAgentLabel={platformAgentLabel}
                        onGenerated={() => {
                          queryClient.invalidateQueries({
                            queryKey: [
                              'call-import-evaluation-prompt-improvements',
                              activeWorkspaceId,
                              id,
                              evalId,
                            ],
                          })
                        }}
                      />
                    )}
                  </div>
                )
              })()}
            </>
          )
        ) : (
          <EvaluationRowsTable
            resultsTab={resultsTab}
            evaluation={evaluation}
            rowsQuery={rowsQuery}
            detailRow={detailRow}
            setDetailRow={setDetailRow}
            detailRowFull={detailRowFull}
            evalPanelTab={evalPanelTab}
            setEvalPanelTab={setEvalPanelTab}
            parentMetrics={parentMetrics}
            displayMetrics={displayMetrics}
            totalPages={totalPages}
            filteredRowsSummary={filteredRowsSummary}
            hasActiveFilters={hasActiveFilters}
            searchInput={searchInput}
            setSearchInput={setSearchInput}
            searchQuery={searchQuery}
            setSearchQuery={setSearchQuery}
            statusFilter={statusFilter}
            setStatusFilter={setStatusFilter}
            tableFilterMetricId={tableFilterMetricId}
            setTableFilterMetricId={setTableFilterMetricId}
            tableFilterMetricValue={tableFilterMetricValue}
            setTableFilterMetricValue={setTableFilterMetricValue}
            classificationTableYesNo={classificationTableYesNo}
            setClassificationTableYesNo={setClassificationTableYesNo}
            classificationTableChoice={classificationTableChoice}
            setClassificationTableChoice={setClassificationTableChoice}
            classificationTableLevel={classificationTableLevel}
            setClassificationTableLevel={setClassificationTableLevel}
            classificationMetricFilter={classificationMetricFilter}
            setClassificationMetricFilter={setClassificationMetricFilter}
            metricFilter={metricFilter}
            setMetricFilter={setMetricFilter}
            flowFilter={flowFilter}
            setFlowFilter={setFlowFilter}
            discoveredFilter={discoveredFilter}
            setDiscoveredFilter={setDiscoveredFilter}
            aggregateQuery={aggregateQuery}
            tableFilterMetricAggregate={tableFilterMetricAggregate}
            tableMetricIsClassification={tableMetricIsClassification}
            tableMetricFilterValueOptions={tableMetricFilterValueOptions}
            applyClassificationTableFilter={applyClassificationTableFilter}
            applyTableMetricFilter={applyTableMetricFilter}
            sortBy={sortBy}
            sortDir={sortDir}
            handleColumnSort={handleColumnSort}
            statusFilterMenuOpen={statusFilterMenuOpen}
            setStatusFilterMenuOpen={setStatusFilterMenuOpen}
            statusFilterMenuRef={statusFilterMenuRef}
            totalMetricColumnCount={totalMetricColumnCount}
            getMetricLlmLabel={getMetricLlmLabel}
            copiedRowId={copiedRowId}
            handleCopyConversationId={handleCopyConversationId}
            bulkOperationActive={bulkOperationActive}
            cancellingRowId={cancellingRowId}
            cancelRowMutation={cancelRowMutation}
            retry={retry}
            pendingDeleteRow={pendingDeleteRow}
            setPendingDeleteRow={setPendingDeleteRow}
            deleteRowMutation={deleteRowMutation}
            formatDateTime={formatDateTime}
            formatRecordingDate={formatRecordingDate}
            setRowDeleteError={setRowDeleteError}
            setPage={setPage}
          />
        )}
      </div>

      <EvaluationRetryRerunModals
        evaluation={evaluation}
        displayMetrics={displayMetrics}
        metricNameById={metricNameById}
        aiProviders={aiProviders}
        hasClassificationCredential={hasClassificationCredential}
        retry={retry}
        retryClassificationIds={retryClassificationIds}
        retryHasStandard={retryHasStandard}
        rerunClassificationIds={rerunClassificationIds}
        rerunHasStandard={rerunHasStandard}
        isClassificationSelectionReady={isClassificationSelectionReady}
        retryClassificationReady={retryClassificationReady}
        rerunClassificationReady={rerunClassificationReady}
      />
      <EvaluationPdfWizard
        id={id}
        evalId={evalId}
        evaluation={evaluation}
        activeWorkspaceId={activeWorkspaceId}
        pdf={pdf}
        reportQualityMetrics={reportQualityMetrics}
        reportInsightMetrics={reportInsightMetrics}
        userInsightsQuery={userInsightsQuery}
        metricClustersQuery={metricClustersQuery}
        promptImprovementsQuery={promptImprovementsQuery}
        queryClient={queryClient}
      />

      <ConfirmModal
        isOpen={pendingDeleteRow !== null}
        title="Delete this evaluation row?"
        description={(() => {
          if (!pendingDeleteRow) return ''
          const callId = pendingDeleteRow.conversation_id || '(no callid)'
          const lines = [
            `Row for Conversation ID ${callId} will be removed from this evaluation only.`,
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


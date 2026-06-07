import { type ChangeEvent, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  ArrowUpDown,
  BarChart3,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Copy,
  Download,
  Edit3,
  ExternalLink,
  Filter,
  FileText,
  Grid3x3,
  LayoutGrid,
  Loader2,
  Merge,
  PieChart as PieChartIcon,
  Plus,
  RefreshCw,
  RotateCw,
  Search,
  Sparkles,
  Table,
  Target,
  TrendingUp,
  Trash2,
  Workflow,
  X,
  XCircle,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  Line,
  LineChart,
  Pie,
  PieChart,
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
  Tooltip,
  Treemap,
  XAxis,
  YAxis,
} from 'recharts'
import { apiClient, type ReportBranding } from '../../lib/api'
import type {
  CallImportEvaluation,
  CallImportEvaluationBaselineCandidate,
  CallImportEvaluationRow,
  CallImportMetricAggregate,
  EvaluationTldrSummary,
  EvaluationMetricClustersState,
  EvaluationPromptImprovementsState,
  MetricClusterEvidence,
  MetricClustersRcaSummary,
  MetricFailurePolicy,
  MetricFailurePolicyMetricPreview,
  MetricClusterEligibleRow,
  EvaluationUserInsightsState,
  EvaluationUserInsightItem,
  MetricPeriodDelta,
} from '../../types/api'
import AIProviderModelPicker from '../../components/AIProviderModelPicker'
import Button from '../../components/Button'
import ConfirmModal from '../../components/ConfirmModal'
import Pagination from '../../components/Pagination'
import ProviderModelPicker, {
  type ProviderModelValue,
} from '../../components/providers/ProviderModelPicker'
import StatusBadge from '../../components/shared/StatusBadge'
import CallImportProgressBar from './components/CallImportProgressBar'
import MetricPromptImprovementsPanel from './components/MetricPromptImprovementsPanel'
import MetricFlowChart, {
  flowFromSequence,
} from './components/MetricFlowChart'

const PIE_COLORS = [
  '#6366f1',
  '#10b981',
  '#f59e0b',
  '#ef4444',
  '#a855f7',
  '#0ea5e9',
  '#ec4899',
  '#14b8a6',
  '#f97316',
  '#84cc16',
]

// All categorical chart types the Visualizations tab can render. Each
// type has a corresponding icon shown in the per-metric chart picker
// and the global default selector. Multi-label-only types (heatmap /
// coverage) are still in the union — the picker just hides them for
// non-multi-label metrics.
type CategoricalChartType =
  | 'pie'
  | 'bar'
  | 'lollipop'
  | 'radial'
  | 'treemap'
  | 'waffle'
  | 'heatmap'
  | 'coverage'

// "auto" lets us pick the best fit per metric (numeric → histogram,
// few categories → radial, more → lollipop, lots → treemap). When the
// user picks an explicit chart type at the global level, every
// non-overridden categorical metric uses that type instead of the
// per-metric auto pick.
type CategoricalChartChoice = 'auto' | CategoricalChartType

const CHART_PREFS_KEY = 'callImportEval.chartPrefs.v1'
const CHART_GLOBAL_DEFAULT_KEY = 'callImportEval.chartGlobalDefault.v1'

function loadChartGlobalDefault(): CategoricalChartChoice {
  if (typeof window === 'undefined') return 'auto'
  try {
    const raw = window.localStorage.getItem(CHART_GLOBAL_DEFAULT_KEY)
    if (!raw) return 'auto'
    return JSON.parse(raw) as CategoricalChartChoice
  } catch {
    return 'auto'
  }
}

function saveChartGlobalDefault(value: CategoricalChartChoice): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(
      CHART_GLOBAL_DEFAULT_KEY,
      JSON.stringify(value),
    )
  } catch {
    /* ignore quota / privacy-mode errors */
  }
}

function loadChartPerMetric(): Record<string, CategoricalChartType> {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(CHART_PREFS_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function saveChartPerMetric(
  value: Record<string, CategoricalChartType>,
): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(CHART_PREFS_KEY, JSON.stringify(value))
  } catch {
    /* ignore quota / privacy-mode errors */
  }
}

/**
 * Pick the best-fitting chart type for a categorical metric when the
 * user hasn't explicitly chosen one. Defaults to a ranked lollipop
 * for everything because it scales cleanly from 2 to ~12 categories,
 * never overlaps labels, and reads as a sorted top-N list at a
 * glance. Truly wide categorical sets (>12 unique values) graduate
 * to a treemap so the lollipop's vertical run doesn't get unwieldy.
 */
function autoPickCategoricalChart(
  metric: CallImportMetricAggregate,
): CategoricalChartType {
  const n = metric.value_counts.length
  if (n > 12) return 'treemap'
  return 'lollipop'
}

/**
 * Resolve the chart type the renderer should use for a given metric,
 * combining (in priority order): per-metric override → global default
 * (when set to a concrete type) → auto pick by cardinality.
 */
function resolveCategoricalChart(
  metric: CallImportMetricAggregate,
  perMetric: Record<string, CategoricalChartType>,
  globalDefault: CategoricalChartChoice,
): CategoricalChartType {
  const override = perMetric[metric.metric_id]
  if (override) return override
  if (globalDefault !== 'auto') {
    if (
      metric.is_multi_label_parent &&
      (globalDefault === 'pie' ||
        globalDefault === 'radial' ||
        globalDefault === 'waffle')
    ) {
      return 'bar'
    }
    if (
      !metric.is_multi_label_parent &&
      (globalDefault === 'heatmap' || globalDefault === 'coverage')
    ) {
      return autoPickCategoricalChart(metric)
    }
    return globalDefault
  }
  return autoPickCategoricalChart(metric)
}

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

const ROWS_PAGE_SIZE = 50

const USER_INSIGHTS_SAMPLE_SIZE_OPTIONS = [50, 100, 150, 200, 300, 500] as const
const DEFAULT_USER_INSIGHTS_SAMPLE_SIZE = 200

// Mirrors the allowlist used on `CallImportDetail` when picking STT
// providers for a new evaluation run. The retry modal exposes the same
// set so the user can't pick an STT provider that the backend's
// `TranscriptionService` doesn't actually wire up.
const STT_PROVIDER_ALLOWLIST = [
  'deepgram',
  'openai',
  'elevenlabs',
  'sarvam',
  'smallest',
  'google',
]

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function formatRecordingDate(value: string | null | undefined): string {
  if (!value) return '-'
  const [year, month, day] = value.split('-')
  return year && month && day ? `${day}/${month}/${year}` : value
}

interface SortableHeaderProps {
  /** Stable column key used as the ``sort_by`` value sent to the API. */
  columnKey: string
  /** Currently-active sort column (``null`` when no sort is set). */
  activeKey: string | null
  /** Currently-active sort direction; ignored when ``activeKey`` differs. */
  activeDir: 'asc' | 'desc'
  /** Tooltip + accessibility label fallback. */
  title?: string
  /** Cycles the sort state for this column. */
  onCycle: (key: string) => void
  /** Optional extra ``<th>`` className (alignment, sticky, etc.). */
  className?: string
  /** Optional trailing slot rendered AFTER the sort glyph (e.g. a
   *  filter popover trigger). Kept outside the sort button so its
   *  click doesn't trigger the sort cycle. */
  rightSlot?: React.ReactNode
  children: React.ReactNode
}

/**
 * Header cell that reads as plain-text until the user clicks it, at
 * which point the column starts cycling through ``asc → desc → off``.
 * The active sort direction renders a solid up/down arrow; inactive
 * columns render a dim double-arrow so users discover the affordance
 * without it being visually noisy.
 */
function SortableHeader({
  columnKey,
  activeKey,
  activeDir,
  title,
  onCycle,
  className,
  rightSlot,
  children,
}: SortableHeaderProps) {
  const isActive = activeKey === columnKey
  const Icon = !isActive
    ? ArrowUpDown
    : activeDir === 'asc'
      ? ArrowUp
      : ArrowDown
  const ariaSort = !isActive
    ? 'none'
    : activeDir === 'asc'
      ? 'ascending'
      : 'descending'
  return (
    <th
      aria-sort={ariaSort}
      className={
        'px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap ' +
        (className || '')
      }
    >
      <div className="inline-flex items-center gap-1">
        <button
          type="button"
          onClick={() => onCycle(columnKey)}
          title={title || (typeof children === 'string' ? children : undefined)}
          className={
            'inline-flex items-start gap-1 rounded px-1 -mx-1 py-0.5 hover:bg-gray-100 transition-colors ' +
            (isActive ? 'text-gray-900' : 'text-gray-500')
          }
        >
          <span className="min-w-0">{children}</span>
          <Icon
            className={
              'h-3 w-3 flex-shrink-0 mt-0.5 ' +
              (isActive ? 'text-primary-600' : 'text-gray-300')
            }
          />
        </button>
        {rightSlot}
      </div>
    </th>
  )
}

export default function CallImportEvaluationDetail() {
  const { id, evalId } = useParams<{ id: string; evalId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
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
  const [forceFailPendingOpen, setForceFailPendingOpen] = useState(false)
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false)
  const downloadMenuRef = useRef<HTMLDivElement>(null)
  const [pdfReportOpen, setPdfReportOpen] = useState(false)
  const [pdfWizardStep, setPdfWizardStep] = useState(1)
  const [pdfUserInsightsTriggering, setPdfUserInsightsTriggering] =
    useState(false)
  const [pdfClusterModalOpen, setPdfClusterModalOpen] = useState(false)
  const [pdfGenerationError, setPdfGenerationError] = useState<string | null>(
    null,
  )
  const [pdfVendorName, setPdfVendorName] = useState('')
  const [pdfReportType, setPdfReportType] = useState<'external' | 'internal'>(
    'external',
  )
  const [pdfIncludeWeeklyDelta, setPdfIncludeWeeklyDelta] = useState(false)
  const [baselineCandidates, setBaselineCandidates] = useState<
    CallImportEvaluationBaselineCandidate[]
  >([])
  const [baselineEvaluationId, setBaselineEvaluationId] = useState<string | null>(
    null,
  )
  const [baselineCandidatesLoading, setBaselineCandidatesLoading] =
    useState(false)
  const [baselineCandidatesError, setBaselineCandidatesError] = useState<
    string | null
  >(null)
  const [pdfUseCase, setPdfUseCase] = useState('')
  const [pdfIncludeAuditSummary, setPdfIncludeAuditSummary] = useState(true)
  const [pdfIncludeQualityPanel, setPdfIncludeQualityPanel] = useState(true)
  const [pdfIncludeUserInsights, setPdfIncludeUserInsights] = useState(true)
  const [pdfIncludeDesignNotes, setPdfIncludeDesignNotes] = useState(true)
  const [pdfIncludeMethodology, setPdfIncludeMethodology] = useState(true)
  const [pdfIncludeFailureDiagnostics, setPdfIncludeFailureDiagnostics] =
    useState(true)
  const [pdfIncludePromptImprovements, setPdfIncludePromptImprovements] =
    useState(true)
  const [pdfPreviewOpen, setPdfPreviewOpen] = useState(false)
  const [pdfPreviewUrl, setPdfPreviewUrl] = useState<string | null>(null)
  const [pdfPreviewFilename, setPdfPreviewFilename] = useState('')
  const [vizBaselineEvaluationId, setVizBaselineEvaluationId] = useState<
    string | null
  >(null)
  const [selectedReportMetricIds, setSelectedReportMetricIds] = useState<Set<string>>(
    new Set(),
  )
  const [selectedReportInsightIds, setSelectedReportInsightIds] = useState<Set<string>>(
    new Set(),
  )
  const [selectedGeneratedUserInsightIds, setSelectedGeneratedUserInsightIds] =
    useState<Set<string>>(new Set())
  const [pdfReportError, setPdfReportError] = useState<string | null>(null)
  const [pdfReportLoadingAction, setPdfReportLoadingAction] = useState<
    null | 'preview' | 'download'
  >(null)
  const pdfReportLoading = pdfReportLoadingAction !== null
  const [reportBranding, setReportBranding] = useState<ReportBranding | null>(
    null,
  )
  const [reportHeadingDraft, setReportHeadingDraft] = useState('')
  const [internalBrandImageId, setInternalBrandImageId] = useState('')
  const [externalBrandImageId, setExternalBrandImageId] = useState('')
  const [reportBrandingLoading, setReportBrandingLoading] = useState(false)
  const [reportLogoUploading, setReportLogoUploading] = useState(false)
  const [reportLogoDeletingId, setReportLogoDeletingId] = useState<string | null>(
    null,
  )
  const [rowDeleteError, setRowDeleteError] = useState<string | null>(null)
  // Retry UX: ``retryError`` surfaces a banner on either failure path
  // (bulk or single-row). ``pendingRetryRowId`` is set while a per-row
  // retry is in flight so we can spin the button for that specific
  // row without disabling the entire actions column.
  const [retryError, setRetryError] = useState<string | null>(null)
  const [pendingRetryRowId, setPendingRetryRowId] = useState<string | null>(
    null,
  )
  const [retryConfirmOpen, setRetryConfirmOpen] = useState(false)
  // Optional overrides the user can set inside the bulk-retry modal.
  // ``null`` provider/model means "keep the run's saved value" — the
  // mutation only sends each field when the picker holds something
  // different from what's already on the evaluation, so the backend
  // never sees a half-configured payload.
  const [retryLLM, setRetryLLM] = useState<ProviderModelValue>({
    provider: null,
    model: null,
    credential_id: null,
  })
  const [retrySTT, setRetrySTT] = useState<ProviderModelValue>({
    provider: null,
    model: null,
    credential_id: null,
  })
  const [retryTranscribeOverwrite, setRetryTranscribeOverwrite] =
    useState(false)

  // "Re-run metrics" UX (separate from the failed-row retry above).
  // The user picks one or more of the run's already-scored metrics
  // and the worker recomputes only those, merging the new scores
  // into the row's existing ``metric_scores`` so other metrics'
  // values stay byte-identical. Backed by the same retry endpoint
  // with ``metric_ids`` + ``include_completed=true``.
  const [rerunMetricsOpen, setRerunMetricsOpen] = useState(false)
  const [rerunMetricIds, setRerunMetricIds] = useState<Set<string>>(
    new Set(),
  )
  const [rerunLLM, setRerunLLM] = useState<ProviderModelValue>({
    provider: null,
    model: null,
    credential_id: null,
  })
  const [rerunError, setRerunError] = useState<string | null>(null)
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
    // Same fallback dance as ``CallImportDetail.handleCopyConversationId``
    // — ``navigator.clipboard`` requires a secure context, so LAN dev
    // over plain HTTP needs the ``execCommand`` escape hatch.
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(finalize).catch(() => {
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
          // Drag-select still works as a last resort.
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
        // Drag-select still works as a last resort.
      }
    }
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
    !!flowFilter ||
    !!discoveredFilter

  const callImportQuery = useQuery({
    queryKey: ['call-import', id],
    queryFn: () => apiClient.getCallImport(id!, { row_limit: 0, row_offset: 0 }),
    enabled: !!id,
    // Poll while diarisation is in flight so the per-run "Diarising
    // audio…" progress bar updates as the upstream transcribe / diarise
    // worker churns through this batch's rows. Stops polling once
    // everything settles to terminal states.
    refetchInterval: (q) => {
      const ci = q.state.data as
        | {
            diarised_pending_rows?: number
            diarised_running_rows?: number
          }
        | undefined
      const inFlight =
        (ci?.diarised_pending_rows ?? 0) + (ci?.diarised_running_rows ?? 0)
      return inFlight > 0 ? 4000 : false
    },
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
      flowFilter?.parentId,
      flowFilter?.nodeId,
      flowFilter?.targetNodeId,
      discoveredFilter?.parentId,
      discoveredFilter?.labelKey,
      discoveredFilter?.anyDiscovered,
      sortBy,
      sortDir,
    ],
    queryFn: () =>
      apiClient.listCallImportEvaluationRows(id!, evalId!, {
        page,
        page_size: ROWS_PAGE_SIZE,
        q: searchQuery || undefined,
        status: statusFilter || undefined,
        metric_id: metricFilter?.metricId,
        metric_value: metricFilter?.value,
        flow_parent_id: flowFilter?.parentId,
        flow_node: flowFilter?.nodeId,
        flow_edge_target: flowFilter?.targetNodeId || undefined,
        discovered_parent_id: discoveredFilter?.parentId,
        discovered_label_key: discoveredFilter?.labelKey,
        has_discovered: discoveredFilter?.anyDiscovered || undefined,
        sort_by: sortBy || undefined,
        sort_dir: sortBy ? sortDir : undefined,
      }),
    enabled: !!id && !!evalId,
    refetchInterval: () => {
      const status = evaluationQuery.data?.status
      return status === 'pending' || status === 'running' ? 3000 : false
    },
  })

  useEffect(() => {
    if (!deepLinkConversationId && !deepLinkRowId) return
    if (deepLinkConversationId && searchQuery !== deepLinkConversationId) {
      setSearchQuery(deepLinkConversationId)
      setPage(1)
    }
  }, [deepLinkConversationId, deepLinkRowId, searchQuery])

  useEffect(() => {
    if (!deepLinkConversationId && !deepLinkRowId) return
    const items = rowsQuery.data?.items ?? []
    const match = items.find((row) =>
      deepLinkRowId
        ? row.id === deepLinkRowId
        : (row.conversation_id || '').trim() === deepLinkConversationId,
    )
    if (match) setDetailRow(match)
  }, [
    rowsQuery.data?.items,
    deepLinkConversationId,
    deepLinkRowId,
  ])

  const pendingRowsQuery = useQuery({
    queryKey: ['call-import-evaluation-pending-rows-count', id, evalId],
    queryFn: () =>
      apiClient.listCallImportEvaluationRows(id!, evalId!, {
        page: 1,
        page_size: 1,
        status: 'pending',
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
    queryKey: [
      'call-import-evaluation-aggregate',
      id,
      evalId,
      vizBaselineEvaluationId,
    ],
    queryFn: () =>
      apiClient.getCallImportEvaluationAggregate(
        id!,
        evalId!,
        vizBaselineEvaluationId,
      ),
    enabled:
      !!id &&
      !!evalId &&
      (resultsTab === 'visualizations' || resultsTab === 'table'),
    refetchInterval: () => {
      const status = evaluationQuery.data?.status
      return status === 'pending' || status === 'running' ? 5000 : false
    },
  })

  const visualizationInsightsQuery = useQuery<EvaluationTldrSummary | null>({
    queryKey: ['call-import-evaluation-insights', id, evalId],
    queryFn: () => apiClient.getCallImportEvaluationInsights(id!, evalId!),
    enabled: !!id && !!evalId && resultsTab === 'visualizations',
    refetchOnWindowFocus: false,
    refetchInterval: false,
  })

  const userInsightsQuery = useQuery<EvaluationUserInsightsState | null>({
    queryKey: ['call-import-evaluation-user-insights', id, evalId],
    queryFn: () =>
      apiClient.getCallImportEvaluationUserInsights(id!, evalId!),
    enabled:
      !!id &&
      !!evalId &&
      (resultsTab === 'visualizations' || pdfReportOpen),
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'running' ? 5000 : false
    },
  })

  const metricClustersQuery = useQuery<EvaluationMetricClustersState | null>({
    queryKey: ['call-import-evaluation-metric-clusters', id, evalId],
    queryFn: () =>
      apiClient.getCallImportEvaluationMetricClusters(id!, evalId!),
    enabled:
      !!id &&
      !!evalId &&
      (resultsTab === 'visualizations' || pdfReportOpen),
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'running' ? 5000 : false
    },
  })

  const promptImprovementsQuery = useQuery<EvaluationPromptImprovementsState | null>({
    queryKey: ['call-import-evaluation-prompt-improvements', id, evalId],
    queryFn: () =>
      apiClient.getCallImportEvaluationPromptImprovements(id!, evalId!),
    enabled:
      !!id &&
      !!evalId &&
      (resultsTab === 'visualizations' || pdfReportOpen),
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'running' ? 5000 : false
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

  // Re-enqueue every failed row in this run. The backend filters to
  // ``status='failed'`` server-side, so we don't need to know which
  // rows are currently failing — the button just hands the whole run
  // back to the workers. When the user changed the LLM / STT pickers
  // inside the retry modal we forward those as overrides; the backend
  // persists them onto the run so the next retry defaults to them.
  const retryAllFailedMutation = useMutation({
    mutationFn: () => {
      // Only forward LLM overrides when the user actually picked
      // BOTH provider and model — backend 400s on half-configured
      // input, and "did the user touch the picker" is fuzzy anyway
      // because it gets seeded from the run's saved values.
      const llmChanged =
        retryLLM.provider !== (evaluation?.llm_provider ?? null) ||
        retryLLM.model !== (evaluation?.llm_model ?? null) ||
        (retryLLM.credential_id ?? null) !==
          (evaluation?.llm_credential_id ?? null)
      const sttChanged =
        retrySTT.provider !== (evaluation?.stt_provider ?? null) ||
        retrySTT.model !== (evaluation?.stt_model ?? null) ||
        (retrySTT.credential_id ?? null) !==
          (evaluation?.stt_credential_id ?? null)

      return apiClient.retryCallImportEvaluation(id!, evalId!, {
        llmProvider:
          llmChanged && retryLLM.provider && retryLLM.model
            ? retryLLM.provider
            : undefined,
        llmModel:
          llmChanged && retryLLM.provider && retryLLM.model
            ? retryLLM.model
            : undefined,
        llmCredentialId:
          llmChanged && retryLLM.provider && retryLLM.model
            ? retryLLM.credential_id ?? null
            : undefined,
        sttProvider:
          sttChanged && retrySTT.provider && retrySTT.model
            ? retrySTT.provider
            : undefined,
        sttModel:
          sttChanged && retrySTT.provider && retrySTT.model
            ? retrySTT.model
            : undefined,
        sttCredentialId:
          sttChanged && retrySTT.provider && retrySTT.model
            ? retrySTT.credential_id ?? null
            : undefined,
        transcribeOverwrite: retryTranscribeOverwrite,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation', id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation-rows', id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluations', id],
      })
      setRetryError(null)
      setRetryConfirmOpen(false)
    },
    onError: (err: any) => {
      setRetryError(
        err?.response?.data?.detail ||
          err?.message ||
          'Failed to retry the evaluation.',
      )
    },
  })

  // Seed the retry pickers from the run's saved config the moment the
  // modal opens, then stop reacting to refetches. The 3s polling on
  // the evaluation query would otherwise clobber whatever the user
  // typed into the pickers, so we deliberately only depend on
  // ``retryConfirmOpen`` here.
  useEffect(() => {
    if (!retryConfirmOpen) return
    if (!evaluation) return
    setRetryLLM({
      provider: evaluation.llm_provider ?? null,
      model: evaluation.llm_model ?? null,
      credential_id: evaluation.llm_credential_id ?? null,
    })
    setRetrySTT({
      provider: evaluation.stt_provider ?? null,
      model: evaluation.stt_model ?? null,
      credential_id: evaluation.stt_credential_id ?? null,
    })
    setRetryTranscribeOverwrite(false)
    setRetryError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [retryConfirmOpen])

  // Same seeding pattern for the "Re-run metrics" modal. We default
  // the LLM picker to the run's saved value (no override) and start
  // with no metrics selected — the user must explicitly pick at
  // least one, otherwise the action is a no-op and we surface a
  // disabled state on the submit button.
  useEffect(() => {
    if (!rerunMetricsOpen) return
    if (!evaluation) return
    setRerunLLM({
      provider: evaluation.llm_provider ?? null,
      model: evaluation.llm_model ?? null,
      credential_id: evaluation.llm_credential_id ?? null,
    })
    setRerunMetricIds(new Set())
    setRerunError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rerunMetricsOpen])

  // Metric-subset re-run mutation. Forwards ``metric_ids`` to the
  // backend so the worker recomputes only those metrics, with
  // ``include_completed`` flipped on so already-successful rows are
  // eligible (the whole point of this UI). LLM overrides flow
  // through the same retry payload — when the user changes the LLM
  // picker, the backend persists the new model on the run and uses
  // it for every selected metric.
  const rerunMetricsMutation = useMutation({
    mutationFn: () => {
      const metricIds = Array.from(rerunMetricIds)
      if (!metricIds.length) {
        return Promise.reject(
          new Error('Pick at least one metric to re-run.'),
        )
      }
      const llmChanged =
        rerunLLM.provider !== (evaluation?.llm_provider ?? null) ||
        rerunLLM.model !== (evaluation?.llm_model ?? null) ||
        (rerunLLM.credential_id ?? null) !==
          (evaluation?.llm_credential_id ?? null)
      return apiClient.retryCallImportEvaluation(id!, evalId!, {
        metricIds,
        // ``include_completed`` would be auto-flipped server-side
        // when ``metricIds`` is set; sending it explicitly here
        // makes the intent obvious in the network tab.
        includeCompleted: true,
        llmProvider:
          llmChanged && rerunLLM.provider && rerunLLM.model
            ? rerunLLM.provider
            : undefined,
        llmModel:
          llmChanged && rerunLLM.provider && rerunLLM.model
            ? rerunLLM.model
            : undefined,
        llmCredentialId:
          llmChanged && rerunLLM.provider && rerunLLM.model
            ? rerunLLM.credential_id ?? null
            : undefined,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation', id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation-rows', id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluations', id],
      })
      setRerunError(null)
      setRerunMetricsOpen(false)
    },
    onError: (err: any) => {
      setRerunError(
        err?.response?.data?.detail ||
          err?.message ||
          'Failed to re-run the selected metrics.',
      )
    },
  })

  // Re-enqueue a single failed row. Returns the refreshed row so we
  // can prime the cache; the next polling tick (3s while running)
  // will catch any subsequent status flips.
  const retryRowMutation = useMutation({
    mutationFn: (rowId: string) =>
      apiClient.retryCallImportEvaluationRow(id!, evalId!, rowId),
    onMutate: (rowId) => {
      setPendingRetryRowId(rowId)
      setRetryError(null)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation', id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation-rows', id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluations', id],
      })
    },
    onError: (err: any) => {
      setRetryError(
        err?.response?.data?.detail ||
          err?.message ||
          'Failed to retry this row.',
      )
    },
    onSettled: () => {
      setPendingRetryRowId(null)
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

  // Run-level cancel: SIGTERM-revokes every in-flight row, flips them
  // to ``failed`` with the cancelled-by-user sentinel, and rolls up
  // the parent run. The 3s parent + rows pollers below pick the new
  // state up automatically; we still invalidate so the UI updates on
  // the next tick rather than waiting up to 3s.
  const cancelEvaluationMutation = useMutation({
    mutationFn: () => apiClient.cancelCallImportEvaluation(id!, evalId!),
    onMutate: () => {
      setCancelError(null)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation', id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation-rows', id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluations', id],
      })
    },
    onError: (err: any) => {
      setCancelError(
        err?.response?.data?.detail ||
          err?.message ||
          'Failed to abort this evaluation run.',
      )
    },
  })

  const forceFailPendingMutation = useMutation({
    mutationFn: () => apiClient.forceFailCallImportEvaluationPending(id!, evalId!),
    onMutate: () => {
      setCancelError(null)
    },
    onSuccess: () => {
      setForceFailPendingOpen(false)
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation', id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation-rows', id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation-pending-rows-count', id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluations', id],
      })
    },
    onError: (err: any) => {
      setCancelError(
        err?.response?.data?.detail ||
          err?.message ||
          'Failed to force-fail pending rows.',
      )
    },
  })

  // Row-level cancel: same shape as the run-level mutation but
  // scoped to a single row so the operator can stop one wedged row
  // without aborting siblings that are progressing fine.
  const cancelRowMutation = useMutation({
    mutationFn: (rowId: string) =>
      apiClient.cancelCallImportEvaluationRow(id!, evalId!, rowId),
    onMutate: (rowId) => {
      setCancellingRowId(rowId)
      setCancelError(null)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation', id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation-rows', id, evalId],
      })
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluations', id],
      })
    },
    onError: (err: any) => {
      setCancelError(
        err?.response?.data?.detail ||
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
    for (const row of rowsQuery.data?.items ?? []) {
      const scores = row.metric_scores
      if (!scores || typeof scores !== 'object') continue
      for (const [metricId, entry] of Object.entries(scores)) {
        if (!metricId) continue
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

  const tableMetricFilterValueOptions = useMemo(() => {
    if (!tableFilterMetricId || !aggregateQuery.data) return []
    const agg = aggregateQuery.data.metrics.find(
      (m) => m.metric_id === tableFilterMetricId,
    )
    if (!agg?.value_counts?.length) return []
    return [...agg.value_counts]
      .sort((a, b) => b.count - a.count)
      .map((vc) => ({
        value: String(vc.label),
        count: vc.count,
      }))
  }, [aggregateQuery.data, tableFilterMetricId])

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
    if (!metricFilter && !flowFilter) {
      setTableFilterMetricId('')
      setTableFilterMetricValue('')
    }
  }, [metricFilter, flowFilter])

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

  useEffect(() => {
    if (!pdfReportOpen) return
    setSelectedReportMetricIds(new Set(reportQualityMetrics.map((metric) => metric.id)))
    setSelectedReportInsightIds(new Set(reportInsightMetrics.map((metric) => metric.id)))
    const generated = userInsightsQuery.data?.insights ?? []
    if (generated.length) {
      setSelectedGeneratedUserInsightIds(new Set(generated.map((item) => item.id)))
    }
  }, [
    pdfReportOpen,
    reportQualityMetrics,
    reportInsightMetrics,
    userInsightsQuery.data?.insights,
  ])

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

  const internalBrandImages = useMemo(
    () =>
      (reportBranding?.images || []).filter(
        (image) => image.role === 'internal' || image.role === 'generic',
      ),
    [reportBranding?.images],
  )
  const externalBrandImages = useMemo(
    () =>
      (reportBranding?.images || []).filter(
        (image) => image.role === 'external' || image.role === 'generic',
      ),
    [reportBranding?.images],
  )

  const syncSelectedBrandImages = (branding: ReportBranding) => {
    const internalDefault =
      branding.images.find((image) => image.role === 'internal') ||
      branding.images.find((image) => image.role === 'generic')
    const externalDefault =
      branding.images.find((image) => image.role === 'external') ||
      branding.images.find((image) => image.role === 'generic')
    setInternalBrandImageId((current) =>
      current && branding.images.some((image) => image.id === current)
        ? current
        : internalDefault?.id || '',
    )
    setExternalBrandImageId((current) =>
      current && branding.images.some((image) => image.id === current)
        ? current
        : externalDefault?.id || '',
    )
  }

  const handleExport = async (format: 'csv' | 'xlsx') => {
    if (!id || !evalId) return
    setDownloadMenuOpen(false)
    try {
      const blob = await apiClient.exportCallImportEvaluation(id, evalId, format)
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `call-import-${id}-evaluation-${evalId}.${format}`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (e) {
      console.error('Failed to export evaluation', e)
      alert(`Failed to export evaluation ${format.toUpperCase()}`)
    }
  }

  const generatePdfReportBlob = async (vendorName: string) => {
    if ((reportBranding?.heading || '') !== reportHeadingDraft.trim()) {
      const branding = await apiClient.updateReportBranding({
        heading: reportHeadingDraft.trim() || null,
      })
      setReportBranding(branding)
      setReportHeadingDraft(branding.heading || '')
    }
    return apiClient.generateCallImportEvaluationPdfReport(
      id!,
      evalId!,
      vendorName,
      pdfReportType,
      pdfIncludeWeeklyDelta,
      {
        internalBrandImageId: internalBrandImageId || null,
        externalBrandImageId: externalBrandImageId || null,
        useCase: pdfUseCase.trim() || null,
        baselineEvaluationId: pdfIncludeWeeklyDelta ? baselineEvaluationId : null,
        platformBaseUrl:
          typeof window !== 'undefined' ? window.location.origin : null,
        reportConfig: {
          use_case: pdfUseCase.trim() || null,
          sections: {
            audit_summary: pdfIncludeAuditSummary,
            quality_panel: pdfIncludeQualityPanel,
            user_insights: pdfIncludeUserInsights,
            failure_diagnostics: pdfIncludeFailureDiagnostics,
            prompt_improvements: pdfIncludePromptImprovements,
            design_notes: pdfIncludeDesignNotes,
            methodology: pdfIncludeMethodology,
          },
          quality_metric_ids: Array.from(selectedReportMetricIds),
          user_insight_ids: Array.from(selectedGeneratedUserInsightIds),
          insights: Array.from(selectedReportInsightIds).map((metricId) => ({
            metric_id: metricId,
            show_observation: true,
            show_evidence: true,
          })),
          include_period_delta: pdfIncludeWeeklyDelta,
          order: {
            insights: Array.from(selectedReportInsightIds),
            user_insights: Array.from(selectedGeneratedUserInsightIds),
          },
        },
      },
    )
  }

  const handlePdfReportSubmit = async () => {
    if (!id || !evalId || pdfReportLoading) return
    const vendorName = pdfVendorName.trim()
    if (!vendorName) {
      setPdfReportError('Vendor name is required.')
      return
    }
    setPdfReportLoadingAction('download')
    setPdfReportError(null)
    try {
      const blob = await generatePdfReportBlob(vendorName)
      const vendorSlug =
        vendorName
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-+|-+$/g, '') || 'client'
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${vendorSlug}-${pdfReportType}-quality-metric-audit-${evalId}.pdf`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
      setPdfReportOpen(false)
      setPdfWizardStep(1)
      setPdfVendorName('')
      setPdfReportType('external')
      setPdfIncludeWeeklyDelta(false)
      setPdfUseCase('')
    } catch (e: any) {
      console.error('Failed to generate PDF report', e)
      setPdfReportError(
        e?.response?.data?.detail ||
          'Failed to generate PDF report. Please try again.',
      )
    } finally {
      setPdfReportLoadingAction(null)
    }
  }

  const handlePdfPreview = async () => {
    if (!id || !evalId || pdfReportLoading) return
    const vendorName = pdfVendorName.trim()
    if (!vendorName) {
      setPdfReportError('Vendor name is required.')
      return
    }
    setPdfReportLoadingAction('preview')
    setPdfReportError(null)
    try {
      const blob = await generatePdfReportBlob(vendorName)
      const vendorSlug =
        vendorName
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-+|-+$/g, '') || 'client'
      if (pdfPreviewUrl) window.URL.revokeObjectURL(pdfPreviewUrl)
      const url = window.URL.createObjectURL(blob)
      setPdfPreviewUrl(url)
      setPdfPreviewFilename(
        `${vendorSlug}-${pdfReportType}-quality-metric-audit-${evalId}.pdf`,
      )
      setPdfPreviewOpen(true)
    } catch (e: any) {
      console.error('Failed to preview PDF report', e)
      setPdfReportError(
        e?.response?.data?.detail ||
          'Failed to generate PDF preview. Please try again.',
      )
    } finally {
      setPdfReportLoadingAction(null)
    }
  }

  const PDF_WIZARD_STEPS = [
    { id: 1, label: 'Type & comparison' },
    { id: 2, label: 'Details & branding' },
    { id: 3, label: 'Content & metrics' },
    { id: 4, label: 'Preview & generate' },
  ] as const

  const pdfWizardVendorValid = pdfVendorName.trim().length > 0

  const pdfWizardMaxReachableStep = pdfWizardVendorValid ? 4 : 2

  const closePdfReportWizard = () => {
    if (pdfReportLoading) return
    setPdfReportOpen(false)
    setPdfWizardStep(1)
    setPdfReportError(null)
    setPdfGenerationError(null)
  }

  const pdfWizardCanReachStep = (step: number) =>
    step >= 1 && step <= pdfWizardMaxReachableStep

  const handlePdfWizardStepClick = (step: number) => {
    if (!pdfWizardCanReachStep(step) || pdfReportLoading) return
    setPdfReportError(null)
    setPdfWizardStep(step)
  }

  const handlePdfWizardNext = () => {
    if (pdfReportLoading) return
    if (pdfWizardStep === 2 && !pdfWizardVendorValid) {
      setPdfReportError('Vendor name is required.')
      return
    }
    setPdfReportError(null)
    if (pdfWizardStep < 4) setPdfWizardStep((s) => s + 1)
  }

  const handlePdfWizardBack = () => {
    if (pdfReportLoading || pdfWizardStep <= 1) return
    setPdfReportError(null)
    setPdfWizardStep((s) => s - 1)
  }

  const handlePdfWizardGenerateUserInsights = async () => {
    if (!id || !evalId || pdfUserInsightsTriggering) return
    const status = userInsightsQuery.data?.status
    if (status === 'running') return
    setPdfUserInsightsTriggering(true)
    setPdfGenerationError(null)
    try {
      await apiClient.generateCallImportEvaluationUserInsights(id, evalId, {})
      await userInsightsQuery.refetch()
    } catch (e: any) {
      setPdfGenerationError(
        e?.response?.data?.detail ||
          'Failed to start user insights generation.',
      )
    } finally {
      setPdfUserInsightsTriggering(false)
    }
  }

  const userInsightsNeedsGeneration =
    !userInsightsQuery.data ||
    userInsightsQuery.data.status === 'idle' ||
    userInsightsQuery.data.status === 'failed'

  const metricClustersNeedsGeneration =
    !metricClustersQuery.data ||
    metricClustersQuery.data.status === 'idle' ||
    metricClustersQuery.data.status === 'failed' ||
    metricClustersQuery.data.status === 'cancelled'

  useEffect(() => {
    if (!pdfReportOpen) return
    let cancelled = false
    setReportBrandingLoading(true)
    apiClient
      .getReportBranding()
      .then((branding) => {
        if (!cancelled) {
          setReportBranding(branding)
          setReportHeadingDraft(branding.heading || '')
          syncSelectedBrandImages(branding)
        }
      })
      .catch((e) => {
        console.error('Failed to load report branding', e)
        if (!cancelled) {
          setPdfReportError(
            e?.response?.data?.detail ||
              'Failed to load saved report branding.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setReportBrandingLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [pdfReportOpen])

  useEffect(() => {
    if (!pdfReportOpen) setPdfClusterModalOpen(false)
  }, [pdfReportOpen])

  useEffect(() => {
    if (resultsTab !== 'visualizations' || !id || !evalId) return
    let cancelled = false
    apiClient
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
    return () => {
      if (pdfPreviewUrl) window.URL.revokeObjectURL(pdfPreviewUrl)
    }
  }, [pdfPreviewUrl])

  useEffect(() => {
    if (!pdfReportOpen || !id || !evalId) return
    if (!pdfIncludeWeeklyDelta) {
      setBaselineCandidates([])
      setBaselineEvaluationId(null)
      setBaselineCandidatesError(null)
      return
    }
    let cancelled = false
    setBaselineCandidatesLoading(true)
    setBaselineCandidatesError(null)
    apiClient
      .listCallImportEvaluationBaselineCandidates(id, evalId)
      .then((response) => {
        if (cancelled) return
        setBaselineCandidates(response.items)
        const defaultId =
          response.default_evaluation_id ||
          response.items.find((item) => item.is_default)?.evaluation_id ||
          response.items[0]?.evaluation_id ||
          null
        setBaselineEvaluationId((current) => {
          if (current && response.items.some((item) => item.evaluation_id === current)) {
            return current
          }
          return defaultId
        })
      })
      .catch((e) => {
        console.error('Failed to load baseline candidates', e)
        if (!cancelled) {
          setBaselineCandidates([])
          setBaselineEvaluationId(null)
          setBaselineCandidatesError(
            e?.response?.data?.detail ||
              'Failed to load prior evaluation runs for weekly deltas.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setBaselineCandidatesLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [pdfReportOpen, pdfIncludeWeeklyDelta, id, evalId])

  const selectedBaselineCandidate = useMemo(
    () =>
      baselineCandidates.find(
        (candidate) => candidate.evaluation_id === baselineEvaluationId,
      ) || null,
    [baselineCandidates, baselineEvaluationId],
  )

  const handleReportLogoUpload = async (
    event: ChangeEvent<HTMLInputElement>,
    role: 'internal' | 'external' | 'generic',
  ) => {
    const files = Array.from(event.target.files || [])
    event.target.value = ''
    if (!files.length || reportLogoUploading) return
    setReportLogoUploading(true)
    setPdfReportError(null)
    try {
      const branding = await apiClient.uploadReportBrandingImages(files, role)
      setReportBranding(branding)
      setReportHeadingDraft(branding.heading || '')
      const newestForRole = [...branding.images]
        .reverse()
        .find((image) => image.role === role)
      if (role === 'internal') {
        setInternalBrandImageId(newestForRole?.id || '')
      } else if (role === 'external') {
        setExternalBrandImageId(newestForRole?.id || '')
      } else {
        syncSelectedBrandImages(branding)
      }
    } catch (e: any) {
      console.error('Failed to upload report logo', e)
      setPdfReportError(
        e?.response?.data?.detail ||
          'Failed to upload images. Use PNG, JPG, WEBP, or SVG up to 5 MB each.',
      )
    } finally {
      setReportLogoUploading(false)
    }
  }

  const handleReportImageDelete = async (imageId: string) => {
    if (reportLogoDeletingId) return
    setReportLogoDeletingId(imageId)
    setPdfReportError(null)
    try {
      const branding = await apiClient.deleteReportBrandingImage(imageId)
      setReportBranding(branding)
      setReportHeadingDraft(branding.heading || '')
      syncSelectedBrandImages(branding)
    } catch (e: any) {
      console.error('Failed to remove report image', e)
      setPdfReportError(
        e?.response?.data?.detail || 'Failed to remove saved report image.',
      )
    } finally {
      setReportLogoDeletingId(null)
    }
  }

  const handleReportHeadingSave = async () => {
    setPdfReportError(null)
    try {
      const branding = await apiClient.updateReportBranding({
        heading: reportHeadingDraft.trim() || null,
      })
      setReportBranding(branding)
      setReportHeadingDraft(branding.heading || '')
    } catch (e: any) {
      console.error('Failed to save report heading', e)
      setPdfReportError(
        e?.response?.data?.detail || 'Failed to save report heading.',
      )
    }
  }

  // Close the download format menu when the user clicks anywhere outside
  // it. Only attach the listener while the menu is open so we don't
  // pollute the global event bus.
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
  const pendingRowCount = pendingRowsQuery.data?.total ?? 0
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
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <Link
          to={`/call-imports/${id}`}
          className="inline-flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to call import
        </Link>
        <div className="flex items-center gap-2">
          {(evaluation.status === 'pending' ||
            evaluation.status === 'running') && (
            <Button
              variant="outline"
              size="sm"
              leftIcon={<XCircle className="h-4 w-4" />}
              onClick={() => {
                if (cancelEvaluationMutation.isPending) return
                cancelEvaluationMutation.mutate()
              }}
              isLoading={cancelEvaluationMutation.isPending}
              disabled={cancelEvaluationMutation.isPending}
              className="text-amber-700 hover:text-amber-800 hover:bg-amber-50 border-amber-200"
              title="Abort every in-flight or queued row in this run"
            >
              Abort run
            </Button>
          )}
          {pendingRowCount > 0 && (
            <Button
              variant="outline"
              size="sm"
              leftIcon={<AlertTriangle className="h-4 w-4" />}
              onClick={() => {
                if (forceFailPendingMutation.isPending) return
                setCancelError(null)
                setForceFailPendingOpen(true)
              }}
              isLoading={forceFailPendingMutation.isPending}
              disabled={forceFailPendingMutation.isPending}
              className="text-amber-700 hover:text-amber-800 hover:bg-amber-50 border-amber-200"
              title={`Mark ${pendingRowCount} pending row${
                pendingRowCount === 1 ? '' : 's'
              } as failed without aborting running rows`}
            >
              Force-fail pending ({pendingRowCount})
            </Button>
          )}
          {evaluation.failed_rows > 0 && (
            <Button
              variant="outline"
              size="sm"
              leftIcon={<RotateCw className="h-4 w-4" />}
              onClick={() => {
                setRetryError(null)
                setRetryConfirmOpen(true)
              }}
              isLoading={retryAllFailedMutation.isPending}
              disabled={retryAllFailedMutation.isPending}
              className="text-amber-700 hover:text-amber-800 hover:bg-amber-50 border-amber-200"
              title={`Re-run evaluation on ${evaluation.failed_rows} failed row${
                evaluation.failed_rows === 1 ? '' : 's'
              }`}
            >
              Retry failed ({evaluation.failed_rows})
            </Button>
          )}
          {(evaluation.metrics?.length ?? 0) > 0 && (
            <Button
              variant="outline"
              size="sm"
              leftIcon={<RefreshCw className="h-4 w-4" />}
              onClick={() => {
                setRerunError(null)
                setRerunMetricsOpen(true)
              }}
              isLoading={rerunMetricsMutation.isPending}
              disabled={rerunMetricsMutation.isPending}
              title="Re-score selected metrics across every row in this run, merging into existing scores."
            >
              Re-run metrics
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            leftIcon={<FileText className="h-4 w-4" />}
            onClick={() => {
              setPdfReportError(null)
              setPdfGenerationError(null)
              setPdfWizardStep(1)
              setPdfReportOpen(true)
            }}
            disabled={!rowsQuery.data?.items?.length}
          >
            Generate PDF Report
          </Button>
          <div className="relative" ref={downloadMenuRef}>
            <Button
              variant="outline"
              size="sm"
              leftIcon={<Download className="h-4 w-4" />}
              rightIcon={
                <ChevronDown
                  className={`h-4 w-4 transition-transform ${
                    downloadMenuOpen ? 'rotate-180' : ''
                  }`}
                />
              }
              onClick={() => setDownloadMenuOpen((prev) => !prev)}
              disabled={!rowsQuery.data?.items?.length}
            >
              Download
            </Button>
            {downloadMenuOpen && (
              <div
                className="absolute right-0 z-20 mt-1 w-44 bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden"
                role="menu"
              >
                <button
                  type="button"
                  className="w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                  onClick={() => handleExport('csv')}
                  role="menuitem"
                >
                  Download as CSV
                </button>
                <button
                  type="button"
                  className="w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                  onClick={() => handleExport('xlsx')}
                  role="menuitem"
                >
                  Download as Excel
                </button>
              </div>
            )}
          </div>
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
              <span
                className={
                  'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ' +
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
          <div className="w-72 flex-shrink-0">
            <div className="text-xs font-medium text-gray-600 mb-1">
              Evaluation progress
            </div>
            <CallImportProgressBar
              total={evaluation.total_rows}
              completed={evaluation.completed_rows}
              failed={evaluation.failed_rows}
            />
            <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
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

            {/*
              Upstream diarisation progress. When the user kicked off
              this run with auto-transcribe enabled on rows missing a
              diarised transcript, the eval row stays ``pending`` while
              the transcribe / diarise worker is in flight. Surfacing
              the parent batch's diarisation counters here tells the
              user the run isn't stalled — it's waiting on audio
              processing — and the bar fills as the worker churns.
              Polling on ``callImportQuery`` keeps these numbers fresh
              without a manual refresh.
            */}
            {(() => {
              const ci = callImport
              if (!ci) return null
              const diarisePending = ci.diarised_pending_rows ?? 0
              const diariseRunning = ci.diarised_running_rows ?? 0
              const diariseInFlight = diarisePending + diariseRunning
              const diariseDone =
                (ci.diarised_completed_rows ?? 0) +
                (ci.diarised_failed_rows ?? 0)
              const evalRunning =
                evaluation.status === 'pending' ||
                evaluation.status === 'running'
              // Only render while the upstream pipeline is actively
              // moving — once everything's settled we don't want a
              // stale 100% bar lingering for terminal runs.
              if (!evalRunning || diariseInFlight + diariseDone === 0) {
                return null
              }
              return (
                <div className="mt-4 pt-4 border-t border-gray-100">
                  <div className="flex items-center justify-between mb-1">
                    <div className="text-xs font-medium text-gray-600">
                      Diarising audio
                    </div>
                    {diariseInFlight > 0 && (
                      <div className="flex items-center gap-1 text-[11px] text-primary-700">
                        <RefreshCw className="h-3 w-3 animate-spin" />
                        {diariseInFlight} in progress
                      </div>
                    )}
                  </div>
                  <CallImportProgressBar
                    total={ci.total_rows}
                    completed={ci.diarised_completed_rows ?? 0}
                    failed={ci.diarised_failed_rows ?? 0}
                  />
                </div>
              )
            })()}
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
        <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Row results</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {filteredRowsSummary}. Scored against {displayMetrics.length}{' '}
              metric{displayMetrics.length === 1 ? '' : 's'}.
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
            <button
              type="button"
              onClick={() => setResultsTab('flow')}
              className={`px-3 py-1.5 text-xs font-medium rounded transition ${
                resultsTab === 'flow'
                  ? 'bg-white text-primary-700 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              <Workflow className="h-3.5 w-3.5 inline mr-1 -mt-0.5" />
              Flow
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
                  placeholder="Search by Conversation ID or transcript…"
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
              <select
                value={tableFilterMetricId}
                onChange={(e) => {
                  const nextId = e.target.value
                  setTableFilterMetricId(nextId)
                  setTableFilterMetricValue('')
                  setMetricFilter(null)
                  if (!nextId || !flowFilter?.targetNodeId) {
                    setFlowFilter(null)
                  }
                }}
                className="min-w-[160px] max-w-[220px] px-3 py-2 text-sm border border-gray-300 rounded-md shadow-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-500"
                title="Filter rows by a metric value"
              >
                <option value="">All metrics</option>
                {displayMetrics.map((metric) => (
                  <option key={metric.id} value={metric.id}>
                    {metric.name}
                  </option>
                ))}
              </select>
              {tableFilterMetricId ? (
                tableMetricFilterValueOptions.length > 0 ? (
                  <select
                    value={tableFilterMetricValue}
                    onChange={(e) => {
                      const nextValue = e.target.value
                      setTableFilterMetricValue(nextValue)
                      if (nextValue) {
                        applyTableMetricFilter(tableFilterMetricId, nextValue)
                      }
                    }}
                    disabled={aggregateQuery.isLoading}
                    className="min-w-[140px] max-w-[240px] px-3 py-2 text-sm border border-gray-300 rounded-md shadow-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-500 disabled:bg-gray-50"
                    title="Metric value to match"
                  >
                    <option value="">
                      {aggregateQuery.isLoading
                        ? 'Loading values…'
                        : 'Select value…'}
                    </option>
                    {tableMetricFilterValueOptions.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.value} ({opt.count})
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={tableFilterMetricValue}
                    onChange={(e) => setTableFilterMetricValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        applyTableMetricFilter(
                          tableFilterMetricId,
                          tableFilterMetricValue,
                        )
                      }
                    }}
                    placeholder={
                      aggregateQuery.isLoading
                        ? 'Loading…'
                        : 'Metric value (Enter to apply)'
                    }
                    className="min-w-[160px] px-3 py-2 text-sm border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-500"
                  />
                )
              ) : null}
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
                {flowFilter && (
                  <FilterChip
                    label={
                      flowFilter.targetNodeId
                        ? `${flowFilter.parentName}: ${flowFilter.nodeLabel} → ${flowFilter.targetNodeLabel}`
                        : `${flowFilter.parentName}: passed through "${flowFilter.nodeLabel}"`
                    }
                    onClear={() => setFlowFilter(null)}
                  />
                )}
                {discoveredFilter && (
                  <FilterChip
                    label={
                      discoveredFilter.anyDiscovered
                        ? `${discoveredFilter.parentName}: any LLM-discovered metric`
                        : `${discoveredFilter.parentName}: discovered "${
                            discoveredFilter.labelName ||
                            discoveredFilter.labelKey
                          }"`
                    }
                    onClear={() => setDiscoveredFilter(null)}
                  />
                )}
                <button
                  type="button"
                  onClick={() => {
                    setSearchInput('')
                    setSearchQuery('')
                    setStatusFilter(null)
                    setMetricFilter(null)
                    setFlowFilter(null)
                    setDiscoveredFilter(null)
                    setTableFilterMetricId('')
                    setTableFilterMetricValue('')
                  }}
                  className="ml-1 text-gray-500 underline underline-offset-2 hover:text-gray-700"
                >
                  Clear all
                </button>
              </div>
            )}
          </>
        )}

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
          ) : aggregateQuery.data.metrics.length === 0 ? (
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
                    <div className="inline-flex border border-gray-200 rounded-lg p-1 bg-gray-50 w-fit">
                      <button
                        type="button"
                        onClick={() => setVisualizationSubtab('quality')}
                        className={`px-3 py-1.5 text-xs font-medium rounded transition ${
                          visualizationSubtab === 'quality'
                            ? 'bg-white text-primary-700 shadow-sm'
                            : 'text-gray-600 hover:text-gray-900'
                        }`}
                      >
                        Quality Metrics
                      </button>
                      <button
                        type="button"
                        onClick={() => setVisualizationSubtab('aiInsights')}
                        className={`px-3 py-1.5 text-xs font-medium rounded transition ${
                          visualizationSubtab === 'aiInsights'
                            ? 'bg-white text-primary-700 shadow-sm'
                            : 'text-gray-600 hover:text-gray-900'
                        }`}
                      >
                        AI User Insights
                      </button>
                      <button
                        type="button"
                        onClick={() => setVisualizationSubtab('clusters')}
                        className={`px-3 py-1.5 text-xs font-medium rounded transition ${
                          visualizationSubtab === 'clusters'
                            ? 'bg-white text-primary-700 shadow-sm'
                            : 'text-gray-600 hover:text-gray-900'
                        }`}
                      >
                        Clusters
                      </button>
                      <button
                        type="button"
                        onClick={() => setVisualizationSubtab('improvements')}
                        className={`px-3 py-1.5 text-xs font-medium rounded transition ${
                          visualizationSubtab === 'improvements'
                            ? 'bg-white text-primary-700 shadow-sm'
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
                        onGenerated={() => {
                          queryClient.invalidateQueries({
                            queryKey: [
                              'call-import-evaluation-prompt-improvements',
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
                  setFlowFilter(null)
                  setDiscoveredFilter(null)
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
            {/* Top pagination mirrors the bottom controls so the user
                doesn't have to scroll past every row to flip pages. */}
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-gray-600">
              <span>{filteredRowsSummary}</span>
              {hasActiveFilters && rowsQuery.data ? (
                <span className="text-gray-500">
                  Page {rowsQuery.data.page} of {totalPages}
                </span>
              ) : null}
            </div>
            <Pagination
              page={rowsQuery.data.page}
              pageCount={totalPages}
              total={rowsQuery.data.total}
              pageSize={rowsQuery.data.page_size}
              className="mb-2"
              onPrev={() => setPage((p) => Math.max(1, p - 1))}
              onNext={() => setPage((p) => p + 1)}
            />
            <div className="overflow-x-auto border border-gray-100 rounded">
              <table className="min-w-max w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <SortableHeader
                      columnKey="row_index"
                      activeKey={sortBy}
                      activeDir={sortDir}
                      onCycle={handleColumnSort}
                      title="Row index"
                      className="sticky left-0 z-10 bg-gray-50"
                    >
                      #
                    </SortableHeader>
                    <SortableHeader
                      columnKey="conversation_id"
                      activeKey={sortBy}
                      activeDir={sortDir}
                      onCycle={handleColumnSort}
                    >
                      Conversation ID
                    </SortableHeader>
                    <SortableHeader
                      columnKey="status"
                      activeKey={sortBy}
                      activeDir={sortDir}
                      onCycle={handleColumnSort}
                      rightSlot={
                        <div className="relative" ref={statusFilterMenuRef}>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              setStatusFilterMenuOpen((v) => !v)
                            }}
                            className={
                              'p-1 rounded hover:bg-gray-200 transition-colors ' +
                              (statusFilter
                                ? 'text-primary-600'
                                : 'text-gray-400')
                            }
                            title={
                              statusFilter
                                ? `Status filter: ${statusFilter} (click to change)`
                                : 'Filter by status'
                            }
                            aria-label="Filter by status"
                          >
                            <Filter className="h-3 w-3" />
                          </button>
                          {statusFilterMenuOpen && (
                            <div
                              role="menu"
                              className="absolute left-0 top-full z-30 mt-1 w-40 bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden text-xs"
                            >
                              {[
                                { value: '', label: 'All statuses' },
                                { value: 'completed', label: 'Completed' },
                                { value: 'failed', label: 'Failed' },
                                { value: 'pending', label: 'Pending' },
                                { value: 'running', label: 'Running' },
                                { value: 'skipped', label: 'Skipped' },
                              ].map((opt) => {
                                const isCurrent =
                                  (statusFilter ?? '') === opt.value
                                return (
                                  <button
                                    key={opt.value || '__all'}
                                    type="button"
                                    role="menuitem"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      setStatusFilter(opt.value || null)
                                      setStatusFilterMenuOpen(false)
                                    }}
                                    className={
                                      'w-full px-3 py-1.5 text-left normal-case font-normal hover:bg-gray-50 flex items-center justify-between ' +
                                      (isCurrent
                                        ? 'text-primary-700'
                                        : 'text-gray-700')
                                    }
                                  >
                                    <span>{opt.label}</span>
                                    {isCurrent && (
                                      <Check className="h-3 w-3" />
                                    )}
                                  </button>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      }
                    >
                      Status
                    </SortableHeader>
                    {displayMetrics.flatMap((metric) => {
                      const llmLabel = getMetricLlmLabel(metric.id)
                      const headers = [
                        <SortableHeader
                          key={metric.id}
                          columnKey={`metric:${metric.id}`}
                          activeKey={sortBy}
                          activeDir={sortDir}
                          onCycle={handleColumnSort}
                          title={metric.name}
                        >
                          <span className="flex flex-col items-start leading-tight normal-case">
                            <span className="truncate max-w-[220px] text-xs font-medium text-gray-700">
                              {metric.name}
                            </span>
                            <span className="text-[10px] font-normal text-gray-400 mt-0.5">
                              {llmLabel}
                            </span>
                          </span>
                        </SortableHeader>,
                      ]
                      if (metric.hasRationale) {
                        headers.push(
                          <th
                            key={`${metric.id}__rationale`}
                            className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap"
                            title={`${metric.name} - LLM Rationale`}
                          >
                            <span className="flex flex-col items-start leading-tight normal-case">
                              <span className="text-xs font-medium text-gray-700">
                                {metric.name}{' '}
                                <span className="text-gray-400">- LLM Rationale</span>
                              </span>
                              <span className="text-[10px] font-normal text-gray-400 mt-0.5">
                                {llmLabel}
                              </span>
                            </span>
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
                        {/*
                          The conversation-id cell is the user-visible
                          row identifier and the most common thing an
                          operator wants to paste into Slack / a
                          ticket. The parent ``<tr>`` already has an
                          onClick to open the detail drawer; we stop
                          propagation here so drag-selecting the text
                          or hitting the inline Copy icon doesn't also
                          open the drawer. ``select-text`` re-enables
                          the native selection cursor that the row's
                          ``cursor-pointer`` would otherwise mask.
                         */}
                        <td
                          className="px-3 py-2 text-sm font-mono text-primary-700 whitespace-nowrap"
                          onClick={(e) => e.stopPropagation()}
                          onMouseDown={(e) => e.stopPropagation()}
                          onDoubleClick={(e) => e.stopPropagation()}
                        >
                          {row.conversation_id ? (
                            <span className="inline-flex items-center gap-2">
                              <span
                                className="select-text cursor-text"
                                title={row.conversation_id}
                              >
                                {row.conversation_id}
                              </span>
                              <button
                                type="button"
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
                                onClick={(e) =>
                                  handleCopyConversationId(row, e)
                                }
                                onMouseDown={(e) => e.stopPropagation()}
                                className={`inline-flex items-center justify-center w-6 h-6 rounded transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 ${
                                  copiedRowId === row.id
                                    ? 'text-green-600 bg-green-50'
                                    : 'text-gray-400 hover:text-primary-700 hover:bg-primary-50'
                                }`}
                              >
                                {copiedRowId === row.id ? (
                                  <Check className="h-3.5 w-3.5" />
                                ) : (
                                  <Copy className="h-3.5 w-3.5" />
                                )}
                              </button>
                            </span>
                          ) : (
                            '-'
                          )}
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
                          <div className="inline-flex items-center gap-1">
                            {(row.status === 'pending' ||
                              row.status === 'running') && (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  if (cancellingRowId) return
                                  cancelRowMutation.mutate(row.id)
                                }}
                                disabled={
                                  cancellingRowId !== null &&
                                  cancellingRowId !== row.id
                                }
                                className="p-1.5 rounded text-gray-400 hover:text-amber-700 hover:bg-amber-50 transition-colors disabled:opacity-40"
                                title="Abort this row"
                                aria-label="Abort evaluation row"
                              >
                                {cancellingRowId === row.id ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <XCircle className="h-4 w-4" />
                                )}
                              </button>
                            )}
                            {row.status === 'failed' && (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  if (pendingRetryRowId) return
                                  retryRowMutation.mutate(row.id)
                                }}
                                disabled={
                                  pendingRetryRowId !== null &&
                                  pendingRetryRowId !== row.id
                                }
                                className="p-1.5 rounded text-gray-400 hover:text-amber-700 hover:bg-amber-50 transition-colors disabled:opacity-40"
                                title="Retry evaluation on this row"
                                aria-label="Retry evaluation row"
                              >
                                {pendingRetryRowId === row.id ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <RotateCw className="h-4 w-4" />
                                )}
                              </button>
                            )}
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
                          </div>
                        </td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </div>

            <Pagination
              page={rowsQuery.data.page}
              pageCount={totalPages}
              total={rowsQuery.data.total}
              pageSize={rowsQuery.data.page_size}
              className="mt-3"
              onPrev={() => setPage((p) => Math.max(1, p - 1))}
              onNext={() => setPage((p) => p + 1)}
            />
          </>
        )}
      </div>

      <RowDetailPanel
        row={detailRow}
        displayMetrics={displayMetrics}
        parentMetrics={parentMetrics}
        onClose={() => setDetailRow(null)}
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
        isOpen={forceFailPendingOpen}
        title={`Force-fail ${pendingRowCount} pending row${
          pendingRowCount === 1 ? '' : 's'
        }?`}
        description={`This marks ${pendingRowCount} pending row${
          pendingRowCount === 1 ? '' : 's'
        } as failed immediately.\n\nThis won't affect rows currently running.`}
        confirmLabel={`Force-fail ${pendingRowCount} pending row${
          pendingRowCount === 1 ? '' : 's'
        }`}
        cancelLabel="Cancel"
        variant="danger"
        isLoading={forceFailPendingMutation.isPending}
        onConfirm={() => {
          if (!forceFailPendingMutation.isPending) {
            forceFailPendingMutation.mutate()
          }
        }}
        onCancel={() => {
          if (forceFailPendingMutation.isPending) return
          setForceFailPendingOpen(false)
        }}
      />

      {retryConfirmOpen &&
        createPortal(
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
              <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-gray-900">
                    Retry {evaluation.failed_rows} failed row
                    {evaluation.failed_rows === 1 ? '' : 's'}
                  </h2>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Reset failed rows and re-run them. You can keep the
                    run's existing LLM / STT or switch to a different
                    provider+model just for this retry pass — your
                    pick is saved onto the run so future retries
                    default to it.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    if (retryAllFailedMutation.isPending) return
                    setRetryConfirmOpen(false)
                    setRetryError(null)
                  }}
                  disabled={retryAllFailedMutation.isPending}
                  className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
                  aria-label="Close retry modal"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="px-6 py-5 overflow-y-auto flex-1 space-y-5">
                <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700 space-y-1">
                  <div>
                    <span className="font-medium">Currently saved:</span>{' '}
                    LLM ={' '}
                    <span className="font-mono">
                      {evaluation.llm_provider ?? '—'} /{' '}
                      {evaluation.llm_model ?? '—'}
                    </span>
                  </div>
                  <div>
                    STT ={' '}
                    <span className="font-mono">
                      {evaluation.stt_provider ?? '—'} /{' '}
                      {evaluation.stt_model ?? '—'}
                    </span>{' '}
                    · Transcript source ={' '}
                    <span className="font-mono">
                      {evaluation.transcript_source}
                    </span>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    LLM for re-evaluation
                  </label>
                  <p className="text-xs text-gray-500 mb-2">
                    Used to score every retried row. Leave as-is to
                    re-run with the same LLM as before.
                  </p>
                  <ProviderModelPicker
                    kind="llm"
                    value={retryLLM}
                    onChange={setRetryLLM}
                    allowCredentialPick
                    defaultLabel="Pick an LLM provider"
                  />
                </div>

                {evaluation.transcript_source === 'diarised' && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      STT for re-diarisation
                    </label>
                    <p className="text-xs text-gray-500 mb-2">
                      Only used when a retried row is missing its
                      diarised transcript, or when you opt to overwrite
                      below.
                    </p>
                    <ProviderModelPicker
                      kind="stt"
                      value={retrySTT}
                      onChange={setRetrySTT}
                      providerAllowList={STT_PROVIDER_ALLOWLIST}
                      allowCredentialPick
                      defaultLabel="Pick an STT provider"
                    />
                    <label className="mt-3 flex items-start gap-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={retryTranscribeOverwrite}
                        onChange={(e) =>
                          setRetryTranscribeOverwrite(e.target.checked)
                        }
                        className="mt-0.5 h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span>
                        <span className="font-medium">
                          Re-diarise existing transcripts
                        </span>{' '}
                        <span className="text-gray-500">
                          — wipe the diarised transcript on every
                          retried row so the new STT runs from scratch.
                          Leave unchecked to keep existing transcripts
                          and only re-score with the new LLM.
                        </span>
                      </span>
                    </label>
                  </div>
                )}

                <div className="rounded-md bg-amber-50 border border-amber-200 p-3 text-xs text-amber-900">
                  Completed rows and rows currently in progress are
                  left alone, so this is safe to run mid-evaluation.
                  The picked LLM / STT becomes the run's new default
                  for any future retry from this screen.
                </div>

                {retryError && (
                  <div className="rounded-md bg-red-50 border border-red-200 p-3">
                    <div className="flex items-start gap-2">
                      <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                      <p className="text-sm text-red-800">{retryError}</p>
                    </div>
                  </div>
                )}
              </div>

              <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-end gap-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    if (retryAllFailedMutation.isPending) return
                    setRetryConfirmOpen(false)
                    setRetryError(null)
                  }}
                  disabled={retryAllFailedMutation.isPending}
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  leftIcon={<RotateCw className="h-4 w-4" />}
                  onClick={() => {
                    if (!retryAllFailedMutation.isPending) {
                      retryAllFailedMutation.mutate()
                    }
                  }}
                  isLoading={retryAllFailedMutation.isPending}
                  disabled={
                    retryAllFailedMutation.isPending ||
                    !retryLLM.provider ||
                    !retryLLM.model
                  }
                >
                  Retry {evaluation.failed_rows} row
                  {evaluation.failed_rows === 1 ? '' : 's'}
                </Button>
              </div>
            </div>
          </div>,
          document.body,
        )}

      {rerunMetricsOpen &&
        createPortal(
          (() => {
            // List every metric known on the run, sorted by name for
            // deterministic scanning. We pull from
            // ``displayMetrics`` (computed above) so the picker stays
            // in sync with what the table renders: child metrics
            // collapsed under their parent, discovered-metric
            // candidates excluded until promoted, etc.
            const pickableMetrics = (displayMetrics ?? [])
              .slice()
              .sort((a, b) => a.name.localeCompare(b.name))
            const allIds = pickableMetrics.map((m) => m.id)
            const selectedCount = rerunMetricIds.size
            const allSelected =
              allIds.length > 0 && allIds.every((id) => rerunMetricIds.has(id))
            const noneSelected = selectedCount === 0
            return (
              <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
                <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
                  <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
                    <div>
                      <h2 className="text-lg font-semibold text-gray-900">
                        Re-run selected metrics
                      </h2>
                      <p className="text-xs text-gray-500 mt-0.5">
                        Pick the metrics you want to recompute. Every
                        row in this run is re-scored on just those
                        metrics; other metrics' values stay
                        byte-identical.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        if (rerunMetricsMutation.isPending) return
                        setRerunMetricsOpen(false)
                        setRerunError(null)
                      }}
                      disabled={rerunMetricsMutation.isPending}
                      className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
                      aria-label="Close re-run metrics modal"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>

                  <div className="px-6 py-5 overflow-y-auto flex-1 space-y-5">
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <label className="block text-sm font-medium text-gray-700">
                          Metrics to recompute
                        </label>
                        {pickableMetrics.length > 0 && (
                          <button
                            type="button"
                            className="text-[11px] text-primary-600 hover:text-primary-700"
                            onClick={() => {
                              if (allSelected) {
                                setRerunMetricIds(new Set())
                              } else {
                                setRerunMetricIds(new Set(allIds))
                              }
                            }}
                          >
                            {allSelected ? 'Clear all' : 'Select all'}
                          </button>
                        )}
                      </div>
                      {pickableMetrics.length === 0 ? (
                        <p className="text-sm text-gray-500 italic">
                          This run has no scored metrics yet — nothing
                          to re-run.
                        </p>
                      ) : (
                        <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-64 overflow-y-auto">
                          {pickableMetrics.map((m) => {
                            const checked = rerunMetricIds.has(m.id)
                            return (
                              <label
                                key={m.id}
                                className="flex items-start gap-3 px-3 py-2 hover:bg-gray-50 cursor-pointer"
                              >
                                <input
                                  type="checkbox"
                                  className="mt-0.5 h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                                  checked={checked}
                                  onChange={(e) => {
                                    setRerunMetricIds((prev) => {
                                      const next = new Set(prev)
                                      if (e.target.checked) {
                                        next.add(m.id)
                                      } else {
                                        next.delete(m.id)
                                      }
                                      return next
                                    })
                                  }}
                                />
                                <div className="min-w-0 flex-1">
                                  <p className="text-sm font-medium text-gray-900 truncate">
                                    {m.name}
                                  </p>
                                  <p className="text-[11px] text-gray-500 font-mono truncate">
                                    {m.id}
                                  </p>
                                </div>
                              </label>
                            )
                          })}
                        </div>
                      )}
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        LLM for re-evaluation
                      </label>
                      <p className="text-xs text-gray-500 mb-2">
                        Used to score the selected metrics. Leave as-is
                        to re-run with the run's existing LLM.
                      </p>
                      <ProviderModelPicker
                        kind="llm"
                        value={rerunLLM}
                        onChange={setRerunLLM}
                        allowCredentialPick
                        defaultLabel="Pick an LLM provider"
                      />
                    </div>

                    <div className="rounded-md bg-blue-50 border border-blue-200 p-3 text-xs text-blue-900">
                      Already-successful rows are eligible too — only
                      the selected metrics' scores are overwritten; the
                      rest of <code>metric_scores</code> is preserved
                      verbatim.
                    </div>

                    {rerunError && (
                      <div className="rounded-md bg-red-50 border border-red-200 p-3">
                        <div className="flex items-start gap-2">
                          <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                          <p className="text-sm text-red-800">{rerunError}</p>
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-end gap-3">
                    <Button
                      variant="outline"
                      onClick={() => {
                        if (rerunMetricsMutation.isPending) return
                        setRerunMetricsOpen(false)
                        setRerunError(null)
                      }}
                      disabled={rerunMetricsMutation.isPending}
                    >
                      Cancel
                    </Button>
                    <Button
                      variant="primary"
                      leftIcon={<RefreshCw className="h-4 w-4" />}
                      onClick={() => {
                        if (!rerunMetricsMutation.isPending && !noneSelected) {
                          rerunMetricsMutation.mutate()
                        }
                      }}
                      isLoading={rerunMetricsMutation.isPending}
                      disabled={
                        rerunMetricsMutation.isPending ||
                        noneSelected ||
                        !rerunLLM.provider ||
                        !rerunLLM.model
                      }
                    >
                      Re-run {selectedCount > 0 ? `${selectedCount} ` : ''}
                      metric{selectedCount === 1 ? '' : 's'}
                    </Button>
                  </div>
                </div>
              </div>
            )
          })(),
          document.body,
        )}

      {pdfReportOpen &&
        createPortal(
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
              <div className="px-6 py-4 border-b border-gray-200 flex-shrink-0">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="text-lg font-semibold text-gray-900">
                      Generate PDF report
                    </h2>
                    <p className="text-xs text-gray-500 mt-0.5">
                      Step {pdfWizardStep} of {PDF_WIZARD_STEPS.length}:{' '}
                      {PDF_WIZARD_STEPS[pdfWizardStep - 1]?.label}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={closePdfReportWizard}
                    disabled={pdfReportLoading}
                    className="text-gray-400 hover:text-gray-600 disabled:opacity-50 shrink-0"
                    aria-label="Close PDF report modal"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
                <ol className="mt-4 flex items-stretch gap-1.5">
                  {PDF_WIZARD_STEPS.map((step) => {
                    const reachable = pdfWizardCanReachStep(step.id)
                    const active = pdfWizardStep === step.id
                    const done = pdfWizardStep > step.id
                    return (
                      <li key={step.id} className="flex-1 min-w-0">
                        <button
                          type="button"
                          onClick={() => handlePdfWizardStepClick(step.id)}
                          disabled={!reachable || pdfReportLoading}
                          className={`w-full rounded-md px-2 py-2 text-left transition-colors disabled:cursor-not-allowed ${
                            active
                              ? 'bg-primary-50 text-primary-800 ring-1 ring-primary-200'
                              : done
                                ? 'text-green-800 hover:bg-green-50'
                                : reachable
                                  ? 'text-gray-700 hover:bg-gray-50'
                                  : 'text-gray-400'
                          }`}
                        >
                          <span className="flex items-center gap-1.5">
                            <span
                              className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                                done
                                  ? 'bg-green-100 text-green-700'
                                  : active
                                    ? 'bg-primary-100 text-primary-700'
                                    : 'bg-gray-100 text-gray-500'
                              }`}
                            >
                              {done ? (
                                <Check className="h-3 w-3" aria-hidden />
                              ) : (
                                step.id
                              )}
                            </span>
                            <span className="truncate text-[10px] font-medium leading-tight sm:text-[11px]">
                              {step.label}
                            </span>
                          </span>
                        </button>
                      </li>
                    )
                  })}
                </ol>
              </div>

              <div className="px-6 py-5 space-y-4 overflow-y-auto flex-1 min-h-0">
                {pdfWizardStep === 1 && (
                  <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Report type
                  </label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <label className="flex items-start gap-2 rounded-md border border-gray-200 p-3 hover:bg-gray-50 cursor-pointer">
                      <input
                        type="radio"
                        name="pdf-report-type"
                        value="external"
                        checked={pdfReportType === 'external'}
                        disabled={pdfReportLoading}
                        onChange={() => setPdfReportType('external')}
                        className="mt-0.5 h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span>
                        <span className="block text-sm font-medium text-gray-900">
                          External vendor
                        </span>
                        <span className="block text-xs text-gray-500">
                          Vendor-safe report without internal diagnostic IDs.
                        </span>
                      </span>
                    </label>
                    <label className="flex items-start gap-2 rounded-md border border-gray-200 p-3 hover:bg-gray-50 cursor-pointer">
                      <input
                        type="radio"
                        name="pdf-report-type"
                        value="internal"
                        checked={pdfReportType === 'internal'}
                        disabled={pdfReportLoading}
                        onChange={() => setPdfReportType('internal')}
                        className="mt-0.5 h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-500"
                      />
                      <span>
                        <span className="block text-sm font-medium text-gray-900">
                          Internal team
                        </span>
                        <span className="block text-xs text-gray-500">
                          Includes diagnostic context for QA review.
                        </span>
                      </span>
                    </label>
                  </div>
                </div>

                <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700 space-y-1">
                  <label className="mb-2 flex items-start gap-2 text-sm text-gray-800">
                    <input
                      type="checkbox"
                      checked={pdfIncludeWeeklyDelta}
                      disabled={pdfReportLoading}
                      onChange={(e) => setPdfIncludeWeeklyDelta(e.target.checked)}
                      className="mt-0.5 h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500 disabled:opacity-50"
                    />
                    <span>
                      <span className="block font-medium">
                        Include previous-week metric deltas
                      </span>
                      <span className="block text-xs text-gray-500">
                        Compares this report against a prior completed evaluation
                        run in the same workspace.
                      </span>
                    </span>
                  </label>
                  {pdfIncludeWeeklyDelta && (
                    <div className="mt-3 space-y-2 rounded-md border border-gray-200 bg-white p-3">
                      <div className="text-xs font-medium text-gray-800">
                        Previous-week comparison run
                      </div>
                      {baselineCandidatesLoading ? (
                        <div className="flex items-center gap-2 text-xs text-gray-500">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          Loading prior evaluation runs...
                        </div>
                      ) : baselineCandidatesError ? (
                        <p className="text-xs text-red-600">{baselineCandidatesError}</p>
                      ) : baselineCandidates.length === 0 ? (
                        <p className="text-xs text-gray-500">
                          No prior completed evaluation run was found in this
                          workspace. Deltas will show as unavailable.
                        </p>
                      ) : (
                        <>
                          {selectedBaselineCandidate && (
                            <p className="text-xs text-gray-600">
                              Using{' '}
                              <span className="font-medium text-gray-900">
                                {selectedBaselineCandidate.name}
                              </span>{' '}
                              from {selectedBaselineCandidate.dataset} (
                              {selectedBaselineCandidate.period_display})
                            </p>
                          )}
                          <label className="block text-xs text-gray-600">
                            Override comparison run
                            <select
                              value={baselineEvaluationId || ''}
                              disabled={pdfReportLoading}
                              onChange={(e) =>
                                setBaselineEvaluationId(e.target.value || null)
                              }
                              className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 disabled:opacity-50"
                            >
                              {baselineCandidates.map((candidate) => (
                                <option
                                  key={candidate.evaluation_id}
                                  value={candidate.evaluation_id}
                                >
                                  {candidate.name} · {candidate.dataset} ·{' '}
                                  {candidate.period_display}
                                  {candidate.is_default ? ' (default)' : ''}
                                </option>
                              ))}
                            </select>
                          </label>
                        </>
                      )}
                    </div>
                  )}
                </div>
                  </>
                )}

                {pdfWizardStep === 2 && (
                  <>
                <div>
                  <label
                    htmlFor="pdf-vendor-name"
                    className="block text-sm font-medium text-gray-700 mb-1"
                  >
                    Vendor / client name
                  </label>
                  <input
                    id="pdf-vendor-name"
                    type="text"
                    value={pdfVendorName}
                    onChange={(e) => {
                      setPdfVendorName(e.target.value)
                      if (pdfReportError) setPdfReportError(null)
                    }}
                    disabled={pdfReportLoading}
                    placeholder="Vendor or client name"
                    className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 disabled:bg-gray-50 disabled:text-gray-500"
                    autoFocus
                  />
                </div>

                <div>
                  <label
                    htmlFor="pdf-use-case"
                    className="block text-sm font-medium text-gray-700 mb-1"
                  >
                    Use case / audit window label
                  </label>
                  <input
                    id="pdf-use-case"
                    type="text"
                    value={pdfUseCase}
                    onChange={(e) => setPdfUseCase(e.target.value)}
                    disabled={pdfReportLoading}
                    placeholder="Inbound · Service"
                    className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 disabled:bg-gray-50 disabled:text-gray-500"
                  />
                </div>

                <div>
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <label className="block text-sm font-medium text-gray-700">
                      Header branding
                    </label>
                    {reportBrandingLoading && (
                      <span className="inline-flex items-center gap-1 text-xs text-gray-500">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        Loading
                      </span>
                    )}
                  </div>
                  <div className="rounded-md border border-gray-200 p-3 space-y-3">
                    <div>
                      <label
                        htmlFor="pdf-report-heading"
                        className="block text-xs font-medium text-gray-600 mb-1"
                      >
                        Custom heading
                      </label>
                      <div className="flex gap-2">
                        <input
                          id="pdf-report-heading"
                          type="text"
                          value={reportHeadingDraft}
                          onChange={(e) => setReportHeadingDraft(e.target.value)}
                          placeholder="Quality Audit Report"
                          className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                          disabled={pdfReportLoading}
                        />
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleReportHeadingSave}
                          disabled={pdfReportLoading}
                        >
                          Save
                        </Button>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div className="rounded border border-gray-200 p-3 space-y-2">
                        <label className="block text-xs font-semibold text-gray-700">
                          Internal brand
                        </label>
                        <select
                          value={internalBrandImageId}
                          onChange={(e) => setInternalBrandImageId(e.target.value)}
                          disabled={pdfReportLoading}
                          className="block w-full rounded-md border border-gray-300 px-2 py-2 text-xs shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                        >
                          <option value="">No internal logo</option>
                          {internalBrandImages.map((image) => (
                            <option key={image.id} value={image.id}>
                              {image.filename}
                            </option>
                          ))}
                        </select>
                        <label className="inline-flex items-center justify-center rounded-md border border-gray-300 px-2 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 cursor-pointer">
                          Upload internal
                          <input
                            type="file"
                            accept="image/png,image/jpeg,image/webp,image/svg+xml"
                            className="sr-only"
                            disabled={reportLogoUploading || pdfReportLoading}
                            onChange={(event) =>
                              handleReportLogoUpload(event, 'internal')
                            }
                          />
                        </label>
                      </div>
                      <div className="rounded border border-gray-200 p-3 space-y-2">
                        <label className="block text-xs font-semibold text-gray-700">
                          Vendor brand
                        </label>
                        <select
                          value={externalBrandImageId}
                          onChange={(e) => setExternalBrandImageId(e.target.value)}
                          disabled={pdfReportLoading}
                          className="block w-full rounded-md border border-gray-300 px-2 py-2 text-xs shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                        >
                          <option value="">No vendor logo</option>
                          {externalBrandImages.map((image) => (
                            <option key={image.id} value={image.id}>
                              {image.filename}
                            </option>
                          ))}
                        </select>
                        <label className="inline-flex items-center justify-center rounded-md border border-gray-300 px-2 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 cursor-pointer">
                          Upload vendor
                          <input
                            type="file"
                            accept="image/png,image/jpeg,image/webp,image/svg+xml"
                            className="sr-only"
                            disabled={reportLogoUploading || pdfReportLoading}
                            onChange={(event) =>
                              handleReportLogoUpload(event, 'external')
                            }
                          />
                        </label>
                      </div>
                    </div>

                    {reportBranding?.images?.length ? (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {reportBranding.images.map((image) => (
                          <div
                            key={image.id}
                            className="flex items-center justify-between gap-2 rounded border border-gray-200 p-2"
                          >
                            <div className="flex items-center gap-2 min-w-0">
                              {image.data_uri && (
                                <img
                                  src={image.data_uri}
                                  alt={image.filename}
                                  className="h-10 w-12 object-contain rounded border border-gray-200 bg-white"
                                />
                              )}
                              <div className="min-w-0">
                                <p className="text-xs font-medium text-gray-900 truncate">
                                  {image.filename}
                                </p>
                                <p className="text-[11px] text-gray-500">
                                  {image.role} · {Math.ceil(image.size_bytes / 1024)} KB
                                </p>
                              </div>
                            </div>
                            <button
                              type="button"
                              onClick={() => handleReportImageDelete(image.id)}
                              disabled={
                                reportLogoDeletingId !== null || pdfReportLoading
                              }
                              className="text-xs font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
                            >
                              {reportLogoDeletingId === image.id
                                ? 'Removing…'
                                : 'Remove'}
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-gray-600">
                        No custom images saved for this workspace.
                      </p>
                    )}
                    <p className="text-xs text-gray-500">
                      PNG, JPG, WEBP, or SVG up to 5 MB each. Saved per workspace.
                    </p>
                  </div>
                </div>
                {pdfReportError && pdfWizardStep === 2 && (
                  <div className="rounded-md bg-red-50 border border-red-200 p-3">
                    <div className="flex items-start gap-2">
                      <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                      <p className="text-sm text-red-800">{pdfReportError}</p>
                    </div>
                  </div>
                )}
                  </>
                )}

                {pdfWizardStep === 3 && (
                  <>
                <div className="rounded-md border border-gray-200 p-3 space-y-3">
                  <div>
                    <h3 className="text-sm font-medium text-gray-900">
                      Report customization
                    </h3>
                    <p className="text-xs text-gray-500">
                      Choose sections and the metrics/insights that should appear in
                      this PDF.
                    </p>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
                    {[
                      ['Audit Summary', pdfIncludeAuditSummary, setPdfIncludeAuditSummary],
                      ['Quality Metric Panel', pdfIncludeQualityPanel, setPdfIncludeQualityPanel],
                      ['User Insights', pdfIncludeUserInsights, setPdfIncludeUserInsights],
                      ...(pdfReportType === 'internal'
                        ? [
                            [
                              'Failure Diagnostics',
                              pdfIncludeFailureDiagnostics,
                              setPdfIncludeFailureDiagnostics,
                            ] as const,
                            [
                              'Prompt Improvements',
                              pdfIncludePromptImprovements,
                              setPdfIncludePromptImprovements,
                            ] as const,
                          ]
                        : []),
                      ['Design Notes', pdfIncludeDesignNotes, setPdfIncludeDesignNotes],
                      ['Methodology', pdfIncludeMethodology, setPdfIncludeMethodology],
                    ].map(([label, checked, setter]) => (
                      <label key={label as string} className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={checked as boolean}
                          disabled={pdfReportLoading}
                          onChange={(e) =>
                            (setter as (value: boolean) => void)(e.target.checked)
                          }
                          className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                        />
                        <span>{label as string}</span>
                      </label>
                    ))}
                  </div>
                  {reportQualityMetrics.length ? (
                    <div>
                      <p className="text-xs font-semibold text-gray-600 mb-1">
                        Quality metrics
                      </p>
                      <div className="max-h-24 overflow-auto rounded border border-gray-100 p-2 space-y-1">
                        {reportQualityMetrics.map((metric) => (
                          <label key={metric.id} className="flex items-center gap-2 text-xs">
                            <input
                              type="checkbox"
                              checked={selectedReportMetricIds.has(metric.id)}
                              onChange={(e) => {
                                setSelectedReportMetricIds((prev) => {
                                  const next = new Set(prev)
                                  if (e.target.checked) next.add(metric.id)
                                  else next.delete(metric.id)
                                  return next
                                })
                              }}
                              className="h-3.5 w-3.5 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                            />
                            <span>{metric.name}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {reportInsightMetrics.length && pdfReportType === 'internal' ? (
                    <div>
                      <p className="text-xs font-semibold text-gray-600 mb-1">
                        User insight metrics (internal)
                      </p>
                      <div className="max-h-24 overflow-auto rounded border border-gray-100 p-2 space-y-1">
                        {reportInsightMetrics.map((metric) => (
                          <label key={metric.id} className="flex items-center gap-2 text-xs">
                            <input
                              type="checkbox"
                              checked={selectedReportInsightIds.has(metric.id)}
                              onChange={(e) => {
                                setSelectedReportInsightIds((prev) => {
                                  const next = new Set(prev)
                                  if (e.target.checked) next.add(metric.id)
                                  else next.delete(metric.id)
                                  return next
                                })
                              }}
                              className="h-3.5 w-3.5 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                            />
                            <span>{metric.name}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {pdfReportType === 'external' ? (
                    <div>
                      <p className="text-xs font-semibold text-gray-600 mb-1">
                        AI user insights (external report)
                      </p>
                      {userInsightsQuery.data?.status === 'running' ? (
                        <p className="text-xs text-amber-700">
                          User insights are still generating. You can continue;
                          the PDF includes them when ready.
                        </p>
                      ) : userInsightsQuery.data?.status === 'completed' &&
                        userInsightsQuery.data.insights.length ? (
                        <div className="max-h-32 overflow-auto rounded border border-gray-100 p-2 space-y-1">
                          {userInsightsQuery.data.insights.map((insight) => (
                            <label
                              key={insight.id}
                              className="flex items-center gap-2 text-xs"
                            >
                              <input
                                type="checkbox"
                                checked={selectedGeneratedUserInsightIds.has(
                                  insight.id,
                                )}
                                disabled={pdfReportLoading}
                                onChange={(e) => {
                                  setSelectedGeneratedUserInsightIds((prev) => {
                                    const next = new Set(prev)
                                    if (e.target.checked) next.add(insight.id)
                                    else next.delete(insight.id)
                                    return next
                                  })
                                }}
                                className="h-3.5 w-3.5 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                              />
                              <span>{insight.title}</span>
                            </label>
                          ))}
                        </div>
                      ) : userInsightsNeedsGeneration ? (
                        <div className="space-y-2">
                          <p className="text-xs text-gray-500">
                            User insights are not available yet. Start generation
                            here (runs in the background) or continue without
                            section 03 content.
                          </p>
                          <Button
                            variant="outline"
                            size="sm"
                            leftIcon={<Sparkles className="h-3.5 w-3.5" />}
                            onClick={handlePdfWizardGenerateUserInsights}
                            isLoading={pdfUserInsightsTriggering}
                            disabled={
                              pdfUserInsightsTriggering || pdfReportLoading
                            }
                          >
                            Generate user insights
                          </Button>
                        </div>
                      ) : (
                        <p className="text-xs text-gray-500">
                          No user insights are available for this evaluation yet.
                        </p>
                      )}
                    </div>
                  ) : null}
                  {pdfReportType === 'internal' && pdfIncludeFailureDiagnostics ? (
                    (() => {
                      const clusterStatus = metricClustersQuery.data?.status
                      const clusterGroups = metricClustersQuery.data?.groups
                      const clusterProgress = metricClustersQuery.data?.progress
                      const clusterCompleted =
                        clusterProgress?.completed_llm_calls ?? 0
                      const clusterTotal = clusterProgress?.total_llm_calls ?? 0
                      const clusterPct =
                        clusterTotal > 0
                          ? Math.min(
                              100,
                              Math.round((clusterCompleted / clusterTotal) * 100),
                            )
                          : 0
                      return (
                        <div className="rounded-md border border-gray-100 bg-gray-50/80 p-3 space-y-2">
                          <p className="text-xs font-semibold text-gray-700">
                            Failure diagnostics
                          </p>
                          {clusterStatus === 'running' ? (
                            <div className="space-y-2">
                              <p className="text-xs text-amber-700">
                                Clusters are generating in the background. You can
                                continue; the PDF includes them when ready.
                              </p>
                              {clusterTotal > 0 ? (
                                <>
                                  <p className="text-[10px] text-gray-600 tabular-nums">
                                    {clusterCompleted} / {clusterTotal} LLM calls
                                    ({clusterPct}%)
                                  </p>
                                  <div className="h-2 rounded-full bg-amber-100 overflow-hidden">
                                    <div
                                      className="h-full bg-amber-600 transition-all duration-300"
                                      style={{ width: `${clusterPct}%` }}
                                      role="progressbar"
                                      aria-valuenow={clusterCompleted}
                                      aria-valuemin={0}
                                      aria-valuemax={clusterTotal}
                                    />
                                  </div>
                                </>
                              ) : (
                                <div className="h-2 rounded-full bg-amber-100 overflow-hidden">
                                  <div className="h-full w-1/3 bg-amber-400 animate-pulse rounded-full" />
                                </div>
                              )}
                            </div>
                          ) : clusterStatus === 'completed' && clusterGroups?.length ? (
                            <p className="text-xs text-green-700">
                              Includes {clusterGroups.length} cluster group
                              {clusterGroups.length === 1 ? '' : 's'} in the PDF:
                              metric-level failure clusters, counts, examples, and
                              RCA summaries where available.
                            </p>
                          ) : metricClustersNeedsGeneration ? (
                            <div className="space-y-2">
                              <p className="text-xs text-gray-500">
                                Clusters are not available yet. Start generation
                                here (runs in the background) or continue without
                                cluster content in the PDF.
                              </p>
                              <Button
                                variant="outline"
                                size="sm"
                                leftIcon={<Grid3x3 className="h-3.5 w-3.5" />}
                                onClick={() => {
                                  setPdfGenerationError(null)
                                  setPdfClusterModalOpen(true)
                                }}
                                disabled={pdfReportLoading}
                              >
                                Generate clusters
                              </Button>
                            </div>
                          ) : (
                            <p className="text-xs text-gray-500">
                              No cluster groups are available for this evaluation
                              yet.
                            </p>
                          )}
                        </div>
                      )
                    })()
                  ) : null}
                  {pdfReportType === 'internal' && pdfIncludePromptImprovements ? (
                    <div className="rounded-md border border-gray-100 bg-gray-50/80 p-3 space-y-2">
                      <p className="text-xs font-semibold text-gray-700">
                        Prompt improvement recommendations
                      </p>
                      {promptImprovementsQuery.data?.status === 'running' ? (
                        <p className="text-xs text-amber-700">
                          Suggestions are generating in the background.
                        </p>
                      ) : promptImprovementsQuery.data?.status === 'completed' &&
                        promptImprovementsQuery.data.suggestions.length ? (
                        <p className="text-xs text-gray-600">
                          Top{' '}
                          {Math.min(5, promptImprovementsQuery.data.suggestions.length)}{' '}
                          recommended change
                          {Math.min(5, promptImprovementsQuery.data.suggestions.length) === 1
                            ? ''
                            : 's'}{' '}
                          for{' '}
                          {promptImprovementsQuery.data.imported_agent_name ||
                            'the mapped imported agent'}{' '}
                          will be included, with before/after prompt text for edits and
                          addition blocks for new content.
                        </p>
                      ) : (
                        <p className="text-xs text-gray-500">
                          Generate suggestions in Visualizations → Prompt / Agent
                          Improvements before including this section.
                        </p>
                      )}
                    </div>
                  ) : null}
                </div>

                {(pdfGenerationError || pdfReportError) && pdfWizardStep === 3 && (
                  <div className="rounded-md bg-red-50 border border-red-200 p-3">
                    <div className="flex items-start gap-2">
                      <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                      <p className="text-sm text-red-800">
                        {pdfGenerationError || pdfReportError}
                      </p>
                    </div>
                  </div>
                )}
                  </>
                )}

                {pdfWizardStep === 4 && (
                  <>
                <div className="rounded-md border border-gray-200 bg-gray-50 p-4 space-y-3 text-sm text-gray-800">
                  <h3 className="font-medium text-gray-900">Review your report</h3>
                  <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-xs">
                    <div>
                      <dt className="text-gray-500">Report type</dt>
                      <dd className="font-medium capitalize">{pdfReportType}</dd>
                    </div>
                    <div>
                      <dt className="text-gray-500">Vendor</dt>
                      <dd className="font-medium">{pdfVendorName.trim() || '—'}</dd>
                    </div>
                    <div>
                      <dt className="text-gray-500">Use case</dt>
                      <dd className="font-medium">
                        {pdfUseCase.trim() || '—'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-gray-500">Previous-week deltas</dt>
                      <dd className="font-medium">
                        {pdfIncludeWeeklyDelta ? 'Yes' : 'No'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-gray-500">Quality metrics</dt>
                      <dd className="font-medium">
                        {selectedReportMetricIds.size} selected
                      </dd>
                    </div>
                    <div>
                      <dt className="text-gray-500">Sections</dt>
                      <dd className="font-medium">
                        {[
                          pdfIncludeAuditSummary && 'Audit',
                          pdfIncludeQualityPanel && 'Quality',
                          pdfIncludeUserInsights && 'Insights',
                          pdfReportType === 'internal' &&
                            pdfIncludeFailureDiagnostics &&
                            'Diagnostics',
                          pdfIncludeDesignNotes && 'Design',
                          pdfIncludeMethodology && 'Methodology',
                        ]
                          .filter(Boolean)
                          .join(', ') || 'None'}
                      </dd>
                    </div>
                  </dl>
                  <p className="text-xs text-gray-600">
                    Preview the PDF before downloading. Metric panels include
                    evaluated counts, flagged rate, passing rate, and value
                    distributions. CSV and Excel exports remain in the Download
                    menu.
                  </p>
                </div>

                {pdfReportError && (
                  <div className="rounded-md bg-red-50 border border-red-200 p-3">
                    <div className="flex items-start gap-2">
                      <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                      <p className="text-sm text-red-800">{pdfReportError}</p>
                    </div>
                  </div>
                )}
                  </>
                )}
              </div>

              <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between gap-3 flex-shrink-0">
                <Button
                  variant="outline"
                  onClick={closePdfReportWizard}
                  disabled={pdfReportLoading}
                >
                  Cancel
                </Button>
                <div className="flex items-center gap-3">
                  {pdfWizardStep > 1 && (
                    <Button
                      variant="outline"
                      onClick={handlePdfWizardBack}
                      disabled={pdfReportLoading}
                    >
                      Back
                    </Button>
                  )}
                  {pdfWizardStep < 4 ? (
                    <Button
                      variant="primary"
                      onClick={handlePdfWizardNext}
                      disabled={pdfReportLoading}
                    >
                      Next
                    </Button>
                  ) : (
                    <>
                      <Button
                        variant="outline"
                        onClick={handlePdfPreview}
                        isLoading={pdfReportLoadingAction === 'preview'}
                        disabled={pdfReportLoading || !pdfWizardVendorValid}
                      >
                        Preview
                      </Button>
                      <Button
                        variant="primary"
                        leftIcon={<FileText className="h-4 w-4" />}
                        onClick={handlePdfReportSubmit}
                        isLoading={pdfReportLoadingAction === 'download'}
                        disabled={pdfReportLoading || !pdfWizardVendorValid}
                      >
                        Download PDF
                      </Button>
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>,
          document.body,
        )}

      {id && evalId ? (
        <MetricClusterGenerationModal
          open={pdfClusterModalOpen}
          onClose={() => setPdfClusterModalOpen(false)}
          callImportId={id}
          evaluationId={evalId}
          defaultProvider={evaluation?.llm_provider ?? ''}
          defaultModel={evaluation?.llm_model ?? ''}
          state={metricClustersQuery.data ?? null}
          overlayZIndexClass="z-[70]"
          onGenerated={() => {
            queryClient.invalidateQueries({
              queryKey: [
                'call-import-evaluation-metric-clusters',
                id,
                evalId,
              ],
            })
            setPdfClusterModalOpen(false)
          }}
          onError={setPdfGenerationError}
        />
      ) : null}

      {pdfPreviewOpen &&
        pdfPreviewUrl &&
        createPortal(
          <div className="fixed inset-0 z-[60] flex flex-col bg-black/50">
            <div className="flex items-center justify-between gap-3 px-4 py-3 bg-white border-b border-gray-200 shadow-sm">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-900 truncate">
                  PDF preview — {pdfPreviewFilename}
                </p>
                <p className="text-xs text-gray-500">
                  Review the report before downloading. Close to return to
                  configuration.
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Button
                  variant="outline"
                  onClick={() => {
                    if (!pdfPreviewUrl) return
                    const link = document.createElement('a')
                    link.href = pdfPreviewUrl
                    link.download = pdfPreviewFilename
                    document.body.appendChild(link)
                    link.click()
                    link.remove()
                  }}
                >
                  Download
                </Button>
                <Button
                  variant="primary"
                  onClick={() => {
                    if (pdfPreviewUrl) window.URL.revokeObjectURL(pdfPreviewUrl)
                    setPdfPreviewUrl(null)
                    setPdfPreviewOpen(false)
                  }}
                >
                  Close
                </Button>
              </div>
            </div>
            <iframe
              title="PDF report preview"
              src={pdfPreviewUrl}
              className="flex-1 w-full bg-gray-100 border-0"
            />
          </div>,
          document.body,
        )}

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
 * and the recording (played back from our S3 copy via a presigned
 * URL). Triggered by clicking a table row.
 *
 * The backdrop matches the platform's standard modal overlay
 * (``bg-gray-500 bg-opacity-75``) so it reads as a proper modal
 * regardless of which page opens it. We portal into ``document.body``
 * so the overlay can't be clipped by an ancestor with ``overflow``.
 */
function RowDetailPanel({
  row,
  displayMetrics,
  parentMetrics,
  onClose,
}: {
  row: CallImportEvaluationRow | null
  displayMetrics: { id: string; name: string; hasRationale: boolean }[]
  parentMetrics: {
    id: string
    name: string
    selection_mode: 'single_choice' | 'multi_label' | null
    children: { id: string; name: string }[]
  }[]
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

  // Resolve the downloaded recording (S3 object) into a short-lived
  // presigned URL. We prefer this over ``row.recording_url`` because
  // many provider URLs are time-limited / auth-gated and won't play
  // back in an <audio> tag.
  const recordingS3Key = row?.recording_s3_key || null
  const {
    data: presignedRecording,
    isLoading: presignedLoading,
    isError: presignedError,
  } = useQuery({
    queryKey: ['call-import-row-recording-presign', recordingS3Key],
    queryFn: () => apiClient.getS3PresignedUrl(recordingS3Key!),
    enabled: !!recordingS3Key,
    staleTime: 60 * 1000,
  })

  if (!row) return null

  const callId = row.conversation_id || `Row ${(row.row_index ?? 0) + 1}`
  const playbackUrl = presignedRecording?.url || null

  const panel = (
    <div
      className="fixed inset-0 z-[9999] flex justify-end bg-gray-500 bg-opacity-75"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <aside
        className="w-full max-w-xl bg-white shadow-2xl overflow-y-auto border-l border-gray-200 h-full"
        onClick={(e) => e.stopPropagation()}
      >
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
              {row.recording_date && (
                <span>· Recorded {formatRecordingDate(row.recording_date)}</span>
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

          {/* Recording — play from our downloaded S3 copy (not the raw
              provider URL) so playback works regardless of provider
              URL expiry / auth requirements. */}
          {recordingS3Key ? (
            <section>
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                Recording
              </h3>
              {presignedLoading && !playbackUrl ? (
                <div className="text-xs text-gray-500 inline-flex items-center gap-2">
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                  Loading audio…
                </div>
              ) : presignedError || !playbackUrl ? (
                <div className="text-xs text-red-700 inline-flex items-center gap-2">
                  <AlertCircle className="h-3.5 w-3.5" />
                  Could not load recording from storage.
                </div>
              ) : (
                <>
                  <audio
                    controls
                    src={playbackUrl}
                    className="w-full"
                    preload="metadata"
                  />
                  <a
                    href={playbackUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-flex items-center gap-1 text-[11px] text-primary-600 hover:text-primary-700"
                  >
                    Open in new tab
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </>
              )}
            </section>
          ) : row.recording_url ? (
            // Fallback: no downloaded copy yet — show the provider URL
            // as a link only (don't try to play it inline, which often
            // fails on expired/auth-gated provider URLs).
            <section>
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                Recording
              </h3>
              <p className="text-xs text-gray-500 mb-1">
                Recording hasn't been downloaded to storage yet.
              </p>
              <a
                href={row.recording_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[11px] text-primary-600 hover:text-primary-700"
              >
                Open source URL in new tab
                <ExternalLink className="h-3 w-3" />
              </a>
            </section>
          ) : null}

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

          {/* Per-call flow diagrams — one per parent category metric.
              Driven entirely by the ``sequence`` array the LLM
              produced for this row, so it always matches the scores
              above. */}
          {parentMetrics.length > 0 && (() => {
            const flowEntries = parentMetrics
              .map((parent) => {
                const score = (row.metric_scores || {})[parent.id]
                if (!score || typeof score !== 'object') return null
                const sequence = (score as any).sequence
                if (!Array.isArray(sequence) || sequence.length === 0)
                  return null
                const childByKey: Record<string, { id: string; name: string }> =
                  {}
                for (const child of parent.children) {
                  childByKey[child.id] = child
                  childByKey[child.name] = child
                  // The worker stores sequence entries as lower_snake_case
                  // slugs of the child name (matching the LLM JSON key).
                  // Accept that shape here so per-call flows render even
                  // when the backend never round-tripped to UUIDs.
                  childByKey[
                    child.name.toLowerCase().replace(/\s+/g, '_')
                  ] = child
                }
                const discovered = Array.isArray(
                  (score as any).discovered_labels,
                )
                  ? ((score as any).discovered_labels as Array<{
                      key?: string
                      name?: string
                    }>)
                      .filter(
                        (d): d is { key: string; name?: string } =>
                          typeof d?.key === 'string' && d.key.length > 0,
                      )
                  : []
                const data = flowFromSequence(
                  parent.id,
                  parent.name,
                  sequence as string[],
                  childByKey,
                  parent.selection_mode,
                  discovered,
                )
                if (data.nodes.length === 0) return null
                return { parent, data }
              })
              .filter(
                (entry): entry is { parent: typeof parentMetrics[number]; data: ReturnType<typeof flowFromSequence> } =>
                  entry !== null,
              )
            if (flowEntries.length === 0) return null
            return (
              <section>
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                  Call flow ({flowEntries.length})
                </h3>
                <div className="space-y-3">
                  {flowEntries.map(({ parent, data }) => (
                    <div
                      key={parent.id}
                      className="border border-gray-200 rounded-md p-2"
                    >
                      <p className="text-xs font-medium text-gray-700 mb-1.5">
                        {parent.name}
                      </p>
                      <MetricFlowChart
                        data={data}
                        mode="per_call"
                        height={220}
                      />
                    </div>
                  ))}
                </div>
              </section>
            )
          })()}

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

  if (typeof document === 'undefined') return panel
  return createPortal(panel, document.body)
}

// Light-themed tooltip styling shared by every recharts ``Tooltip``
// on this page. Replaces the previous dark navy backdrop which made
// the hovered number hard to read against most page colors.
const CHART_TOOLTIP_STYLE: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid #e5e7eb',
  borderRadius: 8,
  fontSize: 11,
  color: '#0f172a',
  boxShadow: '0 8px 24px rgba(15, 23, 42, 0.08)',
  padding: '6px 10px',
}
const CHART_TOOLTIP_LABEL_STYLE: React.CSSProperties = {
  color: '#475569',
  fontWeight: 500,
  marginBottom: 2,
}
const CHART_TOOLTIP_ITEM_STYLE: React.CSSProperties = {
  color: '#0f172a',
  fontWeight: 600,
}

/**
 * Available categorical chart types for a given metric. Multi-label
 * parents get the heatmap + cumulative coverage extras; everything
 * else gets the pie/donut option (which would mislead on multi-label
 * because slices wouldn't sum to 100%). The picker uses this to grey
 * out icons that don't apply.
 */
function availableChartTypesFor(
  metric: CallImportMetricAggregate,
): CategoricalChartType[] {
  const isMulti = metric.is_multi_label_parent === true
  const base: CategoricalChartType[] = ['bar', 'lollipop', 'treemap']
  if (!isMulti) {
    base.push('pie', 'radial', 'waffle')
  }
  if (isMulti) {
    base.push('coverage', 'heatmap')
  }
  return base
}

const CHART_TYPE_META: Record<
  CategoricalChartType,
  { label: string; Icon: React.ComponentType<{ className?: string }> }
> = {
  pie: { label: 'Pie / donut', Icon: PieChartIcon },
  bar: { label: 'Horizontal bar', Icon: BarChart3 },
  lollipop: { label: 'Lollipop', Icon: CircleDot },
  radial: { label: 'Radial bar', Icon: Target },
  treemap: { label: 'Treemap', Icon: LayoutGrid },
  waffle: { label: 'Waffle (10×10)', Icon: Grid3x3 },
  coverage: { label: 'Cumulative coverage', Icon: TrendingUp },
  heatmap: { label: 'Co-occurrence heatmap', Icon: Grid3x3 },
}

/**
 * Compact icon-row picker rendered top-right of every chart card.
 * Clicking a non-active icon overrides the per-metric chart type;
 * clicking the already-active icon when an override is present
 * reverts to the global default ("auto").
 */
function CategoricalChartPicker({
  metric,
  active,
  overridden,
  onChange,
}: {
  metric: CallImportMetricAggregate
  active: CategoricalChartType
  overridden: boolean
  onChange: (type: CategoricalChartType | null) => void
}) {
  const types = availableChartTypesFor(metric)
  return (
    <div className="inline-flex items-center gap-0.5 rounded-md border border-gray-200 bg-gray-50/70 p-0.5">
      {types.map((t) => {
        const meta = CHART_TYPE_META[t]
        const Icon = meta.Icon
        const isActive = active === t
        return (
          <button
            key={t}
            type="button"
            title={meta.label}
            aria-pressed={isActive}
            onClick={() => {
              if (isActive && overridden) onChange(null)
              else onChange(t)
            }}
            className={`p-1 rounded transition ${
              isActive
                ? 'bg-white text-primary-700 shadow-sm'
                : 'text-gray-500 hover:text-gray-800 hover:bg-white/70'
            }`}
          >
            <Icon className="h-3 w-3" />
          </button>
        )
      })}
    </div>
  )
}

/**
 * Sort categorical value counts desc by count so every chart type
 * renders the most-impactful labels first. Backend already does this
 * for the categorical aggregator, but defensive sorting keeps the
 * frontend correct if a future code path returns unsorted data.
 */
function sortValueCounts(
  counts: CallImportMetricAggregate['value_counts'],
): CallImportMetricAggregate['value_counts'] {
  return [...counts].sort((a, b) => b.count - a.count)
}

/**
 * Truncate a long categorical label so it fits inside a tooltip /
 * tile / legend slot. The full text is always available via the
 * surrounding ``title`` attribute or tooltip content.
 */
function truncateLabel(label: string, max = 24): string {
  if (typeof label !== 'string') return ''
  if (label.length <= max) return label
  return `${label.slice(0, max - 1)}…`
}

/**
 * Side-legend below the chart. Every category is clickable so the
 * user can drill in even when the chart itself is hard to click
 * (e.g. tiny treemap tiles or thin pie slices). Defaults to showing
 * the top 6 with a "Show all" toggle so a long-tail metric doesn't
 * dominate the card vertically.
 */
function CategoryLegend({
  valueCounts,
  totalCategorical,
  activeValue,
  onValueClick,
}: {
  valueCounts: CallImportMetricAggregate['value_counts']
  totalCategorical: number
  activeValue: string | null
  onValueClick: (value: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const COLLAPSED_LIMIT = 6
  const visible =
    expanded || valueCounts.length <= COLLAPSED_LIMIT
      ? valueCounts
      : valueCounts.slice(0, COLLAPSED_LIMIT)
  const hidden = valueCounts.length - visible.length
  return (
    <div className="mt-3 text-[11px]">
      <ul className="space-y-1">
        {visible.map((vc, i) => {
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
                <span
                  className="text-left flex-1 break-words"
                  title={vc.label}
                >
                  {vc.label}
                </span>
                <span className="font-medium text-gray-900 tabular-nums">
                  {vc.count}
                </span>
                <span className="text-gray-400 w-10 text-right tabular-nums">
                  {pct.toFixed(0)}%
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mt-1 text-[10px] text-primary-600 hover:text-primary-800 px-1.5"
        >
          Show {hidden} more
        </button>
      )}
      {expanded && valueCounts.length > COLLAPSED_LIMIT && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="mt-1 text-[10px] text-gray-500 hover:text-gray-700 px-1.5"
        >
          Show less
        </button>
      )}
    </div>
  )
}

/**
 * Custom Y-axis tick for the horizontal categorical charts (lollipop
 * and ranked bar). Sizes its truncation to the column width the
 * caller passes via ``colWidth`` (recharts itself does not forward
 * the YAxis ``width`` prop into custom tick components, so we plumb
 * it explicitly) and exposes the full text via an SVG ``<title>``
 * so hovering a clipped row reveals the original label. Long labels
 * also drop one font size so we squeeze in a few extra characters
 * before having to clip.
 */
function LongLabelTick(props: any) {
  const { x, y, payload, colWidth } = props
  const value: string = String(payload?.value ?? '')
  const slot = typeof colWidth === 'number' && colWidth > 0 ? colWidth : 200
  const fontSize = value.length > 22 ? 10 : 11
  const charPx = fontSize * 0.58
  const maxChars = Math.max(8, Math.floor((slot - 12) / charPx))
  const display =
    value.length > maxChars ? `${value.slice(0, maxChars - 1)}…` : value
  return (
    <g transform={`translate(${x},${y})`}>
      <title>{value}</title>
      <text
        x={-6}
        y={0}
        dy={4}
        textAnchor="end"
        fill="#334155"
        fontSize={fontSize}
      >
        {display}
      </text>
    </g>
  )
}

/**
 * Single-metric chart card used inside the Visualizations tab. Picks
 * the chart shape from the aggregate payload: numeric histograms beat
 * categorical pie/bar charts when both are present, since numeric
 * distributions tell a richer story than the top-N category tally.
 *
 * Categorical metrics support pie, bar, lollipop, radial, treemap,
 * waffle, plus multi-label-only co-occurrence heatmap and cumulative
 * coverage. The chart type comes from the resolver in the parent so
 * it picks up both the global default and any per-metric override.
 *
 * Clicking a tile / bar / slice / square calls ``onValueClick(label)``
 * with the value the user wants to drill into — the parent uses that
 * to apply a row-table filter.
 */
function MetricVisualization({
  metric,
  chartType,
  chartOverridden,
  onChangeChartType,
  isActive,
  activeValue,
  businessInsight,
  periodDelta,
  failurePoliciesSource,
  onValueClick,
}: {
  metric: CallImportMetricAggregate
  chartType: CategoricalChartType
  chartOverridden: boolean
  onChangeChartType: (type: CategoricalChartType | null) => void
  isActive: boolean
  activeValue: string | null
  businessInsight?: string | null
  periodDelta?: MetricPeriodDelta | null
  failurePoliciesSource?: 'inferred' | 'user' | null
  onValueClick: (value: string) => void
}) {
  const histogram = metric.histogram_buckets
  const valueCounts = useMemo(
    () => sortValueCounts(metric.value_counts),
    [metric.value_counts],
  )
  const hasNumeric = histogram.length > 0 || metric.mean != null
  const hasCategorical = valueCounts.length > 0
  const totalCategorical = valueCounts.reduce((sum, v) => sum + v.count, 0)
  const isMultiLabelParent = metric.is_multi_label_parent === true

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
            contentStyle={CHART_TOOLTIP_STYLE}
            labelStyle={CHART_TOOLTIP_LABEL_STYLE}
            itemStyle={CHART_TOOLTIP_ITEM_STYLE}
            cursor={{ fill: 'rgba(99,102,241,0.08)' }}
            formatter={(value: any) => [`${value} rows`, 'Count']}
          />
          <Bar
            dataKey="count"
            fill={`url(#bar-num-${metric.metric_id})`}
            radius={[4, 4, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    )
  } else if (valueCounts.length) {
    chart = (
      <CategoricalChart
        metric={metric}
        chartType={chartType}
        valueCounts={valueCounts}
        totalCategorical={totalCategorical}
        activeValue={activeValue}
        onValueClick={onValueClick}
      />
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
            <span
              className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-gray-100 text-gray-700"
              title={
                isMultiLabelParent
                  ? 'Rows scored. Each row may contribute to several labels.'
                  : 'Number of rows that produced a score for this metric.'
              }
            >
              n = {metric.count}
              {isMultiLabelParent ? ' rows' : ''}
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
            {isMultiLabelParent ? (
              <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-primary-50 text-primary-700">
                Multi-label
              </span>
            ) : (
              metric.metric_type && (
                <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-primary-50 text-primary-700 capitalize">
                  {metric.metric_type}
                </span>
              )
            )}
            {periodDelta?.label ? (
              <span
                className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-slate-100 text-slate-700"
                title={periodDelta.detail || 'vs prior evaluation run'}
              >
                {periodDelta.label} vs prior
              </span>
            ) : null}
            {failurePoliciesSource === 'inferred' ? (
              <span
                className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-amber-50 text-amber-800"
                title="Confirm failure values in Failure diagnostics → Generate clusters"
              >
                Suggested failure rate
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {isActive && (
            <span className="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full bg-primary-100 text-primary-800">
              <Filter className="h-3 w-3" />
              Filtering
            </span>
          )}
          {hasCategorical && !hasNumeric && (
            <CategoricalChartPicker
              metric={metric}
              active={chartType}
              overridden={chartOverridden}
              onChange={onChangeChartType}
            />
          )}
        </div>
      </div>

      {periodDelta?.why ? (
        <p className="mb-3 text-[11px] text-slate-600 leading-snug">
          {clampProseToSentences(periodDelta.why, 2)}
        </p>
      ) : null}

      {hasNumeric && (
        <div className="mb-3 grid grid-cols-4 gap-2">
          {[
            {
              label: 'Mean',
              value: metric.mean,
              title: 'Average score across all rows',
              tone: 'neutral' as const,
            },
            {
              label: 'Best',
              value: metric.max,
              title: 'Highest single-row score',
              tone: 'good' as const,
            },
            {
              label: 'Worst',
              value: metric.min,
              title: 'Lowest single-row score',
              tone: 'bad' as const,
            },
            {
              label: 'σ',
              value: metric.stddev,
              title:
                'Standard deviation — lower means more consistent scoring',
              tone: 'neutral' as const,
            },
          ].map((stat) => (
            <div
              key={stat.label}
              title={stat.title}
              className="rounded-md bg-gradient-to-br from-gray-50 to-gray-100/60 border border-gray-100 px-2 py-1.5 text-center"
            >
              <p className="text-[9px] uppercase tracking-wider text-gray-500">
                {stat.label}
              </p>
              <p
                className={`text-xs font-semibold tabular-nums ${
                  stat.tone === 'good'
                    ? 'text-emerald-700'
                    : stat.tone === 'bad'
                      ? 'text-rose-700'
                      : 'text-gray-900'
                }`}
              >
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

      {businessInsight && (
        <div className="mt-3 rounded-lg border border-primary-100 bg-primary-50/60 px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-primary-700">
            Business insight
          </p>
          <p className="mt-1 text-xs leading-relaxed text-gray-700">
            {businessInsight}
          </p>
        </div>
      )}

      {hasCategorical && totalCategorical > 0 && (
        <CategoryLegend
          valueCounts={valueCounts}
          totalCategorical={totalCategorical}
          activeValue={activeValue}
          onValueClick={onValueClick}
        />
      )}
    </div>
  )
}

// Lightweight ReactNode alias keeps the chart variable typed without
// pulling React's full ReactNode through the function signature
// (prevents a "type-only import" tangle on tsx/lint).
type ReactNodeLike = React.ReactNode

type ValueCount = CallImportMetricAggregate['value_counts'][number]

interface CategoricalChartProps {
  metric: CallImportMetricAggregate
  chartType: CategoricalChartType
  valueCounts: ValueCount[]
  totalCategorical: number
  activeValue: string | null
  onValueClick: (value: string) => void
}

/**
 * Routes the categorical render to the right chart sub-component.
 * Each sub-component owns its layout/sizing/animation but shares the
 * tooltip styling and click-to-filter contract.
 */
function CategoricalChart(props: CategoricalChartProps) {
  const { metric, chartType, valueCounts } = props

  // Defensive fallback: a chart type that doesn't apply to this
  // metric (e.g. heatmap on a single-value metric) auto-promotes to
  // the next-best fit. Prevents a stale localStorage preference from
  // leaving the card empty when a metric type changes.
  const safeType: CategoricalChartType = (() => {
    const allowed = availableChartTypesFor(metric)
    if (allowed.includes(chartType)) return chartType
    if (metric.is_multi_label_parent) return 'bar'
    return autoPickCategoricalChart(metric)
  })()

  if (!valueCounts.length) return null

  switch (safeType) {
    case 'pie':
      return <CategoricalPieChart {...props} />
    case 'bar':
      return <CategoricalBarChart {...props} />
    case 'lollipop':
      return <CategoricalLollipopChart {...props} />
    case 'radial':
      return <CategoricalRadialChart {...props} />
    case 'treemap':
      return <CategoricalTreemapChart {...props} />
    case 'waffle':
      return <CategoricalWaffleChart {...props} />
    case 'coverage':
      return <CategoricalCoverageChart {...props} />
    case 'heatmap':
      return <CategoricalHeatmapChart {...props} />
    default:
      return <CategoricalBarChart {...props} />
  }
}

// --- Pie / donut --------------------------------------------------------
//
// Donut variant: hole in the middle keeps the center available for a
// summary stat (top label / share). Slice labels are rendered at the
// pie midpoint with a leader-line guard — small slices (<5%) drop the
// label so they don't pile up on top of each other.
function CategoricalPieChart({
  valueCounts,
  totalCategorical,
  activeValue,
  onValueClick,
}: CategoricalChartProps) {
  const top = valueCounts[0]
  const topShare = top ? top.count / Math.max(totalCategorical, 1) : 0
  return (
    <div className="relative">
      <ResponsiveContainer width="100%" height={240}>
        <PieChart margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <Tooltip
            contentStyle={CHART_TOOLTIP_STYLE}
            labelStyle={CHART_TOOLTIP_LABEL_STYLE}
            itemStyle={CHART_TOOLTIP_ITEM_STYLE}
            formatter={(value: any, name: any) => [`${value} rows`, name]}
          />
          <Pie
            data={valueCounts}
            dataKey="count"
            nameKey="label"
            innerRadius={56}
            outerRadius={92}
            paddingAngle={2}
            stroke="#fff"
            strokeWidth={2}
            isAnimationActive
            animationDuration={400}
            onClick={(slice: any) => {
              const label = slice?.payload?.label ?? slice?.name
              if (typeof label === 'string') onValueClick(label)
            }}
            label={renderInsideSliceLabel}
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
      {top && (
        <div
          className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center"
          style={{ paddingInline: 12 }}
        >
          <p className="text-[9px] uppercase tracking-wider text-gray-500 leading-tight">
            Top
          </p>
          <p
            className="text-[11px] font-semibold text-gray-900 max-w-[88px] truncate leading-tight mt-0.5"
            title={top.label}
          >
            {truncateLabel(top.label, 12)}
          </p>
          <p className="text-[13px] font-bold text-primary-700 leading-tight mt-0.5 tabular-nums">
            {Math.round(topShare * 100)}%
          </p>
        </div>
      )}
    </div>
  )
}

/**
 * Custom Pie ``label`` renderer that places the percent text on the
 * coloured slice itself (between ``innerRadius`` and ``outerRadius``)
 * rather than at the default outside position. The default placement
 * overflows the container on slices whose midpoint sits near the top
 * or sides of the chart and gets clipped by the SVG boundary; placing
 * the label on the ring keeps it visible at every slice angle.
 *
 * Slices below 6% are hidden because the arc is too thin to render
 * legible text — the side legend below the chart already exposes
 * those values.
 */
function renderInsideSliceLabel(props: any) {
  const { cx, cy, midAngle, innerRadius, outerRadius, percent } = props
  if (percent == null || percent < 0.06) return null
  const RADIAN = Math.PI / 180
  const radius = innerRadius + (outerRadius - innerRadius) * 0.55
  const x = cx + radius * Math.cos(-midAngle * RADIAN)
  const y = cy + radius * Math.sin(-midAngle * RADIAN)
  return (
    <text
      x={x}
      y={y}
      fill="#fff"
      textAnchor="middle"
      dominantBaseline="central"
      fontSize={11}
      fontWeight={700}
      style={{ pointerEvents: 'none', textShadow: '0 1px 2px rgba(0,0,0,0.18)' }}
    >
      {`${Math.round(percent * 100)}%`}
    </text>
  )
}

// --- Bar (horizontal, ranked) -------------------------------------------
function CategoricalBarChart({
  metric,
  valueCounts,
  activeValue,
  onValueClick,
}: CategoricalChartProps) {
  const longestLabel = valueCounts.reduce(
    (m, v) => Math.max(m, v.label.length),
    0,
  )
  const yAxisWidth = Math.min(260, Math.max(160, longestLabel * 7 + 24))
  return (
    <ResponsiveContainer
      width="100%"
      height={Math.max(180, 36 + valueCounts.length * 36)}
    >
      <BarChart
        data={valueCounts}
        layout="vertical"
        margin={{ top: 8, right: 32, left: 0, bottom: 8 }}
      >
        <defs>
          <linearGradient
            id={`bar-cat-${metric.metric_id}`}
            x1="0"
            y1="0"
            x2="1"
            y2="0"
          >
            <stop offset="0%" stopColor="#10b981" stopOpacity={0.55} />
            <stop offset="100%" stopColor="#10b981" stopOpacity={0.95} />
          </linearGradient>
        </defs>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="#f1f5f9"
          horizontal={false}
        />
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
          tick={(p: any) => <LongLabelTick {...p} colWidth={yAxisWidth} />}
          axisLine={false}
          tickLine={false}
          width={yAxisWidth}
          interval={0}
        />
        <Tooltip
          contentStyle={CHART_TOOLTIP_STYLE}
          labelStyle={CHART_TOOLTIP_LABEL_STYLE}
          itemStyle={CHART_TOOLTIP_ITEM_STYLE}
          cursor={{ fill: 'rgba(16,185,129,0.08)' }}
          formatter={(value: any) => [`${value} rows`, 'Count']}
        />
        <Bar
          dataKey="count"
          fill={`url(#bar-cat-${metric.metric_id})`}
          radius={[0, 4, 4, 0]}
          isAnimationActive
          animationDuration={400}
          onClick={(bar: any) => {
            const label = bar?.label ?? bar?.payload?.label
            if (typeof label === 'string') onValueClick(label)
          }}
        >
          {valueCounts.map((vc) => (
            <Cell
              key={vc.label}
              cursor="pointer"
              opacity={activeValue && activeValue !== vc.label ? 0.35 : 1}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

// --- Lollipop -----------------------------------------------------------
//
// Custom Bar shape draws a thin horizontal stick + a circle end-cap
// for each row. Visually lighter than a full bar and reads as a
// ranked top-N list at a glance.
function LollipopShape(props: any) {
  const { x, y, width, height, fill } = props
  const cy = (y ?? 0) + (height ?? 0) / 2
  const stickH = 2
  const r = 5
  const safeWidth = Math.max(0, width ?? 0)
  return (
    <g>
      <rect
        x={x}
        y={cy - stickH / 2}
        width={safeWidth}
        height={stickH}
        fill={fill}
        opacity={0.5}
      />
      <circle cx={(x ?? 0) + safeWidth} cy={cy} r={r} fill={fill} />
    </g>
  )
}

function CategoricalLollipopChart({
  valueCounts,
  activeValue,
  onValueClick,
}: CategoricalChartProps) {
  // Sized so the longest label gets all the space it can, capped at
  // ~45% of the typical card width (cards are 480-560px wide in the
  // 2-up grid, so 240 leaves ~240-320 for the bars themselves).
  const longestLabel = valueCounts.reduce(
    (m, v) => Math.max(m, v.label.length),
    0,
  )
  const yAxisWidth = Math.min(260, Math.max(160, longestLabel * 7 + 24))
  return (
    <ResponsiveContainer
      width="100%"
      height={Math.max(180, 28 + valueCounts.length * 30)}
    >
      <BarChart
        data={valueCounts}
        layout="vertical"
        margin={{ top: 8, right: 40, left: 0, bottom: 8 }}
      >
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="#f1f5f9"
          horizontal={false}
        />
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
          tick={(p: any) => <LongLabelTick {...p} colWidth={yAxisWidth} />}
          axisLine={false}
          tickLine={false}
          width={yAxisWidth}
          interval={0}
        />
        <Tooltip
          contentStyle={CHART_TOOLTIP_STYLE}
          labelStyle={CHART_TOOLTIP_LABEL_STYLE}
          itemStyle={CHART_TOOLTIP_ITEM_STYLE}
          cursor={{ fill: 'rgba(99,102,241,0.06)' }}
          formatter={(value: any) => [`${value} rows`, 'Count']}
        />
        <Bar
          dataKey="count"
          shape={<LollipopShape />}
          isAnimationActive
          animationDuration={400}
          onClick={(bar: any) => {
            const label = bar?.label ?? bar?.payload?.label
            if (typeof label === 'string') onValueClick(label)
          }}
        >
          {valueCounts.map((vc, i) => (
            <Cell
              key={vc.label}
              fill={PIE_COLORS[i % PIE_COLORS.length]}
              cursor="pointer"
              opacity={activeValue && activeValue !== vc.label ? 0.35 : 1}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

// --- Radial bar ---------------------------------------------------------
//
// Concentric rings, one per category. The angular extent of each
// ring encodes the count; combined with the colored side legend
// below the chart this is a punchy alternative to the donut for 3-8
// categories.
function CategoricalRadialChart({
  valueCounts,
  totalCategorical,
  activeValue,
  onValueClick,
}: CategoricalChartProps) {
  const data = valueCounts.map((vc, i) => ({
    ...vc,
    fill: PIE_COLORS[i % PIE_COLORS.length],
  }))
  const max = Math.max(...valueCounts.map((v) => v.count), 1)
  return (
    <ResponsiveContainer width="100%" height={220}>
      <RadialBarChart
        innerRadius="20%"
        outerRadius="100%"
        barSize={12}
        startAngle={90}
        endAngle={-270}
        data={data}
      >
        <PolarAngleAxis
          type="number"
          domain={[0, max]}
          dataKey="count"
          tick={false}
        />
        <RadialBar
          dataKey="count"
          background={{ fill: '#f1f5f9' }}
          cornerRadius={6}
          isAnimationActive
          animationDuration={400}
          onClick={(bar: any) => {
            const label = bar?.label ?? bar?.payload?.label
            if (typeof label === 'string') onValueClick(label)
          }}
        >
          {data.map((vc) => (
            <Cell
              key={vc.label}
              fill={vc.fill}
              cursor="pointer"
              opacity={activeValue && activeValue !== vc.label ? 0.35 : 1}
            />
          ))}
        </RadialBar>
        <Tooltip
          contentStyle={CHART_TOOLTIP_STYLE}
          labelStyle={CHART_TOOLTIP_LABEL_STYLE}
          itemStyle={CHART_TOOLTIP_ITEM_STYLE}
          formatter={(value: any, _name: any, payload: any) => {
            const label = payload?.payload?.label ?? '—'
            const share = (Number(value) / Math.max(totalCategorical, 1)) * 100
            return [`${value} rows (${share.toFixed(0)}%)`, label]
          }}
        />
      </RadialBarChart>
    </ResponsiveContainer>
  )
}

// --- Treemap ------------------------------------------------------------
//
// Area-encoded categorical view that gracefully scales to many
// labels without overflowing axis space. Each tile is colored by
// rank in the same palette and shows the label + count when the
// tile is wide enough; small tiles fall back to count-only.
function CategoricalTreemapChart({
  valueCounts,
  totalCategorical,
  activeValue,
  onValueClick,
}: CategoricalChartProps) {
  const data = valueCounts.map((vc, i) => ({
    name: vc.label,
    size: vc.count,
    label: vc.label,
    count: vc.count,
    fill: PIE_COLORS[i % PIE_COLORS.length],
  }))
  return (
    <div>
      <ResponsiveContainer width="100%" height={240}>
        <Treemap
          data={data}
          dataKey="size"
          stroke="#fff"
          isAnimationActive
          animationDuration={400}
          content={
            <TreemapTile
              activeValue={activeValue}
              total={totalCategorical}
              onValueClick={onValueClick}
            />
          }
        />
      </ResponsiveContainer>
    </div>
  )
}

function TreemapTile(props: any) {
  const {
    x,
    y,
    width,
    height,
    name,
    payload,
    activeValue,
    total,
    onValueClick,
  } = props
  const fill = payload?.fill ?? '#94a3b8'
  const count = payload?.count ?? 0
  const isActive = activeValue && activeValue === name
  const dimmed = activeValue && !isActive
  if (!width || !height) return null
  const showLabel = width > 70 && height > 32
  const showCount = width > 36 && height > 20
  const share = total > 0 ? (count / total) * 100 : 0
  return (
    <g
      style={{ cursor: 'pointer' }}
      onClick={() => {
        if (typeof name === 'string') onValueClick(name)
      }}
    >
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        style={{
          fill,
          stroke: '#fff',
          strokeWidth: 2,
          opacity: dimmed ? 0.35 : 1,
        }}
      />
      {showLabel ? (
        <>
          <text
            x={x + 8}
            y={y + 18}
            fill="#fff"
            fontSize={11}
            fontWeight={600}
            style={{ pointerEvents: 'none' }}
          >
            {truncateLabel(String(name ?? ''), Math.floor(width / 7))}
          </text>
          <text
            x={x + 8}
            y={y + 32}
            fill="#fff"
            fontSize={10}
            opacity={0.85}
            style={{ pointerEvents: 'none' }}
          >
            {count} · {share.toFixed(0)}%
          </text>
        </>
      ) : showCount ? (
        <text
          x={x + width / 2}
          y={y + height / 2 + 4}
          textAnchor="middle"
          fill="#fff"
          fontSize={11}
          fontWeight={600}
          style={{ pointerEvents: 'none' }}
        >
          {count}
        </text>
      ) : null}
    </g>
  )
}

// --- Waffle / 10x10 dot grid -------------------------------------------
//
// Pure SVG, no recharts. 100 squares total proportionally allocated
// to each category by largest-remainder. Reads as "X out of 100
// calls", which non-technical users find more concrete than a pie.
function CategoricalWaffleChart({
  valueCounts,
  totalCategorical,
  activeValue,
  onValueClick,
}: CategoricalChartProps) {
  const total = totalCategorical || 1
  // Largest-remainder allocation so the rounded squares always sum
  // to exactly 100. Tiny categories that round to 0 squares still
  // appear in the legend.
  const ideal = valueCounts.map((vc) => (vc.count / total) * 100)
  const floors = ideal.map((v) => Math.floor(v))
  const allocated = floors.reduce((s, v) => s + v, 0)
  let remainder = 100 - allocated
  const remainders = ideal
    .map((v, i) => ({ i, frac: v - Math.floor(v) }))
    .sort((a, b) => b.frac - a.frac)
  const allocations = [...floors]
  for (const r of remainders) {
    if (remainder <= 0) break
    allocations[r.i] += 1
    remainder -= 1
  }

  // Flatten to 100 entries, each tagged with its category index.
  const cells: { catIdx: number; label: string; count: number }[] = []
  allocations.forEach((n, idx) => {
    for (let k = 0; k < n; k++) {
      cells.push({
        catIdx: idx,
        label: valueCounts[idx].label,
        count: valueCounts[idx].count,
      })
    }
  })

  const size = 16
  const gap = 3
  const cols = 10
  const rows = 10
  const w = cols * (size + gap) - gap
  const h = rows * (size + gap) - gap

  return (
    <div className="flex justify-center py-2">
      <svg width={w} height={h} role="img" aria-label="Waffle chart">
        {Array.from({ length: 100 }, (_, i) => {
          const cell = cells[i]
          const r = Math.floor(i / cols)
          const c = i % cols
          const x = c * (size + gap)
          const y = r * (size + gap)
          if (!cell) {
            return (
              <rect
                key={i}
                x={x}
                y={y}
                width={size}
                height={size}
                rx={2}
                fill="#f1f5f9"
              />
            )
          }
          const fill = PIE_COLORS[cell.catIdx % PIE_COLORS.length]
          const dim = activeValue && activeValue !== cell.label
          return (
            <rect
              key={i}
              x={x}
              y={y}
              width={size}
              height={size}
              rx={2}
              fill={fill}
              opacity={dim ? 0.3 : 1}
              style={{ cursor: 'pointer' }}
              onClick={() => onValueClick(cell.label)}
            >
              <title>
                {`${cell.label}: ${cell.count} rows (${(
                  (cell.count / total) *
                  100
                ).toFixed(1)}%)`}
              </title>
            </rect>
          )
        })}
      </svg>
    </div>
  )
}

// --- Cumulative coverage (multi-label only) ----------------------------
//
// Sorted-rank line of cumulative % of label occurrences. Steep early
// slope → distribution is concentrated in a few labels; flat tail →
// long-tail distribution. Helps decide whether to invest more in
// promoting tail labels into first-class metrics.
function CategoricalCoverageChart({
  valueCounts,
  totalCategorical,
}: CategoricalChartProps) {
  const total = totalCategorical || 1
  let running = 0
  const data = valueCounts.map((vc, i) => {
    running += vc.count
    return {
      rank: i + 1,
      label: vc.label,
      cumulative: (running / total) * 100,
      count: vc.count,
    }
  })
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: -8, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
        <XAxis
          dataKey="rank"
          tick={{ fontSize: 10, fill: '#64748b' }}
          axisLine={{ stroke: '#e2e8f0' }}
          tickLine={false}
          label={{
            value: 'Label rank',
            position: 'insideBottomRight',
            offset: -2,
            fontSize: 10,
            fill: '#64748b',
          }}
        />
        <YAxis
          tick={{ fontSize: 10, fill: '#64748b' }}
          axisLine={false}
          tickLine={false}
          domain={[0, 100]}
          tickFormatter={(v) => `${v}%`}
        />
        <Tooltip
          contentStyle={CHART_TOOLTIP_STYLE}
          labelStyle={CHART_TOOLTIP_LABEL_STYLE}
          itemStyle={CHART_TOOLTIP_ITEM_STYLE}
          formatter={(value: any, _name: any, payload: any) => [
            `${Number(value).toFixed(1)}% cumulative`,
            payload?.payload?.label ?? '—',
          ]}
          labelFormatter={(rank) => `Top ${rank}`}
        />
        <Line
          type="monotone"
          dataKey="cumulative"
          stroke="#6366f1"
          strokeWidth={2}
          dot={{ r: 3, fill: '#6366f1' }}
          isAnimationActive
          animationDuration={400}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

// --- Co-occurrence heatmap (multi-label only) --------------------------
//
// Reads ``metric.co_occurrence`` (label_a, label_b, count) emitted
// by the backend aggregator. Each cell encodes how often a pair of
// labels fired together on the same row. Falls back to an empty
// state when the field isn't populated yet (older payloads / rolling
// deploys / single-label metrics).
function CategoricalHeatmapChart({
  metric,
  valueCounts,
  onValueClick,
}: CategoricalChartProps) {
  const co = metric.co_occurrence
  const labels = valueCounts.map((v) => v.label)
  const labelIndex = new Map(labels.map((l, i) => [l, i]))
  const grid: number[][] = labels.map((_, i) =>
    labels.map((_, j) => (i === j ? valueCounts[i].count : 0)),
  )
  if (Array.isArray(co)) {
    for (const row of co) {
      const ai = labelIndex.get(row.a)
      const bi = labelIndex.get(row.b)
      if (ai == null || bi == null) continue
      grid[ai][bi] = row.count
      grid[bi][ai] = row.count
    }
  }
  let max = 0
  for (const row of grid) {
    for (const v of row) max = Math.max(max, v)
  }
  if (!Array.isArray(co) || max === 0) {
    return (
      <div className="rounded-md border border-dashed border-gray-200 bg-gray-50/50 px-4 py-6 text-center text-xs text-gray-500">
        Co-occurrence data isn't available for this metric yet — switch
        to another chart type or re-run the evaluation aggregate.
      </div>
    )
  }
  const cell = 22
  const gap = 2
  const labelW = 130
  const w = labelW + labels.length * (cell + gap)
  const h = labelW + labels.length * (cell + gap)
  return (
    <div className="overflow-auto py-1">
      <svg width={w} height={h} role="img" aria-label="Co-occurrence heatmap">
        {labels.map((lbl, i) => (
          <text
            key={`row-${i}`}
            x={labelW - 6}
            y={labelW + i * (cell + gap) + cell / 2 + 4}
            textAnchor="end"
            fontSize={10}
            fill="#334155"
          >
            <title>{lbl}</title>
            {truncateLabel(lbl, 18)}
          </text>
        ))}
        {labels.map((lbl, j) => (
          <text
            key={`col-${j}`}
            x={labelW + j * (cell + gap) + cell / 2}
            y={labelW - 6}
            transform={`rotate(-45 ${labelW + j * (cell + gap) + cell / 2} ${labelW - 6})`}
            textAnchor="start"
            fontSize={10}
            fill="#334155"
          >
            <title>{lbl}</title>
            {truncateLabel(lbl, 18)}
          </text>
        ))}
        {grid.map((row, i) =>
          row.map((v, j) => {
            const t = max > 0 ? v / max : 0
            const fill =
              v === 0
                ? '#f8fafc'
                : `rgba(99, 102, 241, ${0.15 + 0.85 * t})`
            return (
              <rect
                key={`${i}-${j}`}
                x={labelW + j * (cell + gap)}
                y={labelW + i * (cell + gap)}
                width={cell}
                height={cell}
                rx={3}
                fill={fill}
                style={{ cursor: i === j ? 'pointer' : 'default' }}
                onClick={() => {
                  if (i === j) onValueClick(labels[i])
                }}
              >
                <title>
                  {i === j
                    ? `${labels[i]}: ${v}`
                    : `${labels[i]} ∩ ${labels[j]}: ${v}`}
                </title>
              </rect>
            )
          }),
        )}
      </svg>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TLDR summary: a punchy at-a-glance digest that sits above the charts on
// the Visualizations tab. Pulls signal directly out of the aggregate
// payload so we don't need an extra backend round-trip.
// ---------------------------------------------------------------------------

type TldrTone = 'good' | 'warn' | 'info'

/**
 * Convert a 0-1 ratio into a percentage label rounded to the nearest
 * integer; falls back to "—" for non-finite inputs.
 */
function formatPct(ratio: number): string {
  if (!Number.isFinite(ratio)) return '—'
  return `${Math.round(ratio * 100)}%`
}

function clampProseToSentences(
  text: string,
  maxSentences = 3,
  maxChars = 300,
): string {
  const trimmed = text.trim().replace(/\s*\n+\s*/g, ' ')
  if (!trimmed) return trimmed
  const sentences = trimmed.split(/(?<=[.!?])\s+/).filter(Boolean)
  let result = (sentences.length ? sentences.slice(0, maxSentences) : [trimmed])
    .join(' ')
    .trim()
  if (result.length > maxChars) {
    const cut = result.slice(0, maxChars - 3).replace(/\s+\S*$/, '')
    result = `${cut || result.slice(0, maxChars)}...`
  }
  return result
}

const PROVIDER_DISPLAY: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  deepseek: 'DeepSeek',
  groq: 'Groq',
}

/**
 * Compact stat tile used in the TLDR header strip. Rendered four to a
 * row on >=sm screens, two on mobile. ``tone`` shifts the value color
 * so warnings (failed runs) and successes (>=80% completion) stand
 * out without needing extra layout surface.
 */
function TldrStat({
  label,
  value,
  sub,
  tone = 'info',
}: {
  label: string
  value: number | string
  sub?: string | null
  tone?: TldrTone
}) {
  const valueClass =
    tone === 'good'
      ? 'text-green-700'
      : tone === 'warn'
      ? 'text-amber-700'
      : 'text-gray-900'
  return (
    <div className="rounded-lg border border-gray-100 bg-white/80 px-3 py-2 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <p className="text-[10px] uppercase tracking-wider text-gray-500 truncate">
        {label}
      </p>
      <p className={`text-lg font-semibold leading-tight ${valueClass}`}>
        {value}
      </p>
      {sub ? (
        <p className="text-[11px] text-gray-500 truncate">{sub}</p>
      ) : null}
    </div>
  )
}

/**
 * High-level TLDR card pinned above the Visualizations charts.
 *
 * Layout:
 *   1. Header pill - completion percent, status tone.
 *   2. Stat strip  - rows scored / top-level metrics / sub-labels / failed.
 *   3. Body        - LLM-generated narrative + bullet patterns. Hidden
 *                    behind an explicit "Generate summary" CTA so we
 *                    never auto-burn LLM tokens, with a Regenerate
 *                    affordance once a cached summary exists.
 */
function EvaluationTLDR({
  callImportId,
  evaluation,
  aggregate,
}: {
  callImportId: string
  evaluation: CallImportEvaluation
  aggregate: {
    total_rows: number
    completed_rows: number
    failed_rows: number
    metrics: CallImportMetricAggregate[]
  }
}) {
  const totalRows = aggregate.total_rows
  const completed = aggregate.completed_rows
  const failed = aggregate.failed_rows
  const completionRate =
    totalRows > 0 ? completed / totalRows : null
  const failureRate = totalRows > 0 ? failed / totalRows : null

  // Pick an overall mood for the headline pill - green when >=80% of
  // rows completed cleanly, amber when failures are non-trivial, gray
  // before any rows finish.
  let statusTone: TldrTone = 'info'
  if (completionRate != null && completionRate >= 0.8 && (failureRate ?? 0) < 0.1) {
    statusTone = 'good'
  } else if ((failureRate ?? 0) >= 0.1) {
    statusTone = 'warn'
  }

  const statusToneClass =
    statusTone === 'good'
      ? 'bg-green-100 text-green-800 border-green-200'
      : statusTone === 'warn'
      ? 'bg-amber-100 text-amber-800 border-amber-200'
      : 'bg-gray-100 text-gray-700 border-gray-200'

  // Split aggregate metrics into top-level vs sub-labels using
  // ``parent_metric_id`` from the evaluation summary. The aggregate
  // payload itself is flat (one row per metric_id, parents and
  // promoted children mixed together) so the previous "Metrics: N"
  // pill misled users by counting children as separate metrics.
  const childIdSet = new Set(
    (evaluation.metrics ?? [])
      .filter((m) => (m as any).parent_metric_id)
      .map((m) => m.id),
  )
  const topLevelCount = aggregate.metrics.filter(
    (m) => !childIdSet.has(m.metric_id),
  ).length
  const subLabelCount = Math.max(
    0,
    aggregate.metrics.length - topLevelCount,
  )

  const completionLabel =
    completionRate != null
      ? `${formatPct(completionRate)} completed`
      : 'In progress'

  return (
    <section
      aria-label="Evaluation summary (TLDR)"
      className="rounded-xl border border-primary-100 bg-gradient-to-br from-primary-50/60 via-white to-white p-4 shadow-sm"
    >
      <header className="flex items-center justify-between gap-3 flex-wrap mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="inline-flex items-center justify-center h-6 w-6 rounded-full bg-primary-600 text-white shadow-sm shrink-0">
            <Sparkles className="h-3.5 w-3.5" />
          </span>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-primary-700">
              TLDR
            </p>
            <p className="text-sm font-semibold text-gray-900 truncate">
              At-a-glance summary
            </p>
          </div>
        </div>
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border font-medium text-[11px] ${statusToneClass}`}
        >
          {statusTone === 'good' ? (
            <CheckCircle2 className="h-3 w-3" />
          ) : statusTone === 'warn' ? (
            <AlertTriangle className="h-3 w-3" />
          ) : (
            <Sparkles className="h-3 w-3" />
          )}
          {completionLabel}
        </span>
      </header>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
        <TldrStat
          label="Rows scored"
          value={completed}
          sub={`of ${totalRows}`}
          tone={statusTone}
        />
        <TldrStat
          label="Top-level metrics"
          value={topLevelCount}
          sub={topLevelCount === 1 ? 'metric' : 'metrics'}
        />
        <TldrStat
          label="Sub-labels"
          value={subLabelCount}
          sub={subLabelCount === 1 ? 'discovered' : 'discovered'}
        />
        <TldrStat
          label="Failed"
          value={failed}
          tone={failed > 0 ? 'warn' : 'info'}
        />
      </div>

      {evaluation.status === 'pending' || evaluation.status === 'running' ? (
        <p className="text-xs text-gray-500 inline-flex items-center gap-1.5 mb-3">
          <RefreshCw className="h-3 w-3 animate-spin" />
          Results refresh automatically as workers finish each row.
        </p>
      ) : null}

      <EvaluationTLDRInsights
        callImportId={callImportId}
        evaluationId={evaluation.id}
        completedRows={completed}
        totalRows={totalRows}
      />
    </section>
  )
}

/**
 * LLM-driven body of the TLDR card. Owns the picker state + generate
 * mutation and renders one of three variants:
 *
 *   * empty -> "Get an AI-written summary..." CTA + provider/model
 *     picker + "Generate summary" button.
 *   * cached + fresh -> narrative paragraph, bulleted patterns,
 *     small footer with the model used + Regenerate text button.
 *   * cached + stale -> same as above plus an amber banner that
 *     explains how many newer rows have arrived since generation.
 */
function EvaluationTLDRInsights({
  callImportId,
  evaluationId,
  completedRows,
  totalRows,
}: {
  callImportId: string
  evaluationId: string
  completedRows: number
  totalRows: number
}) {
  const queryClient = useQueryClient()
  const [pickerProvider, setPickerProvider] = useState<string>('')
  const [pickerModel, setPickerModel] = useState<string>('')
  const [userInsightsSampleSize, setUserInsightsSampleSize] = useState<number>(
    DEFAULT_USER_INSIGHTS_SAMPLE_SIZE,
  )
  const [showPicker, setShowPicker] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  const insightsQuery = useQuery<EvaluationTldrSummary | null>({
    queryKey: ['call-import-evaluation-insights', callImportId, evaluationId],
    queryFn: () =>
      apiClient.getCallImportEvaluationInsights(callImportId, evaluationId),
    // Single shot per page-load. We refetch only after a successful
    // mutation; auto-refetching here would be misleading because the
    // backend never auto-generates the summary.
    refetchOnWindowFocus: false,
    refetchInterval: false,
  })

  const cached = insightsQuery.data ?? null

  const userInsightsStateQuery = useQuery<EvaluationUserInsightsState | null>({
    queryKey: ['call-import-evaluation-user-insights', callImportId, evaluationId],
    queryFn: () =>
      apiClient.getCallImportEvaluationUserInsights(callImportId, evaluationId),
    refetchOnWindowFocus: false,
  })

  // Re-seed the picker with the previously-used provider/model so a
  // single click on Regenerate gives the user the same model again.
  useEffect(() => {
    if (cached?.provider && !pickerProvider) {
      setPickerProvider(cached.provider)
    }
    if (cached?.model && !pickerModel) {
      setPickerModel(cached.model)
    }
  }, [cached?.provider, cached?.model, pickerProvider, pickerModel])

  useEffect(() => {
    const sampleSize = userInsightsStateQuery.data?.max_llm_calls
    if (
      sampleSize != null &&
      USER_INSIGHTS_SAMPLE_SIZE_OPTIONS.includes(
        sampleSize as (typeof USER_INSIGHTS_SAMPLE_SIZE_OPTIONS)[number],
      )
    ) {
      setUserInsightsSampleSize(sampleSize)
    }
  }, [userInsightsStateQuery.data?.max_llm_calls])

  const generateMutation = useMutation({
    mutationFn: (regenerate: boolean) =>
      apiClient.generateCallImportEvaluationInsights(
        callImportId,
        evaluationId,
        {
          regenerate,
          provider: pickerProvider || undefined,
          model: pickerModel || undefined,
          max_llm_calls: userInsightsSampleSize,
        },
      ),
    onSuccess: (summary) => {
      queryClient.setQueryData(
        ['call-import-evaluation-insights', callImportId, evaluationId],
        summary,
      )
      queryClient.invalidateQueries({
        queryKey: ['call-import-evaluation-user-insights', callImportId, evaluationId],
      })
      setShowPicker(false)
      setError(null)
    },
    onError: (err: any) => {
      setError(err?.response?.data?.detail || 'Could not generate summary')
    },
  })

  const isLoading = insightsQuery.isLoading
  const isPending = generateMutation.isPending

  if (isLoading) {
    return (
      <p className="text-xs text-gray-500 inline-flex items-center gap-1.5">
        <Loader2 className="h-3 w-3 animate-spin" />
        Loading summary…
      </p>
    )
  }

  // Empty-state CTA: never-summarised yet OR an explicit "regenerate"
  // request landed us here without a cached value.
  if (!cached) {
    return (
      <div className="rounded-lg border border-dashed border-primary-200 bg-white/70 p-3">
        <div className="flex items-start gap-2 mb-2">
          <Sparkles className="h-4 w-4 text-primary-600 mt-0.5 shrink-0" />
          <div className="min-w-0">
            <p className="text-xs font-semibold text-gray-900">
              Get an AI-written summary and user insights
            </p>
            <p className="text-[11px] text-gray-500 leading-snug">
              We feed per-metric numbers + rationales to an LLM for a
              cross-call summary, and start a background job that
              analyzes rationales and diarized transcripts for External
              Audit user insights.
            </p>
          </div>
        </div>
        <div className="mt-2 mb-3 space-y-2">
          <AIProviderModelPicker
            provider={pickerProvider}
            model={pickerModel}
            onProviderChange={setPickerProvider}
            onModelChange={setPickerModel}
            disabled={isPending}
            size="sm"
          />
          <UserInsightsSampleSizeSelect
            value={userInsightsSampleSize}
            onChange={setUserInsightsSampleSize}
            disabled={isPending}
          />
        </div>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <p className="text-[10px] text-gray-400">
            Tokens are only spent when you click Generate.
          </p>
          <button
            type="button"
            onClick={() => generateMutation.mutate(false)}
            disabled={isPending}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-primary-600 rounded-md hover:bg-primary-700 disabled:opacity-60"
          >
            {isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            Generate summary
          </button>
        </div>
        {error && (
          <p className="mt-2 text-[11px] text-red-600">{error}</p>
        )}
      </div>
    )
  }

  // Cached summary - render narrative + bullets, plus a stale banner
  // and Regenerate affordance when more rows have completed since the
  // summary was written.
  const providerLabel = cached.provider
    ? PROVIDER_DISPLAY[cached.provider] || cached.provider
    : null

  return (
    <div className="rounded-lg border border-gray-100 bg-white/80 p-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      {cached.is_stale && (
        <div className="mb-3 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1.5">
          <AlertTriangle className="h-3.5 w-3.5 text-amber-600 mt-0.5 shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-[11px] text-amber-800">
              Generated when {cached.generated_at_completed_rows}/{totalRows}{' '}
              row{cached.generated_at_completed_rows === 1 ? '' : 's'} had
              finished. {completedRows - cached.generated_at_completed_rows}{' '}
              new row
              {completedRows - cached.generated_at_completed_rows === 1
                ? ' has'
                : 's have'}{' '}
              completed since.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowPicker((v) => !v)}
            className="text-[11px] font-medium text-amber-800 hover:text-amber-900 underline underline-offset-2 shrink-0"
          >
            {showPicker ? 'Cancel' : 'Regenerate'}
          </button>
        </div>
      )}

      <p className="text-xs text-gray-700 leading-relaxed whitespace-pre-line">
        {clampProseToSentences(cached.narrative)}
      </p>

      <div className="mt-3 flex items-center justify-between gap-2 flex-wrap">
        <p className="text-[10px] text-gray-400 truncate">
          {providerLabel || cached.model
            ? `Generated by ${providerLabel ?? '—'}${
                cached.model ? ` · ${cached.model}` : ''
              }`
            : 'Generated by AI'}
        </p>
        {!cached.is_stale && (
          <button
            type="button"
            onClick={() => setShowPicker((v) => !v)}
            disabled={isPending}
            className="text-[11px] font-medium text-primary-700 hover:text-primary-800 underline underline-offset-2 disabled:opacity-50"
          >
            {showPicker ? 'Cancel' : 'Regenerate'}
          </button>
        )}
      </div>

      {showPicker && (
        <div className="mt-3 rounded-md border border-gray-200 bg-gray-50 p-2.5 space-y-2">
          <AIProviderModelPicker
            provider={pickerProvider}
            model={pickerModel}
            onProviderChange={setPickerProvider}
            onModelChange={setPickerModel}
            disabled={isPending}
            size="sm"
          />
          <UserInsightsSampleSizeSelect
            value={userInsightsSampleSize}
            onChange={setUserInsightsSampleSize}
            disabled={isPending}
          />
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => generateMutation.mutate(true)}
              disabled={isPending}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium text-white bg-primary-600 rounded-md hover:bg-primary-700 disabled:opacity-60"
            >
              {isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Sparkles className="h-3 w-3" />
              )}
              Regenerate
            </button>
          </div>
        </div>
      )}

      {error && (
        <p className="mt-2 text-[11px] text-red-600">{error}</p>
      )}
    </div>
  )
}

// Renders one aggregate flow diagram for a parent metric. We isolate
// the query into a child component so each parent fetches in parallel
// and stays in its own React Query cache slot.
function FlowDiagramForParent({
  callImportId,
  evalId,
  parent,
  onNodeClick,
  onEdgeClick,
  onViewDiscoveredCalls,
  onViewAnyDiscoveredCalls,
}: {
  callImportId: string
  evalId: string
  parent: {
    id: string
    name: string
    selection_mode: 'single_choice' | 'multi_label' | null
    allow_discovery: boolean
    children: { id: string; name: string }[]
  }
  onNodeClick?: (node: import('./components/MetricFlowChart').FlowNodeClick) => void
  onEdgeClick?: (edge: import('./components/MetricFlowChart').FlowEdgeClick) => void
  onViewDiscoveredCalls?: (item: {
    key: string
    name: string
  }) => void
  onViewAnyDiscoveredCalls?: () => void
}) {
  const flowQuery = useQuery({
    queryKey: ['call-import-eval-flow', callImportId, evalId, parent.id],
    queryFn: () =>
      apiClient.getCallImportEvaluationFlow(callImportId, evalId, parent.id),
  })

  const showDiscoveryPanel =
    !!parent.selection_mode && parent.allow_discovery

  return (
    <div className="border border-gray-200 rounded-lg p-3 bg-white">
      <div className="flex items-baseline justify-between mb-2 gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-gray-900 inline-flex items-center gap-1.5">
            {parent.name}
            {parent.allow_discovery && (
              <span
                className="text-[9px] uppercase tracking-wide font-semibold rounded-sm bg-amber-50 text-amber-700 border border-amber-200 px-1 py-[1px]"
                title="LLM-driven discovery enabled for this category"
              >
                +disc
              </span>
            )}
          </p>
          <p className="text-[11px] text-gray-500">
            {parent.selection_mode === 'single_choice'
              ? 'Pick-one category'
              : 'Multi-label category'}{' '}
            · {parent.children.length} sub-labels
          </p>
        </div>
        {flowQuery.data && (
          <p className="text-[11px] text-gray-500 tabular-nums">
            {flowQuery.data.rows_with_sequence}/{flowQuery.data.total_rows}{' '}
            rows scored
          </p>
        )}
      </div>
      <div
        className={
          showDiscoveryPanel
            ? 'grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-3'
            : ''
        }
      >
        <div>
          {flowQuery.isLoading || !flowQuery.data ? (
            <div className="text-center py-8 text-gray-500">
              <RefreshCw className="h-5 w-5 mx-auto mb-2 animate-spin" />
              <p className="text-xs">Loading flow…</p>
            </div>
          ) : flowQuery.data.rows_with_sequence === 0 ? (
            <p className="text-xs text-gray-500 italic">
              No rows produced a label sequence for this category yet.
            </p>
          ) : (
            <>
              <MetricFlowChart
                data={flowQuery.data}
                mode="aggregate"
                height={360}
                onNodeClick={onNodeClick}
                onEdgeClick={onEdgeClick}
              />
              {(onNodeClick || onEdgeClick) && (
                <p className="text-[11px] text-gray-500 mt-1.5 inline-flex items-center gap-1">
                  <Filter className="h-3 w-3" />
                  Click a node to filter calls that passed through that
                  label, or an edge for the directed transition.
                </p>
              )}
            </>
          )}
        </div>
        {showDiscoveryPanel && (
          <DiscoveredLabelsPanel
            callImportId={callImportId}
            evalId={evalId}
            parent={parent}
            onViewDiscoveredCalls={onViewDiscoveredCalls}
            onViewAnyDiscoveredCalls={onViewAnyDiscoveredCalls}
          />
        )}
      </div>
    </div>
  )
}

// Panel: surfaces LLM-discovered candidate sub-labels next to the flow
// diagram. Each candidate can be merged into another (slug rewrite) or
// promoted to a real child metric. Promotion is the path that keeps the
// already-scored rows' ``sequence`` arrays resolving against the new
// child — the backend enforces slug(name) == key for exactly this
// reason.
function DiscoveredLabelsPanel({
  callImportId,
  evalId,
  parent,
  onViewDiscoveredCalls,
  onViewAnyDiscoveredCalls,
}: {
  callImportId: string
  evalId: string
  parent: {
    id: string
    name: string
    selection_mode: 'single_choice' | 'multi_label' | null
    children: { id: string; name: string }[]
  }
  onViewDiscoveredCalls?: (item: { key: string; name: string }) => void
  onViewAnyDiscoveredCalls?: () => void
}) {
  const queryClient = useQueryClient()
  const discoveredQuery = useQuery({
    queryKey: [
      'call-import-eval-discovered',
      callImportId,
      evalId,
      parent.id,
    ],
    queryFn: () =>
      apiClient.getCallImportEvaluationDiscoveredLabels(
        callImportId,
        evalId,
        parent.id,
      ),
  })

  const invalidateAll = () => {
    queryClient.invalidateQueries({
      queryKey: ['call-import-eval-discovered', callImportId, evalId, parent.id],
    })
    queryClient.invalidateQueries({
      queryKey: ['call-import-eval-flow', callImportId, evalId, parent.id],
    })
    queryClient.invalidateQueries({ queryKey: ['metrics'] })
    queryClient.invalidateQueries({
      queryKey: ['call-import-evaluation', callImportId, evalId],
    })
  }

  const promoteMutation = useMutation({
    mutationFn: (entry: {
      key: string
      name: string
      description?: string | null
      capture_rationale?: boolean
    }) => apiClient.promoteDiscoveredChild(parent.id, entry),
    onSuccess: invalidateAll,
  })

  const mergeMutation = useMutation({
    mutationFn: (body: { from_key: string; to_key: string }) =>
      apiClient.mergeCallImportEvaluationDiscoveredLabels(
        callImportId,
        evalId,
        { parent_metric_id: parent.id, ...body },
      ),
    onSuccess: invalidateAll,
  })

  const deleteMutation = useMutation({
    mutationFn: (key: string) =>
      apiClient.deleteCallImportEvaluationDiscoveredLabel(
        callImportId,
        evalId,
        { parent_metric_id: parent.id, key },
      ),
    onSuccess: invalidateAll,
  })

  // Defense-in-depth: even though the backend now hides candidates whose
  // slug already matches a real promoted child, we re-filter here so a
  // stale GET response can't briefly resurrect a candidate the user has
  // already accepted (e.g. between promote and the discovered-labels
  // refetch).
  const childSlugs = useMemo(() => {
    const set = new Set<string>()
    for (const c of parent.children || []) {
      const slug = c.name.trim().toLowerCase().split(/\s+/).join('_')
      if (slug) set.add(slug)
    }
    return set
  }, [parent.children])
  const items = (discoveredQuery.data?.items ?? []).filter(
    (item) => !childSlugs.has(item.key),
  )

  // Per-parent collapse state. Defaults to expanded so existing users
  // see the panel as before; collapsing only hides the body so the
  // header still shows the candidate count.
  const [collapsed, setCollapsed] = useState(false)
  // Two-step delete confirmation: clicking Delete arms the entry, a
  // second click within ``confirmKey`` actually fires the mutation.
  // Avoids a global modal and keeps the action inline with the
  // candidate row that's about to disappear.
  const [confirmKey, setConfirmKey] = useState<string | null>(null)

  return (
    <aside className="border border-amber-200 bg-amber-50/40 rounded-md p-3 text-xs">
      <header className="flex items-center justify-between mb-2 gap-2">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="font-semibold text-amber-900 inline-flex items-center gap-1 hover:text-amber-950"
          aria-expanded={!collapsed}
          title={collapsed ? 'Expand panel' : 'Collapse panel'}
        >
          {collapsed ? (
            <ChevronRight className="h-3 w-3" />
          ) : (
            <ChevronDown className="h-3 w-3" />
          )}
          <Sparkles className="h-3 w-3" /> Discovered metrics
        </button>
        <span className="text-[10px] text-amber-700">
          {items.length} {items.length === 1 ? 'candidate' : 'candidates'}
        </span>
      </header>
      {collapsed ? null : onViewAnyDiscoveredCalls && items.length > 0 && (
        <button
          type="button"
          onClick={onViewAnyDiscoveredCalls}
          className="mb-2 inline-flex items-center gap-1 text-[10px] font-medium text-amber-800 hover:text-amber-900 underline underline-offset-2"
        >
          <Filter className="h-3 w-3" />
          Show all calls with discovered metrics
        </button>
      )}
      {collapsed ? null : discoveredQuery.isLoading ? (
        <p className="text-amber-700 italic">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-amber-800/70 italic">
          No new metrics yet. As rows finish, the LLM may propose
          candidates here that you can promote into real sub-metrics.
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => {
            const others = items.filter((o) => o.key !== item.key)
            return (
              <li
                key={item.key}
                className="rounded border border-amber-200 bg-white p-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-semibold text-gray-900 truncate">
                      {item.name}
                    </p>
                    <p className="text-[10px] text-gray-500 font-mono truncate">
                      {item.key}
                    </p>
                  </div>
                  <span className="text-[10px] tabular-nums text-amber-700 whitespace-nowrap">
                    {item.count}{' '}
                    {item.count === 1 ? 'call' : 'calls'}
                  </span>
                </div>
                {item.description && (
                  <p className="text-gray-700 mt-1">{item.description}</p>
                )}
                {item.sample_rationale && (
                  <blockquote className="text-gray-500 italic mt-1 border-l-2 border-amber-300 pl-2">
                    "{item.sample_rationale}"
                  </blockquote>
                )}
                <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                  <button
                    type="button"
                    disabled={promoteMutation.isPending}
                    onClick={() => {
                      // Pull up to 2 distinct rationales captured for
                      // this candidate, append them as an Examples
                      // block to the new sub-metric's rubric, and
                      // turn on capture_rationale so future rows that
                      // hit this label keep producing rationales.
                      // Older payloads (before the backend learned to
                      // collect ``examples``) only carry
                      // ``sample_rationale`` — fall back to that so
                      // promote still works against legacy evals.
                      const examplesArr =
                        item.examples && item.examples.length > 0
                          ? item.examples
                          : item.sample_rationale
                            ? [item.sample_rationale]
                            : []
                      const exampleSlice = examplesArr.slice(0, 2)
                      const baseDescription = (item.description || '').trim()
                      const description =
                        exampleSlice.length > 0
                          ? [
                              baseDescription,
                              'Examples:',
                              ...exampleSlice.map((ex) => `- "${ex}"`),
                            ]
                              .filter((part) => part.length > 0)
                              .join('\n\n')
                              .replace(/\n{3,}/g, '\n\n')
                          : baseDescription || null
                      promoteMutation.mutate({
                        key: item.key,
                        name: item.key.replace(/_/g, ' '),
                        description,
                        capture_rationale: true,
                      })
                    }}
                    className="inline-flex items-center gap-1 text-[10px] font-medium rounded px-1.5 py-0.5 bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-60"
                  >
                    <Plus className="h-3 w-3" /> Promote
                  </button>
                  {onViewDiscoveredCalls && (
                    <button
                      type="button"
                      onClick={() =>
                        onViewDiscoveredCalls({
                          key: item.key,
                          name: item.name,
                        })
                      }
                      className="inline-flex items-center gap-1 text-[10px] font-medium rounded px-1.5 py-0.5 border border-amber-300 text-amber-800 bg-white hover:bg-amber-50"
                      title="Filter the row table to calls that produced this discovered metric"
                    >
                      <Filter className="h-3 w-3" /> View calls
                    </button>
                  )}
                  {others.length > 0 && (
                    <label className="inline-flex items-center gap-1 text-[10px] text-gray-700">
                      <Merge className="h-3 w-3" />
                      <select
                        className="border border-gray-300 rounded px-1 py-0.5 text-[10px] bg-white"
                        defaultValue=""
                        disabled={mergeMutation.isPending}
                        onChange={(e) => {
                          const target = e.target.value
                          if (!target) return
                          mergeMutation.mutate({
                            from_key: item.key,
                            to_key: target,
                          })
                          e.target.value = ''
                        }}
                      >
                        <option value="">Merge into…</option>
                        {others.map((o) => (
                          <option key={o.key} value={o.key}>
                            {o.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {confirmKey === item.key ? (
                    <span className="inline-flex items-center gap-1 text-[10px]">
                      <button
                        type="button"
                        onClick={() => {
                          deleteMutation.mutate(item.key)
                          setConfirmKey(null)
                        }}
                        disabled={deleteMutation.isPending}
                        className="inline-flex items-center gap-1 font-medium rounded px-1.5 py-0.5 bg-red-600 text-white hover:bg-red-700 disabled:opacity-60"
                        title="Permanently remove this candidate from the evaluation"
                      >
                        <Trash2 className="h-3 w-3" /> Confirm delete
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmKey(null)}
                        className="inline-flex items-center px-1.5 py-0.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-50"
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirmKey(item.key)}
                      disabled={deleteMutation.isPending}
                      className="inline-flex items-center gap-1 text-[10px] font-medium rounded px-1.5 py-0.5 border border-red-200 text-red-700 hover:bg-red-50 disabled:opacity-60"
                      title="Delete this LLM-discovered candidate (use for gibberish or irrelevant suggestions)"
                    >
                      <Trash2 className="h-3 w-3" /> Delete
                    </button>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {(promoteMutation.isError ||
        mergeMutation.isError ||
        deleteMutation.isError) && (
        <p className="text-[10px] text-red-700 mt-1">
          {String(
            (promoteMutation.error as any)?.message ||
              (mergeMutation.error as any)?.message ||
              (deleteMutation.error as any)?.message ||
              'Action failed.',
          )}
        </p>
      )}
    </aside>
  )
}


// Panel: surfaces LLM-discovered candidate TOP-LEVEL metrics at the
// top of the evaluation detail Flow tab. Parallel to
// :func:`DiscoveredLabelsPanel` but scoped to the evaluation as a
// whole (no parent metric) and promotes into standalone Metric rows
// via ``POST /metrics/from-discovered``. The promote dropdown lets
// the user override the LLM's suggested_type before creating the
// metric — defaults pre-fill from the candidate.
function DiscoveredMetricsTopPanel({
  callImportId,
  evalId,
}: {
  callImportId: string
  evalId: string
}) {
  const queryClient = useQueryClient()

  const discoveredQuery = useQuery({
    queryKey: ['call-import-eval-discovered-metrics', callImportId, evalId],
    queryFn: () =>
      apiClient.getCallImportEvaluationDiscoveredMetrics(
        callImportId,
        evalId,
      ),
  })

  const invalidateAll = () => {
    queryClient.invalidateQueries({
      queryKey: [
        'call-import-eval-discovered-metrics',
        callImportId,
        evalId,
      ],
    })
    queryClient.invalidateQueries({ queryKey: ['metrics'] })
    queryClient.invalidateQueries({
      queryKey: ['call-import-evaluation', callImportId, evalId],
    })
  }

  const promoteMutation = useMutation({
    mutationFn: (entry: {
      key: string
      name: string
      description?: string | null
      metric_type: 'boolean' | 'rating' | 'category'
      capture_rationale?: boolean
    }) => apiClient.promoteDiscoveredMetric(entry),
    onSuccess: invalidateAll,
  })

  const mergeMutation = useMutation({
    mutationFn: (body: { from_key: string; to_key: string }) =>
      apiClient.mergeCallImportEvaluationDiscoveredMetrics(
        callImportId,
        evalId,
        body,
      ),
    onSuccess: invalidateAll,
  })

  const deleteMutation = useMutation({
    mutationFn: (key: string) =>
      apiClient.deleteCallImportEvaluationDiscoveredMetric(
        callImportId,
        evalId,
        { key },
      ),
    onSuccess: invalidateAll,
  })

  const items = discoveredQuery.data?.items ?? []
  const [collapsed, setCollapsed] = useState(false)
  const [confirmKey, setConfirmKey] = useState<string | null>(null)
  // Per-candidate type override. Defaults to the LLM-suggested type
  // on first render; the user can pick a different shape before
  // hitting Promote.
  const [typeOverrides, setTypeOverrides] = useState<
    Record<string, 'boolean' | 'rating' | 'category'>
  >({})

  const typeFor = (item: (typeof items)[number]) =>
    typeOverrides[item.key] || item.suggested_type || 'boolean'

  return (
    <aside className="border border-amber-200 bg-amber-50/40 rounded-md p-3 text-xs">
      <header className="flex items-center justify-between mb-2 gap-2">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="font-semibold text-amber-900 inline-flex items-center gap-1 hover:text-amber-950"
          aria-expanded={!collapsed}
          title={collapsed ? 'Expand panel' : 'Collapse panel'}
        >
          {collapsed ? (
            <ChevronRight className="h-3 w-3" />
          ) : (
            <ChevronDown className="h-3 w-3" />
          )}
          <Sparkles className="h-3 w-3" /> Discovered metrics
        </button>
        <span className="text-[10px] text-amber-700">
          {items.length}{' '}
          {items.length === 1 ? 'candidate' : 'candidates'}
        </span>
      </header>
      {collapsed ? null : discoveredQuery.isLoading ? (
        <p className="text-amber-700 italic">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-amber-800/70 italic">
          No new metrics yet. As rows finish, the LLM may propose
          candidate top-level metrics here that you can promote into
          real Metric rows.
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => {
            const others = items.filter((o) => o.key !== item.key)
            const chosenType = typeFor(item)
            return (
              <li
                key={item.key}
                className="rounded border border-amber-200 bg-white p-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-semibold text-gray-900 truncate">
                      {item.name}
                    </p>
                    <p className="text-[10px] text-gray-500 font-mono truncate">
                      {item.key}
                    </p>
                  </div>
                  <span className="text-[10px] tabular-nums text-amber-700 whitespace-nowrap">
                    {item.count}{' '}
                    {item.count === 1 ? 'call' : 'calls'}
                  </span>
                </div>
                {item.description && (
                  <p className="text-gray-700 mt-1">{item.description}</p>
                )}
                {item.sample_rationale && (
                  <blockquote className="text-gray-500 italic mt-1 border-l-2 border-amber-300 pl-2">
                    "{item.sample_rationale}"
                  </blockquote>
                )}
                <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                  <label className="inline-flex items-center gap-1 text-[10px] text-gray-700">
                    Type
                    <select
                      className="border border-gray-300 rounded px-1 py-0.5 text-[10px] bg-white"
                      value={chosenType}
                      disabled={promoteMutation.isPending}
                      onChange={(e) =>
                        setTypeOverrides((prev) => ({
                          ...prev,
                          [item.key]: e.target.value as
                            | 'boolean'
                            | 'rating'
                            | 'category',
                        }))
                      }
                    >
                      <option value="boolean">Boolean</option>
                      <option value="rating">Rating</option>
                      <option value="category">Category</option>
                    </select>
                  </label>
                  <button
                    type="button"
                    disabled={promoteMutation.isPending}
                    onClick={() => {
                      // Build the description: prefer the LLM's
                      // description, append a single example
                      // rationale so the new metric's rubric starts
                      // with one concrete case. The user can edit
                      // the metric afterwards in the Metrics page.
                      const examplesArr =
                        item.examples && item.examples.length > 0
                          ? item.examples
                          : item.sample_rationale
                            ? [item.sample_rationale]
                            : []
                      const exampleSlice = examplesArr.slice(0, 2)
                      const baseDescription = (item.description || '').trim()
                      const description =
                        exampleSlice.length > 0
                          ? [
                              baseDescription,
                              'Examples:',
                              ...exampleSlice.map((ex) => `- "${ex}"`),
                            ]
                              .filter((part) => part.length > 0)
                              .join('\n\n')
                              .replace(/\n{3,}/g, '\n\n')
                          : baseDescription || null
                      promoteMutation.mutate({
                        key: item.key,
                        name: item.key.replace(/_/g, ' '),
                        description,
                        metric_type: chosenType,
                        capture_rationale: true,
                      })
                    }}
                    className="inline-flex items-center gap-1 text-[10px] font-medium rounded px-1.5 py-0.5 bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-60"
                  >
                    <Plus className="h-3 w-3" /> Promote
                  </button>
                  {others.length > 0 && (
                    <label className="inline-flex items-center gap-1 text-[10px] text-gray-700">
                      <Merge className="h-3 w-3" />
                      <select
                        className="border border-gray-300 rounded px-1 py-0.5 text-[10px] bg-white"
                        defaultValue=""
                        disabled={mergeMutation.isPending}
                        onChange={(e) => {
                          const target = e.target.value
                          if (!target) return
                          mergeMutation.mutate({
                            from_key: item.key,
                            to_key: target,
                          })
                          e.target.value = ''
                        }}
                      >
                        <option value="">Merge into…</option>
                        {others.map((o) => (
                          <option key={o.key} value={o.key}>
                            {o.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {confirmKey === item.key ? (
                    <span className="inline-flex items-center gap-1 text-[10px]">
                      <button
                        type="button"
                        onClick={() => {
                          deleteMutation.mutate(item.key)
                          setConfirmKey(null)
                        }}
                        disabled={deleteMutation.isPending}
                        className="inline-flex items-center gap-1 font-medium rounded px-1.5 py-0.5 bg-red-600 text-white hover:bg-red-700 disabled:opacity-60"
                        title="Permanently remove this candidate from the evaluation"
                      >
                        <Trash2 className="h-3 w-3" /> Confirm delete
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmKey(null)}
                        className="inline-flex items-center px-1.5 py-0.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-50"
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirmKey(item.key)}
                      disabled={deleteMutation.isPending}
                      className="inline-flex items-center gap-1 text-[10px] font-medium rounded px-1.5 py-0.5 border border-red-200 text-red-700 hover:bg-red-50 disabled:opacity-60"
                      title="Delete this LLM-discovered candidate (use for gibberish or irrelevant suggestions)"
                    >
                      <Trash2 className="h-3 w-3" /> Delete
                    </button>
                  )}
                </div>
                {/* Per-type guidance — without this the Promote
                    button silently creates a metric that may not
                    appear on the surface the user expects.
                    Boolean/rating standalone metrics live in the
                    Table / Visualizations tabs (the Flow diagram is
                    reserved for category parents with sub-labels);
                    a category metric promoted with no children is
                    silently skipped by the next eval until children
                    are added. */}
                <p className="text-[10px] text-gray-500 mt-1.5 italic">
                  {chosenType === 'category' ? (
                    <>
                      Creates an empty parent metric. <strong>Add
                      child sub-labels in the Metrics page</strong>{' '}
                      before re-running — without children the next
                      evaluation skips this metric and the Flow
                      diagram has nothing to render.
                    </>
                  ) : chosenType === 'rating' ? (
                    <>
                      Scored 0–1 per call. Appears in the{' '}
                      <strong>Table</strong> and{' '}
                      <strong>Visualizations</strong> tabs on the
                      next run (the Flow diagram is reserved for
                      category metrics with sub-labels).
                    </>
                  ) : (
                    <>
                      Scored true/false per call. Appears in the{' '}
                      <strong>Table</strong> and{' '}
                      <strong>Visualizations</strong> tabs on the
                      next run (the Flow diagram is reserved for
                      category metrics with sub-labels).
                    </>
                  )}
                </p>
              </li>
            )
          })}
        </ul>
      )}
      {(promoteMutation.isError ||
        mergeMutation.isError ||
        deleteMutation.isError) && (
        <p className="text-[10px] text-red-700 mt-1">
          {String(
            (promoteMutation.error as any)?.message ||
              (mergeMutation.error as any)?.message ||
              (deleteMutation.error as any)?.message ||
              'Action failed.',
          )}
        </p>
      )}
    </aside>
  )
}

export type { CallImportEvaluation as _ }

function UserInsightsSampleSizeSelect({
  value,
  onChange,
  disabled = false,
}: {
  value: number
  onChange: (value: number) => void
  disabled?: boolean
}) {
  return (
    <label className="flex items-center justify-between gap-3 text-[11px] text-gray-600">
      <span className="font-medium text-gray-700">
        User insights sample size
      </span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="text-[11px] border border-gray-200 rounded-md bg-white px-2 py-1 text-gray-700 focus:outline-none focus:ring-1 focus:ring-primary-300"
        title="Maximum LLM calls used to sample calls for user insights"
      >
        {USER_INSIGHTS_SAMPLE_SIZE_OPTIONS.map((size) => (
          <option key={size} value={size}>
            {size} LLM calls
          </option>
        ))}
      </select>
    </label>
  )
}

function UserInsightsStatusBanner({
  state,
  isLoading,
}: {
  state: EvaluationUserInsightsState | null
  isLoading: boolean
}) {
  if (isLoading) {
    return (
      <section className="mt-4 rounded-lg border border-gray-200 bg-white px-4 py-3">
        <p className="text-xs text-gray-500 inline-flex items-center gap-1.5">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading user insights…
        </p>
      </section>
    )
  }

  if (!state || state.status === 'idle' || state.status === 'completed') {
    return null
  }

  if (state.status === 'running') {
    const completed = state.progress?.completed_llm_calls ?? 0
    const total = state.progress?.total_llm_calls ?? 0
    const pct = total > 0 ? Math.round((completed / total) * 100) : 0
    return (
      <section className="mt-4 rounded-lg border border-primary-200 bg-primary-50/40 px-4 py-3">
        <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
          <p className="text-xs font-semibold text-gray-900 inline-flex items-center gap-1.5">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-primary-600" />
            AI User Insights — identifying patterns from rationales and transcripts…
          </p>
          {total > 0 ? (
            <p className="text-[10px] text-gray-500 tabular-nums">
              {completed} / {total} LLM calls ({pct}%)
            </p>
          ) : null}
        </div>
        {total > 0 ? (
          <div>
            <div className="h-2 rounded-full bg-primary-100 overflow-hidden">
              <div
                className="h-full bg-primary-600 transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
            {state.max_llm_calls ? (
              <p className="text-[10px] text-gray-500 mt-1">
                Sample budget: {state.max_llm_calls} LLM calls
              </p>
            ) : null}
          </div>
        ) : null}
      </section>
    )
  }

  return (
    <section className="mt-4 rounded-lg border border-red-200 bg-red-50/50 px-4 py-3">
      <p className="text-xs font-semibold text-gray-900 mb-1">
        AI User Insights generation failed
      </p>
      <p className="text-xs text-red-700">
        {state.error_message || 'User insights generation failed.'}
      </p>
      <p className="text-[11px] text-gray-500 mt-1">
        Click Regenerate on the summary card to retry.
      </p>
    </section>
  )
}

const METRIC_CLUSTER_ROW_PRESETS = [25, 50, 100, 200] as const

function MetricClusterRowPicker({
  rows,
  selectedIds,
  onChangeSelectedIds,
  disabled,
}: {
  rows: MetricClusterEligibleRow[]
  selectedIds: Set<string>
  onChangeSelectedIds: (next: Set<string>) => void
  disabled?: boolean
}) {
  const selectFirstN = (n: number) => {
    onChangeSelectedIds(
      new Set(rows.slice(0, n).map((r) => r.evaluation_row_id)),
    )
  }

  const selectAll = () => {
    onChangeSelectedIds(new Set(rows.map((r) => r.evaluation_row_id)))
  }

  const presetActive = (n: number) => {
    const limit = Math.min(n, rows.length)
    if (limit === 0 || selectedIds.size !== limit) return false
    const firstIds = rows.slice(0, limit).map((r) => r.evaluation_row_id)
    return firstIds.every((id) => selectedIds.has(id))
  }

  const allActive =
    rows.length > 0 &&
    selectedIds.size === rows.length &&
    rows.every((r) => selectedIds.has(r.evaluation_row_id))

  const toggleRow = (id: string) => {
    const next = new Set(selectedIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onChangeSelectedIds(next)
  }

  const presetButtonClass = (active: boolean) =>
    'rounded-full px-2 py-0.5 border text-[10px] font-medium transition-colors disabled:opacity-40 ' +
    (active
      ? 'border-primary-300 bg-primary-50 text-primary-800'
      : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50')

  return (
    <div className="rounded-md border border-gray-200 bg-white">
      <div className="px-3 py-2 border-b border-gray-100 bg-gray-50/80 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs font-medium text-gray-700">
            Calls to include ({selectedIds.size} / {rows.length})
          </p>
          <div className="flex items-center gap-2 text-[11px] shrink-0">
            <button
              type="button"
              className="text-primary-600 hover:underline disabled:opacity-50"
              disabled={disabled || rows.length === 0}
              onClick={selectAll}
            >
              All
            </button>
            <span className="text-gray-300">|</span>
            <button
              type="button"
              className="text-gray-600 hover:underline disabled:opacity-50"
              disabled={disabled || selectedIds.size === 0}
              onClick={() => onChangeSelectedIds(new Set())}
            >
              Clear
            </button>
          </div>
        </div>
        {rows.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] text-gray-500 mr-0.5">Quick:</span>
            {METRIC_CLUSTER_ROW_PRESETS.filter((n) => n <= rows.length).map(
              (n) => (
                <button
                  key={n}
                  type="button"
                  disabled={disabled}
                  className={presetButtonClass(presetActive(n))}
                  onClick={() => selectFirstN(n)}
                >
                  First {n}
                </button>
              ),
            )}
            {rows.length > METRIC_CLUSTER_ROW_PRESETS[METRIC_CLUSTER_ROW_PRESETS.length - 1] ? (
              <button
                type="button"
                disabled={disabled}
                className={presetButtonClass(allActive)}
                onClick={selectAll}
              >
                All {rows.length}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      {rows.length === 0 ? (
        <p className="px-3 py-3 text-xs text-gray-500">
          No completed calls with a flagged quality metric yet.
        </p>
      ) : (
        <ul className="max-h-48 overflow-y-auto divide-y divide-gray-100">
          {rows.map((row) => {
            const id = row.evaluation_row_id
            const label =
              row.conversation_id?.trim() ||
              (row.row_index != null ? `Row ${row.row_index}` : id.slice(0, 8))
            const metrics = row.flagged_metric_names.join(', ')
            return (
              <li key={id}>
                <label className="flex items-start gap-2 px-3 py-2 cursor-pointer hover:bg-gray-50/80">
                  <input
                    type="checkbox"
                    className="mt-0.5 rounded border-gray-300"
                    checked={selectedIds.has(id)}
                    disabled={disabled}
                    onChange={() => toggleRow(id)}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-xs font-medium text-gray-900 truncate">
                      {label}
                    </span>
                    {metrics ? (
                      <span className="block text-[10px] text-gray-500 truncate">
                        Flagged: {metrics}
                      </span>
                    ) : null}
                  </span>
                </label>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function normalizeFailureLabel(label: string): string {
  return label.trim().toLowerCase()
}

function failureRowCountForPreview(
  preview: MetricFailurePolicyMetricPreview,
  policy: MetricFailurePolicy,
): number {
  if (preview.is_multi_label_parent) {
    let total = 0
    for (const name of policy.failure_child_names || []) {
      total += preview.row_count_by_value[name] ?? 0
    }
    return total
  }
  let total = 0
  const targets = new Set(
    (policy.failure_values || []).map((v) => normalizeFailureLabel(v)),
  )
  for (const [label, count] of Object.entries(preview.row_count_by_value)) {
    if (targets.has(normalizeFailureLabel(label))) {
      total += count
    }
  }
  return total
}

function policyHasFailureCriteria(
  preview: MetricFailurePolicyMetricPreview,
  policy: MetricFailurePolicy,
): boolean {
  if (preview.is_multi_label_parent) {
    return (policy.failure_child_names?.length ?? 0) > 0
  }
  if (policy.numeric_rule) return true
  return (policy.failure_values?.length ?? 0) > 0
}

function MetricFailurePolicyEditor({
  previews,
  policies,
  policiesSource,
  onChangePolicies,
  disabled,
}: {
  previews: MetricFailurePolicyMetricPreview[]
  policies: Record<string, MetricFailurePolicy>
  policiesSource: 'inferred' | 'user'
  onChangePolicies: (next: Record<string, MetricFailurePolicy>) => void
  disabled?: boolean
}) {
  if (!previews.length) {
    return (
      <p className="text-xs text-gray-500">
        No quality metrics available for failure policy configuration.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      <div>
        <p className="text-xs font-medium text-gray-800">
          Failure values per metric
        </p>
        <p className="text-[10px] text-gray-500 mt-0.5">
          Select which answers count as failures for metrics you want to cluster.
          Metrics with none selected, or with no matching calls, are skipped.{' '}
          {policiesSource === 'inferred' ? (
            <span className="text-amber-700">
              Suggested defaults only where matching rows exist.
            </span>
          ) : (
            <span className="text-green-700">Saved for this evaluation.</span>
          )}
        </p>
      </div>
      {previews.map((preview) => {
        const policy =
          policies[preview.metric_id] ?? preview.effective_policy
        const failureCount = failureRowCountForPreview(preview, policy)
        const hasCriteria = policyHasFailureCriteria(preview, policy)
        const isSkipped = !hasCriteria || failureCount === 0

        const toggleValue = (label: string, checked: boolean) => {
          const norm = normalizeFailureLabel(label)
          const current = new Set(
            (policy.failure_values || []).map(normalizeFailureLabel),
          )
          if (checked) current.add(norm)
          else current.delete(norm)
          const nextValues = preview.value_counts
            .map((vc) => vc.label)
            .filter((l) => current.has(normalizeFailureLabel(l)))
          onChangePolicies({
            ...policies,
            [preview.metric_id]: {
              ...policy,
              metric_id: preview.metric_id,
              failure_values: nextValues.map(normalizeFailureLabel),
            },
          })
        }

        const toggleChild = (name: string, checked: boolean) => {
          const current = new Set(policy.failure_child_names || [])
          if (checked) current.add(name)
          else current.delete(name)
          onChangePolicies({
            ...policies,
            [preview.metric_id]: {
              ...policy,
              metric_id: preview.metric_id,
              failure_child_names: Array.from(current),
            },
          })
        }

        return (
          <div
            key={preview.metric_id}
            className="rounded-md border border-gray-200 bg-gray-50/50 p-3"
          >
            <div className="flex items-start justify-between gap-2 mb-2">
              <p className="text-sm font-semibold text-gray-900">
                {preview.metric_name}
              </p>
              <span
                className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${
                  isSkipped
                    ? 'bg-gray-100 text-gray-600'
                    : 'bg-primary-50 text-primary-800'
                }`}
              >
                {isSkipped
                  ? 'Skipped — no matching calls'
                  : `${failureCount} call${failureCount === 1 ? '' : 's'} to cluster`}
              </span>
            </div>
            {preview.is_multi_label_parent ? (
              <div className="flex flex-wrap gap-2">
                {preview.child_names.map((name) => {
                  const checked = (policy.failure_child_names || []).includes(
                    name,
                  )
                  const count = preview.row_count_by_value[name] ?? 0
                  return (
                    <label
                      key={name}
                      className="inline-flex items-center gap-1.5 text-xs text-gray-700"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={(e) =>
                          toggleChild(name, e.target.checked)
                        }
                      />
                      {name}
                      <span className="text-gray-400">({count})</span>
                    </label>
                  )
                })}
              </div>
            ) : preview.value_counts.length ? (
              <div className="flex flex-wrap gap-2">
                {preview.value_counts.map((vc) => {
                  const checked = (policy.failure_values || []).some(
                    (v) =>
                      normalizeFailureLabel(v) ===
                      normalizeFailureLabel(vc.label),
                  )
                  return (
                    <label
                      key={vc.label}
                      className="inline-flex items-center gap-1.5 text-xs text-gray-700"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={(e) => toggleValue(vc.label, e.target.checked)}
                      />
                      {vc.label}
                      <span className="text-gray-400">({vc.count})</span>
                    </label>
                  )
                })}
              </div>
            ) : policy.numeric_rule ? (
              <p className="text-xs text-gray-600">
                Numeric failures: score {policy.numeric_rule.op}{' '}
                {policy.numeric_rule.threshold}
                {preview.metric_type ? ` (${preview.metric_type})` : ''}
              </p>
            ) : (
              <p className="text-xs text-gray-500">No observed values yet.</p>
            )}
          </div>
        )
      })}
    </div>
  )
}

function MetricClusterGenerationModal({
  open,
  onClose,
  callImportId,
  evaluationId,
  defaultProvider = '',
  defaultModel = '',
  state,
  onGenerated,
  onError,
  overlayZIndexClass = 'z-50',
}: {
  open: boolean
  onClose: () => void
  callImportId: string
  evaluationId: string
  defaultProvider?: string
  defaultModel?: string
  state: EvaluationMetricClustersState | null
  onGenerated: () => void
  onError?: (message: string | null) => void
  overlayZIndexClass?: string
}) {
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pickerProvider, setPickerProvider] = useState('')
  const [pickerModel, setPickerModel] = useState('')
  const [selectedRowIds, setSelectedRowIds] = useState<Set<string>>(new Set())
  const [selectionTouched, setSelectionTouched] = useState(false)
  const [llmPickerTouched, setLlmPickerTouched] = useState(false)
  const [policies, setPolicies] = useState<Record<string, MetricFailurePolicy>>(
    {},
  )
  const [policiesSource, setPoliciesSource] = useState<'inferred' | 'user'>(
    'inferred',
  )
  const [policiesTouched, setPoliciesTouched] = useState(false)

  const failurePoliciesQuery = useQuery({
    queryKey: [
      'call-import-evaluation-metric-cluster-failure-policies',
      callImportId,
      evaluationId,
    ],
    queryFn: () =>
      apiClient.getCallImportEvaluationMetricClusterFailurePolicies(
        callImportId,
        evaluationId,
      ),
    enabled: open && !!callImportId && !!evaluationId,
    staleTime: 30_000,
  })

  const eligibleRowsQuery = useQuery({
    queryKey: [
      'call-import-evaluation-metric-cluster-eligible-rows',
      callImportId,
      evaluationId,
      policiesSource,
      JSON.stringify(policies),
    ],
    queryFn: () =>
      apiClient.listCallImportEvaluationMetricClusterEligibleRows(
        callImportId,
        evaluationId,
      ),
    enabled: open && !!callImportId && !!evaluationId,
    staleTime: 30_000,
  })

  const eligibleRows = eligibleRowsQuery.data?.items ?? []
  const hasExistingClusters = !!state?.groups?.length

  useEffect(() => {
    if (!open) return
    setError(null)
    onError?.(null)
  }, [open])

  useEffect(() => {
    const data = failurePoliciesQuery.data
    if (!open || !data || policiesTouched) return
    setPolicies(data.policies)
    setPoliciesSource(data.source)
  }, [open, failurePoliciesQuery.data, policiesTouched])

  useEffect(() => {
    if (!open || !policiesTouched || generating) return
    const timer = window.setTimeout(() => {
      apiClient
        .saveCallImportEvaluationMetricClusterFailurePolicies(
          callImportId,
          evaluationId,
          policies,
        )
        .then((saved) => {
          setPoliciesSource(saved.source)
          eligibleRowsQuery.refetch()
        })
        .catch(() => {
          /* keep local edits; generate will persist */
        })
    }, 600)
    return () => window.clearTimeout(timer)
  }, [
    open,
    policies,
    policiesTouched,
    generating,
    callImportId,
    evaluationId,
  ])

  useEffect(() => {
    if (state?.provider) {
      setPickerProvider(state.provider)
      if (state.model) setPickerModel(state.model)
      return
    }
    if (llmPickerTouched) return
    if (defaultProvider) setPickerProvider(defaultProvider)
    if (defaultModel) setPickerModel(defaultModel)
  }, [
    state?.provider,
    state?.model,
    defaultProvider,
    defaultModel,
    llmPickerTouched,
  ])

  useEffect(() => {
    if (!open || selectionTouched || eligibleRows.length === 0) return
    const fromState = state?.selected_evaluation_row_ids
    if (fromState?.length) {
      const valid = fromState.filter((id) =>
        eligibleRows.some((r) => r.evaluation_row_id === id),
      )
      if (valid.length) {
        setSelectedRowIds(new Set(valid))
        return
      }
    }
    setSelectedRowIds(new Set(eligibleRows.map((r) => r.evaluation_row_id)))
  }, [
    open,
    eligibleRows,
    selectionTouched,
    state?.selected_evaluation_row_ids,
  ])

  const reportError = (message: string | null) => {
    setError(message)
    onError?.(message)
  }

  const handleGenerate = async () => {
    if (selectedRowIds.size === 0) {
      reportError('Select at least one call to cluster.')
      return
    }
    const previews = failurePoliciesQuery.data?.previews ?? []
    const hasClusterableMetric = previews.some((p) => {
      const policy = policies[p.metric_id] ?? p.effective_policy
      return (
        policyHasFailureCriteria(p, policy) &&
        failureRowCountForPreview(p, policy) > 0
      )
    })
    if (!hasClusterableMetric) {
      reportError(
        'No calls match any failure policy. Select failure values on at least one metric that has matching rows.',
      )
      return
    }
    setGenerating(true)
    reportError(null)
    try {
      const force = hasExistingClusters
      const allSelected =
        eligibleRows.length > 0 &&
        selectedRowIds.size === eligibleRows.length
      await apiClient.generateCallImportEvaluationMetricClusters(
        callImportId,
        evaluationId,
        {
          force,
          regenerate: force,
          provider: pickerProvider || undefined,
          model: pickerModel || undefined,
          evaluation_row_ids: allSelected
            ? undefined
            : Array.from(selectedRowIds),
          failure_policies: policies,
        },
      )
      onGenerated()
      onClose()
    } catch (e: any) {
      reportError(
        e?.response?.data?.detail ||
          'Failed to start metric cluster generation.',
      )
    } finally {
      setGenerating(false)
    }
  }

  const handleClose = () => {
    if (generating) return
    reportError(null)
    onClose()
  }

  if (!open || typeof document === 'undefined') return null

  return createPortal(
    <div
      className={`fixed inset-0 ${overlayZIndexClass} flex items-center justify-center p-4 bg-black/40`}
    >
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[92vh] overflow-hidden flex flex-col">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              Generate clusters
            </h2>
            <p className="text-sm text-gray-600 mt-0.5">
              Configure failure values per metric, choose calls, then generate
              clusters from LLM rationales.
            </p>
          </div>
          <button
            type="button"
            onClick={handleClose}
            disabled={generating}
            className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
            aria-label="Close cluster generation modal"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="px-6 py-5 overflow-y-auto flex-1">
          <div className="mb-4">
            {failurePoliciesQuery.isLoading ? (
              <p className="text-xs text-gray-500">Loading failure policies…</p>
            ) : failurePoliciesQuery.data ? (
              <MetricFailurePolicyEditor
                previews={failurePoliciesQuery.data.previews}
                policies={policies}
                policiesSource={policiesSource}
                onChangePolicies={(next) => {
                  setPoliciesTouched(true)
                  setPolicies(next)
                }}
                disabled={generating}
              />
            ) : null}
          </div>
          <div className="mb-3">
            {eligibleRowsQuery.isLoading ? (
              <p className="text-xs text-gray-500">Loading eligible calls…</p>
            ) : (
              <MetricClusterRowPicker
                rows={eligibleRows}
                selectedIds={selectedRowIds}
                onChangeSelectedIds={(next) => {
                  setSelectionTouched(true)
                  setSelectedRowIds(next)
                }}
                disabled={generating}
              />
            )}
          </div>
          <div className="mb-3 rounded-md border border-gray-100 bg-white/80 p-3">
            <p className="text-xs font-medium text-gray-800 mb-0.5">
              LLM for clustering
            </p>
            <p className="text-[10px] text-gray-500 mb-2">
              Provider and model used for failure signatures and cluster
              synthesis. Defaults to this evaluation&apos;s scoring LLM when
              unset.
            </p>
            <AIProviderModelPicker
              provider={pickerProvider}
              model={pickerModel}
              onProviderChange={(next) => {
                setLlmPickerTouched(true)
                setPickerProvider(next)
              }}
              onModelChange={(next) => {
                setLlmPickerTouched(true)
                setPickerModel(next)
              }}
              disabled={generating}
              size="sm"
            />
          </div>
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
        </div>
        <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-end gap-2">
          <Button variant="outline" onClick={handleClose} disabled={generating}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleGenerate}
            isLoading={generating}
            disabled={generating || selectedRowIds.size === 0}
          >
            Generate clusters
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function buildEvaluationCallDeepLink(
  callImportId: string,
  evaluationId: string,
  evidence: MetricClusterEvidence,
): string | null {
  const conv = evidence.conversation_id?.trim()
  const rowId = evidence.evaluation_row_id?.trim()
  if (!conv && !rowId) return null
  const base = `/call-imports/${callImportId}/evaluations/${evaluationId}`
  if (conv) {
    return `${base}?conversation_id=${encodeURIComponent(conv)}`
  }
  return `${base}?row_id=${encodeURIComponent(rowId!)}`
}

function RcaExecutiveBar({ pct, scaleMax }: { pct: number; scaleMax: number }) {
  const width =
    scaleMax > 0 ? Math.min(100, Math.round((pct / scaleMax) * 100)) : 0
  return (
    <div className="h-2.5 rounded-sm bg-[#e7ddd1] border border-[#d7cfc2] overflow-hidden min-w-[80px]">
      <div
        className="h-full bg-[#c7725e] rounded-sm transition-all"
        style={{ width: `${width}%` }}
      />
    </div>
  )
}

function RcaExecutiveInterpretation({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-rose-100 bg-rose-50/70 px-3 py-2.5 mt-3">
      <p className="text-[10px] font-bold uppercase tracking-wide text-rose-800 mb-1">
        Executive interpretation
      </p>
      <p className="text-xs text-gray-800 leading-relaxed">{children}</p>
    </div>
  )
}

function MetricClustersRcaSummaryPanel({
  summary,
}: {
  summary: MetricClustersRcaSummary
}) {
  const topPattern = summary.repeated_patterns[0]
  const topHotspot = summary.metric_hotspots[0]
  const maxPatternShare = Math.max(
    ...summary.repeated_patterns.map((r) => r.evidence_share_pct),
    1,
  )
  const maxHotspotRate = Math.max(
    ...summary.metric_hotspots.map((r) => r.metric_rate_pct),
    1,
  )
  const totalFlagged =
    summary.total_flagged_instances ??
    summary.metric_hotspots.reduce((sum, r) => sum + r.flagged_calls, 0)

  return (
    <article className="rounded-lg border border-gray-200 bg-[#faf7f2]/80 p-4 space-y-6">
      <div>
        <h4 className="text-base font-semibold text-gray-900">
          Executive summary — evaluation set
        </h4>
        <p className="text-xs text-gray-600 mt-1">
          Top metrics by clustered failure patterns and overall flagged rate across{' '}
          {summary.analysed_calls.toLocaleString()} analysed calls.
        </p>
      </div>

      {summary.repeated_patterns.length ? (
        <section className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-gray-200 pb-2">
            <h5 className="text-sm font-semibold text-gray-900">
              Repeated failure patterns
            </h5>
            <p className="text-[10px] text-gray-500 uppercase tracking-wide text-right max-w-md">
              Base: {summary.total_clusters} RCA clusters from{' '}
              {summary.total_clustered_instances.toLocaleString()} clustered instances ·{' '}
              {totalFlagged.toLocaleString()} flagged metric-call instances
            </p>
          </div>
          <div className="overflow-x-auto rounded-md border border-gray-100 bg-white">
            <table className="w-full min-w-[520px] text-xs">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wide text-gray-500 border-b border-gray-100">
                  <th className="px-3 py-2 font-semibold w-[42%]">Finding</th>
                  <th className="px-3 py-2 font-semibold text-right w-[14%]">
                    Evidence share
                  </th>
                  <th className="px-3 py-2 font-semibold w-[26%]">Distribution</th>
                  <th className="px-3 py-2 font-semibold text-right w-[18%]">
                    Evidence calls
                  </th>
                </tr>
              </thead>
              <tbody>
                {summary.repeated_patterns.map((row) => (
                  <tr
                    key={row.metric_id}
                    className="border-b border-gray-50 align-top last:border-0"
                  >
                    <td className="px-3 py-2.5">
                      <p className="font-bold text-gray-900 uppercase tracking-tight text-[11px]">
                        {row.metric_name}
                      </p>
                      <p className="text-[10px] text-gray-500 mt-1 leading-snug">
                        Top RCA patterns: {row.top_rca_patterns}
                      </p>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums font-semibold text-gray-900">
                      {row.evidence_share_pct.toFixed(1)}%
                    </td>
                    <td className="px-3 py-2.5">
                      <RcaExecutiveBar
                        pct={row.evidence_share_pct}
                        scaleMax={maxPatternShare}
                      />
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums font-semibold text-gray-900">
                      {row.evidence_calls.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {topPattern ? (
            <RcaExecutiveInterpretation>
              These rows group repeated RCA failure patterns by metric so the same
              metric is not repeated across multiple rows. The largest group is{' '}
              <span className="font-semibold">{topPattern.metric_name}</span>; focus
              remediation there first using the example calls in each cluster below.
            </RcaExecutiveInterpretation>
          ) : null}
        </section>
      ) : null}

      {summary.metric_hotspots.length ? (
        <section className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-gray-200 pb-2">
            <h5 className="text-sm font-semibold text-gray-900">Metric hotspots</h5>
            <p className="text-[10px] text-gray-500 uppercase tracking-wide">
              Base: selected metric flags across{' '}
              {summary.analysed_calls.toLocaleString()} analysed calls
            </p>
          </div>
          <div className="overflow-x-auto rounded-md border border-gray-100 bg-white">
            <table className="w-full min-w-[520px] text-xs">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wide text-gray-500 border-b border-gray-100">
                  <th className="px-3 py-2 font-semibold w-[42%]">Finding</th>
                  <th className="px-3 py-2 font-semibold text-right w-[14%]">
                    Metric rate
                  </th>
                  <th className="px-3 py-2 font-semibold w-[26%]">Distribution</th>
                  <th className="px-3 py-2 font-semibold text-right w-[18%]">
                    Flagged calls
                  </th>
                </tr>
              </thead>
              <tbody>
                {summary.metric_hotspots.map((row) => (
                  <tr
                    key={row.metric_id}
                    className="border-b border-gray-50 align-top last:border-0"
                  >
                    <td className="px-3 py-2.5">
                      <p className="font-bold text-gray-900 uppercase tracking-tight text-[11px]">
                        {row.metric_name}
                      </p>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums font-semibold text-gray-900">
                      {row.metric_rate_pct.toFixed(2)}%
                    </td>
                    <td className="px-3 py-2.5">
                      <RcaExecutiveBar
                        pct={row.metric_rate_pct}
                        scaleMax={maxHotspotRate}
                      />
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums font-semibold text-gray-900">
                      {row.flagged_calls.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {topHotspot ? (
            <RcaExecutiveInterpretation>
              Across {summary.analysed_calls.toLocaleString()} analysed calls,{' '}
              <span className="font-semibold">{topHotspot.metric_name}</span> has the
              highest metric rate at {topHotspot.metric_rate_pct.toFixed(2)}%.
            </RcaExecutiveInterpretation>
          ) : null}
        </section>
      ) : null}

      {summary.prompt_areas.length ? (
        <section className="space-y-2 pt-2 border-t border-gray-200">
          <h5 className="text-sm font-semibold text-gray-900">RCA data summary</h5>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-600">
            Prompt areas to inspect
          </p>
          <table className="w-full text-xs border border-gray-100 rounded-md overflow-hidden bg-white">
            <thead className="bg-gray-50 text-gray-500">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Area</th>
                <th className="text-right px-3 py-2 font-medium">%</th>
              </tr>
            </thead>
            <tbody>
              {summary.prompt_areas.map((row) => (
                <tr key={row.label} className="border-t border-gray-100">
                  <td className="px-3 py-2 text-gray-800">{row.label}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-gray-700">
                    {row.share_pct.toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </article>
  )
}

function MetricClustersPanel({
  callImportId,
  evaluationId,
  defaultProvider = '',
  defaultModel = '',
  state,
  isLoading,
  onGenerated,
}: {
  callImportId: string
  evaluationId: string
  defaultProvider?: string
  defaultModel?: string
  state: EvaluationMetricClustersState | null
  isLoading: boolean
  onGenerated: () => void
}) {
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pickerProvider, setPickerProvider] = useState('')
  const [pickerModel, setPickerModel] = useState('')
  const [llmPickerTouched, setLlmPickerTouched] = useState(false)
  const [clusterActionModalOpen, setClusterActionModalOpen] = useState(false)

  useEffect(() => {
    if (state?.provider) {
      setPickerProvider(state.provider)
      if (state.model) setPickerModel(state.model)
      return
    }
    if (llmPickerTouched) return
    if (defaultProvider) setPickerProvider(defaultProvider)
    if (defaultModel) setPickerModel(defaultModel)
  }, [
    state?.provider,
    state?.model,
    defaultProvider,
    defaultModel,
    llmPickerTouched,
  ])

  const llmPickerDisabled = cancelling || state?.status === 'running'

  const llmPickerBlock = (
    <div className="mb-3 rounded-md border border-gray-100 bg-white/80 p-3">
      <p className="text-xs font-medium text-gray-800 mb-0.5">
        LLM for clustering
      </p>
      <p className="text-[10px] text-gray-500 mb-2">
        Provider and model used for failure signatures and cluster synthesis.
        Defaults to this evaluation&apos;s scoring LLM when unset.
      </p>
      <AIProviderModelPicker
        provider={pickerProvider}
        model={pickerModel}
        onProviderChange={(next) => {
          setLlmPickerTouched(true)
          setPickerProvider(next)
        }}
        onModelChange={(next) => {
          setLlmPickerTouched(true)
          setPickerModel(next)
        }}
        disabled={llmPickerDisabled}
        size="sm"
      />
    </div>
  )

  const selectedCountLabel = state?.selected_evaluation_row_ids?.length

  const clusterGenerationModal = (
    <MetricClusterGenerationModal
      open={clusterActionModalOpen}
      onClose={() => {
        setClusterActionModalOpen(false)
        setError(null)
      }}
      callImportId={callImportId}
      evaluationId={evaluationId}
      defaultProvider={defaultProvider}
      defaultModel={defaultModel}
      state={state}
      onGenerated={onGenerated}
      onError={setError}
    />
  )

  const handleCancel = async () => {
    setCancelling(true)
    setError(null)
    try {
      await apiClient.cancelCallImportEvaluationMetricClusters(
        callImportId,
        evaluationId,
      )
      onGenerated()
    } catch (e: any) {
      setError(
        e?.response?.data?.detail || 'Failed to stop cluster generation.',
      )
    } finally {
      setCancelling(false)
    }
  }

  if (isLoading && !state) {
    return (
      <>
        <section className="rounded-lg border border-dashed border-gray-200 bg-gray-50/60 p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-1">
            Failure diagnostics (internal)
          </h3>
          <p className="text-xs text-gray-500 mb-3">Loading…</p>
          {llmPickerBlock}
        </section>
        {clusterGenerationModal}
      </>
    )
  }

  if (state?.status === 'running') {
    const progress = state.progress
    const completed = progress?.completed_llm_calls ?? 0
    const total = progress?.total_llm_calls ?? 0
    const pct = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0
    const providerLabel = state.provider
      ? PROVIDER_DISPLAY[state.provider] || state.provider
      : null
    const callsLabel = selectedCountLabel
      ? `${selectedCountLabel} selected call${selectedCountLabel === 1 ? '' : 's'}`
      : 'flagged calls'
    return (
      <>
        <section className="rounded-lg border border-amber-200 bg-amber-50/60 px-4 py-3">
          <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
            <p className="text-xs font-semibold text-gray-900 inline-flex items-center gap-1.5">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-600" />
              Failure diagnostics — generating clusters
            </p>
            {total > 0 ? (
              <p className="text-[10px] text-gray-600 tabular-nums">
                {completed} / {total} LLM calls ({pct}%)
              </p>
            ) : null}
          </div>
          <p className="text-xs text-amber-800 mb-2">
            Clustering {callsLabel} for each enabled quality metric.
          </p>
          {total > 0 ? (
            <div className="mb-2">
              <div className="h-2.5 rounded-full bg-amber-100 overflow-hidden">
                <div
                  className="h-full bg-amber-600 transition-all duration-300"
                  style={{ width: `${pct}%` }}
                  role="progressbar"
                  aria-valuenow={completed}
                  aria-valuemin={0}
                  aria-valuemax={total}
                  aria-label="Cluster generation progress"
                />
              </div>
            </div>
          ) : (
            <div className="mb-2 h-2.5 rounded-full bg-amber-100 overflow-hidden">
              <div className="h-full w-1/3 bg-amber-400 animate-pulse rounded-full" />
            </div>
          )}
          {providerLabel || state.model ? (
            <p className="text-[10px] text-gray-500">
              Using {providerLabel || 'LLM'}
              {state.model ? ` · ${state.model}` : ''}
            </p>
          ) : null}
          <div className="mt-3 flex items-center gap-2">
            <Button
              variant="outline"
              onClick={handleCancel}
              isLoading={cancelling}
              disabled={cancelling}
            >
              Stop
            </Button>
          </div>
          {error ? <p className="text-xs text-red-600 mt-2">{error}</p> : null}
        </section>
        {clusterGenerationModal}
      </>
    )
  }

  if (state?.status === 'cancelled') {
    return (
      <section className="rounded-lg border border-gray-200 bg-gray-50/80 px-4 py-3">
        <p className="text-sm font-semibold text-gray-900 mb-1">
          Failure diagnostics stopped
        </p>
        <p className="text-sm text-gray-600">
          {state.error_message ||
            'Cluster generation was cancelled. Partial results were not saved.'}
        </p>
        {state.progress ? (
          <p className="text-xs text-gray-500 mt-1">
            Stopped at {state.progress.completed_llm_calls} /{' '}
            {state.progress.total_llm_calls} LLM calls
          </p>
        ) : null}
        <div className="mt-3">
          <Button
            variant="primary"
            onClick={() => setClusterActionModalOpen(true)}
            disabled={cancelling}
          >
            Generate clusters
          </Button>
        </div>
        {clusterGenerationModal}
      </section>
    )
  }

  if (state?.status === 'failed') {
    return (
      <section className="rounded-lg border border-red-200 bg-red-50/50 px-4 py-3">
        <p className="text-sm font-semibold text-gray-900 mb-1">
          Failure diagnostics failed
        </p>
        <p className="text-sm text-red-700">
          {state.error_message || 'Cluster generation failed.'}
        </p>
        <div className="mt-3">
          <Button
            variant="outline"
            onClick={() => setClusterActionModalOpen(true)}
          >
            Retry
          </Button>
        </div>
        {clusterGenerationModal}
      </section>
    )
  }

  if (!state || state.status === 'idle' || !state.groups.length) {
    return (
      <section className="rounded-lg border border-dashed border-gray-200 bg-gray-50/60 p-4">
        <div className="mb-3">
          <h3 className="text-base font-semibold text-gray-900 mb-1">
            Failure diagnostics (internal)
          </h3>
          <p className="text-sm text-gray-600">
            Choose which flagged calls to include, then cluster per enabled
            quality metric (gap labels: LOGIC_GAP, UNDERSPEC, EXISTS_NO_TRIGGER,
            MISSING).
          </p>
        </div>
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="primary"
            onClick={() => setClusterActionModalOpen(true)}
            disabled={cancelling}
          >
            Generate clusters
          </Button>
        </div>
        {clusterGenerationModal}
      </section>
    )
  }

  return (
    <section className="space-y-4">
      <article className="rounded-lg border border-gray-200 bg-gray-50/40 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-base font-semibold text-gray-900">Generation</h3>
          <Button
            variant="primary"
            className="shrink-0"
            onClick={() => setClusterActionModalOpen(true)}
          >
            Generate clusters
          </Button>
        </div>
        <div className="mt-2 space-y-1 min-w-0">
          <p className="text-sm text-gray-600">
            Select the calls and model in a modal, then generate clusters.
            Run again after more rows complete or when you change the model.
          </p>
          {state.overview ? (
            <p className="text-sm text-gray-600 break-words">
              {clampProseToSentences(state.overview)}
            </p>
          ) : null}
          {state.is_stale ? (
            <p className="text-sm text-amber-700">
              More rows completed since clusters were generated. Generate again
              to refresh.
            </p>
          ) : null}
          {state.selected_evaluation_row_ids?.length ? (
            <p className="text-[10px] text-gray-500">
              Based on {state.selected_evaluation_row_ids.length} selected call
              {state.selected_evaluation_row_ids.length === 1 ? '' : 's'}.
            </p>
          ) : null}
        </div>
        {error ? <p className="text-sm text-red-600 mt-2">{error}</p> : null}
      </article>

      {clusterGenerationModal}

      <article className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
        <div>
          <h3 className="text-base font-semibold text-gray-900">Results</h3>
          <p className="text-sm text-gray-600 mt-1">
            Per-metric clusters of flagged calls with gap labels and Level-2
            sub-categories.
          </p>
        </div>
        {state.rca_summary ? (
          <MetricClustersRcaSummaryPanel summary={state.rca_summary} />
        ) : null}
        {state.groups.map((group) => {
          const topClusters = [...group.clusters]
            .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
            .slice(0, 5)
          return (
          <article
            key={group.metric_id}
            className="rounded-lg border border-gray-200 bg-white overflow-hidden"
          >
            <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/80">
              <h4 className="text-base font-semibold text-gray-900">
                {group.metric_name}
              </h4>
              <p className="text-xs text-gray-500">
                {group.flagged_count} flagged calls · {topClusters.length}
                {group.clusters.length > 5
                  ? ` of ${group.clusters.length}`
                  : ''}{' '}
                cluster(s) shown
                {state.failure_policies?.[group.metric_id] ? (
                  <>
                    {' '}
                    · failure:{' '}
                    {[
                      ...(state.failure_policies[group.metric_id]
                        .failure_values || []),
                      ...(state.failure_policies[group.metric_id]
                        .failure_child_names || []),
                    ].join(', ') || 'numeric rule'}
                  </>
                ) : null}
              </p>
              {group.failure_reason ? (
                <p className="text-xs text-gray-600 mt-1">
                  <span className="font-semibold text-gray-700">Why flagged:</span>{' '}
                  {group.failure_reason}
                </p>
              ) : null}
            </div>
            <div className="p-4 space-y-3">
              {(() => {
                const categorizedCalls = topClusters.reduce(
                  (sum, cluster) => sum + Math.max(0, cluster.count || 0),
                  0,
                )
                const totalFlagged = Math.max(0, group.flagged_count || 0)
                return (
                  <div className="rounded-md border border-gray-100 bg-gray-50/60 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">
                        Cluster breakdown
                      </p>
                      <span className="text-xs font-semibold text-gray-700">
                        {categorizedCalls} / {totalFlagged}
                      </span>
                    </div>
                  </div>
                )
              })()}
              {topClusters.map((cluster) => {
                const exampleHref = buildEvaluationCallDeepLink(
                  callImportId,
                  evaluationId,
                  cluster.evidence,
                )
                return (
                <div
                  key={cluster.id}
                  className="rounded-md border border-gray-100 p-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-semibold text-gray-900">
                      {cluster.label}
                    </p>
                    <span className="text-xs font-bold uppercase text-primary-700">
                      {cluster.gap_label.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <p className="text-xs text-gray-600 mt-0.5">
                    {cluster.count} calls · {cluster.share_pct.toFixed(1)}% share
                  </p>
                  {cluster.failure_reason ? (
                    <p className="text-xs text-gray-600 mt-1">
                      <span className="font-semibold">Why flagged:</span>{' '}
                      {cluster.failure_reason}
                    </p>
                  ) : null}
                  {group.flagged_count > 0 ? (
                    <div className="mt-2">
                      <div className="h-2.5 w-full rounded bg-primary-100 overflow-hidden">
                        <div
                          className="h-full rounded bg-primary-500"
                          style={{
                            width: `${Math.min(
                              100,
                              (cluster.count / group.flagged_count) * 100,
                            ).toFixed(1)}%`,
                          }}
                        />
                      </div>
                    </div>
                  ) : null}
                  {cluster.observation ? (
                    <p className="text-sm text-gray-700 mt-2">
                      {cluster.observation}
                    </p>
                  ) : null}
                  {cluster.sub_clusters.length ? (
                    <ul className="mt-2 text-xs text-gray-600 list-disc pl-4">
                      {cluster.sub_clusters.map((sub) => (
                        <li key={sub.label}>
                          {sub.label} — {sub.count} ({sub.share_pct.toFixed(1)}%)
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {(cluster.evidence.quote ||
                    cluster.evidence.turns?.length ||
                    cluster.evidence.conversation_id) ? (
                    <div className="mt-2 rounded-md bg-gray-50 border border-gray-100 p-2 space-y-1">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-600">
                        Example call
                      </p>
                      {cluster.evidence.turns?.length ? (
                        cluster.evidence.turns.map((turn, i) => (
                          <p key={i} className="text-xs text-gray-800">
                            <span className="font-semibold text-primary-700">
                              {turn.speaker}:
                            </span>{' '}
                            {turn.text}
                          </p>
                        ))
                      ) : cluster.evidence.quote ? (
                        <p className="text-xs text-gray-800">{cluster.evidence.quote}</p>
                      ) : null}
                      {exampleHref && cluster.evidence.conversation_id ? (
                        <Link
                          to={exampleHref}
                          className="inline-flex items-center gap-1 text-xs font-medium text-primary-700 hover:text-primary-800"
                        >
                          <ExternalLink className="h-3 w-3" />
                          {cluster.evidence.conversation_id}
                        </Link>
                      ) : cluster.evidence.conversation_id ? (
                        <p className="text-[10px] text-gray-500 font-mono">
                          {cluster.evidence.conversation_id}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              )})}
            </div>
          </article>
        )})}
        {state.discovered_problems.length ? (
          <article className="rounded-lg border border-dashed border-primary-200 bg-primary-50/30 p-4">
            <h4 className="text-base font-semibold text-gray-900 mb-2">
              Proactive problem discovery
            </h4>
            <div className="space-y-2">
              {state.discovered_problems.map((item) => (
                <div key={item.id} className="text-sm text-gray-800">
                  <span className="font-semibold">{item.label}</span>
                  <span className="text-primary-700 ml-2 uppercase text-xs font-semibold">
                    {item.gap_label.replace(/_/g, ' ')}
                  </span>
                  <span className="text-gray-500 ml-2">
                    {item.count} · {item.share_pct.toFixed(1)}%
                  </span>
                  {item.observation ? (
                    <p className="mt-1 text-gray-600">{item.observation}</p>
                  ) : null}
                </div>
              ))}
            </div>
          </article>
        ) : null}
      </article>
    </section>
  )
}

function EvaluationUserInsightsPanel({
  state,
  isLoading,
}: {
  state: EvaluationUserInsightsState | null
  isLoading: boolean
}) {
  if (isLoading || !state || state.status === 'running' || state.status === 'failed') {
    return null
  }

  if (state.status === 'idle') {
    return (
      <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50/60 p-4">
        <p className="text-xs text-gray-500">
          User insights generate automatically in the background when you
          click Generate summary above.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs text-gray-500">
          LLM-identified patterns for section 03 of the external audit report.
          {state.max_llm_calls ? (
            <span className="block mt-0.5">
              Sample size: up to {state.max_llm_calls} LLM calls.
            </span>
          ) : null}
        </p>
        {state.is_stale ? (
          <p className="text-[11px] text-amber-700 mt-1">
            More rows completed since these insights were generated. Regenerate
            the summary to refresh.
          </p>
        ) : null}
      </div>
      {state.overview ? (
        <p className="text-xs text-gray-600 break-words leading-relaxed">
          {clampProseToSentences(state.overview)}
        </p>
      ) : null}
      {state.insights.map((insight, index) => (
        <GeneratedUserInsightCard key={insight.id} insight={insight} index={index + 1} />
      ))}
    </div>
  )
}

function GeneratedUserInsightCard({
  insight,
  index,
}: {
  insight: EvaluationUserInsightItem
  index: number
}) {
  const maxCount = Math.max(
    ...insight.categories.map((c) => c.count),
    1,
  )
  return (
    <article className="rounded-lg border border-gray-200 bg-white overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/80">
        <h4 className="text-sm font-semibold text-gray-900">
          3.{index} {insight.title}
        </h4>
        <p className="text-[10px] text-gray-500">pattern-analysis · LLM-identified</p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 lg:divide-x divide-gray-100">
        <div className="p-4 overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-100">
                <th className="pb-2 pr-3 font-medium">Category</th>
                <th className="pb-2 pr-3 font-medium">Share</th>
                <th className="pb-2 pr-3 font-medium">Distribution</th>
                <th className="pb-2 font-medium">Calls</th>
              </tr>
            </thead>
            <tbody>
              {insight.categories.map((cat) => (
                <tr key={cat.label} className="border-b border-gray-50">
                  <td className="py-2 pr-3 text-gray-800">{cat.label}</td>
                  <td className="py-2 pr-3 text-gray-600">{cat.share_pct.toFixed(1)}%</td>
                  <td className="py-2 pr-3">
                    <div className="h-2 w-24 rounded bg-gray-100 overflow-hidden">
                      <div
                        className="h-full bg-gray-800 rounded"
                        style={{
                          width: `${Math.min(100, (cat.count / maxCount) * 100)}%`,
                        }}
                      />
                    </div>
                  </td>
                  <td className="py-2 text-gray-600">{cat.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="p-4 space-y-3">
          <div className="rounded-md bg-rose-50/80 border border-rose-100 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-rose-800 mb-1">
              Observation
            </p>
            <p className="text-xs text-gray-800 leading-relaxed">{insight.observation}</p>
          </div>
          <div className="rounded-md bg-amber-50/60 border border-amber-100 p-3 space-y-2">
            {insight.evidence.turns?.length ? (
              insight.evidence.turns.map((turn, i) => (
                <p key={i} className="text-xs text-gray-800">
                  <span className="font-semibold text-rose-700">{turn.speaker}:</span>{' '}
                  {turn.text}
                </p>
              ))
            ) : insight.evidence.quote ? (
              <p className="text-xs text-gray-800">
                <span className="font-semibold text-rose-700">User:</span>{' '}
                {insight.evidence.quote}
              </p>
            ) : null}
            {insight.evidence.conversation_id ? (
              <p className="text-[10px] text-gray-500">
                {insight.evidence.conversation_id}
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </article>
  )
}

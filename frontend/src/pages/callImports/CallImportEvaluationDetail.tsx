import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate, useParams } from 'react-router-dom'
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
  Download,
  Edit3,
  ExternalLink,
  Filter,
  Loader2,
  Merge,
  PieChart as PieChartIcon,
  Plus,
  RefreshCw,
  RotateCw,
  Search,
  Sparkles,
  Table,
  Trash2,
  Workflow,
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
  EvaluationTldrSummary,
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
import MetricFlowChart, {
  flowFromSequence,
} from './components/MetricFlowChart'

const PIE_COLORS = ['#10b981', '#ef4444', '#6366f1', '#f59e0b', '#a855f7']

const ROWS_PAGE_SIZE = 50

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
            'inline-flex items-center gap-1 rounded px-1 -mx-1 py-0.5 hover:bg-gray-100 transition-colors ' +
            (isActive ? 'text-gray-900' : 'text-gray-500')
          }
        >
          <span className="truncate">{children}</span>
          <Icon
            className={
              'h-3 w-3 flex-shrink-0 ' +
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

  const [page, setPage] = useState(1)
  const [editingName, setEditingName] = useState(false)
  const [draftName, setDraftName] = useState('')
  const [renameError, setRenameError] = useState<string | null>(null)
  const [pendingDeleteRow, setPendingDeleteRow] =
    useState<CallImportEvaluationRow | null>(null)
  const [deleteEvalOpen, setDeleteEvalOpen] = useState(false)
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false)
  const downloadMenuRef = useRef<HTMLDivElement>(null)
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
  // Categorical metrics can be rendered either as a pie (default,
  // best for ≤5 buckets) or as a vertical bar chart. Numeric metrics
  // always use a histogram regardless of this toggle.
  const [categoricalChartType, setCategoricalChartType] = useState<
    'pie' | 'bar'
  >('pie')

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
  type DisplayMetric = { id: string; name: string; hasRationale: boolean }
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
                  Click any bar or slice to filter the row table by that value.
                </p>
                <div className="inline-flex border border-gray-200 rounded-lg p-1 bg-gray-50">
                  <button
                    type="button"
                    onClick={() => setCategoricalChartType('pie')}
                    className={`px-2.5 py-1 text-[11px] font-medium rounded transition inline-flex items-center gap-1.5 ${
                      categoricalChartType === 'pie'
                        ? 'bg-white text-primary-700 shadow-sm'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                    aria-pressed={categoricalChartType === 'pie'}
                    title="Render categorical metrics as pie charts"
                  >
                    <PieChartIcon className="h-3 w-3" />
                    Pie
                  </button>
                  <button
                    type="button"
                    onClick={() => setCategoricalChartType('bar')}
                    className={`px-2.5 py-1 text-[11px] font-medium rounded transition inline-flex items-center gap-1.5 ${
                      categoricalChartType === 'bar'
                        ? 'bg-white text-primary-700 shadow-sm'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                    aria-pressed={categoricalChartType === 'bar'}
                    title="Render categorical metrics as bar charts"
                  >
                    <BarChart3 className="h-3 w-3" />
                    Bar
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {aggregateQuery.data.metrics.map((m) => {
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
                        categoricalChartType={categoricalChartType}
                        isActive={isActive}
                        activeValue={activeValue}
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
                })}
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
                      const headers = [
                        <SortableHeader
                          key={metric.id}
                          columnKey={`metric:${metric.id}`}
                          activeKey={sortBy}
                          activeDir={sortDir}
                          onCycle={handleColumnSort}
                          title={metric.name}
                        >
                          {metric.name}
                        </SortableHeader>,
                      ]
                      if (metric.hasRationale) {
                        headers.push(
                          <th
                            key={`${metric.id}__rationale`}
                            className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap"
                            title={`${metric.name} - LLM Rationale`}
                          >
                            {metric.name} <span className="text-gray-400">- LLM Rationale</span>
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
                          {row.conversation_id || '-'}
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
 * Single-metric chart card used inside the Visualizations tab. Picks
 * the chart shape from the aggregate payload: numeric histograms beat
 * categorical pie/bar charts when both are present, since numeric
 * distributions tell a richer story than the top-N category tally.
 *
 * Categorical metrics render as either a pie or a vertical bar
 * depending on ``categoricalChartType``. Wide categorical sets (>8
 * unique values) always render as a horizontal bar regardless so we
 * don't truncate labels in a cramped pie chart.
 *
 * Categorical bars and pie slices are clickable: clicking one calls
 * ``onValueClick(label)`` with the value the user wants to drill into
 * — the parent uses that to apply a row-table filter.
 */
function MetricVisualization({
  metric,
  categoricalChartType,
  isActive,
  activeValue,
  onValueClick,
}: {
  metric: CallImportMetricAggregate
  categoricalChartType: 'pie' | 'bar'
  isActive: boolean
  activeValue: string | null
  onValueClick: (value: string) => void
}) {
  const histogram = metric.histogram_buckets
  const valueCounts = metric.value_counts
  const hasNumeric = histogram.length > 0 || metric.mean != null
  const hasCategorical = valueCounts.length > 0
  const totalCategorical = valueCounts.reduce((sum, v) => sum + v.count, 0)
  const isMultiLabelParent = metric.is_multi_label_parent === true

  // Render mode: numeric histogram, categorical pie/bar, or empty state.
  // Numeric metrics always render as a histogram (richer than counts).
  // Categorical pies are capped to a low-cardinality threshold (<=8) so
  // they stay readable — beyond that we always fall back to bars.
  // Multi-label parents NEVER render as pie because their slices
  // wouldn't sum to 100% (each row votes for >=1 label) — a pie would
  // misleadingly suggest exclusive proportions.
  const wideCategorical = valueCounts.length > 8
  const usePieForCategorical =
    categoricalChartType === 'pie' && !wideCategorical && !isMultiLabelParent
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
  } else if (valueCounts.length && usePieForCategorical) {
    chart = (
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
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
    // Vertical bar chart when ``categoricalChartType === 'bar'`` and
    // the category list is short; otherwise horizontal so long labels
    // (e.g. "Failed to extract") don't get truncated on the X axis.
    // Multi-label parents are forced horizontal regardless of the
    // toggle because their child labels are typically multi-word
    // sentences ("Pitch done with data (personalized growth)") that
    // would never fit on a vertical axis.
    const useVertical =
      !isMultiLabelParent &&
      categoricalChartType === 'bar' &&
      valueCounts.length <= 6
    chart = useVertical ? (
      <ResponsiveContainer width="100%" height={220}>
        <BarChart
          data={valueCounts}
          margin={{ top: 4, right: 8, left: -16, bottom: 4 }}
        >
          <defs>
            <linearGradient id={`bar-cat-v-${metric.metric_id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#10b981" stopOpacity={0.95} />
              <stop offset="100%" stopColor="#10b981" stopOpacity={0.55} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 11, fill: '#334155' }}
            axisLine={{ stroke: '#e2e8f0' }}
            tickLine={false}
            interval={0}
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
            cursor={{ fill: 'rgba(16,185,129,0.08)' }}
            formatter={(value: any) => [`${value} rows`, 'Count']}
          />
          <Bar
            dataKey="count"
            fill={`url(#bar-cat-v-${metric.metric_id})`}
            radius={[6, 6, 0, 0]}
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
    ) : (
      // Horizontal bar layout for wide categorical / multi-label
      // metrics. Each row gets ~36px of vertical space (single-line
      // label + breathing room) so the recharts auto-wrapped ticks
      // never collide with the next row's label. The y-axis is wide
      // enough (180px) for typical multi-word labels; anything
      // longer is truncated with an ellipsis at ~28 chars and the
      // tooltip surfaces the full text on hover.
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
            width={180}
            interval={0}
            tickFormatter={(value: string) =>
              typeof value === 'string' && value.length > 28
                ? `${value.slice(0, 27)}…`
                : value
            }
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

  const generateMutation = useMutation({
    mutationFn: (regenerate: boolean) =>
      apiClient.generateCallImportEvaluationInsights(
        callImportId,
        evaluationId,
        {
          regenerate,
          provider: pickerProvider || undefined,
          model: pickerModel || undefined,
        },
      ),
    onSuccess: (summary) => {
      queryClient.setQueryData(
        ['call-import-evaluation-insights', callImportId, evaluationId],
        summary,
      )
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
              Get an AI-written summary of patterns across these calls
            </p>
            <p className="text-[11px] text-gray-500 leading-snug">
              We feed the per-metric numbers + a sample of rationales
              to an LLM and surface the cross-call patterns it finds.
            </p>
          </div>
        </div>
        <div className="mt-2 mb-3">
          <AIProviderModelPicker
            provider={pickerProvider}
            model={pickerModel}
            onProviderChange={setPickerProvider}
            onModelChange={setPickerModel}
            disabled={isPending}
            size="sm"
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
        {cached.narrative}
      </p>

      {cached.patterns.length > 0 && (
        <ul className="mt-2 space-y-1">
          {cached.patterns.map((pattern, i) => (
            <li
              key={`${i}-${pattern.slice(0, 24)}`}
              className="flex items-start gap-2 text-[11px] text-gray-700 leading-snug"
            >
              <span
                className="mt-1 h-1.5 w-1.5 rounded-full bg-primary-400 shrink-0"
                aria-hidden="true"
              />
              <span className="min-w-0">{pattern}</span>
            </li>
          ))}
        </ul>
      )}

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
        <div className="mt-3 rounded-md border border-gray-200 bg-gray-50 p-2.5">
          <AIProviderModelPicker
            provider={pickerProvider}
            model={pickerModel}
            onProviderChange={setPickerProvider}
            onModelChange={setPickerModel}
            disabled={isPending}
            size="sm"
          />
          <div className="mt-2 flex items-center justify-end gap-2">
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

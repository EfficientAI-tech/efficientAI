import { Fragment, useState, useEffect, useMemo, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'
import { useWorkspaceStore } from '../../store/workspaceStore'
import {
  Edit,
  Trash2,
  X,
  ToggleLeft,
  ToggleRight,
  Brain,
  RefreshCw,
  AudioWaveform,
  Sparkles,
  Plus,
  MoreVertical,
  ChevronRight,
  ChevronDown,
  ChevronLeft,
  Layers,
  AlertTriangle,
  FileText,
  Database,
} from 'lucide-react'

interface Metric {
  id: string
  name: string
  description?: string
  metric_type: 'number' | 'boolean' | 'rating' | 'text'
  metric_origin: 'default' | 'custom'
  supported_surfaces: Array<'agent' | 'voice_playground' | 'blind_test'>
  enabled_surfaces: Array<'agent' | 'voice_playground' | 'blind_test'>
  custom_data_type?: 'boolean' | 'enum' | 'number_range' | null
  custom_config?: Record<string, any> | null
  tags?: string[] | null
  capture_rationale?: boolean
  trigger: 'always'
  enabled: boolean
  is_default: boolean
  created_at: string
  updated_at: string
  parent_metric_id?: string | null
  selection_mode?: 'single_choice' | 'multi_label' | null
  allow_discovery?: boolean
  /**
   * CSV header names this metric reads from a call import row's
   * ``raw_columns`` instead of the transcript. Empty / missing means
   * today's transcript-based judge behavior. Children of a parent
   * category metric never carry this list (server enforces it).
   */
  input_columns?: string[]
  /**
   * When true, this metric is a "transcript-compare judge": at
   * call-import evaluation time the worker feeds BOTH the production
   * and diarised transcripts to the LLM as a labeled pair and the
   * run's transcript_source toggle is ignored for this metric.
   * Mutually exclusive with input_columns, parent_metric_id, and
   * selection_mode (server enforces).
   */
  compare_transcripts?: boolean
  children?: Metric[]
}

type MetricSurface = 'agent' | 'voice_playground' | 'blind_test'
type CustomDataType = 'boolean' | 'enum' | 'number_range'

// Quantitative: Raw acoustic measurements (Parselmouth - signal processing)
// These are pure physical/mathematical measurements of the audio signal
const ACOUSTIC_METRICS = new Set(['Pitch Variance', 'Jitter', 'Shimmer', 'HNR'])

// Qualitative: AI Voice metrics (ML models - human perception, emotion, quality)
// These measure subjective qualities like human-likeness, emotion, expressiveness
const AI_VOICE_METRICS = new Set([
  'MOS Score',           // Mean Opinion Score (1.0-5.0) - Human-likeness perception
  'Emotion Category',     // Categorical emotion (angry, happy, etc.)
  'Emotion Confidence',   // Confidence of emotion prediction
  'Valence',             // Emotional positivity (-1.0 to 1.0)
  'Arousal',             // Emotional intensity (0.0 to 1.0)
  'Speaker Consistency',  // Voice identity stability (0.0-1.0)
  'Prosody Score',       // Expressiveness/Drama (0.0-1.0)
])

// All audio-based metrics (calculated from audio file, not from text)
const AUDIO_METRICS = new Set([...ACOUSTIC_METRICS, ...AI_VOICE_METRICS])

// Deprecated default metrics that can be deleted
const DEPRECATED_METRICS = new Set(['Response Time', 'Customer Satisfaction'])

const isAudioMetric = (metricName: string): boolean => AUDIO_METRICS.has(metricName)
const isDeprecatedMetric = (metricName: string): boolean => DEPRECATED_METRICS.has(metricName)
const isAIVoiceMetric = (metricName: string): boolean => AI_VOICE_METRICS.has(metricName)

// Quantitative = raw physical measurements (acoustic signal analysis)
// Qualitative = quality assessments (human perception, emotion, LLM evaluation)
const isQuantitativeMetric = (metricName: string): boolean => ACOUSTIC_METRICS.has(metricName)

const ALL_SURFACES: MetricSurface[] = ['agent', 'voice_playground', 'blind_test']

const SURFACE_LABELS: Record<MetricSurface, string> = {
  agent: 'Agent',
  voice_playground: 'Voice Playground',
  blind_test: 'Blind Test',
}

// Shared "modernized" form-control styling used across the Create /
// Edit Metric modal. Lighter border, larger padding, smooth focus
// transition, translucent ring — applied uniformly to text inputs,
// selects, and textareas so the modal feels like one consistent form
// rather than a collection of differently-aged widgets.
const MODERN_INPUT_CLASS =
  'w-full rounded-lg border border-gray-200 bg-white px-3.5 py-2.5 text-sm text-gray-900 placeholder-gray-400 shadow-sm transition focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20 disabled:bg-gray-50 disabled:text-gray-500'
const MODERN_INPUT_SM_CLASS =
  'w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 shadow-sm transition focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20 disabled:bg-gray-50 disabled:text-gray-500'

export default function MetricsManagement() {
  const queryClient = useQueryClient()
  // Adding the active workspace id to every metrics queryKey so a
  // workspace switch produces a clean cache miss instead of showing
  // the previously-loaded metric library.
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const { showToast, ToastContainer } = useToast()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [isCustomMetricMode, setIsCustomMetricMode] = useState(false)
  const [showEnableModal, setShowEnableModal] = useState(false)
  // The unified "Create Metric" modal hosts two flows — pick the
  // active one with these tabs. Default is 'single' (the legacy
  // single-metric experience); 'category' opens the parent + sub-labels
  // builder.
  type CreateMode = 'single' | 'category'
  const [createMode, setCreateMode] = useState<CreateMode>('single')
  const [categoryForm, setCategoryForm] = useState<{
    name: string
    description: string
    selection_mode: 'single_choice' | 'multi_label'
    allow_discovery: boolean
    surfaces: MetricSurface[]
    children: Array<{
      local_id: string
      name: string
      description: string
      capture_rationale: boolean
    }>
  }>({
    name: '',
    description: '',
    selection_mode: 'single_choice',
    allow_discovery: false,
    surfaces: ['agent'],
    children: [
      { local_id: 'c1', name: '', description: '', capture_rationale: true },
      { local_id: 'c2', name: '', description: '', capture_rationale: true },
    ],
  })
  // Track which parent metric ids are EXPANDED in the metrics list.
  // Default is empty → every parent is collapsed on first paint so the
  // category list reads as a tidy summary; users click the chevron on
  // a parent row to drill in.
  const [expandedParents, setExpandedParents] = useState<Set<string>>(
    new Set(),
  )
  const toggleParentExpanded = (parentId: string) => {
    setExpandedParents((prev) => {
      const next = new Set(prev)
      if (next.has(parentId)) next.delete(parentId)
      else next.add(parentId)
      return next
    })
  }
  // ---------------------------------------------------------------------------
  // Manage Metric modal — a per-row contextual sheet that hosts Edit /
  // Enable / Delete. We pulled these affordances out of the row to keep
  // the table scan-friendly; the modal is opened either by clicking the
  // row body OR the kebab button (both routes set ``manageMetric``).
  // ---------------------------------------------------------------------------
  const [manageMetric, setManageMetric] = useState<Metric | null>(null)
  // Inline confirmation step inside the Manage modal so we don't fall
  // back on the native browser ``confirm()`` dialog (jarring, unstyled,
  // and easy to dismiss). The confirmed-delete handler reads from this
  // and clears it once the mutation kicks off.
  const [pendingDeleteMetric, setPendingDeleteMetric] = useState<Metric | null>(
    null,
  )
  // ---------------------------------------------------------------------------
  // Edit-category form — only used when editing an existing PARENT
  // (``selection_mode`` set, no ``parent_metric_id``). Reuses the
  // create-category modal layout but tracks each child's existing
  // ``server_id`` (``null`` for newly-added drafts) and a list of
  // ``deleted_ids`` so the save handler can fan out the right mix of
  // PUT / POST / DELETE calls against the metrics API.
  // ---------------------------------------------------------------------------
  type EditCategoryChild = {
    local_id: string
    server_id: string | null
    name: string
    description: string
    capture_rationale: boolean
    enabled: boolean
  }
  const [editCategoryForm, setEditCategoryForm] = useState<{
    name: string
    description: string
    selection_mode: 'single_choice' | 'multi_label'
    allow_discovery: boolean
    surfaces: MetricSurface[]
    children: EditCategoryChild[]
    deleted_child_ids: string[]
  }>({
    name: '',
    description: '',
    selection_mode: 'multi_label',
    allow_discovery: false,
    surfaces: ['agent'],
    children: [],
    deleted_child_ids: [],
  })
  // Distinguishes the "edit parent category" flow from the legacy
  // single-row edit flow inside the same modal. When this is true the
  // modal renders the category editor instead of the flat form, even
  // though ``editingMetric`` is also set.
  const [isEditingCategory, setIsEditingCategory] = useState(false)
  const [showAIAssist, setShowAIAssist] = useState(false)
  const [aiMode, setAIMode] = useState<'description' | 'examples'>('description')
  const [aiDescription, setAIDescription] = useState('')
  const [aiExamples, setAIExamples] = useState<Array<{ transcript: string; rating: string; notes: string }>>([
    { transcript: '', rating: '', notes: '' },
  ])
  const [surfaceFilter, setSurfaceFilter] = useState<'all' | MetricSurface>('all')
  const [editingMetric, setEditingMetric] = useState<Metric | null>(null)
  const [sortField, setSortField] = useState<'type' | 'method'>('type')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')
  const [selectedDisabledMetricIds, setSelectedDisabledMetricIds] = useState<Set<string>>(new Set())
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    metric_type: 'rating' as 'number' | 'boolean' | 'rating' | 'text',
    metric_origin: 'custom' as 'default' | 'custom',
    supported_surfaces: ['agent'] as MetricSurface[],
    enabled_surfaces: ['agent'] as MetricSurface[],
    // ``custom_data_type`` must match ``metric_type`` so the unified
    // "Type" dropdown and the sub-config renderer agree on first
    // paint. ``rating`` ↔ ``enum`` is the default because that is what
    // the unified select shows out of the box.
    custom_data_type: 'enum' as CustomDataType,
    enum_options_csv: '',
    number_min: 0,
    number_max: 10,
    number_step: 1,
    tags_csv: '',
    trigger: 'always' as 'always',
    enabled: true,
    capture_rationale: false,
    // Only surfaced in the edit form for parent metrics with
    // ``selection_mode === 'multi_label'``. Backend rejects setting
    // true on anything else, so leaving it false everywhere else is
    // the safe default.
    allow_discovery: false,
    // CSV header names this metric reads from a call import row's
    // ``raw_columns`` instead of the transcript. Empty array (the
    // default) preserves today's transcript-based judge behavior.
    input_columns: [] as string[],
    // When true, the worker scores this metric against BOTH the
    // production and diarised transcripts on each call-import row.
    // Mutually exclusive with ``input_columns`` and unavailable on
    // parent / child metrics. The Run Evaluation transcript_source
    // toggle is ignored for these metrics — they always read both.
    compare_transcripts: false,
  })
  // Draft string for the "Input columns" tag input — kept outside
  // ``formData`` so a half-typed header doesn't get persisted on Save.
  const [inputColumnDraft, setInputColumnDraft] = useState('')
  // UI-only toggle that gates the "Call Imports" sub-section of the
  // metric editor. Both ``input_columns`` (column-input judge) and
  // ``compare_transcripts`` (transcript-compare judge) only make sense
  // for metrics that score CSV-imported call rows, so we hide them
  // behind a single header check to keep the form scan-friendly for
  // people authoring plain live-call metrics. The state is purely
  // visual: when the user toggles it off we clear both underlying
  // fields so the saved metric matches what the user sees.
  const [isForCallImports, setIsForCallImports] = useState(false)
  // Visibility of the "Browse imported columns" popover that hangs
  // under the input. Toggled by the picker button and by click-outside
  // on the wrapping container.
  const [columnPickerOpen, setColumnPickerOpen] = useState(false)
  // Which call import the user is currently looking at inside the
  // popover. ``null`` means the popover shows the import list view;
  // a string id means we're showing that import's column groupings.
  const [columnPickerImportId, setColumnPickerImportId] = useState<
    string | null
  >(null)
  const columnPickerRef = useRef<HTMLDivElement | null>(null)

  const { data: metrics = [], isLoading } = useQuery({
    queryKey: ['metrics', activeWorkspaceId, surfaceFilter],
    queryFn: () => apiClient.listMetrics(surfaceFilter === 'all' ? undefined : surfaceFilter),
  })

  // Recent call imports for the active workspace — the user picks
  // input columns by drilling into a specific batch instead of
  // browsing a workspace-wide flat list. We pull a generous page so a
  // typical workspace's recent imports all fit without pagination
  // complexity inside the popover.
  const { data: recentImportsResponse } = useQuery({
    queryKey: ['call-imports-for-metric-picker', activeWorkspaceId],
    queryFn: () => apiClient.listCallImports({ page: 1, page_size: 50 }),
    staleTime: 60_000,
  })
  const recentImports = recentImportsResponse?.items ?? []

  // Seed default metrics on first load if none exist
  const seedMutation = useMutation({
    mutationFn: () => apiClient.seedDefaultMetrics(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      if (data && data.length > 0) {
        showToast(`Added ${data.length} new default metric${data.length > 1 ? 's' : ''}`, 'success')
      } else {
        showToast('All default metrics already exist', 'success')
      }
    },
    onError: () => {
      showToast('Failed to sync default metrics', 'error')
    },
  })

  useEffect(() => {
    if (metrics.length === 0 && !isLoading) {
      seedMutation.mutate()
    }
  }, [metrics.length, isLoading])

  // Close the "Browse imported columns" popover when the user clicks
  // anywhere outside the picker container. We attach the listener only
  // while the popover is open so it doesn't add overhead to every
  // page render.
  useEffect(() => {
    if (!columnPickerOpen) return
    const handlePointerDown = (event: MouseEvent | TouchEvent) => {
      const target = event.target as Node | null
      if (
        columnPickerRef.current &&
        target &&
        !columnPickerRef.current.contains(target)
      ) {
        setColumnPickerOpen(false)
        // Reset the drill-in state so reopening starts fresh on the
        // import list rather than the last-viewed import's columns.
        setColumnPickerImportId(null)
      }
    }
    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('touchstart', handlePointerDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('touchstart', handlePointerDown)
    }
  }, [columnPickerOpen])

  // When another page navigates here with `state.prefillInputColumns`
  // (e.g. the "Create metric from columns…" action on the call import
  // detail page), auto-open the single-metric create modal with the
  // headers pre-populated. We then clear the state so a refresh / nav
  // back doesn't keep re-triggering the modal.
  const location = useLocation()
  const navigate = useNavigate()
  useEffect(() => {
    const state = (location.state || {}) as {
      prefillInputColumns?: string[]
    }
    const headers = Array.isArray(state.prefillInputColumns)
      ? state.prefillInputColumns
          .map((h) => String(h || '').trim())
          .filter(Boolean)
      : []
    if (headers.length === 0) return
    setIsCustomMetricMode(true)
    setEditingMetric(null)
    setCreateMode('single')
    setFormData({
      name: '',
      description: '',
      metric_origin: 'custom',
      metric_type: 'rating',
      custom_data_type: 'enum',
      enum_options_csv: '',
      number_min: 0,
      number_max: 10,
      number_step: 1,
      tags_csv: '',
      supported_surfaces: ['agent'],
      enabled_surfaces: ['agent'],
      trigger: 'always',
      enabled: true,
      capture_rationale: false,
      allow_discovery: false,
      input_columns: Array.from(new Set(headers)),
      // Pre-seeded column-input judge from a CSV import — compare-
      // transcripts is mutually exclusive so it stays off here.
      compare_transcripts: false,
    })
    setInputColumnDraft('')
    // The user arrived here from a CSV import's "Create metric" CTA,
    // so the Call Imports sub-section is the whole point — keep it
    // expanded on first paint.
    setIsForCallImports(true)
    setShowCreateModal(true)
    navigate(location.pathname, { replace: true, state: null })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state])

  const createMutation = useMutation({
    mutationFn: (data: typeof formData) => apiClient.createMetric(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      setShowCreateModal(false)
      resetForm()
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<typeof formData> }) =>
      apiClient.updateMetric(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      setEditingMetric(null)
      resetForm()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteMetric(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
    },
  })

  const toggleEnabledMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      apiClient.updateMetric(id, { enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
    },
  })

  const enableMetricsMutation = useMutation({
    mutationFn: async (metricIds: string[]) =>
      Promise.all(metricIds.map((metricId) => apiClient.updateMetric(metricId, { enabled: true }))),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      const count = selectedDisabledMetricIds.size
      setSelectedDisabledMetricIds(new Set())
      setShowEnableModal(false)
      showToast(`Enabled ${count} metric${count > 1 ? 's' : ''}`, 'success')
    },
    onError: () => {
      showToast('Failed to enable selected metrics', 'error')
    },
  })

  const toggleSurfaceMutation = useMutation({
    mutationFn: ({ id, enabled_surfaces }: { id: string; enabled_surfaces: MetricSurface[] }) =>
      apiClient.updateMetric(id, { enabled_surfaces }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
    },
    onError: () => {
      showToast('Failed to update surface', 'error')
    },
  })

  const createCategoryMutation = useMutation({
    mutationFn: (payload: {
      name: string
      description?: string | null
      selection_mode: 'single_choice' | 'multi_label'
      allow_discovery?: boolean
      supported_surfaces: string[]
      enabled_surfaces: string[]
      children: Array<{
        name: string
        description?: string | null
        capture_rationale?: boolean
        enabled?: boolean
      }>
    }) => apiClient.createMetricWithChildren(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      closeModal()
      showToast('Category metric created', 'success')
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail || 'Failed to create category metric'
      showToast(detail, 'error')
    },
  })

  // Update an existing parent + reconcile its children. The metrics
  // API has no atomic "update with children" endpoint, so we fan out:
  //   1. PUT  /metrics/{parent}   — parent-level fields
  //   2. PUT  /metrics/{child}    — for each existing child the user
  //                                 touched (name/description/rationale/enabled)
  //   3. POST /metrics/{parent}/children — for newly added child drafts
  //   4. DELETE /metrics/{child} — for children the user removed
  // We deliberately run them in parallel after the parent PUT to keep
  // wall-clock latency reasonable; the metrics list is invalidated
  // once at the end so the table re-fetches with the final state.
  // selection_mode is intentionally NOT included in the parent PUT
  // because the edit form locks it (per user choice) — flipping it on
  // a parent with completed evaluations corrupts stored selections.
  const updateCategoryMutation = useMutation({
    mutationFn: async ({
      parentId,
      parent,
      childrenToUpdate,
      childrenToCreate,
      childIdsToDelete,
    }: {
      parentId: string
      parent: {
        name: string
        description?: string | null
        allow_discovery: boolean
        supported_surfaces: string[]
        enabled_surfaces: string[]
      }
      childrenToUpdate: Array<{
        id: string
        name: string
        description?: string | null
        capture_rationale: boolean
        enabled: boolean
      }>
      childrenToCreate: Array<{
        name: string
        description?: string | null
        capture_rationale: boolean
        enabled: boolean
      }>
      childIdsToDelete: string[]
    }) => {
      await apiClient.updateMetric(parentId, parent as any)
      const tasks: Promise<any>[] = []
      for (const child of childrenToUpdate) {
        tasks.push(
          apiClient.updateMetric(child.id, {
            name: child.name,
            description: child.description ?? undefined,
            capture_rationale: child.capture_rationale,
            enabled: child.enabled,
          } as any),
        )
      }
      for (const child of childrenToCreate) {
        tasks.push(
          apiClient.addMetricChild(parentId, {
            name: child.name,
            description: child.description ?? undefined,
            capture_rationale: child.capture_rationale,
            enabled: child.enabled,
          }),
        )
      }
      for (const childId of childIdsToDelete) {
        tasks.push(apiClient.deleteMetric(childId))
      }
      const settled = await Promise.allSettled(tasks)
      const failures = settled.filter((r) => r.status === 'rejected')
      if (failures.length > 0) {
        // Surface the first error so the user has something actionable
        // — the rest get logged. The parent PUT already succeeded by
        // this point, so partial failures end up with the parent
        // updated and some children out of sync; the list refetch will
        // reflect the actual server state.
        const first = failures[0] as PromiseRejectedResult
        const detail =
          first.reason?.response?.data?.detail ||
          first.reason?.message ||
          'Some child updates failed'
        throw new Error(String(detail))
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      closeModal()
      showToast('Category updated', 'success')
    },
    onError: (err: any) => {
      const detail =
        err?.response?.data?.detail || err?.message || 'Failed to update category'
      showToast(detail, 'error')
    },
  })

  const generateMetricMutation = useMutation({
    mutationFn: (payload: {
      mode: 'description' | 'examples'
      surface: MetricSurface
      description?: string
      examples?: Array<{ transcript: string; rating: any; notes?: string }>
    }) => apiClient.generateMetric(payload),
    onSuccess: (suggestion) => {
      const cfg = suggestion.custom_config || {}
      const fallbackSurface: MetricSurface = formData.supported_surfaces[0] || 'agent'
      const isText = suggestion.metric_type === 'text'
      // For text metrics there is no custom_data_type / custom_config; we
      // keep the previous form value for those fields purely so the user
      // can flip the type back without losing what they had typed (the
      // payload builder will strip them on submit anyway).
      const inferredCustomDataType: CustomDataType = isText
        ? formData.custom_data_type
        : (suggestion.custom_data_type as CustomDataType) ||
          (suggestion.metric_type === 'boolean'
            ? 'boolean'
            : suggestion.metric_type === 'number'
              ? 'number_range'
              : 'enum')
      setFormData((prev) => ({
        ...prev,
        name: suggestion.name,
        description: suggestion.description,
        metric_type: suggestion.metric_type,
        metric_origin: 'custom',
        supported_surfaces:
          (suggestion.supported_surfaces as MetricSurface[]) || [fallbackSurface],
        enabled_surfaces:
          (suggestion.enabled_surfaces as MetricSurface[]) || [fallbackSurface],
        custom_data_type: inferredCustomDataType,
        enum_options_csv:
          !isText && Array.isArray(cfg.options) ? cfg.options.join(', ') : prev.enum_options_csv,
        number_min: !isText ? Number(cfg.min ?? prev.number_min) : prev.number_min,
        number_max: !isText ? Number(cfg.max ?? prev.number_max) : prev.number_max,
        number_step: !isText ? Number(cfg.step ?? prev.number_step) : prev.number_step,
        tags_csv: (suggestion.suggested_tags || []).join(', '),
        trigger: 'always',
        enabled: true,
      }))
      showToast(
        isText
          ? 'AI suggestion applied - a Text (LLM summary) metric'
          : 'AI suggestion applied - review and save',
        'success',
      )
    },
    onError: () => {
      showToast('Failed to generate metric with AI', 'error')
    },
  })

  const resetCategoryForm = () => {
    setCategoryForm({
      name: '',
      description: '',
      selection_mode: 'single_choice',
      allow_discovery: false,
      surfaces: ['agent'],
      children: [
        { local_id: 'c1', name: '', description: '', capture_rationale: true },
        { local_id: 'c2', name: '', description: '', capture_rationale: true },
      ],
    })
  }

  const handleToggleSurface = (metric: Metric, surface: MetricSurface) => {
    const current = new Set<MetricSurface>(metric.enabled_surfaces || [])
    if (current.has(surface)) {
      current.delete(surface)
    } else {
      current.add(surface)
    }
    const next = Array.from(current).filter((s) =>
      (metric.supported_surfaces || []).includes(s),
    )
    toggleSurfaceMutation.mutate({ id: metric.id, enabled_surfaces: next })
  }

  const resetAIForm = () => {
    setShowAIAssist(false)
    setAIMode('description')
    setAIDescription('')
    setAIExamples([{ transcript: '', rating: '', notes: '' }])
  }

  const handleGenerateAIMetric = () => {
    const surface: MetricSurface = formData.supported_surfaces[0] || 'agent'
    if (aiMode === 'description') {
      if (!aiDescription.trim()) {
        showToast('Please enter a description', 'error')
        return
      }
      generateMetricMutation.mutate({
        mode: 'description',
        surface,
        description: aiDescription.trim(),
      })
    } else {
      const validExamples = aiExamples
        .map((ex) => ({ transcript: ex.transcript.trim(), rating: ex.rating.trim(), notes: ex.notes.trim() }))
        .filter((ex) => ex.transcript && ex.rating)
      if (validExamples.length === 0) {
        showToast('Please add at least one example with transcript and rating', 'error')
        return
      }
      generateMetricMutation.mutate({
        mode: 'examples',
        surface,
        examples: validExamples.map((ex) => ({
          transcript: ex.transcript,
          rating: ex.rating,
          notes: ex.notes || undefined,
        })),
      })
    }
  }

  const resetForm = () => {
    setFormData({
      name: '',
      description: '',
      metric_type: 'rating',
      metric_origin: 'custom',
      supported_surfaces: ['agent'],
      enabled_surfaces: ['agent'],
      custom_data_type: 'enum',
      enum_options_csv: '',
      number_min: 0,
      number_max: 10,
      number_step: 1,
      tags_csv: '',
      trigger: 'always',
      enabled: true,
      capture_rationale: false,
      allow_discovery: false,
      input_columns: [],
      compare_transcripts: false,
    })
    setInputColumnDraft('')
    setIsForCallImports(false)
  }

  const getCustomConfigFromForm = () => {
    if (formData.custom_data_type === 'enum') {
      const options = formData.enum_options_csv
        .split(',')
        .map((opt) => opt.trim())
        .filter(Boolean)
      return { options }
    }
    if (formData.custom_data_type === 'number_range') {
      return {
        min: Number(formData.number_min),
        max: Number(formData.number_max),
        step: Number(formData.number_step),
      }
    }
    return {}
  }

  const buildPayload = () => {
    const tags = formData.tags_csv
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean)
    // Text metrics are unstructured by definition, so we never persist a
    // ``custom_data_type``/``custom_config`` for them even when the modal was
    // opened in "custom" mode. This keeps the backend's LLM prompt branch
    // clean (no stale enum/number_range hints attached to text metrics).
    const useCustomConfig =
      formData.metric_origin === 'custom' && formData.metric_type !== 'text'
    // ``allow_discovery`` is valid on any parent (single_choice or
    // multi_label) but is meaningless on standalone or child metrics.
    // We only forward the field when editing an actual parent metric
    // so the server-side value on non-parents stays untouched.
    const isParentBeingEdited =
      !!editingMetric &&
      !!editingMetric.selection_mode &&
      !editingMetric.parent_metric_id
    return {
      name: formData.name,
      description: formData.description,
      metric_type: formData.metric_type,
      trigger: formData.trigger,
      enabled: formData.enabled,
      metric_origin: formData.metric_origin,
      supported_surfaces: formData.supported_surfaces,
      enabled_surfaces: formData.enabled ? formData.enabled_surfaces : [],
      custom_data_type: useCustomConfig ? formData.custom_data_type : undefined,
      custom_config: useCustomConfig ? getCustomConfigFromForm() : undefined,
      tags: tags.length > 0 ? tags : undefined,
      // Capture LLM rationale only makes sense for LLM-judged metrics
      // (i.e. anything that isn't a free-form text summary). The CSV
      // exporter and worker both no-op when the flag is false.
      capture_rationale:
        formData.metric_type !== 'text' ? formData.capture_rationale : false,
      ...(isParentBeingEdited
        ? { allow_discovery: !!formData.allow_discovery }
        : {}),
      // Backend rejects ``input_columns`` on child sub-metrics with
      // a 400. Children have no parent_metric_id at create time
      // (only set explicitly elsewhere), so the only way the field
      // can leak there is via edit — gate on the row's
      // ``parent_metric_id`` to be safe.
      ...((!editingMetric || !editingMetric.parent_metric_id)
        ? { input_columns: formData.input_columns }
        : {}),
      // Transcript-compare judge metrics live alongside column-input
      // judges and standalone transcript metrics. The server rejects
      // the flag on child sub-metrics and parents (selection_mode
      // set), so we only forward it for standalone rows where the
      // toggle could legitimately be on. ``buildPayload`` is also
      // used by the create flow (no editingMetric yet) — there the
      // flag is always forwarded since the body is a fresh row.
      ...((!editingMetric
        || (!editingMetric.parent_metric_id
          && !editingMetric.selection_mode))
        ? { compare_transcripts: !!formData.compare_transcripts }
        : {}),
    }
  }

  const handleCreate = () => {
    if (!formData.name.trim()) {
      alert('Please enter a metric name')
      return
    }
    createMutation.mutate(buildPayload() as any)
  }

  // Opens the per-row "Manage" modal. The modal is the entrypoint for
  // both Edit and Delete now that we've removed those buttons from the
  // table row itself.
  const handleManage = (metric: Metric) => {
    setManageMetric(metric)
    setPendingDeleteMetric(null)
  }

  const handleEdit = (metric: Metric) => {
    // A parent category metric: switch to the dedicated category
    // editor (children appear as editable rows inside the form).
    // Standalone metrics + children still fall into the flat editor
    // they used before.
    const isParent =
      !!metric.selection_mode && !metric.parent_metric_id
    if (isParent) {
      handleEditCategory(metric)
      return
    }
    setEditingMetric(metric)
    setIsEditingCategory(false)
    setFormData({
      name: metric.name,
      description: metric.description || '',
      metric_type: metric.metric_type,
      metric_origin: metric.metric_origin || 'custom',
      supported_surfaces: (metric.supported_surfaces?.length ? metric.supported_surfaces : ['agent']) as MetricSurface[],
      enabled_surfaces: (metric.enabled_surfaces?.length ? metric.enabled_surfaces : ['agent']) as MetricSurface[],
      // If the stored row has no ``custom_data_type`` (older default
      // metrics, edge migrations, etc.), derive a value from
      // ``metric_type`` so the unified Type dropdown and the
      // sub-config renderer stay aligned on the very first paint.
      custom_data_type: (metric.custom_data_type ||
        (metric.metric_type === 'rating'
          ? 'enum'
          : metric.metric_type === 'number'
            ? 'number_range'
            : 'boolean')) as CustomDataType,
      enum_options_csv: Array.isArray(metric.custom_config?.options) ? metric.custom_config.options.join(', ') : '',
      number_min: Number(metric.custom_config?.min ?? 0),
      number_max: Number(metric.custom_config?.max ?? 10),
      number_step: Number(metric.custom_config?.step ?? 1),
      tags_csv: metric.tags?.join(', ') || '',
      trigger: metric.trigger,
      enabled: metric.enabled,
      capture_rationale: !!metric.capture_rationale,
      allow_discovery: !!metric.allow_discovery,
      input_columns: Array.isArray(metric.input_columns)
        ? [...metric.input_columns]
        : [],
      compare_transcripts: !!metric.compare_transcripts,
    })
    setInputColumnDraft('')
    // The Call Imports sub-section auto-expands when the metric we're
    // opening has either call-import-specific knob configured —
    // otherwise it stays collapsed so the form reads as a plain
    // live-call metric editor by default.
    setIsForCallImports(
      (Array.isArray(metric.input_columns) && metric.input_columns.length > 0)
        || !!metric.compare_transcripts,
    )
    setIsCustomMetricMode(metric.metric_origin === 'custom')
    setShowCreateModal(true)
  }

  // Seed the edit-category form from a parent + its existing children
  // and open the modal in category-edit mode. Each child gets a stable
  // ``local_id`` (for React keys) and remembers its ``server_id`` so
  // the save handler can tell new drafts (server_id === null) apart
  // from updates.
  const handleEditCategory = (parent: Metric) => {
    setEditingMetric(parent)
    setIsEditingCategory(true)
    const existingChildren: EditCategoryChild[] = (parent.children || []).map(
      (child) => ({
        local_id: `srv-${child.id}`,
        server_id: child.id,
        name: child.name,
        description: child.description || '',
        capture_rationale: !!child.capture_rationale,
        enabled: child.enabled,
      }),
    )
    setEditCategoryForm({
      name: parent.name,
      description: parent.description || '',
      selection_mode:
        (parent.selection_mode as 'single_choice' | 'multi_label') ||
        'multi_label',
      allow_discovery: !!parent.allow_discovery,
      surfaces: (parent.supported_surfaces?.length
        ? parent.supported_surfaces
        : ['agent']) as MetricSurface[],
      children: existingChildren,
      deleted_child_ids: [],
    })
    setShowCreateModal(true)
  }

  const handleUpdate = () => {
    if (!editingMetric) return
    if (!formData.name.trim()) {
      alert('Please enter a metric name')
      return
    }
    updateMutation.mutate({ id: editingMetric.id, data: buildPayload() as any })
  }

  // Build the fan-out payload from ``editCategoryForm`` and submit it
  // through ``updateCategoryMutation``. Children with an empty name
  // are silently dropped (matches the create-category form rule of
  // "must have a name to count"). The mutation handler enforces the
  // "at least 2 named children" invariant before sending anything.
  const handleUpdateCategory = () => {
    if (!editingMetric) return
    if (!editCategoryForm.name.trim()) {
      alert('Please enter a category name')
      return
    }
    const namedChildren = editCategoryForm.children.filter((c) =>
      c.name.trim(),
    )
    if (namedChildren.length < 2) {
      alert('A category needs at least 2 named sub-labels')
      return
    }
    const childrenToUpdate = namedChildren
      .filter((c) => !!c.server_id)
      .map((c) => ({
        id: c.server_id as string,
        name: c.name.trim(),
        description: c.description.trim() || null,
        capture_rationale: c.capture_rationale,
        enabled: c.enabled,
      }))
    const childrenToCreate = namedChildren
      .filter((c) => !c.server_id)
      .map((c) => ({
        name: c.name.trim(),
        description: c.description.trim() || null,
        capture_rationale: c.capture_rationale,
        enabled: c.enabled,
      }))
    updateCategoryMutation.mutate({
      parentId: editingMetric.id,
      parent: {
        name: editCategoryForm.name.trim(),
        description: editCategoryForm.description.trim() || null,
        allow_discovery: editCategoryForm.allow_discovery,
        supported_surfaces: editCategoryForm.surfaces,
        enabled_surfaces: editCategoryForm.surfaces,
      },
      childrenToUpdate,
      childrenToCreate,
      childIdsToDelete: editCategoryForm.deleted_child_ids,
    })
  }

  const handleToggleEnabled = (metric: Metric) => {
    toggleEnabledMutation.mutate({ id: metric.id, enabled: !metric.enabled })
  }

  // Now that there is no per-row Delete button, this is invoked
  // exclusively from the Manage modal's confirmation step. We still
  // hard-block deleting non-deprecated default metrics — the server
  // would reject the request anyway, but the early return keeps the
  // confirmation modal honest. Successful delete also dismisses the
  // Manage modal because the metric no longer exists.
  const handleConfirmDelete = (metric: Metric) => {
    if (metric.is_default && !isDeprecatedMetric(metric.name)) {
      alert('Cannot delete default metrics')
      setPendingDeleteMetric(null)
      return
    }
    deleteMutation.mutate(metric.id, {
      onSuccess: () => {
        setPendingDeleteMetric(null)
        setManageMetric(null)
      },
    })
  }

  const closeModal = () => {
    setShowCreateModal(false)
    setIsCustomMetricMode(false)
    setEditingMetric(null)
    setIsEditingCategory(false)
    setCreateMode('single')
    resetForm()
    resetAIForm()
    resetCategoryForm()
  }

  const handleSort = (field: 'type' | 'method') => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))
      return
    }
    setSortField(field)
    setSortDirection('asc')
  }

  const disabledMetrics = useMemo(
    () => metrics.filter((metric: Metric) => !metric.enabled),
    [metrics]
  )

  const toggleDisabledMetricSelection = (metricId: string) => {
    setSelectedDisabledMetricIds((prev) => {
      const next = new Set(prev)
      if (next.has(metricId)) {
        next.delete(metricId)
      } else {
        next.add(metricId)
      }
      return next
    })
  }

  const handleEnableSelectedMetrics = () => {
    if (selectedDisabledMetricIds.size === 0) return
    enableMetricsMutation.mutate(Array.from(selectedDisabledMetricIds))
  }

  // Only TOP-LEVEL metrics (parents + standalone) are sorted into the
  // table. Children are rendered inline beneath their parent when
  // ``expandedParents`` includes the parent id — keeping them out of
  // this list means children no longer fight the parent's sort key,
  // don't render as full table rows, and don't show up in any column
  // (Type/Method) that doesn't apply to a boolean sub-label.
  const sortedTopLevelMetrics = useMemo(() => {
    const getTypeLabel = (metric: Metric) =>
      isQuantitativeMetric(metric.name) ? 'quantitative' : 'qualitative'
    const getMethodLabel = (metric: Metric) =>
      isAIVoiceMetric(metric.name)
        ? 'ai voice'
        : isAudioMetric(metric.name)
          ? 'acoustic'
          : 'llm'

    return metrics
      .filter(
        (metric: Metric) => metric.enabled && !metric.parent_metric_id,
      )
      .sort((a: Metric, b: Metric) => {
        const aValue =
          sortField === 'type' ? getTypeLabel(a) : getMethodLabel(a)
        const bValue =
          sortField === 'type' ? getTypeLabel(b) : getMethodLabel(b)

        const baseCompare = aValue.localeCompare(bValue)
        if (baseCompare !== 0) {
          return sortDirection === 'asc' ? baseCompare : -baseCompare
        }

        // Stable secondary sort for predictable ordering within groups.
        return a.name.localeCompare(b.name)
      })
  }, [metrics, sortField, sortDirection])

  return (
    <div className="space-y-6">
      <ToastContainer />
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Metrics</h1>
          <p className="mt-2 text-sm text-gray-600">
            Manage evaluation metrics for your conversations
          </p>
          <p className="mt-1 text-xs text-gray-500">
            Acoustic defaults: only <span className="font-medium">Pitch Variance</span> is enabled; <span className="font-medium">Jitter</span>, <span className="font-medium">Shimmer</span>, and <span className="font-medium">HNR</span> start disabled.
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <Button
            variant="primary"
            onClick={() => {
              setSelectedDisabledMetricIds(new Set())
              setShowEnableModal(true)
            }}
            disabled={disabledMetrics.length === 0}
            leftIcon={<Plus className="w-4 h-4" />}
          >
            Add Metric
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              setIsCustomMetricMode(true)
              setEditingMetric(null)
              setCreateMode('single')
              setFormData({
                name: '',
                description: '',
                metric_origin: 'custom',
                metric_type: 'rating',
                custom_data_type: 'enum',
                enum_options_csv: '',
                number_min: 0,
                number_max: 10,
                number_step: 1,
                tags_csv: '',
                supported_surfaces: ['agent'],
                enabled_surfaces: ['agent'],
                trigger: 'always',
                enabled: true,
                capture_rationale: false,
                allow_discovery: false,
                input_columns: [],
                compare_transcripts: false,
              })
              setInputColumnDraft('')
              setIsForCallImports(false)
              resetCategoryForm()
              setShowCreateModal(true)
            }}
            leftIcon={<Plus className="w-4 h-4" />}
            title="Create a single custom metric or a parent category with sub-labels — switch flows from inside the modal"
          >
            Create Custom Metric
          </Button>
          <Button
            variant="outline"
            onClick={() => seedMutation.mutate()}
            isLoading={seedMutation.isPending}
            leftIcon={<RefreshCw className="w-4 h-4" />}
          >
            Sync Default Metrics
          </Button>
        </div>
      </div>

      {/* Metrics Table */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold text-gray-900">Metrics</h2>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500">Surface:</span>
              <select
                value={surfaceFilter}
                onChange={(e) => setSurfaceFilter(e.target.value as 'all' | MetricSurface)}
                className="text-sm border border-gray-300 rounded-md px-2 py-1"
              >
                <option value="all">All</option>
                <option value="agent">Agent</option>
                <option value="voice_playground">Voice Playground</option>
                <option value="blind_test">Blind Test</option>
              </select>
            </div>
          </div>
        </div>
        {isLoading ? (
          <div className="p-6 text-center text-gray-500">Loading...</div>
        ) : sortedTopLevelMetrics.length === 0 ? (
          <div className="p-12 text-center">
            <p className="text-gray-500 mb-2">No enabled metrics.</p>
            <p className="text-sm text-gray-500">
              Use <span className="font-medium">Add Metric</span> above to enable one from the disabled list.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  {/* Leading column is reserved for the expand/collapse
                      chevron on parent rows. Standalone rows leave it
                      empty so the rest of the table stays aligned. */}
                  <th className="w-8 px-2 py-3" />
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Name
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Description
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    <button
                      type="button"
                      onClick={() => handleSort('type')}
                      className="inline-flex items-center gap-1 hover:text-gray-700"
                    >
                      Type
                      <span className="text-[10px]">
                        {sortField === 'type' ? (sortDirection === 'asc' ? '↑' : '↓') : '↕'}
                      </span>
                    </button>
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Data Type
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Surface
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    <button
                      type="button"
                      onClick={() => handleSort('method')}
                      className="inline-flex items-center gap-1 hover:text-gray-700"
                    >
                      Method
                      <span className="text-[10px]">
                        {sortField === 'method' ? (sortDirection === 'asc' ? '↑' : '↓') : '↕'}
                      </span>
                    </button>
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Enabled
                  </th>
                  {/* Replaces the old per-row Edit / Delete column. The
                      single kebab opens the Manage Metric modal. */}
                  <th className="w-10 px-2 py-3" />
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {sortedTopLevelMetrics.map((metric: Metric) => {
                  const isAudio = isAudioMetric(metric.name)
                  const isQuantitative = isQuantitativeMetric(metric.name)
                  const isParent =
                    !!metric.selection_mode && !metric.parent_metric_id
                  const enabledChildren = isParent
                    ? (metric.children || []).filter((c) => c.enabled)
                    : []
                  const isExpanded = expandedParents.has(metric.id)
                  // Group key: a parent + its (currently expanded)
                  // children share a top/bottom border so they read as
                  // one unit. Standalone rows get the default cell
                  // borders.
                  const groupBorderClass =
                    isParent && enabledChildren.length > 0
                      ? 'bg-purple-50/30 border-l-2 border-l-purple-300'
                      : ''
                  return (
                    <Fragment key={metric.id}>
                      <tr
                        onClick={() => handleManage(metric)}
                        className={`hover:bg-gray-50 cursor-pointer transition-colors ${groupBorderClass}`}
                        title="Click to open Manage"
                      >
                        <td className="w-8 px-2 py-4 align-middle text-center">
                          {isParent && enabledChildren.length > 0 ? (
                            <button
                              type="button"
                              onClick={(e) => {
                                // Don't bubble — the row's onClick
                                // would otherwise open the Manage
                                // modal at the same time.
                                e.stopPropagation()
                                toggleParentExpanded(metric.id)
                              }}
                              className="inline-flex items-center justify-center w-6 h-6 rounded hover:bg-purple-100 text-purple-700"
                              aria-label={isExpanded ? 'Collapse children' : 'Expand children'}
                              title={`${isExpanded ? 'Hide' : 'Show'} ${enabledChildren.length} sub-label${enabledChildren.length === 1 ? '' : 's'}`}
                            >
                              {isExpanded ? (
                                <ChevronDown className="w-4 h-4" />
                              ) : (
                                <ChevronRight className="w-4 h-4" />
                              )}
                            </button>
                          ) : null}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center flex-wrap gap-2">
                            <span className="text-sm font-medium text-gray-900">
                              {metric.name}
                            </span>
                            {metric.is_default && (
                              <span className="px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded">
                                Default
                              </span>
                            )}
                            {isParent && (
                              <span
                                className="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide bg-purple-100 text-purple-800 rounded"
                                title={`Category metric (${metric.selection_mode}) with ${enabledChildren.length} sub-label${enabledChildren.length === 1 ? '' : 's'}.`}
                              >
                                <Layers className="w-3 h-3" />
                                {metric.selection_mode === 'single_choice'
                                  ? 'Single-choice'
                                  : 'Multi-label'}
                                <span className="ml-0.5 px-1 py-0.5 bg-purple-200 text-purple-900 rounded text-[10px]">
                                  {enabledChildren.length}
                                </span>
                              </span>
                            )}
                            {isParent && metric.allow_discovery && (
                              <span
                                className="px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide bg-amber-50 text-amber-700 border border-amber-200 rounded"
                                title="LLM may discover and propose additional sub-labels for this category during call-import evaluations."
                              >
                                Auto-discover
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <div className="text-sm text-gray-500 max-w-md truncate">
                            {metric.description || '-'}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          {isQuantitative ? (
                            <span className="px-2.5 py-1 text-xs font-medium bg-blue-100 text-blue-800 rounded-full">
                              Quantitative
                            </span>
                          ) : (
                            <span className="px-2.5 py-1 text-xs font-medium bg-amber-100 text-amber-800 rounded-full">
                              Qualitative
                            </span>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span className="px-2 py-1 text-xs font-medium bg-gray-100 text-gray-800 rounded capitalize">
                            {metric.metric_origin === 'custom'
                              ? metric.custom_data_type || metric.metric_type
                              : metric.metric_type}
                          </span>
                        </td>
                        <td
                          className="px-6 py-4 whitespace-nowrap"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div className="flex flex-wrap gap-1.5">
                            {(metric.supported_surfaces || []).map(
                              (surface) => {
                                const isEnabled = (
                                  metric.enabled_surfaces || []
                                ).includes(surface)
                                return (
                                  <button
                                    key={surface}
                                    type="button"
                                    onClick={() =>
                                      handleToggleSurface(metric, surface)
                                    }
                                    disabled={toggleSurfaceMutation.isPending}
                                    title={`${isEnabled ? 'Disable' : 'Enable'} on ${SURFACE_LABELS[surface]}`}
                                    className={`px-2 py-0.5 text-[11px] rounded-full border transition-colors ${
                                      isEnabled
                                        ? 'bg-emerald-100 text-emerald-800 border-emerald-200 hover:bg-emerald-200'
                                        : 'bg-gray-100 text-gray-500 border-gray-200 hover:bg-gray-200'
                                    }`}
                                  >
                                    {SURFACE_LABELS[surface]}
                                    {isEnabled ? ' ✓' : ''}
                                  </button>
                                )
                              },
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          {isAIVoiceMetric(metric.name) ? (
                            <span className="inline-flex items-center px-2.5 py-1 text-xs font-medium bg-purple-100 text-purple-800 rounded-full">
                              <Sparkles className="w-3 h-3 mr-1" />
                              AI Voice
                            </span>
                          ) : isAudio ? (
                            <span className="inline-flex items-center px-2.5 py-1 text-xs font-medium bg-violet-100 text-violet-800 rounded-full">
                              <AudioWaveform className="w-3 h-3 mr-1" />
                              Acoustic
                            </span>
                          ) : (
                            <span className="inline-flex items-center px-2.5 py-1 text-xs font-medium bg-emerald-100 text-emerald-800 rounded-full">
                              <Brain className="w-3 h-3 mr-1" />
                              LLM
                            </span>
                          )}
                        </td>
                        <td
                          className="px-6 py-4 whitespace-nowrap"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <button
                            onClick={() => handleToggleEnabled(metric)}
                            className="flex items-center"
                            disabled={toggleEnabledMutation.isPending}
                          >
                            {metric.enabled ? (
                              <ToggleRight className="w-10 h-10 text-green-600" />
                            ) : (
                              <ToggleLeft className="w-10 h-10 text-gray-400" />
                            )}
                          </button>
                        </td>
                        <td
                          className="w-10 px-2 py-4 text-right"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <button
                            type="button"
                            onClick={() => handleManage(metric)}
                            className="inline-flex items-center justify-center w-8 h-8 rounded-full text-gray-500 hover:text-gray-700 hover:bg-gray-100"
                            aria-label="Manage metric"
                            title="Manage metric"
                          >
                            <MoreVertical className="w-4 h-4" />
                          </button>
                        </td>
                      </tr>
                      {isParent &&
                        isExpanded &&
                        enabledChildren.map((child) => (
                          <tr
                            key={child.id}
                            onClick={() => handleManage(child)}
                            className="cursor-pointer hover:bg-purple-50/50 bg-purple-50/20 border-l-2 border-l-purple-300"
                            title="Click to open Manage"
                          >
                            <td className="w-8 px-2 py-2.5" />
                            <td className="px-6 py-2.5 whitespace-nowrap">
                              <div className="flex items-center gap-2 pl-4 border-l border-purple-200">
                                <span className="text-xs text-purple-500">
                                  ↳
                                </span>
                                <span className="text-sm text-gray-800">
                                  {child.name}
                                </span>
                                {child.capture_rationale && (
                                  <span
                                    className="px-1.5 py-0.5 text-[10px] font-medium bg-gray-100 text-gray-600 rounded"
                                    title="LLM is asked to return a short rationale for this sub-label."
                                  >
                                    Rationale
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="px-6 py-2.5">
                              <div className="text-xs text-gray-500 max-w-md truncate">
                                {child.description || '-'}
                              </div>
                            </td>
                            <td className="px-6 py-2.5 whitespace-nowrap text-[11px] text-gray-400">
                              —
                            </td>
                            <td className="px-6 py-2.5 whitespace-nowrap">
                              <span className="px-2 py-0.5 text-[11px] font-medium bg-gray-100 text-gray-700 rounded capitalize">
                                Boolean
                              </span>
                            </td>
                            <td className="px-6 py-2.5 whitespace-nowrap text-[11px] text-gray-400">
                              Inherits parent
                            </td>
                            <td className="px-6 py-2.5 whitespace-nowrap text-[11px] text-gray-400">
                              —
                            </td>
                            <td
                              className="px-6 py-2.5 whitespace-nowrap"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <button
                                onClick={() => handleToggleEnabled(child)}
                                className="flex items-center"
                                disabled={toggleEnabledMutation.isPending}
                              >
                                {child.enabled ? (
                                  <ToggleRight className="w-7 h-7 text-green-600" />
                                ) : (
                                  <ToggleLeft className="w-7 h-7 text-gray-400" />
                                )}
                              </button>
                            </td>
                            <td
                              className="w-10 px-2 py-2.5 text-right"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <button
                                type="button"
                                onClick={() => handleManage(child)}
                                className="inline-flex items-center justify-center w-7 h-7 rounded-full text-gray-400 hover:text-gray-700 hover:bg-gray-100"
                                aria-label="Manage sub-label"
                                title="Manage sub-label"
                              >
                                <MoreVertical className="w-3.5 h-3.5" />
                              </button>
                            </td>
                          </tr>
                        ))}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create/Edit Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
              onClick={closeModal}
            />
            <div
              className={`relative bg-white rounded-2xl shadow-2xl ring-1 ring-gray-100 ${
                editingMetric
                  ? isEditingCategory
                    ? 'max-w-5xl'
                    : 'max-w-4xl'
                  : createMode === 'category'
                    ? 'max-w-5xl'
                    : 'max-w-4xl'
              } w-full p-6 max-h-[90vh] overflow-y-auto`}
            >
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-2xl font-bold text-gray-900">
                  {editingMetric
                    ? isEditingCategory
                      ? `Edit category · ${editingMetric.name}`
                      : 'Edit Metric'
                    : createMode === 'category'
                      ? 'Create a category metric'
                      : isCustomMetricMode
                        ? 'Create Custom Metric'
                        : 'Create Metric'}
                </h2>
                <button
                  onClick={closeModal}
                  className="text-gray-400 hover:text-gray-500"
                >
                  <X className="h-6 w-6" />
                </button>
              </div>

              {/* Mode switcher: lets the user pick between the single
                  metric and the parent category flow without leaving
                  this modal. Hidden during edit because edit always
                  targets one row. */}
              {!editingMetric && (
                <div className="mb-4">
                  <div className="inline-flex rounded-md border border-gray-200 bg-gray-50 p-1 text-xs font-medium">
                    {(
                      [
                        { id: 'single', label: 'Single metric' },
                        { id: 'category', label: 'Category with sub-labels' },
                      ] as Array<{ id: CreateMode; label: string }>
                    ).map((tab) => (
                      <button
                        key={tab.id}
                        type="button"
                        onClick={() => setCreateMode(tab.id)}
                        className={`px-3 py-1.5 rounded ${
                          createMode === tab.id
                            ? 'bg-white text-gray-900 shadow-sm border border-gray-200'
                            : 'text-gray-600 hover:text-gray-900'
                        }`}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>
                  <p className="mt-2 text-[11px] text-gray-500">
                    {createMode === 'single'
                      ? 'Configure one custom metric end-to-end.'
                      : 'A parent metric groups N sub-label children that the LLM scores together. Pick a selection mode to control how children relate (one-of vs. independent yes/no).'}
                  </p>
                </div>
              )}

              {((createMode === 'single' && !editingMetric) ||
                (editingMetric && !isEditingCategory)) && (
              <div className="space-y-5">
                {isCustomMetricMode && !editingMetric && (
                  <div className="border border-purple-200 rounded-xl bg-purple-50/40">
                    <button
                      type="button"
                      onClick={() => setShowAIAssist((v) => !v)}
                      className="w-full flex items-center justify-between px-4 py-3 text-left"
                    >
                      <span className="flex items-center gap-2 text-sm font-semibold text-purple-900">
                        <Sparkles className="w-4 h-4 text-purple-600" />
                        Generate with AI
                      </span>
                      <span className="text-xs text-purple-700">
                        {showAIAssist ? 'Hide' : 'Show'}
                      </span>
                    </button>
                    {showAIAssist && (
                      <div className="px-4 pb-4 space-y-3">
                        <p className="text-xs text-purple-800">
                          Describe what to measure or paste labeled examples; the rest of the form will be prefilled.
                        </p>

                        <div className="border-b border-purple-200">
                          <nav className="flex space-x-4">
                            <button
                              type="button"
                              onClick={() => setAIMode('description')}
                              className={`pb-2 px-1 text-xs font-medium border-b-2 transition-colors ${
                                aiMode === 'description'
                                  ? 'border-purple-600 text-purple-700'
                                  : 'border-transparent text-purple-500 hover:text-purple-700'
                              }`}
                            >
                              From description
                            </button>
                            <button
                              type="button"
                              onClick={() => setAIMode('examples')}
                              className={`pb-2 px-1 text-xs font-medium border-b-2 transition-colors ${
                                aiMode === 'examples'
                                  ? 'border-purple-600 text-purple-700'
                                  : 'border-transparent text-purple-500 hover:text-purple-700'
                              }`}
                            >
                              From examples
                            </button>
                          </nav>
                        </div>

                        {aiMode === 'description' ? (
                          <textarea
                            value={aiDescription}
                            onChange={(e) => setAIDescription(e.target.value)}
                            rows={4}
                            placeholder="e.g. Measure whether the agent confirmed the customer's booking date and time before ending the call."
                            className="w-full rounded-lg border border-purple-200 bg-white px-3.5 py-2.5 text-sm text-gray-900 placeholder-gray-400 shadow-sm transition focus:border-purple-500 focus:outline-none focus:ring-2 focus:ring-purple-500/20"
                          />
                        ) : (
                          <div className="space-y-2">
                            {aiExamples.map((ex, idx) => (
                              <div key={idx} className="border border-purple-200 rounded-lg p-2 bg-white space-y-2">
                                <div className="flex items-center justify-between">
                                  <span className="text-[11px] font-medium text-purple-700">Example {idx + 1}</span>
                                  {aiExamples.length > 1 && (
                                    <button
                                      type="button"
                                      onClick={() =>
                                        setAIExamples((prev) => prev.filter((_, i) => i !== idx))
                                      }
                                      className="text-[11px] text-red-600 hover:text-red-800"
                                    >
                                      Remove
                                    </button>
                                  )}
                                </div>
                                <textarea
                                  value={ex.transcript}
                                  onChange={(e) =>
                                    setAIExamples((prev) =>
                                      prev.map((row, i) => (i === idx ? { ...row, transcript: e.target.value } : row)),
                                    )
                                  }
                                  rows={2}
                                  placeholder="Transcript snippet..."
                                  className="w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-900 placeholder-gray-400 shadow-sm transition focus:border-purple-500 focus:outline-none focus:ring-2 focus:ring-purple-500/20"
                                />
                                <div className="grid grid-cols-2 gap-2">
                                  <input
                                    type="text"
                                    value={ex.rating}
                                    onChange={(e) =>
                                      setAIExamples((prev) =>
                                        prev.map((row, i) => (i === idx ? { ...row, rating: e.target.value } : row)),
                                      )
                                    }
                                    placeholder="Rating (e.g. 0.8, true, Excellent)"
                                    className="rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-900 placeholder-gray-400 shadow-sm transition focus:border-purple-500 focus:outline-none focus:ring-2 focus:ring-purple-500/20"
                                  />
                                  <input
                                    type="text"
                                    value={ex.notes}
                                    onChange={(e) =>
                                      setAIExamples((prev) =>
                                        prev.map((row, i) => (i === idx ? { ...row, notes: e.target.value } : row)),
                                      )
                                    }
                                    placeholder="Notes (optional)"
                                    className="rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-900 placeholder-gray-400 shadow-sm transition focus:border-purple-500 focus:outline-none focus:ring-2 focus:ring-purple-500/20"
                                  />
                                </div>
                              </div>
                            ))}
                            <button
                              type="button"
                              onClick={() =>
                                setAIExamples((prev) => [...prev, { transcript: '', rating: '', notes: '' }])
                              }
                              className="text-xs text-purple-700 hover:text-purple-900 inline-flex items-center gap-1"
                            >
                              <Plus className="w-3 h-3" /> Add example
                            </button>
                          </div>
                        )}

                        <div className="flex justify-end">
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={handleGenerateAIMetric}
                            isLoading={generateMetricMutation.isPending}
                            leftIcon={<Sparkles className="w-3.5 h-3.5" />}
                          >
                            Generate
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Two-column layout: text-y "what" fields on the left,
                    configuration "how" controls on the right. Some
                    fields (Description, Custom Data Type group, Surfaces,
                    Discovery, Enable) span both columns because they
                    benefit from the full canvas; everything else picks
                    up the responsive grid columns automatically. */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-6 gap-y-5">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Name *
                    </label>
                    <input
                      type="text"
                      value={formData.name}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      disabled={editingMetric?.is_default}
                      className={MODERN_INPUT_CLASS}
                      placeholder="e.g. Booking Confirmation"
                    />
                  </div>

                  {/* Unified "Type" select — replaces the older split
                      between "Metric Type" and "Custom Data Type". The
                      four options below cover every shape the LLM
                      judge can produce; the handler keeps both
                      ``metric_type`` (the storage shape on the
                      backend) and ``custom_data_type`` (the UI/config
                      shape) in sync so existing payload logic in
                      ``buildPayload`` keeps working unchanged. */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Type *
                    </label>
                    {(() => {
                      // Derive the unified value from formData. We read
                      // both fields so an existing metric whose
                      // ``custom_data_type`` is set takes priority over
                      // the legacy ``metric_type`` (the two were almost
                      // always stored together via the old form).
                      type UnifiedType =
                        | 'boolean'
                        | 'enum'
                        | 'number_range'
                        | 'text'
                      const unifiedValue: UnifiedType =
                        formData.metric_type === 'text'
                          ? 'text'
                          : formData.metric_type === 'boolean'
                            ? 'boolean'
                            : formData.custom_data_type === 'enum' ||
                                formData.metric_type === 'rating'
                              ? 'enum'
                              : formData.custom_data_type === 'number_range' ||
                                  formData.metric_type === 'number'
                                ? 'number_range'
                                : 'boolean'
                      return (
                        <select
                          value={unifiedValue}
                          onChange={(e) => {
                            const next = e.target.value as UnifiedType
                            setFormData((prev) => {
                              if (next === 'text') {
                                return { ...prev, metric_type: 'text' }
                              }
                              if (next === 'boolean') {
                                return {
                                  ...prev,
                                  metric_type: 'boolean',
                                  custom_data_type: 'boolean',
                                }
                              }
                              if (next === 'enum') {
                                return {
                                  ...prev,
                                  metric_type: 'rating',
                                  custom_data_type: 'enum',
                                }
                              }
                              return {
                                ...prev,
                                metric_type: 'number',
                                custom_data_type: 'number_range',
                              }
                            })
                          }}
                          disabled={editingMetric?.is_default}
                          className={MODERN_INPUT_CLASS}
                        >
                          <option value="boolean">Boolean (true / false)</option>
                          <option value="enum">Enum (pick from a list)</option>
                          <option value="number_range">
                            Number range (min / max / step)
                          </option>
                          <option value="text">Text (LLM summary)</option>
                        </select>
                      )
                    })()}
                    {formData.metric_type === 'text' && (
                      <p className="mt-1.5 text-xs text-gray-500">
                        The LLM returns a free-form sentence / summary instead
                        of a score. Use the Description field to tell the
                        model what to summarize. Text metrics are not
                        aggregated in numeric dashboards.
                      </p>
                    )}
                    {editingMetric?.is_default && (
                      <p className="mt-1.5 text-xs text-gray-500">
                        The type of a built-in default metric cannot be changed.
                      </p>
                    )}
                  </div>

                  <div className="lg:col-span-2">
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Description
                    </label>
                    <textarea
                      value={formData.description}
                      onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                      rows={4}
                      className={MODERN_INPUT_CLASS}
                      placeholder="Tell the LLM what to look for. Be specific — e.g. 'True when the agent reads back the appointment date and time exactly as the customer said it.'"
                    />
                  </div>

                  {formData.metric_type !== 'text' && (
                    <div className="rounded-xl border border-gray-200 bg-gray-50/70 p-3.5">
                      <label className="flex items-start gap-2.5">
                        <input
                          type="checkbox"
                          checked={formData.capture_rationale}
                          onChange={(e) =>
                            setFormData({ ...formData, capture_rationale: e.target.checked })
                          }
                          className="mt-0.5 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                        />
                        <span className="text-sm text-gray-800">
                          <span className="font-medium">Capture LLM Rationale</span>
                          <span className="block text-xs text-gray-500 mt-0.5">
                            Ask the LLM to also return a 1-2 sentence reason
                            alongside the value. Adds a{' '}
                            <code className="px-1 py-0.5 bg-white border border-gray-200 rounded text-[11px]">
                              &lt;Name&gt; - LLM Rationale
                            </code>{' '}
                            column to the call-import CSV export.
                          </span>
                        </span>
                      </label>
                    </div>
                  )}

                  {/*
                    Call Imports configuration: ``input_columns``
                    (column-input judge) and ``compare_transcripts``
                    (transcript-compare judge) are knobs that ONLY
                    affect call-import evaluation runs (the CSV /
                    Excel "Call Imports" upload flow). Grouping them
                    behind a single "is this metric for Call Imports?"
                    toggle keeps the form scan-friendly for people
                    authoring plain live-call metrics, who don't need
                    to know either flag exists. Hidden for child
                    sub-metrics because the backend rejects either
                    field on rows with a parent.
                  */}
                  {!editingMetric?.parent_metric_id && (
                    <div className="rounded-xl border border-gray-200 bg-white p-3.5 space-y-3.5">
                      <label className="flex items-start gap-2.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={isForCallImports}
                          onChange={(e) => {
                            const next = e.target.checked
                            setIsForCallImports(next)
                            // Collapsing the section also clears both
                            // fields so the saved metric exactly
                            // mirrors what the user can see in the
                            // form — no hidden state lingering after a
                            // user changed their mind about routing
                            // this metric through Call Imports.
                            if (!next) {
                              setFormData({
                                ...formData,
                                input_columns: [],
                                compare_transcripts: false,
                              })
                              setInputColumnDraft('')
                            }
                          }}
                          className="mt-0.5 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                        />
                        <span className="text-sm text-gray-800">
                          <span className="font-medium">
                            This metric is for Call Imports
                          </span>
                          <span className="block text-xs text-gray-500 mt-0.5">
                            Configure how this metric scores rows from a
                            CSV / Excel call-import batch — pick specific
                            columns to judge, or compare the production
                            and diarised transcripts side-by-side.
                            Live-call evaluations are unaffected by
                            either option below.
                          </span>
                        </span>
                      </label>

                      {isForCallImports && (
                        <div className="ml-7 pl-3.5 border-l-2 border-gray-100 space-y-3.5">
                  {/*
                    Compare-transcripts judge: the metric reads BOTH
                    the production and diarised transcripts on each
                    call-import row and the Run Evaluation
                    transcript_source toggle is ignored. Hidden for
                    parent categories (server rejects the flag on
                    rows with ``selection_mode``); also disabled when
                    the metric is configured as a column-input judge
                    (the two prompt templates are mutually exclusive).
                    Toggling this flag on clears ``input_columns`` so
                    the user can't end up with an incoherent metric
                    shape on Save.
                  */}
                  {!editingMetric?.selection_mode
                    && (() => {
                      const hasInputColumns =
                        (formData.input_columns?.length ?? 0) > 0
                      const disabledByInputColumns =
                        hasInputColumns && !formData.compare_transcripts
                      const onToggle = (next: boolean) => {
                        // Enabling compare_transcripts wipes
                        // ``input_columns`` so the schema validator's
                        // mutual-exclusion rule is satisfied in one
                        // round-trip.
                        setFormData({
                          ...formData,
                          compare_transcripts: next,
                          input_columns: next ? [] : formData.input_columns,
                        })
                        if (next) setInputColumnDraft('')
                      }
                      return (
                        <div className="rounded-xl border border-gray-200 bg-gray-50/70 p-3.5">
                          <label
                            className={`flex items-start gap-2.5 ${
                              disabledByInputColumns
                                ? 'cursor-not-allowed opacity-60'
                                : 'cursor-pointer'
                            }`}
                            title={
                              disabledByInputColumns
                                ? 'Clear Input columns first — a metric can be either a column-input judge or a transcript-compare judge, not both.'
                                : undefined
                            }
                          >
                            <input
                              type="checkbox"
                              checked={!!formData.compare_transcripts}
                              disabled={disabledByInputColumns}
                              onChange={(e) => onToggle(e.target.checked)}
                              className="mt-0.5 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded disabled:opacity-60"
                            />
                            <span className="text-sm text-gray-800">
                              <span className="font-medium">
                                Compare transcripts (Production vs Diarised)
                              </span>
                              <span className="block text-xs text-gray-500 mt-0.5">
                                When on, this metric reads BOTH transcripts
                                on each row and the judge scores based on
                                the relationship between them. The Run
                                Evaluation transcript_source setting is
                                ignored for this metric.
                              </span>
                            </span>
                          </label>
                        </div>
                      )
                    })()}

                  {/*
                    Input columns: when one or more entries are listed
                    here the metric becomes a "column-input judge" — at
                    call-import evaluation time the worker reads each
                    entry from the row's ``raw_columns`` (with a
                    fallback through the parent CallImport's
                    ``custom_column_mapping`` when the entry is a
                    friendly name) and feeds the values to the LLM as
                    Context Inputs instead of the transcript. The
                    child-sub-metric guard lives on the outer Call
                    Imports wrapper now; here we just hide the chip
                    input when the metric is configured as a
                    transcript-compare judge (the two prompt
                    templates are mutually exclusive).
                  */}
                  {!formData.compare_transcripts
                    && (() => {
                    // Helpers scoped to the picker so they close over
                    // the latest formData / draft without us threading
                    // them through props.
                    const isAlreadySelected = (entry: string) =>
                      formData.input_columns.some(
                        (h) => h.toLowerCase() === entry.toLowerCase(),
                      )
                    const addEntry = (entry: string) => {
                      const trimmed = entry.trim()
                      if (!trimmed || isAlreadySelected(trimmed)) return
                      setFormData({
                        ...formData,
                        input_columns: [...formData.input_columns, trimmed],
                      })
                    }
                    const removeEntry = (entry: string) => {
                      setFormData({
                        ...formData,
                        input_columns: formData.input_columns.filter(
                          (h) => h !== entry,
                        ),
                      })
                    }

                    // The drilled-in CallImport (if any). When the
                    // popover is at the import-list step this is
                    // undefined and the popover renders the list view.
                    const drilledImport = columnPickerImportId
                      ? recentImports.find(
                          (ci) => ci.id === columnPickerImportId,
                        )
                      : undefined

                    // Build the column groups for the drilled-in
                    // import. Custom-mapped columns expose the
                    // friendly name (key of ``custom_column_mapping``)
                    // because that's what the rest of the call-import
                    // UI surfaces — the worker resolves it back to the
                    // CSV header at evaluation time. Extra columns
                    // expose their CSV header verbatim because that's
                    // already the user-visible identifier.
                    const customMappingEntries = drilledImport
                      ? Object.entries(drilledImport.custom_column_mapping || {})
                          .filter(([key]) => typeof key === 'string' && key.trim())
                          .sort(([a], [b]) =>
                            a.toLowerCase().localeCompare(b.toLowerCase()),
                          )
                      : []
                    const extraColumnEntries = drilledImport
                      ? (drilledImport.extra_columns || [])
                          .filter((h) => typeof h === 'string' && h.trim())
                          .slice()
                          .sort((a, b) =>
                            a.toLowerCase().localeCompare(b.toLowerCase()),
                          )
                      : []
                    const drilledImportColumnCount =
                      customMappingEntries.length + extraColumnEntries.length

                    const importLabel = (
                      ci: (typeof recentImports)[number],
                    ) => ci.original_filename || `Import ${ci.id.slice(0, 8)}`

                    const importColumnCount = (
                      ci: (typeof recentImports)[number],
                    ): number => {
                      const customCount = Object.keys(
                        ci.custom_column_mapping || {},
                      ).filter((k) => typeof k === 'string' && k.trim()).length
                      const extraCount = (ci.extra_columns || []).filter(
                        (h) => typeof h === 'string' && h.trim(),
                      ).length
                      return customCount + extraCount
                    }

                    return (
                      <div ref={columnPickerRef}>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          Input columns (optional)
                        </label>
                        <p className="text-xs text-gray-500 mb-2">
                          Pick from a specific imported CSV's columns —
                          either the friendly names you assigned during
                          import or the extra columns you preserved
                          verbatim. The next evaluation run will judge
                          those values (instead of the transcript) and
                          the verdict becomes a new column in the
                          export. Leave empty to keep the default
                          transcript-based behavior.
                        </p>
                        {/* Chip-input + popover wrapper. ``relative``
                            anchors the absolute-positioned popover. */}
                        <div className="relative">
                          <div className="flex flex-wrap items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 bg-white shadow-sm transition focus-within:border-primary-500 focus-within:ring-2 focus-within:ring-primary-500/20">
                            {formData.input_columns.map((entry) => (
                              <span
                                key={entry}
                                className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-primary-50 text-primary-700 border border-primary-200"
                              >
                                {entry}
                                <button
                                  type="button"
                                  aria-label={`Remove ${entry}`}
                                  onClick={() => removeEntry(entry)}
                                  className="hover:text-primary-900"
                                >
                                  <X className="w-3 h-3" />
                                </button>
                              </span>
                            ))}
                            <input
                              type="text"
                              value={inputColumnDraft}
                              onChange={(e) =>
                                setInputColumnDraft(e.target.value)
                              }
                              onKeyDown={(e) => {
                                // Free-text Enter / comma is the
                                // forward-compat escape hatch — useful
                                // when authoring a metric before the
                                // first matching CSV is uploaded.
                                if (e.key === 'Enter' || e.key === ',') {
                                  e.preventDefault()
                                  const trimmed = inputColumnDraft.trim()
                                  if (trimmed) {
                                    addEntry(trimmed)
                                    setInputColumnDraft('')
                                  }
                                  return
                                }
                                if (
                                  e.key === 'Backspace' &&
                                  !inputColumnDraft &&
                                  formData.input_columns.length > 0
                                ) {
                                  setFormData({
                                    ...formData,
                                    input_columns:
                                      formData.input_columns.slice(0, -1),
                                  })
                                }
                              }}
                              onBlur={() => {
                                const trimmed = inputColumnDraft.trim()
                                if (trimmed) {
                                  addEntry(trimmed)
                                  setInputColumnDraft('')
                                }
                              }}
                              placeholder={
                                formData.input_columns.length === 0
                                  ? 'Type a column name and press Enter, or use the picker →'
                                  : ''
                              }
                              className="flex-1 min-w-[10rem] text-sm text-gray-900 placeholder-gray-400 focus:outline-none bg-transparent"
                            />
                            <button
                              type="button"
                              onClick={() => {
                                setColumnPickerOpen((prev) => !prev)
                                setColumnPickerImportId(null)
                              }}
                              className="ml-auto inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md bg-gray-100 hover:bg-gray-200 text-gray-700 transition"
                              title="Browse columns from a specific imported CSV"
                            >
                              <Layers className="h-3.5 w-3.5" />
                              Browse imports
                              <ChevronDown
                                className={`h-3 w-3 transition-transform ${
                                  columnPickerOpen ? 'rotate-180' : ''
                                }`}
                              />
                            </button>
                          </div>

                          {columnPickerOpen && (
                            <div className="absolute z-20 left-0 right-0 mt-1 max-h-80 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg ring-1 ring-black/5">
                              {/* IMPORT LIST VIEW — shown when no
                                  specific import is drilled into. */}
                              {!drilledImport && (
                                <div>
                                  <div className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-gray-500 bg-gray-50 border-b border-gray-100 flex items-center justify-between">
                                    <span>Pick a call import</span>
                                    {recentImports.length > 0 && (
                                      <span className="text-[10px] font-normal normal-case text-gray-400">
                                        {recentImports.length} most recent
                                      </span>
                                    )}
                                  </div>
                                  {recentImports.length === 0 && (
                                    <div className="px-3 py-3 text-xs text-gray-500">
                                      No call imports in this workspace
                                      yet. Type a column name in the
                                      field above and press Enter to add
                                      it manually — the metric will
                                      start judging it as soon as a
                                      matching column shows up in an
                                      upload.
                                    </div>
                                  )}
                                  {recentImports.map((ci) => {
                                    const cols = importColumnCount(ci)
                                    return (
                                      <button
                                        key={ci.id}
                                        type="button"
                                        onClick={() =>
                                          setColumnPickerImportId(ci.id)
                                        }
                                        disabled={cols === 0}
                                        className={`w-full flex items-center justify-between gap-3 px-3 py-2.5 text-left transition border-b border-gray-50 last:border-b-0 ${
                                          cols === 0
                                            ? 'opacity-50 cursor-not-allowed'
                                            : 'hover:bg-gray-50'
                                        }`}
                                      >
                                        <div className="min-w-0 flex-1">
                                          <div className="flex items-center gap-1.5">
                                            <FileText className="h-3.5 w-3.5 text-gray-400 shrink-0" />
                                            <span className="truncate text-sm font-medium text-gray-800">
                                              {importLabel(ci)}
                                            </span>
                                          </div>
                                          <div className="mt-0.5 flex items-center gap-2 text-[11px] text-gray-500">
                                            {ci.dataset && (
                                              <span className="inline-flex items-center gap-0.5">
                                                <Database className="h-3 w-3" />
                                                {ci.dataset}
                                              </span>
                                            )}
                                            <span>
                                              {ci.total_rows} row
                                              {ci.total_rows === 1 ? '' : 's'}
                                            </span>
                                            <span>
                                              {cols} mappable column
                                              {cols === 1 ? '' : 's'}
                                            </span>
                                          </div>
                                        </div>
                                        {cols > 0 && (
                                          <ChevronRight className="h-4 w-4 text-gray-400 shrink-0" />
                                        )}
                                      </button>
                                    )
                                  })}
                                </div>
                              )}

                              {/* COLUMN VIEW — shown after the user
                                  picks an import. Friendly-mapped
                                  columns and extra (verbatim) columns
                                  are split into clearly labeled
                                  groups. */}
                              {drilledImport && (
                                <div>
                                  <div className="px-3 py-2 bg-gray-50 border-b border-gray-100 flex items-center gap-2">
                                    <button
                                      type="button"
                                      onClick={() =>
                                        setColumnPickerImportId(null)
                                      }
                                      className="inline-flex items-center gap-1 text-[11px] font-medium text-gray-600 hover:text-gray-900"
                                    >
                                      <ChevronLeft className="h-3.5 w-3.5" />
                                      Imports
                                    </button>
                                    <span className="text-[11px] text-gray-400">
                                      /
                                    </span>
                                    <span className="text-[11px] font-semibold text-gray-700 truncate">
                                      {importLabel(drilledImport)}
                                    </span>
                                  </div>

                                  {drilledImportColumnCount === 0 && (
                                    <div className="px-3 py-3 text-xs text-gray-500">
                                      This import didn't preserve any
                                      extra columns or define custom
                                      mappings, so there's nothing for a
                                      column-input metric to read. Pick
                                      a different import or upload one
                                      that includes the columns you
                                      want to score.
                                    </div>
                                  )}

                                  {customMappingEntries.length > 0 && (
                                    <div>
                                      <div className="px-3 pt-2.5 pb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                                        Custom-mapped columns
                                      </div>
                                      {customMappingEntries.map(
                                        ([friendlyName, csvHeader]) => {
                                          const already =
                                            isAlreadySelected(friendlyName)
                                          return (
                                            <button
                                              key={`custom-${friendlyName}`}
                                              type="button"
                                              onClick={() => {
                                                addEntry(friendlyName)
                                              }}
                                              disabled={already}
                                              className={`w-full flex items-start justify-between gap-2 px-3 py-2 text-left transition ${
                                                already
                                                  ? 'opacity-50 cursor-not-allowed'
                                                  : 'hover:bg-primary-50'
                                              }`}
                                            >
                                              <div className="min-w-0 flex-1">
                                                <div className="text-sm text-gray-800 truncate font-mono text-[12px]">
                                                  {friendlyName}
                                                </div>
                                                <div className="text-[10px] text-gray-500 truncate">
                                                  CSV column:{' '}
                                                  <span className="font-mono">
                                                    {csvHeader}
                                                  </span>
                                                </div>
                                              </div>
                                              {already ? (
                                                <span className="text-[10px] text-gray-400">
                                                  added
                                                </span>
                                              ) : (
                                                <Plus className="h-3.5 w-3.5 text-primary-600 shrink-0 mt-0.5" />
                                              )}
                                            </button>
                                          )
                                        },
                                      )}
                                    </div>
                                  )}

                                  {extraColumnEntries.length > 0 && (
                                    <div>
                                      <div className="px-3 pt-2.5 pb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-500 border-t border-gray-100 mt-1">
                                        Extra preserved columns
                                      </div>
                                      {extraColumnEntries.map((header) => {
                                        const already =
                                          isAlreadySelected(header)
                                        return (
                                          <button
                                            key={`extra-${header}`}
                                            type="button"
                                            onClick={() => addEntry(header)}
                                            disabled={already}
                                            className={`w-full flex items-center justify-between gap-2 px-3 py-2 text-left transition ${
                                              already
                                                ? 'opacity-50 cursor-not-allowed'
                                                : 'hover:bg-primary-50'
                                            }`}
                                          >
                                            <span className="truncate font-mono text-[12px] text-gray-800">
                                              {header}
                                            </span>
                                            {already ? (
                                              <span className="text-[10px] text-gray-400">
                                                added
                                              </span>
                                            ) : (
                                              <Plus className="h-3.5 w-3.5 text-primary-600 shrink-0" />
                                            )}
                                          </button>
                                        )
                                      })}
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  })()}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Per-shape sub-config that the unified Type select
                      drives. Only renders for custom metrics where the
                      shape needs extra inputs (enum options, or
                      min/max/step for number range). Boolean and Text
                      have no extra config. */}
                  {isCustomMetricMode &&
                    formData.metric_type !== 'text' &&
                    (formData.custom_data_type === 'enum' ||
                      formData.custom_data_type === 'number_range') && (
                      <div className="lg:col-span-2 rounded-xl border border-gray-200 bg-gray-50/70 p-4">
                        {formData.custom_data_type === 'enum' && (
                          <div>
                            <label className="block text-sm font-medium text-gray-700 mb-2">
                              Enum options (comma separated) *
                            </label>
                            <input
                              type="text"
                              value={formData.enum_options_csv}
                              onChange={(e) => setFormData({ ...formData, enum_options_csv: e.target.value })}
                              className={MODERN_INPUT_SM_CLASS}
                              placeholder="Excellent, Good, Neutral, Poor"
                            />
                            <p className="mt-1.5 text-xs text-gray-500">
                              The LLM judge must pick exactly one of these
                              labels for every evaluated row. Order is
                              preserved in dashboards and CSV exports.
                            </p>
                          </div>
                        )}

                        {formData.custom_data_type === 'number_range' && (
                          <div className="grid grid-cols-3 gap-3">
                            <div>
                              <label className="block text-sm font-medium text-gray-700 mb-2">Min</label>
                              <input
                                type="number"
                                value={formData.number_min}
                                onChange={(e) => setFormData({ ...formData, number_min: Number(e.target.value) })}
                                className={MODERN_INPUT_SM_CLASS}
                              />
                            </div>
                            <div>
                              <label className="block text-sm font-medium text-gray-700 mb-2">Max</label>
                              <input
                                type="number"
                                value={formData.number_max}
                                onChange={(e) => setFormData({ ...formData, number_max: Number(e.target.value) })}
                                className={MODERN_INPUT_SM_CLASS}
                              />
                            </div>
                            <div>
                              <label className="block text-sm font-medium text-gray-700 mb-2">Step</label>
                              <input
                                type="number"
                                value={formData.number_step}
                                onChange={(e) => setFormData({ ...formData, number_step: Number(e.target.value) })}
                                className={MODERN_INPUT_SM_CLASS}
                              />
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                  <div className="lg:col-span-2">
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Supported Surfaces
                    </label>
                    <div className="flex flex-wrap gap-3">
                      {ALL_SURFACES.map((surface) => {
                        const checked = formData.supported_surfaces.includes(surface)
                        return (
                          <label
                            key={surface}
                            className={`inline-flex items-center gap-2 text-sm cursor-pointer rounded-lg border px-3 py-2 transition ${
                              checked
                                ? 'border-primary-300 bg-primary-50 text-primary-800'
                                : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={(e) => {
                                const supported = e.target.checked
                                  ? [...new Set([...formData.supported_surfaces, surface])]
                                  : formData.supported_surfaces.filter((s) => s !== surface)
                                const enabledSurfaces = e.target.checked
                                  ? [...new Set([...formData.enabled_surfaces, surface])]
                                  : formData.enabled_surfaces.filter((s) => supported.includes(s))
                                setFormData({ ...formData, supported_surfaces: supported, enabled_surfaces: enabledSurfaces })
                              }}
                              className="h-4 w-4 text-primary-600 border-gray-300 rounded"
                            />
                            {SURFACE_LABELS[surface]}
                          </label>
                        )
                      })}
                    </div>
                    <p className="mt-1.5 text-xs text-gray-500">
                      Custom metrics on Agent / Voice Playground are evaluated by an LLM judge using the conversation transcript.
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Tags (comma separated)
                    </label>
                    <input
                      type="text"
                      value={formData.tags_csv}
                      onChange={(e) => setFormData({ ...formData, tags_csv: e.target.value })}
                      className={MODERN_INPUT_CLASS}
                      placeholder="quality, compliance, friendliness"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Trigger
                    </label>
                    <select
                      value={formData.trigger}
                      onChange={(e) => setFormData({ ...formData, trigger: e.target.value as any })}
                      className={MODERN_INPUT_CLASS}
                    >
                      <option value="always">Always</option>
                    </select>
                  </div>

                  {/* Discovery toggle: surfaces in the edit form so a
                      user who forgot to tick the box during Create
                      Category can flip it on later without having to
                      delete + recreate the category. The backend now
                      accepts allow_discovery on both single_choice and
                      multi_label parents. */}
                  {editingMetric &&
                    !editingMetric.parent_metric_id &&
                    !!editingMetric.selection_mode && (
                      <div className="lg:col-span-2 border border-amber-200 bg-amber-50/40 rounded-xl p-3.5">
                        <label className="flex items-start gap-2.5 text-sm text-gray-800">
                          <input
                            type="checkbox"
                            checked={formData.allow_discovery}
                            onChange={(e) =>
                              setFormData({
                                ...formData,
                                allow_discovery: e.target.checked,
                              })
                            }
                            className="mt-0.5 h-4 w-4 text-amber-600 focus:ring-amber-500 border-gray-300 rounded"
                          />
                          <span>
                            <span className="font-medium">
                              Allow LLM-discovered labels
                            </span>
                            <span className="block text-xs text-gray-600 mt-0.5">
                              Lets the LLM emit candidate sub-labels beyond
                              the children below during call-import
                              evaluation. Promote useful candidates from
                              the Discovered Labels panel on each
                              evaluation.
                              {editingMetric.selection_mode === 'single_choice'
                                ? ' For single-choice categories the discovered labels are supplemental — the existing children still control the picked outcome.'
                                : ''}
                            </span>
                          </span>
                        </label>
                      </div>
                    )}

                  <div className="lg:col-span-2 flex items-center">
                    <input
                      type="checkbox"
                      id="enabled"
                      checked={formData.enabled}
                      onChange={(e) => setFormData({ ...formData, enabled: e.target.checked })}
                      className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                    />
                    <label htmlFor="enabled" className="ml-2 block text-sm text-gray-900">
                      Enable this metric
                    </label>
                  </div>
                </div>

                <div className="flex justify-end space-x-3 pt-2 border-t border-gray-100">
                  <Button variant="ghost" onClick={closeModal}>
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    onClick={editingMetric ? handleUpdate : handleCreate}
                    isLoading={createMutation.isPending || updateMutation.isPending}
                  >
                    {editingMetric ? 'Update' : 'Create'}
                  </Button>
                </div>
              </div>
              )}

              {!editingMetric && createMode === 'category' && (
                <div className="space-y-5">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-5">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Category name *
                      </label>
                      <input
                        type="text"
                        value={categoryForm.name}
                        onChange={(e) =>
                          setCategoryForm((s) => ({ ...s, name: e.target.value }))
                        }
                        placeholder="e.g. Call Outcome"
                        className={MODERN_INPUT_CLASS}
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Selection mode *
                      </label>
                      <select
                        value={categoryForm.selection_mode}
                        onChange={(e) => {
                          const next = e.target.value as
                            | 'single_choice'
                            | 'multi_label'
                          setCategoryForm((s) => ({
                            ...s,
                            selection_mode: next,
                          }))
                        }}
                        className={MODERN_INPUT_CLASS}
                      >
                        <option value="single_choice">Single choice (exactly one true)</option>
                        <option value="multi_label">Multi-label (each child independent)</option>
                      </select>
                    </div>

                    <div className="md:col-span-2 rounded-xl border border-amber-200 bg-amber-50/40 p-3.5">
                      <label className="flex items-start gap-2.5 text-sm text-gray-800">
                        <input
                          type="checkbox"
                          checked={categoryForm.allow_discovery}
                          onChange={(e) =>
                            setCategoryForm((s) => ({
                              ...s,
                              allow_discovery: e.target.checked,
                            }))
                          }
                          className="mt-0.5 h-4 w-4 text-amber-600 focus:ring-amber-500 border-gray-300 rounded"
                        />
                        <span>
                          <span className="font-medium">Allow LLM-discovered labels</span>
                          <span className="block text-xs text-gray-600 mt-0.5">
                            Lets the LLM emit candidate sub-labels beyond
                            the ones below during call-import evaluation.
                            You can promote useful candidates into real
                            sub-labels afterwards.
                            {categoryForm.selection_mode === 'single_choice'
                              ? ' For single-choice categories the discovered labels are supplemental — the existing children still control the picked outcome.'
                              : ''}
                          </span>
                        </span>
                      </label>
                    </div>

                    <div className="md:col-span-2">
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Description / context for the LLM
                      </label>
                      <textarea
                        value={categoryForm.description}
                        onChange={(e) =>
                          setCategoryForm((s) => ({ ...s, description: e.target.value }))
                        }
                        rows={3}
                        placeholder="e.g. Outcomes for an outbound survey call. The LLM uses this as context when scoring sub-labels below."
                        className={MODERN_INPUT_CLASS}
                      />
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <label className="block text-sm font-medium text-gray-700">
                        Sub-labels ({categoryForm.children.length})
                      </label>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setCategoryForm((s) => ({
                            ...s,
                            children: [
                              ...s.children,
                              {
                                local_id: `c-${Date.now()}-${s.children.length + 1}`,
                                name: '',
                                description: '',
                                capture_rationale: true,
                              },
                            ],
                          }))
                        }
                        leftIcon={<Plus className="w-3 h-3" />}
                      >
                        Add sub-label
                      </Button>
                    </div>
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                      {categoryForm.children.map((child, idx) => (
                        <div
                          key={child.local_id}
                          className="border border-gray-200 rounded-xl p-3 space-y-2 bg-gray-50/60"
                        >
                          <div className="flex items-start gap-2">
                            <div className="flex-1">
                              <input
                                type="text"
                                value={child.name}
                                onChange={(e) =>
                                  setCategoryForm((s) => ({
                                    ...s,
                                    children: s.children.map((c, i) =>
                                      i === idx ? { ...c, name: e.target.value } : c,
                                    ),
                                  }))
                                }
                                placeholder="sub-label name (e.g. happy_completion)"
                                className={MODERN_INPUT_SM_CLASS}
                              />
                            </div>
                            <label className="inline-flex items-center gap-1.5 text-xs text-gray-700 px-2.5 py-2 rounded-lg border border-gray-200 bg-white whitespace-nowrap">
                              <input
                                type="checkbox"
                                checked={child.capture_rationale}
                                onChange={(e) =>
                                  setCategoryForm((s) => ({
                                    ...s,
                                    children: s.children.map((c, i) =>
                                      i === idx
                                        ? { ...c, capture_rationale: e.target.checked }
                                        : c,
                                    ),
                                  }))
                                }
                                className="h-3.5 w-3.5 text-primary-600 border-gray-300 rounded"
                              />
                              Rationale
                            </label>
                            {categoryForm.children.length > 2 && (
                              <button
                                onClick={() =>
                                  setCategoryForm((s) => ({
                                    ...s,
                                    children: s.children.filter((_, i) => i !== idx),
                                  }))
                                }
                                className="text-gray-400 hover:text-red-600 px-2 py-1.5 rounded-lg hover:bg-red-50 transition-colors"
                                title="Remove sub-label"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            )}
                          </div>
                          <textarea
                            value={child.description}
                            onChange={(e) =>
                              setCategoryForm((s) => ({
                                ...s,
                                children: s.children.map((c, i) =>
                                  i === idx
                                    ? { ...c, description: e.target.value }
                                    : c,
                                ),
                              }))
                            }
                            rows={3}
                            placeholder="Rubric: when should the LLM mark this child true?"
                            className={MODERN_INPUT_SM_CLASS}
                          />
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="flex items-center justify-end gap-3 pt-2 border-t border-gray-100">
                    <Button variant="ghost" onClick={closeModal}>
                      Cancel
                    </Button>
                    <Button
                      variant="primary"
                      isLoading={createCategoryMutation.isPending}
                      disabled={
                        !categoryForm.name.trim() ||
                        categoryForm.children.filter((c) => c.name.trim()).length < 2
                      }
                      onClick={() => {
                        const cleanedChildren = categoryForm.children
                          .filter((c) => c.name.trim())
                          .map((c) => ({
                            name: c.name.trim(),
                            description: c.description.trim() || null,
                            capture_rationale: c.capture_rationale,
                            enabled: true,
                          }))
                        createCategoryMutation.mutate({
                          name: categoryForm.name.trim(),
                          description:
                            categoryForm.description.trim() || null,
                          selection_mode: categoryForm.selection_mode,
                          allow_discovery: categoryForm.allow_discovery,
                          supported_surfaces: categoryForm.surfaces,
                          enabled_surfaces: categoryForm.surfaces,
                          children: cleanedChildren,
                        })
                      }}
                    >
                      Create category
                    </Button>
                  </div>
                </div>
              )}

              {/* ------------------------------------------------------------------
                  EDIT CATEGORY VIEW
                  ------------------------------------------------------------------
                  Active when ``editingMetric`` is a parent metric (see
                  ``handleEditCategory``). Mirrors the create-category
                  layout but adds:
                    - selection_mode is locked (read-only badge) so we
                      don't silently invalidate completed evaluations
                      that depend on the original mode.
                    - Each child carries a ``server_id`` (string |
                      null). null = newly added in this session and
                      will be POSTed; existing rows are PATCHed if
                      ``name`` / ``description`` / ``capture_rationale``
                      / ``enabled`` changed. Removing a child stores
                      its server id in ``deleted_child_ids`` so the
                      save handler can issue the DELETE.
              ------------------------------------------------------------------ */}
              {editingMetric && isEditingCategory && (
                <div className="space-y-5">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-5">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Category name *
                      </label>
                      <input
                        type="text"
                        value={editCategoryForm.name}
                        onChange={(e) =>
                          setEditCategoryForm((s) => ({
                            ...s,
                            name: e.target.value,
                          }))
                        }
                        className={MODERN_INPUT_CLASS}
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Selection mode
                      </label>
                      <div className="inline-flex items-center gap-2 px-3.5 py-2.5 rounded-lg border border-gray-200 bg-gray-50 text-sm text-gray-700 shadow-sm">
                        <Layers className="w-4 h-4 text-purple-600" />
                        <span className="font-medium">
                          {editCategoryForm.selection_mode === 'single_choice'
                            ? 'Single-choice'
                            : 'Multi-label'}
                        </span>
                        <span
                          className="text-[11px] text-gray-500"
                          title="Selection mode is locked after creation. Changing it can invalidate completed evaluations that depend on the original mode."
                        >
                          (locked)
                        </span>
                      </div>
                    </div>

                    <div className="md:col-span-2 rounded-xl border border-amber-200 bg-amber-50/40 p-3.5">
                      <label className="flex items-start gap-2.5 text-sm text-gray-800">
                        <input
                          type="checkbox"
                          checked={editCategoryForm.allow_discovery}
                          onChange={(e) =>
                            setEditCategoryForm((s) => ({
                              ...s,
                              allow_discovery: e.target.checked,
                            }))
                          }
                          className="mt-0.5 h-4 w-4 text-amber-600 focus:ring-amber-500 border-gray-300 rounded"
                        />
                        <span>
                          <span className="font-medium">
                            Allow LLM-discovered labels
                          </span>
                          <span className="block text-xs text-gray-600 mt-0.5">
                            Lets the LLM emit candidate sub-labels beyond
                            the ones below during call-import evaluation.
                            You can promote useful candidates into real
                            sub-labels afterwards.
                            {editCategoryForm.selection_mode === 'single_choice'
                              ? ' For single-choice categories the discovered labels are supplemental — the existing children still control the picked outcome.'
                              : ''}
                          </span>
                        </span>
                      </label>
                    </div>

                    <div className="md:col-span-2">
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Description / context for the LLM
                      </label>
                      <textarea
                        value={editCategoryForm.description}
                        onChange={(e) =>
                          setEditCategoryForm((s) => ({
                            ...s,
                            description: e.target.value,
                          }))
                        }
                        rows={3}
                        placeholder="The LLM uses this as context when scoring sub-labels below."
                        className={MODERN_INPUT_CLASS}
                      />
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <label className="block text-sm font-medium text-gray-700">
                        Sub-labels ({editCategoryForm.children.length})
                      </label>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setEditCategoryForm((s) => ({
                            ...s,
                            children: [
                              ...s.children,
                              {
                                local_id: `new-${Date.now()}-${s.children.length}`,
                                server_id: null,
                                name: '',
                                description: '',
                                capture_rationale: true,
                                enabled: true,
                              },
                            ],
                          }))
                        }
                        leftIcon={<Plus className="w-3 h-3" />}
                      >
                        Add sub-label
                      </Button>
                    </div>
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                      {editCategoryForm.children.map((child, idx) => (
                        <div
                          key={child.local_id}
                          className={`rounded-xl border p-3 space-y-2 ${
                            child.server_id
                              ? 'border-gray-200 bg-gray-50/60'
                              : 'border-emerald-200 bg-emerald-50/30'
                          }`}
                        >
                          <div className="flex items-start gap-2 flex-wrap">
                            <div className="flex-1 min-w-[12rem]">
                              <input
                                type="text"
                                value={child.name}
                                onChange={(e) =>
                                  setEditCategoryForm((s) => ({
                                    ...s,
                                    children: s.children.map((c, i) =>
                                      i === idx
                                        ? { ...c, name: e.target.value }
                                        : c,
                                    ),
                                  }))
                                }
                                placeholder="Sub-label name (e.g. happy_completion)"
                                className={MODERN_INPUT_SM_CLASS}
                              />
                            </div>
                            <label className="inline-flex items-center gap-1.5 text-xs text-gray-700 px-2.5 py-2 rounded-lg border border-gray-200 bg-white whitespace-nowrap">
                              <input
                                type="checkbox"
                                checked={child.capture_rationale}
                                onChange={(e) =>
                                  setEditCategoryForm((s) => ({
                                    ...s,
                                    children: s.children.map((c, i) =>
                                      i === idx
                                        ? {
                                            ...c,
                                            capture_rationale:
                                              e.target.checked,
                                          }
                                        : c,
                                    ),
                                  }))
                                }
                                className="h-3.5 w-3.5 text-primary-600 border-gray-300 rounded"
                              />
                              Rationale
                            </label>
                            <label className="inline-flex items-center gap-1.5 text-xs text-gray-700 px-2.5 py-2 rounded-lg border border-gray-200 bg-white whitespace-nowrap">
                              <input
                                type="checkbox"
                                checked={child.enabled}
                                onChange={(e) =>
                                  setEditCategoryForm((s) => ({
                                    ...s,
                                    children: s.children.map((c, i) =>
                                      i === idx
                                        ? { ...c, enabled: e.target.checked }
                                        : c,
                                    ),
                                  }))
                                }
                                className="h-3.5 w-3.5 text-primary-600 border-gray-300 rounded"
                              />
                              Enabled
                            </label>
                            {!child.server_id ? (
                              <span
                                className="px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide bg-emerald-100 text-emerald-800 border border-emerald-200 rounded"
                                title="This sub-label was added in this edit session and will be created on Save."
                              >
                                New
                              </span>
                            ) : null}
                            <button
                              type="button"
                              onClick={() =>
                                setEditCategoryForm((s) => {
                                  // Newly-added drafts: just splice out
                                  // (nothing to delete on the server).
                                  // Existing rows: stash the id so the
                                  // save handler can issue the DELETE
                                  // call, then remove from the visible
                                  // list.
                                  const target = s.children[idx]
                                  const remainingDrafts = s.children.filter(
                                    (_, i) => i !== idx,
                                  )
                                  return {
                                    ...s,
                                    children: remainingDrafts,
                                    deleted_child_ids: target?.server_id
                                      ? [
                                          ...s.deleted_child_ids,
                                          target.server_id,
                                        ]
                                      : s.deleted_child_ids,
                                  }
                                })
                              }
                              className="text-gray-400 hover:text-red-600 px-2 py-1.5 rounded-lg hover:bg-red-50 transition-colors"
                              title="Remove this sub-label"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                          <textarea
                            value={child.description}
                            onChange={(e) =>
                              setEditCategoryForm((s) => ({
                                ...s,
                                children: s.children.map((c, i) =>
                                  i === idx
                                    ? { ...c, description: e.target.value }
                                    : c,
                                ),
                              }))
                            }
                            rows={3}
                            placeholder="Rubric: when should the LLM mark this sub-label true?"
                            className={MODERN_INPUT_SM_CLASS}
                          />
                        </div>
                      ))}
                    </div>
                    {editCategoryForm.deleted_child_ids.length > 0 && (
                      <p className="mt-2 text-[11px] text-amber-700">
                        {editCategoryForm.deleted_child_ids.length} sub-label
                        {editCategoryForm.deleted_child_ids.length === 1
                          ? ''
                          : 's'}{' '}
                        will be deleted on Save. Past evaluation rows keep
                        their stored scores but the sub-label will no longer
                        appear in new runs.
                      </p>
                    )}
                  </div>

                  <div className="flex items-center justify-end gap-3 pt-2 border-t border-gray-100">
                    <Button variant="ghost" onClick={closeModal}>
                      Cancel
                    </Button>
                    <Button
                      variant="primary"
                      isLoading={updateCategoryMutation.isPending}
                      disabled={
                        !editCategoryForm.name.trim() ||
                        editCategoryForm.children.filter((c) =>
                          c.name.trim(),
                        ).length < 2
                      }
                      onClick={handleUpdateCategory}
                    >
                      Save changes
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------------
          MANAGE METRIC MODAL
          ------------------------------------------------------------------
          Opened either by clicking the row body or the "..." kebab on
          any metric row. Hosts Edit / Enable / Delete affordances that
          used to live in the table's Actions column — pulling them out
          keeps the table compact and makes destructive actions
          deliberate (you have to open the modal to delete).
          ------------------------------------------------------------------ */}
      {manageMetric && (() => {
        const m = manageMetric
        const isParent = !!m.selection_mode && !m.parent_metric_id
        const isChild = !!m.parent_metric_id
        const childCount = isParent
          ? (m.children || []).filter((c) => c.enabled).length
          : 0
        const canDelete = !m.is_default || isDeprecatedMetric(m.name)
        const pendingDelete =
          pendingDeleteMetric && pendingDeleteMetric.id === m.id
        return (
          <div className="fixed inset-0 z-50 overflow-y-auto">
            <div className="flex min-h-screen items-center justify-center p-4">
              <div
                className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
                onClick={() => {
                  setManageMetric(null)
                  setPendingDeleteMetric(null)
                }}
              />
              <div className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6">
                <div className="flex items-start justify-between mb-3">
                  <div className="min-w-0">
                    <p className="text-[11px] uppercase tracking-wide font-semibold text-gray-500">
                      Manage metric
                    </p>
                    <h2 className="text-lg font-bold text-gray-900 truncate">
                      {m.name}
                    </h2>
                  </div>
                  <button
                    onClick={() => {
                      setManageMetric(null)
                      setPendingDeleteMetric(null)
                    }}
                    className="text-gray-400 hover:text-gray-500"
                    aria-label="Close"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>

                <div className="mb-4 space-y-1.5">
                  <div className="flex items-center gap-2 flex-wrap text-xs">
                    {isParent && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 font-semibold uppercase tracking-wide bg-purple-100 text-purple-800 rounded">
                        <Layers className="w-3 h-3" />
                        {m.selection_mode === 'single_choice'
                          ? 'Single-choice'
                          : 'Multi-label'}
                        <span className="ml-0.5 px-1 py-0.5 bg-purple-200 text-purple-900 rounded text-[10px]">
                          {childCount}
                        </span>
                      </span>
                    )}
                    {isChild && (
                      <span className="px-2 py-0.5 font-medium bg-gray-100 text-gray-700 rounded">
                        Sub-label
                      </span>
                    )}
                    {m.is_default && (
                      <span className="px-2 py-0.5 bg-blue-100 text-blue-800 rounded">
                        Default
                      </span>
                    )}
                    {isParent && m.allow_discovery && (
                      <span className="px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide bg-amber-50 text-amber-700 border border-amber-200 rounded">
                        Auto-discover
                      </span>
                    )}
                  </div>
                  {m.description && (
                    <p className="text-sm text-gray-600 line-clamp-3">
                      {m.description}
                    </p>
                  )}
                </div>

                {!pendingDelete ? (
                  <div className="flex flex-col gap-2">
                    <Button
                      variant="primary"
                      leftIcon={<Edit className="w-4 h-4" />}
                      onClick={() => {
                        setManageMetric(null)
                        handleEdit(m)
                      }}
                    >
                      {isParent
                        ? 'Edit category & sub-labels'
                        : 'Edit metric'}
                    </Button>
                    <Button
                      variant="secondary"
                      leftIcon={
                        m.enabled ? (
                          <ToggleRight className="w-4 h-4" />
                        ) : (
                          <ToggleLeft className="w-4 h-4" />
                        )
                      }
                      onClick={() => handleToggleEnabled(m)}
                      isLoading={toggleEnabledMutation.isPending}
                    >
                      {m.enabled ? 'Disable' : 'Enable'}
                    </Button>
                    {canDelete ? (
                      <Button
                        variant="outline"
                        leftIcon={<Trash2 className="w-4 h-4" />}
                        onClick={() => setPendingDeleteMetric(m)}
                      >
                        Delete
                      </Button>
                    ) : (
                      <p className="text-xs text-gray-500 px-1 mt-1">
                        Default metrics cannot be deleted.
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="rounded border border-red-200 bg-red-50/60 p-3 space-y-3">
                    <div className="flex items-start gap-2">
                      <AlertTriangle className="w-4 h-4 text-red-600 mt-0.5 flex-shrink-0" />
                      <div className="text-sm text-red-800">
                        <p className="font-semibold">Delete "{m.name}"?</p>
                        <p className="mt-1 text-xs text-red-700">
                          {isParent && childCount > 0 ? (
                            <>
                              This category has {childCount} sub-label
                              {childCount === 1 ? '' : 's'}, all of which
                              will also be deleted. Past evaluation rows
                              keep their stored scores, but new runs will
                              no longer reference this category.
                            </>
                          ) : isDeprecatedMetric(m.name) ? (
                            <>
                              This is a deprecated default metric. Removal
                              is permanent.
                            </>
                          ) : (
                            <>This action cannot be undone.</>
                          )}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setPendingDeleteMetric(null)}
                      >
                        Cancel
                      </Button>
                      <Button
                        variant="primary"
                        size="sm"
                        isLoading={deleteMutation.isPending}
                        onClick={() => handleConfirmDelete(m)}
                        className="!bg-red-600 hover:!bg-red-700"
                      >
                        Delete permanently
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )
      })()}

      {/* Enable Metrics Modal */}
      {showEnableModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
              onClick={() => {
                setShowEnableModal(false)
                setSelectedDisabledMetricIds(new Set())
              }}
            />
            <div className="relative bg-white rounded-lg shadow-xl max-w-3xl w-full p-6 max-h-[90vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-2">
                <h2 className="text-2xl font-bold text-gray-900">Add Metrics</h2>
                <button
                  onClick={() => {
                    setShowEnableModal(false)
                    setSelectedDisabledMetricIds(new Set())
                  }}
                  className="text-gray-400 hover:text-gray-500"
                >
                  <X className="h-6 w-6" />
                </button>
              </div>
              <p className="text-sm text-gray-600 mb-5">
                Choose from disabled metrics below to enable them. Each metric includes its purpose and evaluation method.
              </p>

              {disabledMetrics.length === 0 ? (
                <div className="border border-gray-200 rounded-lg p-8 text-center text-gray-500">
                  All metrics are currently enabled.
                </div>
              ) : (
                <div className="space-y-3">
                  {disabledMetrics.map((metric: Metric) => {
                    const isAudio = isAudioMetric(metric.name)
                    const isQuantitative = isQuantitativeMetric(metric.name)
                    const isSelected = selectedDisabledMetricIds.has(metric.id)

                    return (
                      <label
                        key={metric.id}
                        className={`flex items-start gap-3 border rounded-lg p-4 cursor-pointer transition-colors ${isSelected ? 'border-primary-300 bg-primary-50' : 'border-gray-200 hover:bg-gray-50'
                          }`}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleDisabledMetricSelection(metric.id)}
                          className="mt-0.5 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <p className="text-sm font-semibold text-gray-900">{metric.name}</p>
                            <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${isQuantitative ? 'bg-blue-100 text-blue-800' : 'bg-amber-100 text-amber-800'}`}>
                              {isQuantitative ? 'Quantitative' : 'Qualitative'}
                            </span>
                            {isAIVoiceMetric(metric.name) ? (
                              <span className="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-800 rounded-full">
                                <Sparkles className="w-3 h-3 mr-1" />
                                AI Voice
                              </span>
                            ) : isAudio ? (
                              <span className="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-violet-100 text-violet-800 rounded-full">
                                <AudioWaveform className="w-3 h-3 mr-1" />
                                Acoustic
                              </span>
                            ) : (
                              <span className="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-emerald-100 text-emerald-800 rounded-full">
                                <Brain className="w-3 h-3 mr-1" />
                                LLM
                              </span>
                            )}
                          </div>
                          <p className="mt-1 text-sm text-gray-600">{metric.description || 'No description available.'}</p>
                        </div>
                      </label>
                    )
                  })}
                </div>
              )}

              <div className="flex justify-end space-x-3 pt-6">
                <Button
                  variant="ghost"
                  onClick={() => {
                    setShowEnableModal(false)
                    setSelectedDisabledMetricIds(new Set())
                  }}
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  onClick={handleEnableSelectedMetrics}
                  isLoading={enableMetricsMutation.isPending}
                  disabled={selectedDisabledMetricIds.size === 0}
                >
                  Enable Selected ({selectedDisabledMetricIds.size})
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* The "Bulk Create Metrics" and "Create Category" flows are now
          rendered inside the unified showCreateModal above, switched by
          createMode. */}

    </div>
  )
}


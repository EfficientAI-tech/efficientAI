import { Fragment, useState, useEffect, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../lib/api'
import { getApiErrorMessage } from '../../lib/apiErrors'
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
  Layers,
  AlertTriangle,
} from 'lucide-react'
import {
  categoryChildrenFromPartial,
  createCategoryChildrenFromPartial,
  formatMetricPartialPreview,
  metricPartialHasSaveableContent,
  parseMetricPartialContent,
  serializeMetricPartialContent,
  type MetricPartialContent,
} from '../promptPartials/metricPartialUtils'

interface Metric {
  id: string
  name: string
  // ``null`` when this metric is shared org-wide (``scope ===
  // 'organization'``); a real UUID when it's pinned to a specific
  // workspace (the default).
  workspace_id?: string | null
  // Convenience field computed by the backend so the UI doesn't have
  // to check ``workspace_id == null`` everywhere.
  scope?: 'workspace' | 'organization'
  description?: string
  /**
   * Optional illustrative example. Populated mainly on categorization
   * child labels (via the Categorization Labels editor's "Example
   * (Optional)" field) but accepted on every metric.
   */
  example?: string | null
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
   * When true, this metric is a "transcript-compare judge": at
   * call-import evaluation time the worker feeds BOTH the production
   * and diarised transcripts to the LLM as a labeled pair and the
   * run's transcript_source toggle is ignored for this metric.
   * Mutually exclusive with parent_metric_id and selection_mode
   * (server enforces).
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

function buildMetricPartialContentForTarget(
  target: 'single' | 'category' | 'edit_category',
  formData: { description: string },
  categoryForm: {
    description: string
    children: Array<{ name: string; description: string; example: string }>
  },
  editCategoryForm: {
    description: string
    children: Array<{ name: string; description: string; example: string }>
  },
): MetricPartialContent {
  if (target === 'single') {
    return {
      schema_version: 1,
      metric_kind: 'single',
      description: formData.description.trim(),
    }
  }
  const source = target === 'category' ? categoryForm : editCategoryForm
  return {
    schema_version: 1,
    metric_kind: 'category',
    description: source.description.trim(),
    children: source.children
      .filter((child) => child.name.trim())
      .map((child) => ({
        name: child.name.trim(),
        description: child.description.trim(),
        example: child.example.trim(),
      })),
  }
}

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
  // Categorization Labels create form. Mirrors the "Manage Categorization
  // Labels" screen: name + description (acts as the LLM Prompt) + N
  // labels with name/definition/example, plus an "Enable LLM Rationale"
  // toggle that propagates to every child (we re-use the existing
  // MetricChildDraft.capture_rationale so the prompt builder picks
  // rationales up without extra wiring).
  //
  // ``selection_mode`` is hardcoded to ``single_choice`` server-side so
  // the CSV export emits ONE column per metric whose row value is the
  // chosen label's name. ``allow_discovery`` is hardcoded false: the
  // simplified UI no longer surfaces it.
  const [categoryForm, setCategoryForm] = useState<{
    name: string
    description: string
    surfaces: MetricSurface[]
    capture_rationale: boolean
    // CREATE-time visibility scope (same semantics as ``formData.scope``).
    // Inherited by every child of the new category.
    scope: 'workspace' | 'organization'
    children: Array<{
      local_id: string
      name: string
      description: string
      example: string
    }>
  }>({
    name: '',
    description: '',
    surfaces: ['agent'],
    capture_rationale: false,
    scope: 'workspace',
    children: [
      { local_id: 'c1', name: '', description: '', example: '' },
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
    example: string
    enabled: boolean
  }
  const [editCategoryForm, setEditCategoryForm] = useState<{
    name: string
    description: string
    // Selection mode lives here only so the save handler can avoid
    // sending it in the PUT (the server rejects flipping it on a
    // metric with completed evaluations). The simplified UI no longer
    // surfaces a picker.
    selection_mode: 'single_choice' | 'multi_label'
    surfaces: MetricSurface[]
    // Metric-level rationale toggle. Mirrors the create flow: on save
    // it propagates uniformly to every child's capture_rationale.
    capture_rationale: boolean
    children: EditCategoryChild[]
    deleted_child_ids: string[]
  }>({
    name: '',
    description: '',
    selection_mode: 'single_choice',
    surfaces: ['agent'],
    capture_rationale: false,
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
    // When true, the worker scores this metric against BOTH the
    // production and diarised transcripts on each call-import row.
    // Unavailable on parent / child metrics. The Run Evaluation
    // transcript_source toggle is ignored for these metrics —
    // they always read both.
    compare_transcripts: false,
    // Visibility scope. ``'workspace'`` (default) pins the metric to
    // the currently active workspace via X-Workspace-Id; ``'organization'``
    // stores it with workspace_id=NULL so it shows up in every
    // workspace of the org. Only honoured by the CREATE endpoints —
    // the edit form does not surface this toggle (changing scope
    // post-creation would break uniqueness invariants and so is not
    // supported in this iteration).
    scope: 'workspace' as 'workspace' | 'organization',
  })

  // --- Prompt-partial import sub-modal --------------------------------------
  // The metric editors carry several "Description (Prompt)" textareas that
  // all feed into the LLM evaluation prompt: the single-metric form
  // (``formData.description``), the create-category form
  // (``categoryForm.description``), and the edit-category form
  // (``editCategoryForm.description``). Rather than duplicate a partials
  // picker per spot, we route a single picker through ``partialsImportTarget``
  // so opening any of the three "Import from saved partials" links shows the
  // same modal and the success path injects the partial's content into the
  // textarea the user originated from. Mirrors the pattern already shipped on
  // [`CallImportDetail`](frontend/src/pages/callImports/CallImportDetail.tsx).
  const [partialsImportTarget, setPartialsImportTarget] = useState<
    'single' | 'category' | 'edit_category' | null
  >(null)
  const [partialsSearchInput, setPartialsSearchInput] = useState('')
  const [partialsSearchQuery, setPartialsSearchQuery] = useState('')
  const [selectedPartialId, setSelectedPartialId] = useState<string>('')
  const [partialsImportError, setPartialsImportError] = useState<
    string | null
  >(null)

  // --- Prompt-partial SAVE sub-modal ----------------------------------------
  // Mirror of the import picker, except the data flow is reversed: the
  // currently-edited Description textarea content is pushed back into the
  // Prompt Partials library. ``savePartialTarget`` decides which form's
  // description sources the content; ``savePartialMode`` picks between
  // creating a brand-new partial vs appending a new version to an existing
  // one.
  const [savePartialTarget, setSavePartialTarget] = useState<
    'single' | 'category' | 'edit_category' | null
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

  // Debounce the partials-search input so we don't refire the list query on
  // every keystroke while the import sub-modal is open.
  useEffect(() => {
    const handle = setTimeout(() => {
      setPartialsSearchQuery(partialsSearchInput.trim())
    }, 250)
    return () => clearTimeout(handle)
  }, [partialsSearchInput])

  const { data: promptPartials = [], isLoading: isLoadingPartials } = useQuery<
    Array<{ id: string; name: string; description?: string | null }>
  >({
    queryKey: ['metrics-prompt-partials', partialsSearchQuery],
    queryFn: () =>
      apiClient.listPromptPartials(
        0,
        100,
        partialsSearchQuery ? partialsSearchQuery : undefined,
        'metric',
      ),
    enabled:
      partialsImportTarget !== null ||
      (savePartialTarget !== null && savePartialMode === 'existing'),
  })

  // Apply the chosen partial's content to whichever textarea opened the
  // picker, then close. We fetch the full partial body on-demand because
  // ``listPromptPartials`` only returns the index card (name + description),
  // not the prompt content itself.
  const importPartialMutation = useMutation({
    mutationFn: (partialId: string) => apiClient.getPromptPartial(partialId),
    onSuccess: (partial) => {
      const parsed = parseMetricPartialContent(
        ((partial?.content as string | undefined) || '').trim(),
      )
      const { content, isLegacyPlainText } = parsed

      if (partialsImportTarget === 'single') {
        if (!isLegacyPlainText && content.metric_kind === 'category') {
          setPartialsImportError(
            'Selected partial is for categorization labels. Import it from the category form instead.',
          )
          return
        }
        setFormData((prev) => ({ ...prev, description: content.description }))
      } else if (partialsImportTarget === 'category') {
        if (!isLegacyPlainText && content.metric_kind === 'single') {
          setPartialsImportError(
            'Selected partial is for a single metric. Import it from the single metric form instead.',
          )
          return
        }
        setCategoryForm((prev) => ({
          ...prev,
          description: content.description,
          children: createCategoryChildrenFromPartial(content.children),
        }))
      } else if (partialsImportTarget === 'edit_category') {
        if (!isLegacyPlainText && content.metric_kind === 'single') {
          setPartialsImportError(
            'Selected partial is for a single metric. Import it from the single metric form instead.',
          )
          return
        }
        setEditCategoryForm((prev) => {
          const deletedIds = prev.children
            .map((child) => child.server_id)
            .filter((id): id is string => !!id)
          return {
            ...prev,
            description: content.description,
            children: categoryChildrenFromPartial(content.children, 'edit'),
            deleted_child_ids: [...new Set([...prev.deleted_child_ids, ...deletedIds])],
          }
        })
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

  const openPartialsImport = (
    target: 'single' | 'category' | 'edit_category',
  ) => {
    setPartialsImportError(null)
    setSelectedPartialId('')
    setPartialsSearchInput('')
    setPartialsSearchQuery('')
    setPartialsImportTarget(target)
  }

  const closePartialsImport = () => {
    if (importPartialMutation.isPending) return
    setPartialsImportTarget(null)
    setPartialsSearchInput('')
    setPartialsSearchQuery('')
    setSelectedPartialId('')
    setPartialsImportError(null)
  }

  // Push the currently-edited Description back into the Prompt Partials
  // library. ``new`` POSTs a fresh partial, ``existing`` PUTs against the
  // selected partial which appends a new version row to its history.
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
        return apiClient.createMetricPartial({
          name: input.name || 'Untitled metric partial',
          description: input.description || undefined,
          content: input.content,
        })
      }
      return apiClient.updateMetricPartial(input.partialId!, {
        content: input.content,
        change_summary: input.changeSummary || undefined,
      })
    },
    onSuccess: (partial: any) => {
      queryClient.invalidateQueries({
        queryKey: ['metrics-prompt-partials'],
      })
      const label =
        partial?.name || (savePartialMode === 'new' ? 'new metric partial' : 'metric partial')
      setSavePartialSuccess(
        savePartialMode === 'new'
          ? `Saved as new metric partial “${label}”.`
          : `Updated metric partial “${label}” (new version saved).`,
      )
      setSavePartialError(null)
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

  const openSavePartial = (
    target: 'single' | 'category' | 'edit_category',
  ) => {
    // Pre-fill the name with the metric name the user is editing so the
    // partial card has a sensible default. The user can override it before
    // hitting "Create Partial".
    const seedName =
      target === 'single'
        ? formData.name
        : target === 'category'
          ? categoryForm.name
          : editCategoryForm.name
    setSavePartialTarget(target)
    setSavePartialMode('new')
    setSavePartialName(seedName || '')
    setSavePartialDescription('')
    setSavePartialChangeSummary('')
    setSavePartialExistingId('')
    setSavePartialError(null)
    setSavePartialSuccess(null)
    setPartialsSearchInput('')
    setPartialsSearchQuery('')
  }

  const closeSavePartial = () => {
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

  const { data: metrics = [], isLoading } = useQuery({
    queryKey: ['metrics', activeWorkspaceId, surfaceFilter],
    queryFn: () => apiClient.listMetrics(surfaceFilter === 'all' ? undefined : surfaceFilter),
  })

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
    onError: (err: unknown) => {
      showToast(getApiErrorMessage(err, 'Failed to delete metric'), 'error')
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
      // Parent-level rationale toggle. Children never carry their own
      // rationale in hierarchical mode — the parent owns the single
      // rationale column.
      capture_rationale?: boolean
      supported_surfaces: string[]
      enabled_surfaces: string[]
      children: Array<{
        name: string
        description?: string | null
        capture_rationale?: boolean
        enabled?: boolean
      }>
      // CREATE-time visibility scope. ``'organization'`` writes the
      // parent + every child with workspace_id=NULL so the whole
      // category subtree appears in every workspace.
      scope?: 'workspace' | 'organization'
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
        // Parent-level rationale toggle (children never carry their own
        // rationale in hierarchical mode).
        capture_rationale: boolean
        supported_surfaces: string[]
        enabled_surfaces: string[]
      }
      childrenToUpdate: Array<{
        id: string
        name: string
        description?: string | null
        example?: string | null
        capture_rationale: boolean
        enabled: boolean
      }>
      childrenToCreate: Array<{
        name: string
        description?: string | null
        example?: string | null
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
            // Send the example explicitly (including "" to clear) so
            // the backend's "None = leave unchanged" rule still lets
            // the user wipe a previously stored example.
            example: child.example ?? '',
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
            example: child.example ?? undefined,
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
      surfaces: ['agent'],
      capture_rationale: false,
      scope: 'workspace',
      children: [
        { local_id: 'c1', name: '', description: '', example: '' },
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
      compare_transcripts: false,
      scope: 'workspace',
    })
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
      // Transcript-compare judge metrics live alongside standalone
      // transcript metrics. The server rejects the flag on child
      // sub-metrics and parents (selection_mode set), so we only
      // forward it for standalone rows where the toggle could
      // legitimately be on. ``buildPayload`` is also used by the
      // create flow (no editingMetric yet) — there the flag is
      // always forwarded since the body is a fresh row.
      ...((!editingMetric
        || (!editingMetric.parent_metric_id
          && !editingMetric.selection_mode))
        ? { compare_transcripts: !!formData.compare_transcripts }
        : {}),
      // Scope is a CREATE-time decision (the row is stored with a
      // workspace_id of either the active UUID or NULL). PUT /metrics
      // does not accept ``scope``, so we omit it when editing to keep
      // the body honest.
      ...(!editingMetric ? { scope: formData.scope } : {}),
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
      compare_transcripts: !!metric.compare_transcripts,
      // Mirror the persisted scope so the form state is honest, even
      // though the edit UI doesn't expose a scope picker.
      scope:
        metric.scope ||
        (metric.workspace_id == null ? 'organization' : 'workspace'),
    })
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
        example: child.example || '',
        enabled: child.enabled,
      }),
    )
    // Seed the metric-level rationale toggle from the parent's own
    // ``capture_rationale`` flag — the LLM emits a single parent-level
    // rationale, so the parent row is the source of truth. We fall back
    // to ``children.some(c.capture_rationale)`` for legacy parents that
    // never had the flag set on the parent (the 034 migration backfills
    // those, but be defensive in case the migration hasn't run yet).
    const inheritedRationale =
      !!parent.capture_rationale ||
      (parent.children || []).some((c) => !!c.capture_rationale)
    setEditCategoryForm({
      name: parent.name,
      description: parent.description || '',
      selection_mode:
        (parent.selection_mode as 'single_choice' | 'multi_label') ||
        'single_choice',
      surfaces: (parent.supported_surfaces?.length
        ? parent.supported_surfaces
        : ['agent']) as MetricSurface[],
      capture_rationale: inheritedRationale,
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
      alert('Please enter a metric name')
      return
    }
    const namedChildren = editCategoryForm.children.filter((c) =>
      c.name.trim(),
    )
    if (namedChildren.length < 1) {
      alert('Please add at least one named label')
      return
    }
    // Parent-level rationale toggle goes on the parent payload only.
    // Children always send ``capture_rationale: false`` because the LLM
    // emits a single parent rationale per categorization — the server
    // also coerces child capture_rationale to false defensively.
    const childrenToUpdate = namedChildren
      .filter((c) => !!c.server_id)
      .map((c) => ({
        id: c.server_id as string,
        name: c.name.trim(),
        description: c.description.trim() || null,
        example: c.example.trim(),
        capture_rationale: false,
        enabled: c.enabled,
      }))
    const childrenToCreate = namedChildren
      .filter((c) => !c.server_id)
      .map((c) => ({
        name: c.name.trim(),
        description: c.description.trim() || null,
        example: c.example.trim() || null,
        capture_rationale: false,
        enabled: c.enabled,
      }))
    updateCategoryMutation.mutate({
      parentId: editingMetric.id,
      parent: {
        name: editCategoryForm.name.trim(),
        description: editCategoryForm.description.trim() || null,
        // The simplified UI no longer surfaces allow_discovery. Force
        // false so a re-save on an older legacy parent also turns it
        // off, keeping the post-save UX honest.
        allow_discovery: false,
        capture_rationale: editCategoryForm.capture_rationale,
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
                compare_transcripts: false,
                scope: 'workspace',
              })
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
                            {/* Org-shared marker: surfaces only when
                                the metric has no workspace association
                                (``scope === 'organization'`` / NULL
                                workspace_id). Same row will appear in
                                every workspace, so the badge tells
                                users "editing this affects everyone in
                                the org". */}
                            {(metric.scope === 'organization' ||
                              metric.workspace_id == null) && (
                              <span
                                className="px-2 py-0.5 text-xs font-semibold uppercase tracking-wide bg-indigo-100 text-indigo-800 rounded"
                                title="This metric is shared across every workspace in the organization."
                              >
                                Shared
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
                              {child.example ? (
                                <div
                                  className="mt-0.5 text-[11px] text-gray-400 max-w-md truncate italic"
                                  title={child.example}
                                >
                                  e.g. {child.example}
                                </div>
                              ) : null}
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
                      ? `Manage Categorization Labels for: ${editingMetric.name}`
                      : 'Edit Metric'
                    : createMode === 'category'
                      ? `Manage Categorization Labels${categoryForm.name.trim() ? ` for: ${categoryForm.name.trim()}` : ''}`
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
                        { id: 'category', label: 'Categorization Labels' },
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
                      : 'Create a metric with N labels. On a CSV-import evaluation the metric becomes one column whose row value is the LLM-chosen label name.'}
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
                    <div className="flex items-center justify-between mb-2">
                      <label className="block text-sm font-medium text-gray-700">
                        Description
                      </label>
                      <div className="flex items-center gap-3">
                        <button
                          type="button"
                          onClick={() => openPartialsImport('single')}
                          className="inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:text-primary-700"
                        >
                          <Layers className="w-3.5 h-3.5" />
                          Import metric partial
                        </button>
                        <button
                          type="button"
                          onClick={() => openSavePartial('single')}
                          disabled={
                            !metricPartialHasSaveableContent(
                              buildMetricPartialContentForTarget(
                                'single',
                                formData,
                                categoryForm,
                                editCategoryForm,
                              ),
                            )
                          }
                          title="Save the current metric prompt to your metric partials library"
                          className="inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:text-primary-700 disabled:text-gray-400 disabled:cursor-not-allowed"
                        >
                          <Layers className="w-3.5 h-3.5" />
                          Save metric partial
                        </button>
                      </div>
                    </div>
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
                    Call Imports configuration: previously housed a
                    per-metric "Input columns" picker that turned the
                    metric into a "column-input judge". The product
                    now always injects EVERY non-empty CSV column
                    into the evaluation prompt for every metric (see
                    ``_build_all_columns_block`` in the call-import
                    worker), so a per-metric column allow-list is
                    redundant and was removed.
                  */}
                  {/* end of removed Input-columns picker block */}

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
                  {/* Visibility scope picker. Only meaningful at
                      CREATE time — the metrics API does not support
                      flipping a row between workspace and org scope
                      after the fact (would break the partial unique
                      indexes added in migration 041). We hide the
                      picker when editing so users don't expect to
                      be able to change it. */}
                  {!editingMetric && (
                    <div className="lg:col-span-2 rounded-xl border border-gray-200 bg-gray-50/70 p-3.5">
                      <span className="block text-sm font-medium text-gray-700 mb-2">
                        Available in
                      </span>
                      <div className="space-y-2">
                        <label className="flex items-start gap-2.5 cursor-pointer">
                          <input
                            type="radio"
                            name="metric-scope"
                            value="workspace"
                            checked={formData.scope === 'workspace'}
                            onChange={() =>
                              setFormData({ ...formData, scope: 'workspace' })
                            }
                            className="mt-0.5 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300"
                          />
                          <span className="text-sm text-gray-800">
                            <span className="font-medium">This workspace only</span>
                            <span className="block text-xs text-gray-500 mt-0.5">
                              The metric is created inside the currently
                              active workspace and is invisible to other
                              workspaces in this organization.
                            </span>
                          </span>
                        </label>
                        <label className="flex items-start gap-2.5 cursor-pointer">
                          <input
                            type="radio"
                            name="metric-scope"
                            value="organization"
                            checked={formData.scope === 'organization'}
                            onChange={() =>
                              setFormData({ ...formData, scope: 'organization' })
                            }
                            className="mt-0.5 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300"
                          />
                          <span className="text-sm text-gray-800">
                            <span className="font-medium">All workspaces in this organization</span>
                            <span className="block text-xs text-gray-500 mt-0.5">
                              The metric is shared org-wide and shows up in
                              every workspace's metric list. Pick this for
                              standard metrics you want to reuse without
                              recreating them per workspace.
                            </span>
                          </span>
                        </label>
                      </div>
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
                  {/* Metric-level fields: Name + Description (the LLM
                      Prompt) + Enable LLM Rationale toggle. Selection
                      mode and allow-discovery are not surfaced here —
                      every new categorization metric is single-choice
                      under the hood so the CSV export emits ONE column
                      whose value is the chosen label name. */}
                  <p className="text-sm text-gray-600">
                    Add, edit, or remove specific labels with definitions
                    and examples for this evaluation parameter.
                  </p>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-5">
                    <div className="md:col-span-2">
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Metric name *
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

                    <div className="md:col-span-2">
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Description (Prompt)
                      </label>
                      <textarea
                        value={categoryForm.description}
                        onChange={(e) =>
                          setCategoryForm((s) => ({ ...s, description: e.target.value }))
                        }
                        rows={3}
                        placeholder="Tell the LLM what this metric measures. The labels below are the possible outcomes."
                        className={MODERN_INPUT_CLASS}
                      />
                    </div>

                    {/* Enable LLM Rationale toggle. The flag is stored
                        on every child (via MetricChildDraft.capture_rationale)
                        so the existing rationale-key emit logic in
                        _render_parent_block picks it up without any
                        prompt-builder changes. */}
                    <div className="md:col-span-2 rounded-xl border border-gray-200 bg-gray-50/70 p-3.5">
                      <label className="flex items-start gap-2.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={categoryForm.capture_rationale}
                          onChange={(e) =>
                            setCategoryForm((s) => ({
                              ...s,
                              capture_rationale: e.target.checked,
                            }))
                          }
                          className="mt-0.5 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                        />
                        <span className="text-sm text-gray-800">
                          <span className="font-medium">Enable LLM Rationale</span>
                          <span className="block text-xs text-gray-500 mt-0.5">
                            Ask the LLM to also return a 1-2 sentence
                            reason for the chosen label. Adds a{' '}
                            <code className="px-1 py-0.5 bg-white border border-gray-200 rounded text-[11px]">
                              &lt;Name&gt; - LLM Rationale
                            </code>{' '}
                            column to the call-import CSV export.
                          </span>
                        </span>
                      </label>
                    </div>

                    {/* Visibility scope picker. Same shape + semantics
                        as the single-metric scope picker — the parent
                        and every child inherit the chosen scope. */}
                    <div className="md:col-span-2 rounded-xl border border-gray-200 bg-gray-50/70 p-3.5">
                      <span className="block text-sm font-medium text-gray-700 mb-2">
                        Available in
                      </span>
                      <div className="space-y-2">
                        <label className="flex items-start gap-2.5 cursor-pointer">
                          <input
                            type="radio"
                            name="category-scope"
                            value="workspace"
                            checked={categoryForm.scope === 'workspace'}
                            onChange={() =>
                              setCategoryForm((s) => ({ ...s, scope: 'workspace' }))
                            }
                            className="mt-0.5 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300"
                          />
                          <span className="text-sm text-gray-800">
                            <span className="font-medium">This workspace only</span>
                            <span className="block text-xs text-gray-500 mt-0.5">
                              The category and all of its labels are created
                              inside the currently active workspace.
                            </span>
                          </span>
                        </label>
                        <label className="flex items-start gap-2.5 cursor-pointer">
                          <input
                            type="radio"
                            name="category-scope"
                            value="organization"
                            checked={categoryForm.scope === 'organization'}
                            onChange={() =>
                              setCategoryForm((s) => ({ ...s, scope: 'organization' }))
                            }
                            className="mt-0.5 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300"
                          />
                          <span className="text-sm text-gray-800">
                            <span className="font-medium">All workspaces in this organization</span>
                            <span className="block text-xs text-gray-500 mt-0.5">
                              The category subtree is shared org-wide and
                              shows up in every workspace's metric list.
                            </span>
                          </span>
                        </label>
                      </div>
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-2 gap-3">
                      <label className="block text-sm font-medium text-gray-700">
                        Categorization Labels ({categoryForm.children.length})
                      </label>
                      <div className="flex items-center gap-3 shrink-0">
                        <button
                          type="button"
                          onClick={() => openPartialsImport('category')}
                          className="inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:text-primary-700"
                        >
                          <Layers className="w-3.5 h-3.5" />
                          Import metric partial
                        </button>
                        <button
                          type="button"
                          onClick={() => openSavePartial('category')}
                          disabled={
                            !metricPartialHasSaveableContent(
                              buildMetricPartialContentForTarget(
                                'category',
                                formData,
                                categoryForm,
                                editCategoryForm,
                              ),
                            )
                          }
                          title="Save the full category prompt and all labels to metric partials"
                          className="inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:text-primary-700 disabled:text-gray-400 disabled:cursor-not-allowed"
                        >
                          <Layers className="w-3.5 h-3.5" />
                          Save metric partial
                        </button>
                      </div>
                    </div>
                    <div className="space-y-3">
                      {categoryForm.children.map((child, idx) => (
                        <div
                          key={child.local_id}
                          className="border border-gray-200 rounded-xl p-4 space-y-3 bg-gray-50/60"
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-semibold text-gray-800">
                              Label #{idx + 1}
                            </span>
                            {categoryForm.children.length > 1 && (
                              <button
                                type="button"
                                onClick={() =>
                                  setCategoryForm((s) => ({
                                    ...s,
                                    children: s.children.filter((_, i) => i !== idx),
                                  }))
                                }
                                className="inline-flex items-center justify-center w-7 h-7 rounded-full border border-red-200 text-red-500 hover:text-red-700 hover:bg-red-50 transition-colors"
                                title="Remove label"
                                aria-label={`Remove label ${idx + 1}`}
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            )}
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-gray-700 mb-1">
                              Label Name
                            </label>
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
                              placeholder="e.g. happy_completion"
                              className={MODERN_INPUT_SM_CLASS}
                            />
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-gray-700 mb-1">
                              Label Definition
                            </label>
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
                              rows={2}
                              placeholder="Define this specific label..."
                              className={MODERN_INPUT_SM_CLASS}
                            />
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-gray-700 mb-1">
                              Example (Optional)
                            </label>
                            <textarea
                              value={child.example}
                              onChange={(e) =>
                                setCategoryForm((s) => ({
                                  ...s,
                                  children: s.children.map((c, i) =>
                                    i === idx
                                      ? { ...c, example: e.target.value }
                                      : c,
                                  ),
                                }))
                              }
                              rows={2}
                              placeholder="Provide an illustrative example for this label..."
                              className={MODERN_INPUT_SM_CLASS}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                    <button
                      type="button"
                      onClick={() =>
                        setCategoryForm((s) => ({
                          ...s,
                          children: [
                            ...s.children,
                            {
                              local_id: `c-${Date.now()}-${s.children.length + 1}`,
                              name: '',
                              description: '',
                              example: '',
                            },
                          ],
                        }))
                      }
                      className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-primary-600 hover:text-primary-700"
                    >
                      <Plus className="w-4 h-4" />
                      Add New Label
                    </button>
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
                        categoryForm.children.filter((c) => c.name.trim()).length < 1
                      }
                      onClick={() => {
                        // Parent-level capture_rationale is now sent on
                        // the PARENT payload (the LLM emits one
                        // rationale per category, never per child). The
                        // server forces every child to
                        // capture_rationale=false regardless of what we
                        // send, but we still set it explicitly here so
                        // the request body reads honestly.
                        const cleanedChildren = categoryForm.children
                          .filter((c) => c.name.trim())
                          .map((c) => ({
                            name: c.name.trim(),
                            description: c.description.trim() || null,
                            example: c.example.trim() || null,
                            capture_rationale: false,
                            enabled: true,
                          }))
                        createCategoryMutation.mutate({
                          name: categoryForm.name.trim(),
                          description:
                            categoryForm.description.trim() || null,
                          // Always single_choice for the new flow.
                          selection_mode: 'single_choice',
                          allow_discovery: false,
                          capture_rationale: categoryForm.capture_rationale,
                          supported_surfaces: categoryForm.surfaces,
                          enabled_surfaces: categoryForm.surfaces,
                          children: cleanedChildren,
                          scope: categoryForm.scope,
                        })
                      }}
                    >
                      Save Labels
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
                  <p className="text-sm text-gray-600">
                    Add, edit, or remove specific labels with definitions
                    and examples for this evaluation parameter.
                  </p>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-5">
                    <div className="md:col-span-2">
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Metric name *
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

                    <div className="md:col-span-2">
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Description (Prompt)
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
                        placeholder="Tell the LLM what this metric measures. The labels below are the possible outcomes."
                        className={MODERN_INPUT_CLASS}
                      />
                    </div>

                    <div className="md:col-span-2 rounded-xl border border-gray-200 bg-gray-50/70 p-3.5">
                      <label className="flex items-start gap-2.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={editCategoryForm.capture_rationale}
                          onChange={(e) =>
                            setEditCategoryForm((s) => ({
                              ...s,
                              capture_rationale: e.target.checked,
                            }))
                          }
                          className="mt-0.5 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                        />
                        <span className="text-sm text-gray-800">
                          <span className="font-medium">Enable LLM Rationale</span>
                          <span className="block text-xs text-gray-500 mt-0.5">
                            Ask the LLM to also return a 1-2 sentence
                            reason for the chosen label. Adds a{' '}
                            <code className="px-1 py-0.5 bg-white border border-gray-200 rounded text-[11px]">
                              &lt;Name&gt; - LLM Rationale
                            </code>{' '}
                            column to the call-import CSV export.
                          </span>
                        </span>
                      </label>
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-2 gap-3">
                      <label className="block text-sm font-medium text-gray-700">
                        Categorization Labels ({editCategoryForm.children.length})
                      </label>
                      <div className="flex items-center gap-3 shrink-0">
                        <button
                          type="button"
                          onClick={() => openPartialsImport('edit_category')}
                          className="inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:text-primary-700"
                        >
                          <Layers className="w-3.5 h-3.5" />
                          Import metric partial
                        </button>
                        <button
                          type="button"
                          onClick={() => openSavePartial('edit_category')}
                          disabled={
                            !metricPartialHasSaveableContent(
                              buildMetricPartialContentForTarget(
                                'edit_category',
                                formData,
                                categoryForm,
                                editCategoryForm,
                              ),
                            )
                          }
                          title="Save the full category prompt and all labels to metric partials"
                          className="inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:text-primary-700 disabled:text-gray-400 disabled:cursor-not-allowed"
                        >
                          <Layers className="w-3.5 h-3.5" />
                          Save metric partial
                        </button>
                      </div>
                    </div>
                    <div className="space-y-3">
                      {editCategoryForm.children.map((child, idx) => (
                        <div
                          key={child.local_id}
                          className={`rounded-xl border p-4 space-y-3 ${
                            child.server_id
                              ? 'border-gray-200 bg-gray-50/60'
                              : 'border-emerald-200 bg-emerald-50/30'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2 flex-wrap">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-semibold text-gray-800">
                                Label #{idx + 1}
                              </span>
                              {!child.server_id ? (
                                <span
                                  className="px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide bg-emerald-100 text-emerald-800 border border-emerald-200 rounded"
                                  title="This label was added in this edit session and will be created on Save."
                                >
                                  New
                                </span>
                              ) : null}
                              <label className="inline-flex items-center gap-1.5 text-xs text-gray-700 px-2.5 py-1.5 rounded-lg border border-gray-200 bg-white whitespace-nowrap">
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
                            </div>
                            {editCategoryForm.children.length > 1 && (
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
                                className="inline-flex items-center justify-center w-7 h-7 rounded-full border border-red-200 text-red-500 hover:text-red-700 hover:bg-red-50 transition-colors"
                                title="Remove label"
                                aria-label={`Remove label ${idx + 1}`}
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            )}
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-gray-700 mb-1">
                              Label Name
                            </label>
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
                              placeholder="e.g. happy_completion"
                              className={MODERN_INPUT_SM_CLASS}
                            />
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-gray-700 mb-1">
                              Label Definition
                            </label>
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
                              rows={2}
                              placeholder="Define this specific label..."
                              className={MODERN_INPUT_SM_CLASS}
                            />
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-gray-700 mb-1">
                              Example (Optional)
                            </label>
                            <textarea
                              value={child.example}
                              onChange={(e) =>
                                setEditCategoryForm((s) => ({
                                  ...s,
                                  children: s.children.map((c, i) =>
                                    i === idx
                                      ? { ...c, example: e.target.value }
                                      : c,
                                  ),
                                }))
                              }
                              rows={2}
                              placeholder="Provide an illustrative example for this label..."
                              className={MODERN_INPUT_SM_CLASS}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                    <button
                      type="button"
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
                              example: '',
                              enabled: true,
                            },
                          ],
                        }))
                      }
                      className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-primary-600 hover:text-primary-700"
                    >
                      <Plus className="w-4 h-4" />
                      Add New Label
                    </button>
                    {editCategoryForm.deleted_child_ids.length > 0 && (
                      <p className="mt-2 text-[11px] text-amber-700">
                        {editCategoryForm.deleted_child_ids.length} label
                        {editCategoryForm.deleted_child_ids.length === 1
                          ? ''
                          : 's'}{' '}
                        will be deleted on Save. Past evaluation rows keep
                        their stored scores but the label will no longer
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
                        ).length < 1
                      }
                      onClick={handleUpdateCategory}
                    >
                      Save Labels
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
                            {(metric.scope === 'organization' ||
                              metric.workspace_id == null) && (
                              <span
                                className="px-2 py-0.5 text-xs font-semibold uppercase tracking-wide bg-indigo-100 text-indigo-800 rounded"
                                title="This metric is shared across every workspace in the organization."
                              >
                                Shared
                              </span>
                            )}
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

      {/* Prompt-partial import sub-modal. One picker that all three metric
          Description textareas share — opening it from any of them sets
          ``partialsImportTarget`` so the success path knows which setter to
          run. ``z-[10000]`` keeps it above the create/edit metric modal
          (``z-50``). */}
      {partialsImportTarget !== null && (
        <div
          className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[10000]"
          onClick={closePartialsImport}
        >
          <div
            className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[85vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">
                Import metric partial
              </h3>
              <button
                onClick={closePartialsImport}
                className="text-gray-400 hover:text-gray-600"
                aria-label="Close prompt partials modal"
                disabled={importPartialMutation.isPending}
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6 space-y-4 overflow-y-auto flex-1">
              <p className="text-xs text-gray-500">
                Pick a saved metric partial from the Metrics library. For
                categorization metrics, importing replaces the description and
                all label rows.
              </p>
              <input
                type="text"
                value={partialsSearchInput}
                onChange={(e) => setPartialsSearchInput(e.target.value)}
                placeholder="Search metric partials..."
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              />

              {isLoadingPartials ? (
                <div className="flex items-center justify-center py-8 text-sm text-gray-500">
                  <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                  Loading metric partials...
                </div>
              ) : promptPartials.length === 0 ? (
                <div className="rounded-lg border border-gray-200 p-8 text-center text-sm text-gray-500">
                  {partialsSearchQuery
                    ? `No metric partials match “${partialsSearchQuery}”.`
                    : 'No metric partials yet. Save one from this form first.'}
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
                            name="metric-prompt-partial"
                            checked={isSelected}
                            onChange={() => setSelectedPartialId(partial.id)}
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
                onClick={closePartialsImport}
                disabled={importPartialMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={() => importPartialMutation.mutate(selectedPartialId)}
                isLoading={importPartialMutation.isPending}
                disabled={!selectedPartialId}
              >
                Use Selected Partial
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Prompt-partial SAVE sub-modal. Mirror of the import picker — the
          current Description textarea content is pushed back into the
          Prompt Partials library either as a brand-new partial or as a
          new version appended to an existing partial's history. */}
      {savePartialTarget !== null &&
        (() => {
          const metricPartialContent = buildMetricPartialContentForTarget(
            savePartialTarget,
            formData,
            categoryForm,
            editCategoryForm,
          )
          const serializedContent = serializeMetricPartialContent(metricPartialContent)
          const previewText = formatMetricPartialPreview(metricPartialContent)
          const hasSaveableContent = metricPartialHasSaveableContent(metricPartialContent)
          const canSubmit =
            savePartialMode === 'new'
              ? !!savePartialName.trim() && hasSaveableContent
              : !!savePartialExistingId && hasSaveableContent
          return (
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[10000]"
              onClick={closeSavePartial}
            >
              <div
                className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[85vh] overflow-hidden flex flex-col"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                  <h3 className="text-lg font-semibold text-gray-900">
                    Save metric partial
                  </h3>
                  <button
                    onClick={closeSavePartial}
                    className="text-gray-400 hover:text-gray-600"
                    aria-label="Close save prompt partial modal"
                    disabled={savePartialMutation.isPending}
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
                <div className="p-6 space-y-4 overflow-y-auto flex-1">
                  <div
                    role="tablist"
                    aria-label="Save prompt mode"
                    className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-0.5"
                  >
                    <button
                      type="button"
                      role="tab"
                      aria-pressed={savePartialMode === 'new'}
                      onClick={() => {
                        setSavePartialMode('new')
                        setSavePartialError(null)
                      }}
                      className={`px-3 py-1 text-xs font-medium rounded-md transition ${
                        savePartialMode === 'new'
                          ? 'bg-white text-gray-900 shadow-sm ring-1 ring-inset ring-gray-200'
                          : 'text-gray-600 hover:text-gray-900'
                      }`}
                    >
                      Save as new
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-pressed={savePartialMode === 'existing'}
                      onClick={() => {
                        setSavePartialMode('existing')
                        setSavePartialError(null)
                      }}
                      className={`px-3 py-1 text-xs font-medium rounded-md transition ${
                        savePartialMode === 'existing'
                          ? 'bg-white text-gray-900 shadow-sm ring-1 ring-inset ring-gray-200'
                          : 'text-gray-600 hover:text-gray-900'
                      }`}
                    >
                      Update existing
                    </button>
                  </div>

                  {!hasSaveableContent && (
                    <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                      Add a description or at least one named label before saving.
                    </div>
                  )}

                  {savePartialMode === 'new' ? (
                    <div className="space-y-3">
                      <div>
                        <label className="block text-xs font-medium text-gray-700 mb-1">
                          Name
                          <span
                            className="ml-1 text-red-600"
                            aria-label="required"
                          >
                            *
                          </span>
                        </label>
                        <input
                          type="text"
                          value={savePartialName}
                          onChange={(e) =>
                            setSavePartialName(e.target.value)
                          }
                          placeholder="e.g. Appointment date readback"
                          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                        />
                        <p className="mt-1 text-[11px] text-gray-500">
                          Defaults to the metric name; rename it if you want
                          the partial to be reusable across metrics.
                        </p>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-700 mb-1">
                          Description
                        </label>
                        <textarea
                          value={savePartialDescription}
                          onChange={(e) =>
                            setSavePartialDescription(e.target.value)
                          }
                          rows={2}
                          placeholder="Optional: short context for teammates browsing the library."
                          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                        />
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <p className="text-xs text-gray-500">
                        Pick the saved metric partial to overwrite. A new
                        version row is appended — previous versions stay in
                        the partial's history and can be reverted to.
                      </p>
                      <input
                        type="text"
                        value={partialsSearchInput}
                        onChange={(e) =>
                          setPartialsSearchInput(e.target.value)
                        }
                        placeholder="Search metric partials..."
                        className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      />

                      {isLoadingPartials ? (
                        <div className="flex items-center justify-center py-8 text-sm text-gray-500">
                          <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                          Loading metric partials...
                        </div>
                      ) : promptPartials.length === 0 ? (
                        <div className="rounded-lg border border-gray-200 p-8 text-center text-sm text-gray-500">
                          {partialsSearchQuery
                            ? `No metric partials match “${partialsSearchQuery}”.`
                            : 'No metric partials yet. Switch to "Save as new" to create one.'}
                        </div>
                      ) : (
                        <div className="space-y-2 max-h-[35vh] overflow-y-auto">
                          {promptPartials.map((partial) => {
                            const isSelected =
                              savePartialExistingId === partial.id
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
                                    name="metric-save-partial"
                                    checked={isSelected}
                                    onChange={() =>
                                      setSavePartialExistingId(partial.id)
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
                      <div>
                        <label className="block text-xs font-medium text-gray-700 mb-1">
                          Change summary
                        </label>
                        <input
                          type="text"
                          value={savePartialChangeSummary}
                          onChange={(e) =>
                            setSavePartialChangeSummary(e.target.value)
                          }
                          placeholder="Optional: what changed in this version?"
                          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                        />
                      </div>
                    </div>
                  )}

                  <details className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs">
                    <summary className="cursor-pointer font-medium text-gray-700">
                      Preview metric partial content
                      <span className="ml-1 font-normal text-gray-500">
                        ({serializedContent.length} chars JSON)
                      </span>
                    </summary>
                    <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded border border-gray-200 bg-white p-2 font-mono text-[11px] text-gray-800">
                      {previewText || '(empty)'}
                    </pre>
                  </details>

                  {savePartialError && (
                    <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                      {savePartialError}
                    </div>
                  )}
                  {savePartialSuccess && (
                    <div className="rounded-md border border-green-200 bg-green-50 p-3 text-sm text-green-800">
                      {savePartialSuccess}
                    </div>
                  )}
                </div>
                <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-2 bg-gray-50 rounded-b-lg">
                  <Button
                    variant="outline"
                    onClick={closeSavePartial}
                    disabled={savePartialMutation.isPending}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    onClick={() =>
                      savePartialMutation.mutate({
                        content: serializedContent,
                        mode: savePartialMode,
                        name: savePartialName.trim(),
                        description: savePartialDescription.trim(),
                        partialId: savePartialExistingId,
                        changeSummary: savePartialChangeSummary.trim(),
                      })
                    }
                    isLoading={savePartialMutation.isPending}
                    disabled={!canSubmit}
                  >
                    {savePartialMode === 'new'
                      ? 'Create Metric Partial'
                      : 'Save New Version'}
                  </Button>
                </div>
              </div>
            </div>
          )
        })()}

    </div>
  )
}


import { useState, useEffect, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'
import { Edit, Trash2, X, ToggleLeft, ToggleRight, Brain, RefreshCw, AudioWaveform, Sparkles, Plus } from 'lucide-react'

interface Metric {
  id: string
  name: string
  description?: string
  metric_type: 'number' | 'boolean' | 'rating'
  metric_origin: 'default' | 'custom'
  supported_surfaces: Array<'agent' | 'voice_playground' | 'blind_test'>
  enabled_surfaces: Array<'agent' | 'voice_playground' | 'blind_test'>
  custom_data_type?: 'boolean' | 'enum' | 'number_range' | null
  custom_config?: Record<string, any> | null
  tags?: string[] | null
  trigger: 'always'
  enabled: boolean
  is_default: boolean
  created_at: string
  updated_at: string
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

export default function MetricsManagement() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [isCustomMetricMode, setIsCustomMetricMode] = useState(false)
  const [showEnableModal, setShowEnableModal] = useState(false)
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
    metric_type: 'rating' as 'number' | 'boolean' | 'rating',
    metric_origin: 'custom' as 'default' | 'custom',
    supported_surfaces: ['agent'] as MetricSurface[],
    enabled_surfaces: ['agent'] as MetricSurface[],
    custom_data_type: 'boolean' as CustomDataType,
    enum_options_csv: '',
    number_min: 0,
    number_max: 10,
    number_step: 1,
    tags_csv: '',
    trigger: 'always' as 'always',
    enabled: true,
  })

  const { data: metrics = [], isLoading } = useQuery({
    queryKey: ['metrics', surfaceFilter],
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

  const generateMetricMutation = useMutation({
    mutationFn: (payload: {
      mode: 'description' | 'examples'
      surface: MetricSurface
      description?: string
      examples?: Array<{ transcript: string; rating: any; notes?: string }>
    }) => apiClient.generateMetric(payload),
    onSuccess: (suggestion) => {
      const inferredCustomDataType: CustomDataType =
        (suggestion.custom_data_type as CustomDataType) ||
        (suggestion.metric_type === 'boolean'
          ? 'boolean'
          : suggestion.metric_type === 'number'
            ? 'number_range'
            : 'enum')
      const cfg = suggestion.custom_config || {}
      const fallbackSurface: MetricSurface = formData.supported_surfaces[0] || 'agent'
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
        enum_options_csv: Array.isArray(cfg.options) ? cfg.options.join(', ') : '',
        number_min: Number(cfg.min ?? 0),
        number_max: Number(cfg.max ?? 10),
        number_step: Number(cfg.step ?? 1),
        tags_csv: (suggestion.suggested_tags || []).join(', '),
        trigger: 'always',
        enabled: true,
      }))
      showToast('AI suggestion applied - review and save', 'success')
    },
    onError: () => {
      showToast('Failed to generate metric with AI', 'error')
    },
  })

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
      custom_data_type: 'boolean',
      enum_options_csv: '',
      number_min: 0,
      number_max: 10,
      number_step: 1,
      tags_csv: '',
      trigger: 'always',
      enabled: true,
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
    return {
      name: formData.name,
      description: formData.description,
      metric_type: formData.metric_type,
      trigger: formData.trigger,
      enabled: formData.enabled,
      metric_origin: formData.metric_origin,
      supported_surfaces: formData.supported_surfaces,
      enabled_surfaces: formData.enabled ? formData.enabled_surfaces : [],
      custom_data_type: formData.metric_origin === 'custom' ? formData.custom_data_type : undefined,
      custom_config: formData.metric_origin === 'custom' ? getCustomConfigFromForm() : undefined,
      tags: tags.length > 0 ? tags : undefined,
    }
  }

  const handleCreate = () => {
    if (!formData.name.trim()) {
      alert('Please enter a metric name')
      return
    }
    createMutation.mutate(buildPayload() as any)
  }

  const handleEdit = (metric: Metric) => {
    setEditingMetric(metric)
    setFormData({
      name: metric.name,
      description: metric.description || '',
      metric_type: metric.metric_type,
      metric_origin: metric.metric_origin || 'custom',
      supported_surfaces: (metric.supported_surfaces?.length ? metric.supported_surfaces : ['agent']) as MetricSurface[],
      enabled_surfaces: (metric.enabled_surfaces?.length ? metric.enabled_surfaces : ['agent']) as MetricSurface[],
      custom_data_type: (metric.custom_data_type || 'boolean') as CustomDataType,
      enum_options_csv: Array.isArray(metric.custom_config?.options) ? metric.custom_config.options.join(', ') : '',
      number_min: Number(metric.custom_config?.min ?? 0),
      number_max: Number(metric.custom_config?.max ?? 10),
      number_step: Number(metric.custom_config?.step ?? 1),
      tags_csv: metric.tags?.join(', ') || '',
      trigger: metric.trigger,
      enabled: metric.enabled,
    })
    setIsCustomMetricMode(metric.metric_origin === 'custom')
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

  const handleToggleEnabled = (metric: Metric) => {
    toggleEnabledMutation.mutate({ id: metric.id, enabled: !metric.enabled })
  }

  const handleDelete = (metric: Metric) => {
    if (metric.is_default && !isDeprecatedMetric(metric.name)) {
      alert('Cannot delete default metrics')
      return
    }
    const message = isDeprecatedMetric(metric.name)
      ? `"${metric.name}" is a deprecated metric. Are you sure you want to delete it?`
      : `Are you sure you want to delete "${metric.name}"?`
    if (confirm(message)) {
      deleteMutation.mutate(metric.id)
    }
  }

  const closeModal = () => {
    setShowCreateModal(false)
    setIsCustomMetricMode(false)
    setEditingMetric(null)
    resetForm()
    resetAIForm()
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

  const sortedEnabledMetrics = useMemo(() => {
    const getTypeLabel = (metric: Metric) => (isQuantitativeMetric(metric.name) ? 'quantitative' : 'qualitative')
    const getMethodLabel = (metric: Metric) => (isAIVoiceMetric(metric.name) ? 'ai voice' : isAudioMetric(metric.name) ? 'acoustic' : 'llm')

    return metrics
      .filter((metric: Metric) => metric.enabled)
      .sort((a: Metric, b: Metric) => {
      const aValue = sortField === 'type' ? getTypeLabel(a) : getMethodLabel(a)
      const bValue = sortField === 'type' ? getTypeLabel(b) : getMethodLabel(b)

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
              })
              setShowCreateModal(true)
            }}
            leftIcon={<Plus className="w-4 h-4" />}
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
        ) : sortedEnabledMetrics.length === 0 ? (
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
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {sortedEnabledMetrics.map((metric: Metric) => {
                  const isAudio = isAudioMetric(metric.name)
                  const isQuantitative = isQuantitativeMetric(metric.name)
                  return (
                    <tr key={metric.id} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center">
                          <div className="text-sm font-medium text-gray-900">{metric.name}</div>
                          {metric.is_default && (
                            <span className="ml-2 px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded">
                              Default
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
                          {metric.metric_origin === 'custom' ? metric.custom_data_type || metric.metric_type : metric.metric_type}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex flex-wrap gap-1.5">
                          {(metric.supported_surfaces || []).map((surface) => {
                            const isEnabled = (metric.enabled_surfaces || []).includes(surface)
                            return (
                              <button
                                key={surface}
                                type="button"
                                onClick={() => handleToggleSurface(metric, surface)}
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
                          })}
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
                      <td className="px-6 py-4 whitespace-nowrap">
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
                      <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                        <div className="flex items-center justify-end space-x-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleEdit(metric)}
                            leftIcon={<Edit className="w-4 h-4" />}
                          >
                            Edit
                          </Button>
                          {(!metric.is_default || isDeprecatedMetric(metric.name)) && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleDelete(metric)}
                              leftIcon={<Trash2 className="w-4 h-4" />}
                            >
                              Delete
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
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
            <div className="relative bg-white rounded-lg shadow-xl max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-2xl font-bold text-gray-900">
                  {editingMetric ? 'Edit Metric' : (isCustomMetricMode ? 'Create Custom Metric' : 'Create Metric')}
                </h2>
                <button
                  onClick={closeModal}
                  className="text-gray-400 hover:text-gray-500"
                >
                  <X className="h-6 w-6" />
                </button>
              </div>

              <div className="space-y-4">
                {isCustomMetricMode && !editingMetric && (
                  <div className="border border-purple-200 rounded-lg bg-purple-50/40">
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
                            className="w-full px-3 py-2 text-sm border border-purple-200 rounded-md shadow-sm focus:outline-none focus:ring-purple-500 focus:border-purple-500"
                          />
                        ) : (
                          <div className="space-y-2">
                            {aiExamples.map((ex, idx) => (
                              <div key={idx} className="border border-purple-200 rounded-md p-2 bg-white space-y-2">
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
                                  className="w-full px-2 py-1 text-xs border border-gray-300 rounded shadow-sm focus:outline-none focus:ring-purple-500 focus:border-purple-500"
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
                                    className="px-2 py-1 text-xs border border-gray-300 rounded shadow-sm focus:outline-none focus:ring-purple-500 focus:border-purple-500"
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
                                    className="px-2 py-1 text-xs border border-gray-300 rounded shadow-sm focus:outline-none focus:ring-purple-500 focus:border-purple-500"
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

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Name *
                  </label>
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    disabled={editingMetric?.is_default}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500 disabled:bg-gray-100"
                    placeholder="Enter metric name"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Description
                  </label>
                  <textarea
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    rows={3}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                    placeholder="Enter metric description"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Metric Type *
                  </label>
                  <select
                    value={formData.metric_type}
                    onChange={(e) => setFormData({ ...formData, metric_type: e.target.value as any })}
                    disabled={editingMetric?.is_default || isCustomMetricMode}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500 disabled:bg-gray-100"
                  >
                    <option value="number">Number</option>
                    <option value="boolean">Boolean</option>
                    <option value="rating">Rating</option>
                  </select>
                </div>

                {isCustomMetricMode && (
                  <>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Custom Data Type *
                      </label>
                      <select
                        value={formData.custom_data_type}
                        onChange={(e) => {
                          const next = e.target.value as CustomDataType
                          setFormData({
                            ...formData,
                            custom_data_type: next,
                            metric_type: next === 'boolean' ? 'boolean' : next === 'number_range' ? 'number' : 'rating',
                          })
                        }}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                      >
                        <option value="boolean">Boolean</option>
                        <option value="enum">Enum</option>
                        <option value="number_range">Number Range</option>
                      </select>
                    </div>

                    {formData.custom_data_type === 'enum' && (
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          Enum Options (comma separated) *
                        </label>
                        <input
                          type="text"
                          value={formData.enum_options_csv}
                          onChange={(e) => setFormData({ ...formData, enum_options_csv: e.target.value })}
                          className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                          placeholder="Excellent, Good, Neutral, Poor"
                        />
                      </div>
                    )}

                    {formData.custom_data_type === 'number_range' && (
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">Min</label>
                          <input
                            type="number"
                            value={formData.number_min}
                            onChange={(e) => setFormData({ ...formData, number_min: Number(e.target.value) })}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">Max</label>
                          <input
                            type="number"
                            value={formData.number_max}
                            onChange={(e) => setFormData({ ...formData, number_max: Number(e.target.value) })}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">Step</label>
                          <input
                            type="number"
                            value={formData.number_step}
                            onChange={(e) => setFormData({ ...formData, number_step: Number(e.target.value) })}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                          />
                        </div>
                      </div>
                    )}
                  </>
                )}

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Supported Surfaces
                  </label>
                  <div className="flex flex-wrap gap-4">
                    {ALL_SURFACES.map((surface) => (
                      <label key={surface} className="inline-flex items-center gap-2 text-sm text-gray-700">
                        <input
                          type="checkbox"
                          checked={formData.supported_surfaces.includes(surface)}
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
                    ))}
                  </div>
                  <p className="mt-1 text-xs text-gray-500">
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
                    className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
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
                    className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                  >
                    <option value="always">Always</option>
                  </select>
                </div>

                <div className="flex items-center">
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

                <div className="flex justify-end space-x-3 pt-4">
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
            </div>
          </div>
        </div>
      )}

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

    </div>
  )
}


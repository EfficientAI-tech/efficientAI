import { useState, useMemo, useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import {
  FileText,
  Tag,
  Plus,
  Sparkles,
  Trash2,
  X,
  Loader,
  Phone,
  Brain,
  ChevronDown,
  AlertCircle,
  Lock,
  BarChart3,
} from 'lucide-react'
import { apiClient } from '../../lib/api'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'
import { AIProvider, ModelProvider } from '../../types/api'
import { getProviderLabel, getProviderLogo } from '../../config/providers'
import LLMAdvancedOptionsPanel from '../../components/providers/LLMAdvancedOptionsPanel'
import type { LLMGenerationConfig } from '../../config/llmGenerationParams'
import type { GenerateScenariosFromPromptParams } from '../../types/agentTestSetupGeneration'
import { useWalkthroughSectionState } from '../../context/WalkthroughContext'
import WalkthroughToggleButton from '../../components/walkthrough/WalkthroughToggleButton'
import { resolveActiveAIProvider } from '../../lib/gatewayRouting'
import { resolveLLMModelsForCredential } from '../../lib/llmModelOptions'
import {
  buildScenarioEditGenerationUserPrompt,
  scenarioEditGenerationSystemPrompt,
} from './scenarioGenerationPrompts'
import MarkdownEditor from '../../components/shared/MarkdownEditor'
import ScenarioMarkdownView from './ScenarioMarkdownView'
import ScenariosAgentSidebar from './ScenariosAgentSidebar'
import ScenariosListPanel from './ScenariosListPanel'
import type { Scenario, AgentOption } from './scenarioTypes'
import ScenarioAgentMediumTabs from './ScenarioAgentMediumTabs'
import ScenarioMetricsFromScenariosModal from './ScenarioMetricsFromScenariosModal'
import {
  filterAgentsByMedium,
  isChatMedium,
  type AgentMediumFilter,
} from '../../lib/agentMedium'
import { useLicenseStore } from '../../store/licenseStore'

interface GeneratedScenarioMetricDraft {
  name: string
  description: string
  metric_type: 'rating' | 'boolean' | 'number' | 'text'
  custom_data_type: 'boolean' | 'enum' | 'number_range' | null
  custom_config: Record<string, unknown>
  supported_surfaces: string[]
  enabled_surfaces: string[]
  tags: string[]
}

type PlannedScenarioMetricType = 'auto' | 'boolean' | 'rating' | 'number' | 'text'

interface GeneratedScenarioDraft {
  id: string
  name: string
  description: string
  goal?: string
  plannedMetricType: PlannedScenarioMetricType
  metric?: GeneratedScenarioMetricDraft
  metricPushed?: boolean
}

function customDataTypeForMetricType(
  metricType: GeneratedScenarioMetricDraft['metric_type']
): GeneratedScenarioMetricDraft['custom_data_type'] {
  if (metricType === 'boolean') return 'boolean'
  if (metricType === 'number') return 'number_range'
  if (metricType === 'text') return null
  return 'enum'
}

function mergeRequiredMetricTags(tags: string[], agentName: string): string[] {
  const required = [agentName.trim(), 'auto-generated'].filter(Boolean)
  const seen = new Set<string>()
  const merged: string[] = []
  for (const tag of required) {
    if (!seen.has(tag)) {
      seen.add(tag)
      merged.push(tag)
    }
  }
  for (const tag of tags) {
    const trimmed = tag.trim()
    if (trimmed && !seen.has(trimmed)) {
      seen.add(trimmed)
      merged.push(trimmed)
    }
  }
  return merged
}

type CreateMode = 'agent_prompt' | 'call' | 'custom' | null

export default function Scenarios() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const { isFeatureEnabled, isLoaded: licenseLoaded, getFeatureMeta } = useLicenseStore()
  const scenarioMetricsEnabled = licenseLoaded && isFeatureEnabled('scenario_metrics')
  const [showMainModal, setShowMainModal] = useState(false)
  const [createMode, setCreateMode] = useState<CreateMode>(null)
  const [showDetailsModal, setShowDetailsModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(false)
  const [selectedScenario, setSelectedScenario] = useState<Scenario | null>(null)
  const [deleteDependencies, setDeleteDependencies] = useState<Record<string, number> | null>(null)
  const [formData, setFormData] = useState({
    name: '',
    agent_id: '',
    description: '',
    required_info: {} as Record<string, string>,
  })

  const renderModal = (content: ReactNode) => {
    if (typeof document === 'undefined') return null
    return createPortal(content, document.body)
  }

  // Shared AI generation selectors
  const [selectedAIProvider, setSelectedAIProvider] = useState<ModelProvider | null>(null)
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [llmConfig, setLlmConfig] = useState<LLMGenerationConfig | null>(null)
  const [showProviderDropdown, setShowProviderDropdown] = useState(false)
  const providerDropdownRef = useRef<HTMLDivElement>(null)
  const [selectedAgentIdForGeneration, setSelectedAgentIdForGeneration] = useState('')
  const [scenarioCount, setScenarioCount] = useState(3)
  const [additionalAgentPromptContext, setAdditionalAgentPromptContext] = useState('')
  const [generatedScenarioDrafts, setGeneratedScenarioDrafts] = useState<GeneratedScenarioDraft[]>([])
  const [isGeneratingFromAgentPrompt, setIsGeneratingFromAgentPrompt] = useState(false)
  const [isGeneratingScenarioMetrics, setIsGeneratingScenarioMetrics] = useState(false)
  const [savingDraftIds, setSavingDraftIds] = useState<Set<string>>(new Set())
  const [pushingMetricDraftIds, setPushingMetricDraftIds] = useState<Set<string>>(new Set())
  const [metricSelectedAIProvider, setMetricSelectedAIProvider] = useState<ModelProvider | null>(
    null
  )
  const [metricSelectedModel, setMetricSelectedModel] = useState<string>('')
  const [metricLlmConfig, setMetricLlmConfig] = useState<LLMGenerationConfig | null>(null)
  const [showMetricProviderDropdown, setShowMetricProviderDropdown] = useState(false)
  const metricProviderDropdownRef = useRef<HTMLDivElement>(null)
  const [editGeneratePrompt, setEditGeneratePrompt] = useState('')
  const [isGeneratingEditDescription, setIsGeneratingEditDescription] = useState(false)
  const [showScenarioMetricsModal, setShowScenarioMetricsModal] = useState(false)
  const [scenarioMetricsModalScenarios, setScenarioMetricsModalScenarios] = useState<Scenario[]>(
    []
  )

  useWalkthroughSectionState('scenarios', { createMode }, [createMode])

  // For Generate from Call
  const [callData, setCallData] = useState('')
  const [selectedNavAgentId, setSelectedNavAgentId] = useState<string>('')
  const [scenarioMediumFilter, setScenarioMediumFilter] = useState<AgentMediumFilter>('voice')

  const { data: scenarios = [], isLoading } = useQuery({
    queryKey: ['scenarios'],
    queryFn: () => apiClient.listScenarios(),
  })

  const { data: aiProviders = [] } = useQuery({
    queryKey: ['aiproviders'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => apiClient.listAgents(),
  })

  // Get configured and active AI providers
  const availableProviders = useMemo(() => {
    return aiProviders.filter((p: AIProvider) => p.is_active)
  }, [aiProviders])

  // Get configured providers as ModelProvider enum values
  const configuredProviders = useMemo(() => {
    return availableProviders.map((p: AIProvider) => p.provider as ModelProvider)
  }, [availableProviders])

  // Get models for selected provider
  const { data: modelOptions } = useQuery({
    queryKey: ['model-options', selectedAIProvider],
    queryFn: () => apiClient.getModelOptions(selectedAIProvider!),
    enabled: !!selectedAIProvider && (createMode === 'agent_prompt' || showEditModal),
  })

  const { data: metricModelOptions } = useQuery({
    queryKey: ['model-options', metricSelectedAIProvider],
    queryFn: () => apiClient.getModelOptions(metricSelectedAIProvider!),
    enabled:
      !!metricSelectedAIProvider &&
      createMode === 'agent_prompt' &&
      generatedScenarioDrafts.length > 0,
  })

  // Get LLM models for the selected provider
  const llmModels = useMemo(() => {
    return modelOptions?.llm || []
  }, [modelOptions])

  const selectedAiCredential = useMemo(() => {
    if (!selectedAIProvider) return undefined
    return resolveActiveAIProvider(aiProviders, selectedAIProvider)
  }, [aiProviders, selectedAIProvider])

  const llmModelResolution = useMemo(() => {
    if (!selectedAiCredential) {
      return { mode: 'catalog' as const, models: llmModels }
    }
    return resolveLLMModelsForCredential(selectedAiCredential, llmModels)
  }, [selectedAiCredential, llmModels])

  const selectableLlmModels =
    llmModelResolution.mode === 'catalog' ? llmModelResolution.models : []

  const gatewayDirectModel =
    llmModelResolution.mode === 'gateway_direct' ? llmModelResolution.model : null

  const metricLlmModels = useMemo(() => metricModelOptions?.llm || [], [metricModelOptions])

  const metricSelectedAiCredential = useMemo(() => {
    if (!metricSelectedAIProvider) return undefined
    return resolveActiveAIProvider(aiProviders, metricSelectedAIProvider)
  }, [aiProviders, metricSelectedAIProvider])

  const metricLlmModelResolution = useMemo(() => {
    if (!metricSelectedAiCredential) {
      return { mode: 'catalog' as const, models: metricLlmModels }
    }
    return resolveLLMModelsForCredential(metricSelectedAiCredential, metricLlmModels)
  }, [metricSelectedAiCredential, metricLlmModels])

  const selectableMetricLlmModels =
    metricLlmModelResolution.mode === 'catalog' ? metricLlmModelResolution.models : []

  const metricGatewayDirectModel =
    metricLlmModelResolution.mode === 'gateway_direct' ? metricLlmModelResolution.model : null

  const userScenarios = useMemo(() => scenarios as Scenario[], [scenarios])
  const availableAgents = useMemo(() => agents as AgentOption[], [agents])
  const agentNameById = useMemo(() => {
    const map = new Map<string, string>()
    availableAgents.forEach((agent) => map.set(agent.id, agent.name))
    return map
  }, [availableAgents])

  const agentsForScenarioMedium = useMemo(
    () => filterAgentsByMedium(availableAgents, scenarioMediumFilter),
    [availableAgents, scenarioMediumFilter],
  )

  const scenarioCountByAgent = useMemo(() => {
    const counts = new Map<string, number>()
    userScenarios.forEach((scenario) => {
      if (scenario.agent_id) {
        counts.set(scenario.agent_id, (counts.get(scenario.agent_id) ?? 0) + 1)
      }
    })
    return counts
  }, [userScenarios])

  const agentsWithScenarios = useMemo(
    () =>
      availableAgents
        .filter((agent) => (scenarioCountByAgent.get(agent.id) ?? 0) > 0)
        .map((agent) => ({
          id: agent.id,
          name: agent.name,
          call_medium: agent.call_medium,
        })),
    [availableAgents, scenarioCountByAgent],
  )

  const unlinkedScenarioCount = useMemo(
    () => userScenarios.filter((s) => !s.agent_id).length,
    [userScenarios],
  )

  const visibleScenarios = useMemo(() => {
    if (selectedNavAgentId === 'unlinked') {
      return userScenarios.filter((s) => !s.agent_id)
    }
    if (selectedNavAgentId) {
      return userScenarios.filter((s) => s.agent_id === selectedNavAgentId)
    }
    return []
  }, [userScenarios, selectedNavAgentId])

  const selectedAgentLabel = useMemo(() => {
    if (selectedNavAgentId === 'unlinked') return 'Unlinked scenarios'
    return agentNameById.get(selectedNavAgentId) || 'Scenarios'
  }, [selectedNavAgentId, agentNameById])

  useEffect(() => {
    const selectedLinkedCount =
      selectedNavAgentId && selectedNavAgentId !== 'unlinked'
        ? (scenarioCountByAgent.get(selectedNavAgentId) ?? 0)
        : 0

    if (selectedNavAgentId === 'unlinked') {
      if (unlinkedScenarioCount === 0) {
        if (agentsWithScenarios.length > 0) {
          setSelectedNavAgentId(agentsWithScenarios[0].id)
        } else {
          setSelectedNavAgentId('')
        }
      }
      return
    }

    if (selectedNavAgentId && selectedLinkedCount > 0) {
      return
    }

    if (agentsWithScenarios.length > 0) {
      setSelectedNavAgentId(agentsWithScenarios[0].id)
      return
    }
    if (unlinkedScenarioCount > 0) {
      setSelectedNavAgentId('unlinked')
      return
    }
    setSelectedNavAgentId('')
  }, [agentsWithScenarios, unlinkedScenarioCount, selectedNavAgentId, scenarioCountByAgent])

  // Reset model when provider changes
  useEffect(() => {
    if (gatewayDirectModel) {
      setSelectedModel('')
      return
    }
    if (selectedAIProvider && selectableLlmModels.length > 0) {
      setSelectedModel(selectableLlmModels[0])
    } else {
      setSelectedModel('')
    }
  }, [selectedAIProvider, selectableLlmModels, gatewayDirectModel])

  useEffect(() => {
    if (metricGatewayDirectModel) {
      setMetricSelectedModel(metricGatewayDirectModel)
    } else if (
      metricSelectedModel &&
      !selectableMetricLlmModels.includes(metricSelectedModel)
    ) {
      setMetricSelectedModel('')
    } else if (!metricSelectedAIProvider) {
      setMetricSelectedModel('')
    }
  }, [
    metricSelectedAIProvider,
    selectableMetricLlmModels,
    metricGatewayDirectModel,
    metricSelectedModel,
  ])

  // Handle click outside provider dropdown
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (providerDropdownRef.current && !providerDropdownRef.current.contains(event.target as Node)) {
        setShowProviderDropdown(false)
      }
      if (
        metricProviderDropdownRef.current &&
        !metricProviderDropdownRef.current.contains(event.target as Node)
      ) {
        setShowMetricProviderDropdown(false)
      }
    }

    if (showProviderDropdown || showMetricProviderDropdown) {
      document.addEventListener('mousedown', handleClickOutside)
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [showProviderDropdown, showMetricProviderDropdown])

  const createMutation = useMutation({
    mutationFn: (data: { name: string; agent_id?: string | null; description?: string; required_info: Record<string, string> }) =>
      apiClient.createScenario(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scenarios'] })
      showToast('Scenario created successfully!', 'success')
      handleCloseMainModal()
    },
    onError: (error: any) => {
      showToast(`Failed to create scenario: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const generateFromCallMutation = useMutation({
    mutationFn: async (callDataText: string) => {
      // TODO: Implement API endpoint for generating scenario from call data
      // For now, we'll create a basic scenario structure
      // This should analyze call transcript/data and extract scenario
      const scenarioData = {
        name: `Extracted from Call`,
        description: `Scenario extracted from call data: ${callDataText.substring(0, 100)}${callDataText.length > 100 ? '...' : ''}`,
        required_info: {},
      }
      return apiClient.createScenario(scenarioData)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scenarios'] })
      showToast('Scenario generated from call successfully!', 'success')
      handleCloseMainModal()
    },
    onError: (error: any) => {
      showToast(`Failed to generate scenario: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name: string; agent_id?: string | null; description?: string; required_info: Record<string, string> } }) =>
      apiClient.updateScenario(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scenarios'] })
      showToast('Scenario updated successfully!', 'success')
      handleCloseEditModal()
    },
    onError: (error: any) => {
      showToast(`Failed to update scenario: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: ({ id, force }: { id: string; force?: boolean }) => apiClient.deleteScenario(id, force),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scenarios'] })
      setShowDeleteModal(false)
      setSelectedScenario(null)
      setDeleteDependencies(null)
      showToast('Scenario deleted successfully!', 'success')
    },
    onError: (error: any) => {
      const status = error.response?.status
      const detail = error.response?.data?.detail

      if (status === 409 && detail?.dependencies) {
        setDeleteDependencies(detail.dependencies)
        return
      }

      const errorMessage = typeof detail === 'string'
        ? detail
        : detail?.message || error.message || 'Failed to delete scenario.'
      showToast(errorMessage, 'error')
    },
  })

  const resetForm = () => {
    setFormData({
      name: '',
      agent_id: '',
      description: '',
      required_info: {},
    })
  }

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.name.trim()) {
      showToast('Please enter a scenario name', 'error')
      return
    }
    createMutation.mutate({
      name: formData.name,
      agent_id: formData.agent_id || undefined,
      description: formData.description || undefined,
      required_info: formData.required_info || {},
    })
  }

  const handleGenerateFromAgentPrompt = async () => {
    const selectedAgent = availableAgents.find((a) => a.id === selectedAgentIdForGeneration)
    if (!selectedAgent) {
      showToast('Please select an agent', 'error')
      return
    }
    if (!selectedAIProvider) {
      showToast('Please select an AI provider', 'error')
      return
    }
    if (!selectedModel) {
      showToast('Please select a model', 'error')
      return
    }
    if (scenarioCount < 1 || scenarioCount > 10) {
      showToast('Scenario count must be between 1 and 10', 'error')
      return
    }

    const chatAgent = isChatMedium(selectedAgent.call_medium)
    const agentPrompt = (
      chatAgent
        ? (selectedAgent.provider_prompt || selectedAgent.description || '').trim()
        : (selectedAgent.description || '').trim()
    )
    if (!agentPrompt) {
      showToast('Selected agent has no production prompt to generate from', 'error')
      return
    }

    setIsGeneratingFromAgentPrompt(true)
    try {
      const generationRequest: GenerateScenariosFromPromptParams = {
        test_agent_prompt: agentPrompt,
        agent_name: selectedAgent.name,
        scenario_count: scenarioCount,
        language: selectedAgent.language,
        call_type: selectedAgent.call_type,
        call_medium: selectedAgent.call_medium,
        additional_context: additionalAgentPromptContext.trim() || undefined,
        provider: selectedAIProvider,
        model: selectedModel,
        ...(llmConfig ? { llm_config: llmConfig } : {}),
      }
      const response = await apiClient.generateScenariosFromPrompt(generationRequest)

      const drafts = response.scenarios.map((item, index) => ({
        id: `draft-${Date.now()}-${index}`,
        name: String(item.name).trim(),
        description: String(item.description).trim(),
        goal: item.goal ? String(item.goal).trim() : undefined,
        plannedMetricType: 'auto' as PlannedScenarioMetricType,
      }))
      if (drafts.length === 0) {
        showToast('Could not parse generated scenarios. Try again.', 'error')
        return
      }

      setGeneratedScenarioDrafts(drafts)
      showToast(`Generated ${drafts.length} scenario drafts`, 'success')
    } catch (error: any) {
      showToast(`Failed to generate scenarios: ${error.response?.data?.detail || error.message}`, 'error')
    } finally {
      setIsGeneratingFromAgentPrompt(false)
    }
  }

  const updateGeneratedDraft = (draftId: string, updates: Partial<GeneratedScenarioDraft>) => {
    setGeneratedScenarioDrafts((prev) =>
      prev.map((draft) => (draft.id === draftId ? { ...draft, ...updates } : draft))
    )
  }

  const removeGeneratedDraft = (draftId: string) => {
    setGeneratedScenarioDrafts((prev) => prev.filter((draft) => draft.id !== draftId))
  }

  const resolveAgentProductionPrompt = (agent: AgentOption) => {
    const chatAgent = isChatMedium(agent.call_medium)
    return (
      chatAgent
        ? (agent.provider_prompt || agent.description || '').trim()
        : (agent.description || '').trim()
    )
  }

  const updateGeneratedDraftMetric = (
    draftId: string,
    updates: Partial<GeneratedScenarioMetricDraft>
  ) => {
    setGeneratedScenarioDrafts((prev) =>
      prev.map((draft) =>
        draft.id === draftId && draft.metric
          ? { ...draft, metric: { ...draft.metric, ...updates } }
          : draft
      )
    )
  }

  const handleGenerateMetricsForDrafts = async () => {
    if (!scenarioMetricsEnabled) {
      const title = getFeatureMeta('scenario_metrics')?.title ?? 'Scenario Metrics'
      showToast(`${title} requires an EfficientAI Enterprise license.`, 'error')
      return
    }
    const selectedAgent = availableAgents.find((a) => a.id === selectedAgentIdForGeneration)
    if (!selectedAgent) {
      showToast('Please select an agent', 'error')
      return
    }
    if (!metricSelectedAIProvider || !metricSelectedModel) {
      showToast('Please select an AI provider and model for metric generation', 'error')
      return
    }
    if (generatedScenarioDrafts.length === 0) {
      showToast('Generate scenarios first', 'error')
      return
    }

    const agentPrompt = resolveAgentProductionPrompt(selectedAgent)
    if (!agentPrompt) {
      showToast('Selected agent has no production prompt', 'error')
      return
    }

    setIsGeneratingScenarioMetrics(true)
    try {
      const response = await apiClient.generateMetricsFromScenarios({
        agent_name: selectedAgent.name,
        production_prompt: agentPrompt,
        call_medium: selectedAgent.call_medium,
        scenarios: generatedScenarioDrafts.map((draft) => ({
          name: draft.name.trim(),
          description: draft.description.trim(),
          goal: draft.goal?.trim() || undefined,
          metric_type: draft.plannedMetricType,
        })),
        provider: metricSelectedAIProvider,
        model: metricSelectedModel,
        ...(metricLlmConfig ? { llm_config: metricLlmConfig } : {}),
      })

      setGeneratedScenarioDrafts((prev) =>
        prev.map((draft, index) => {
          const generated = response.metrics[index]
          if (!generated) return draft
          return {
            ...draft,
            metricPushed: false,
            metric: {
              name: generated.name,
              description: generated.description,
              metric_type: generated.metric_type,
              custom_data_type: generated.custom_data_type,
              custom_config: generated.custom_config ?? {},
              supported_surfaces: generated.supported_surfaces,
              enabled_surfaces: generated.enabled_surfaces,
              tags: generated.tags ?? [],
            },
          }
        })
      )
      showToast(`Generated ${response.metrics.length} metric drafts`, 'success')
    } catch (error: any) {
      showToast(
        `Failed to generate metrics: ${error.response?.data?.detail || error.message}`,
        'error'
      )
    } finally {
      setIsGeneratingScenarioMetrics(false)
    }
  }

  const pushMetricForDraft = async (draft: GeneratedScenarioDraft) => {
    if (!draft.metric || draft.metricPushed) return
    const selectedAgent = availableAgents.find((a) => a.id === selectedAgentIdForGeneration)
    const agentName = selectedAgent?.name?.trim() || 'Agent'
    const metric = draft.metric
    const tags = mergeRequiredMetricTags(metric.tags, agentName)

    setPushingMetricDraftIds((prev) => new Set(prev).add(draft.id))
    try {
      await apiClient.createMetric({
        name: metric.name.trim(),
        description: metric.description.trim() || undefined,
        metric_type: metric.metric_type,
        metric_origin: 'custom',
        supported_surfaces: metric.supported_surfaces,
        enabled_surfaces: metric.enabled_surfaces,
        custom_data_type: metric.custom_data_type ?? undefined,
        custom_config:
          metric.custom_config && Object.keys(metric.custom_config).length > 0
            ? metric.custom_config
            : undefined,
        tags,
        scope: 'workspace',
      })
      await queryClient.invalidateQueries({ queryKey: ['metrics'] })
      setGeneratedScenarioDrafts((prev) =>
        prev.map((item) =>
          item.id === draft.id ? { ...item, metricPushed: true, metric: { ...metric, tags } } : item
        )
      )
      showToast(`Added metric "${metric.name}" to Metrics`, 'success')
    } catch (error: any) {
      showToast(`Failed to add metric: ${error.response?.data?.detail || error.message}`, 'error')
    } finally {
      setPushingMetricDraftIds((prev) => {
        const next = new Set(prev)
        next.delete(draft.id)
        return next
      })
    }
  }

  const saveGeneratedDraft = async (draft: GeneratedScenarioDraft) => {
    if (!draft.name.trim()) {
      showToast('Scenario name cannot be empty', 'error')
      return
    }

    setSavingDraftIds((prev) => new Set(prev).add(draft.id))
    try {
      await apiClient.createScenario({
        name: draft.name.trim(),
        agent_id: selectedAgentIdForGeneration || undefined,
        description: draft.description?.trim() || undefined,
        required_info: draft.goal ? { goal: draft.goal } : {},
      })
      queryClient.invalidateQueries({ queryKey: ['scenarios'] })
      showToast(`Saved scenario "${draft.name}"`, 'success')
      removeGeneratedDraft(draft.id)
    } catch (error: any) {
      showToast(`Failed to save scenario: ${error.response?.data?.detail || error.message}`, 'error')
    } finally {
      setSavingDraftIds((prev) => {
        const next = new Set(prev)
        next.delete(draft.id)
        return next
      })
    }
  }


  const agentMatchesScenarioMedium = (agentId: string, medium: AgentMediumFilter) => {
    if (!agentId) return true
    const agent = availableAgents.find((a) => a.id === agentId)
    if (!agent) return false
    return medium === 'chat' ? isChatMedium(agent.call_medium) : !isChatMedium(agent.call_medium)
  }

  const handleScenarioMediumFilterChange = (medium: AgentMediumFilter) => {
    setScenarioMediumFilter(medium)
    if (createMode === 'call' && medium === 'chat') {
      setCreateMode(null)
    }
    if (!agentMatchesScenarioMedium(selectedAgentIdForGeneration, medium)) {
      setSelectedAgentIdForGeneration('')
    }
    if (!agentMatchesScenarioMedium(formData.agent_id, medium)) {
      setFormData((prev) => ({ ...prev, agent_id: '' }))
    }
  }

  const handleCloseMainModal = () => {
    setShowMainModal(false)
    setCreateMode(null)
    setCallData('')
    setSelectedAIProvider(null)
    setSelectedModel('')
    setSelectedAgentIdForGeneration('')
    setScenarioCount(3)
    setAdditionalAgentPromptContext('')
    setGeneratedScenarioDrafts([])
    setSavingDraftIds(new Set())
    setPushingMetricDraftIds(new Set())
    setIsGeneratingScenarioMetrics(false)
    setMetricSelectedAIProvider(null)
    setMetricSelectedModel('')
    setMetricLlmConfig(null)
    setShowMetricProviderDropdown(false)
    setShowProviderDropdown(false)
    setScenarioMediumFilter('voice')
    resetForm()
  }

  const handleProviderSelect = (provider: ModelProvider) => {
    setSelectedAIProvider(provider)
    setShowProviderDropdown(false)
    setSelectedModel('') // Reset model selection when provider changes
  }

  const handleMetricProviderSelect = (provider: ModelProvider) => {
    setMetricSelectedAIProvider(provider)
    setShowMetricProviderDropdown(false)
    setMetricSelectedModel('')
  }

  const agentPromptModalWidthClass =
    createMode === 'agent_prompt' && generatedScenarioDrafts.length > 0
      ? 'max-w-6xl'
      : 'max-w-2xl'

  const handleGenerateFromCall = () => {
    if (!callData.trim()) {
      showToast('Please enter call data', 'error')
      return
    }
    generateFromCallMutation.mutate(callData)
  }

  const openScenarioMetricsWorkflow = (items: Scenario[]) => {
    const eligible = items.filter(
      (s) => (s.description || '').trim().length > 0 || s.name.trim().length > 0
    )
    if (eligible.length === 0) {
      showToast('Add a description to scenarios before generating metrics', 'error')
      return
    }
    setScenarioMetricsModalScenarios(eligible)
    setShowScenarioMetricsModal(true)
  }

  const scenarioMetricsModalDefaultAgentId =
    selectedNavAgentId && selectedNavAgentId !== 'unlinked' ? selectedNavAgentId : null

  const openCreateModal = () => {
    resetForm()
    const linkedAgentId = selectedNavAgentId !== 'unlinked' ? selectedNavAgentId : ''
    const linkedAgent = linkedAgentId
      ? availableAgents.find((a) => a.id === linkedAgentId)
      : undefined
    setScenarioMediumFilter(
      linkedAgent && isChatMedium(linkedAgent.call_medium) ? 'chat' : 'voice',
    )
    if (linkedAgentId) {
      setFormData((prev) => ({ ...prev, agent_id: linkedAgentId }))
      setSelectedAgentIdForGeneration(linkedAgentId)
    }
    setShowMainModal(true)
  }

  const renderCreateMediumTabs = () => (
    <div className="mb-5">
      <p className="text-xs font-medium text-gray-500 mb-2">Agent medium</p>
      <ScenarioAgentMediumTabs
        value={scenarioMediumFilter}
        onChange={handleScenarioMediumFilterChange}
      />
      <p className="mt-2 text-xs text-gray-500">
        {scenarioMediumFilter === 'chat'
          ? 'Chat agents only — scenarios for chat evals.'
          : 'Voice agents only — phone, web call, and platform voice.'}
      </p>
    </div>
  )

  const handleViewScenario = (scenario: Scenario) => {
    setSelectedScenario(scenario)
    setShowDetailsModal(true)
  }

  const handleEdit = (scenario: Scenario) => {
    setSelectedScenario(scenario)
    const linked = scenario.agent_id
      ? availableAgents.find((a) => a.id === scenario.agent_id)
      : undefined
    setScenarioMediumFilter(linked && isChatMedium(linked.call_medium) ? 'chat' : 'voice')
    setFormData({
      name: scenario.name,
      agent_id: scenario.agent_id || '',
      description: scenario.description || '',
      required_info: scenario.required_info,
    })
    setShowEditModal(true)
  }

  const handleUpdate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.name.trim()) {
      showToast('Please enter a scenario name', 'error')
      return
    }
    if (!selectedScenario) return

    updateMutation.mutate({
      id: selectedScenario.id,
      data: {
        name: formData.name,
        agent_id: formData.agent_id || null,
        description: formData.description || undefined,
        required_info: formData.required_info,
      },
    })
  }

  const handleGenerateDescriptionForEdit = async () => {
    if (!selectedScenario) return
    if (!selectedAIProvider) {
      showToast('Please select an AI provider', 'error')
      return
    }
    if (!selectedModel) {
      showToast('Please select a model', 'error')
      return
    }
    if (!editGeneratePrompt.trim()) {
      showToast('Please enter what you want to generate', 'error')
      return
    }

    const editModality =
      formData.agent_id
        ? (isChatMedium(availableAgents.find((a) => a.id === formData.agent_id)?.call_medium)
            ? 'chat'
            : 'voice')
        : scenarioMediumFilter

    setIsGeneratingEditDescription(true)
    try {
      const response = await apiClient.chatCompletion({
        messages: [
          {
            role: 'system',
            content: scenarioEditGenerationSystemPrompt(editModality),
          },
          {
            role: 'user',
            content: buildScenarioEditGenerationUserPrompt({
              scenarioName: formData.name || selectedScenario.name,
              currentDescription: formData.description || selectedScenario.description || 'None',
              request: editGeneratePrompt.trim(),
              modality: editModality,
            }),
          },
        ],
        provider: selectedAIProvider,
        model: selectedModel,
        llm_config: llmConfig,
        max_tokens: 4000,
      })

      setFormData((prev) => ({
        ...prev,
        description: response.text?.trim() || prev.description,
      }))
      showToast('Description generated. You can edit before saving.', 'success')
    } catch (error: any) {
      showToast(`Failed to generate description: ${error.response?.data?.detail || error.message}`, 'error')
    } finally {
      setIsGeneratingEditDescription(false)
    }
  }

  const handleCloseEditModal = () => {
    setShowEditModal(false)
    setSelectedScenario(null)
    setEditGeneratePrompt('')
    resetForm()
  }

  const handleDelete = (scenario: Scenario) => {
    setSelectedScenario(scenario)
    setDeleteDependencies(null)
    setShowDeleteModal(true)
  }

  const confirmDelete = (force?: boolean) => {
    if (selectedScenario) {
      deleteMutation.mutate({ id: selectedScenario.id, force })
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader className="h-8 w-8 animate-spin text-primary-600" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <ToastContainer />

      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-3xl font-bold text-gray-900">Test Scenarios</h1>
          <p className="text-gray-600 mt-1">
            Browse scenarios by agent — select an agent on the left to view and manage its scenarios
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 pr-2">
          {visibleScenarios.length > 0 ? (
            <Button
              variant="outline"
              onClick={() => openScenarioMetricsWorkflow(visibleScenarios)}
              leftIcon={
                !scenarioMetricsEnabled && licenseLoaded ? (
                  <Lock className="h-4 w-4 text-amber-600" />
                ) : (
                  <BarChart3 className="h-4 w-4" />
                )
              }
            >
              Generate metrics
            </Button>
          ) : null}
          <Button
            variant="primary"
            onClick={openCreateModal}
            leftIcon={<Plus className="h-5 w-5" />}
          >
            Create Scenario
          </Button>
          <WalkthroughToggleButton />
        </div>
      </div>

      {availableAgents.length === 0 && userScenarios.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <FileText className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No scenarios yet</h3>
          <p className="text-gray-500 mb-4">Create your first scenario to get started</p>
          <Button variant="primary" onClick={openCreateModal} leftIcon={<Plus className="h-5 w-5" />}>
            Create Scenario
          </Button>
        </div>
      ) : (
        <div className="flex flex-col lg:flex-row gap-4 min-h-[calc(100vh-11rem)]">
          <ScenariosAgentSidebar
            agents={agentsWithScenarios}
            selectedAgentId={selectedNavAgentId || agentsWithScenarios[0]?.id || ''}
            scenarioCountByAgent={scenarioCountByAgent}
            unlinkedCount={unlinkedScenarioCount}
            onSelectAgent={setSelectedNavAgentId}
          />
          <ScenariosListPanel
            agentLabel={selectedAgentLabel}
            scenarios={visibleScenarios}
            onEditScenario={handleEdit}
            onDeleteScenario={handleDelete}
            onViewScenario={handleViewScenario}
            showGenerateMetrics={licenseLoaded}
            onGenerateMetrics={(scenario) => openScenarioMetricsWorkflow([scenario])}
          />
        </div>
      )}

      {/* Main Create Scenario Modal */}
      {showMainModal && renderModal(
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
          <div
            className={`bg-white rounded-lg shadow-xl w-full mx-4 ${agentPromptModalWidthClass} max-h-[90vh] overflow-hidden flex flex-col`}
          >
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Create Scenario</h3>
              <button
                onClick={handleCloseMainModal}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {!createMode ? (
              // Mode Selection
              <div className="p-6">
                <div className="mx-auto max-w-2xl">
                {renderCreateMediumTabs()}
                <div className="mb-5 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3">
                  <p className="text-sm font-medium text-blue-900">Choose how you want to create this scenario</p>
                  <p className="mt-1 text-xs text-blue-700">
                    Fastest option: <span className="font-medium">Generate from Agent Prompt</span>. Most flexibility:
                    <span className="font-medium"> Create Custom Prompt</span>.
                  </p>
                </div>
                <div className="space-y-4">
                  {/* Generate from Agent Prompt */}
                  <button
                    onClick={() => setCreateMode('agent_prompt')}
                    className="group relative w-full p-5 bg-gradient-to-br from-blue-50 to-indigo-50 border-2 border-blue-200 rounded-xl hover:border-blue-400 hover:shadow-lg transition-all text-left focus:outline-none focus:ring-2 focus:ring-blue-400"
                  >
                    <div className="flex items-start gap-4">
                      <div className="flex-shrink-0">
                        <div className="w-12 h-12 bg-blue-500 rounded-lg flex items-center justify-center group-hover:bg-blue-600 transition-colors">
                          <Sparkles className="h-6 w-6 text-white" />
                        </div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="mb-2 flex items-start justify-between gap-2">
                          <h3 className="text-base font-semibold text-gray-900">Generate from Agent Prompt</h3>
                          <span className="shrink-0 whitespace-nowrap rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-medium text-blue-700">
                            Recommended
                          </span>
                        </div>
                        <p className="text-sm text-gray-600 leading-relaxed">
                          Select an existing agent and generate multiple scenario drafts from its system prompt.
                        </p>
                        <p className="mt-2 text-xs text-blue-700">Best for: creating many scenarios quickly</p>
                      </div>
                    </div>
                  </button>

                  {scenarioMediumFilter === 'voice' ? (
                  <button
                    onClick={() => setCreateMode('call')}
                    className="group relative w-full p-5 bg-gradient-to-br from-green-50 to-emerald-50 border-2 border-green-200 rounded-xl hover:border-green-400 hover:shadow-lg transition-all text-left focus:outline-none focus:ring-2 focus:ring-green-400"
                  >
                    <div className="flex items-start gap-4">
                      <div className="flex-shrink-0">
                        <div className="w-12 h-12 bg-green-500 rounded-lg flex items-center justify-center group-hover:bg-green-600 transition-colors">
                          <Phone className="h-6 w-6 text-white" />
                        </div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-base font-semibold text-gray-900 mb-2">Generate from Call</h3>
                        <p className="text-sm text-gray-600 leading-relaxed">
                          Extract and create a scenario from existing call transcripts or recordings.
                        </p>
                        <p className="mt-2 text-xs text-green-700">Best for: converting real calls into test scenarios</p>
                      </div>
                    </div>
                  </button>
                  ) : null}

                  {/* Create Custom Prompt */}
                  <button
                    onClick={() => setCreateMode('custom')}
                    className="group relative w-full p-5 bg-gradient-to-br from-orange-50 to-amber-50 border-2 border-orange-200 rounded-xl hover:border-orange-400 hover:shadow-lg transition-all text-left focus:outline-none focus:ring-2 focus:ring-orange-400"
                  >
                    <div className="flex items-start gap-4">
                      <div className="flex-shrink-0">
                        <div className="w-12 h-12 bg-orange-500 rounded-lg flex items-center justify-center group-hover:bg-orange-600 transition-colors">
                          <Plus className="h-6 w-6 text-white" />
                        </div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-base font-semibold text-gray-900 mb-2">Create Manually</h3>
                        <p className="text-sm text-gray-600 leading-relaxed">
                          Manually create a custom scenario with specific requirements and conversation flow.
                        </p>
                        <p className="mt-2 text-xs text-orange-700">Best for: manual control over scenario details</p>
                      </div>
                    </div>
                  </button>
                </div>
                <div className="mt-6 flex justify-end">
                  <Button type="button" variant="outline" onClick={handleCloseMainModal}>
                    Cancel
                  </Button>
                </div>
                </div>
              </div>
            ) : createMode === 'agent_prompt' ? (
              // Generate from Agent Prompt
              <div className="p-6 overflow-y-auto flex-1">
                <button
                  onClick={() => setCreateMode(null)}
                  className="mb-4 text-sm text-gray-600 hover:text-gray-900 flex items-center gap-2"
                >
                  <X className="h-4 w-4" />
                  Back
                </button>
                <h4 className="text-lg font-semibold text-gray-900 mb-4">Generate from Agent Prompt</h4>
                {renderCreateMediumTabs()}
                <div className="space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Agent *</label>
                      <select
                        value={selectedAgentIdForGeneration}
                        onChange={(e) => setSelectedAgentIdForGeneration(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      >
                        <option value="">Select an agent</option>
                        {agentsForScenarioMedium.map((agent) => (
                          <option key={agent.id} value={agent.id}>
                            {agent.name}
                          </option>
                        ))}
                      </select>
                      {agentsForScenarioMedium.length === 0 ? (
                        <p className="mt-1 text-xs text-amber-700">
                          No {scenarioMediumFilter === 'chat' ? 'chat' : 'voice'} agents yet. Create one
                          under Agents first.
                        </p>
                      ) : null}
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Number of Scenarios *</label>
                      <input
                        type="number"
                        min={1}
                        max={10}
                        value={scenarioCount}
                        onChange={(e) => setScenarioCount(Number(e.target.value))}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">AI Provider *</label>
                      <div className="relative" ref={providerDropdownRef}>
                        <button
                          type="button"
                          onClick={() => setShowProviderDropdown(!showProviderDropdown)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white text-left flex items-center justify-between"
                        >
                          <div className="flex items-center gap-2">
                            {selectedAIProvider && getProviderLogo(selectedAIProvider) ? (
                              <img
                                src={getProviderLogo(selectedAIProvider)!}
                                alt={getProviderLabel(selectedAIProvider)}
                                className="w-5 h-5 object-contain"
                              />
                            ) : selectedAIProvider ? (
                              <Brain className="h-5 w-5 text-primary-600" />
                            ) : null}
                            <span>{selectedAIProvider ? getProviderLabel(selectedAIProvider) : 'Select an AI Provider'}</span>
                          </div>
                          <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${showProviderDropdown ? 'transform rotate-180' : ''}`} />
                        </button>
                        {showProviderDropdown && (
                          <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-auto">
                            {configuredProviders.map((provider: ModelProvider) => (
                              <button
                                key={provider}
                                type="button"
                                onClick={() => handleProviderSelect(provider)}
                                className="w-full px-3 py-2 text-left hover:bg-gray-50 transition-colors flex items-center gap-2"
                              >
                                {getProviderLogo(provider) ? (
                                  <img
                                    src={getProviderLogo(provider)!}
                                    alt={getProviderLabel(provider)}
                                    className="w-5 h-5 object-contain"
                                  />
                                ) : (
                                  <Brain className="h-5 w-5 text-primary-600" />
                                )}
                                {getProviderLabel(provider)}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Model *</label>
                      {gatewayDirectModel ? (
                        <div
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-gray-50 text-gray-700 truncate"
                          title={gatewayDirectModel}
                        >
                          {gatewayDirectModel}
                        </div>
                      ) : (
                        <select
                          value={selectedModel}
                          onChange={(e) => setSelectedModel(e.target.value)}
                          disabled={!selectedAIProvider || selectableLlmModels.length === 0}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent disabled:bg-gray-100 disabled:text-gray-500"
                        >
                          <option value="">
                            {!selectedAIProvider ? 'Select provider first' : selectableLlmModels.length === 0 ? 'No models found' : 'Select model'}
                          </option>
                          {selectableLlmModels.map((model) => (
                            <option key={model} value={model}>
                              {model}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                    {selectedAIProvider && !gatewayDirectModel && (
                      <div className="md:col-span-2">
                        <LLMAdvancedOptionsPanel
                          provider={selectedAIProvider}
                          value={llmConfig}
                          onChange={setLlmConfig}
                        />
                      </div>
                    )}
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Additional Instructions (Optional)
                    </label>
                    <textarea
                      value={additionalAgentPromptContext}
                      onChange={(e) => setAdditionalAgentPromptContext(e.target.value)}
                      rows={3}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      placeholder={
                        scenarioMediumFilter === 'chat'
                          ? 'Optional: edge cases, compliance, chat-specific flows (customer/user language, not phone calls).'
                          : 'Add context to combine with agent system prompt (e.g., edge cases, payment failures, escalation paths).'
                      }
                    />
                  </div>

                  <div className="flex gap-3 pt-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleCloseMainModal}
                      className="flex-1"
                    >
                      Cancel
                    </Button>
                    <Button
                      type="button"
                      variant="primary"
                      onClick={handleGenerateFromAgentPrompt}
                      isLoading={isGeneratingFromAgentPrompt}
                      disabled={!selectedAgentIdForGeneration || !selectedAIProvider || !selectedModel}
                      className="flex-1"
                    >
                      Generate Scenarios
                    </Button>
                  </div>

                  {generatedScenarioDrafts.length > 0 && (
                    <div className="pt-4 border-t border-gray-200 space-y-4">
                      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                        <h5 className="text-sm font-semibold text-gray-900">
                          Generated Scenarios ({generatedScenarioDrafts.length})
                        </h5>
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => {
                            void handleGenerateMetricsForDrafts()
                          }}
                          isLoading={isGeneratingScenarioMetrics}
                          disabled={
                            !selectedAgentIdForGeneration ||
                            !metricSelectedAIProvider ||
                            !metricSelectedModel ||
                            isGeneratingFromAgentPrompt
                          }
                          className="shrink-0"
                        >
                          {!scenarioMetricsEnabled && (
                            <Lock className="h-4 w-4 text-amber-600 mr-1.5" aria-hidden />
                          )}
                          <BarChart3 className="h-4 w-4 mr-1.5" aria-hidden />
                          Generate Metrics
                        </Button>
                      </div>
                      {!scenarioMetricsEnabled && licenseLoaded && (
                        <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                          {getFeatureMeta('scenario_metrics')?.title ?? 'Scenario Metrics'} is an
                          Enterprise feature. Set{' '}
                          <code className="font-mono text-[11px] bg-amber-100/80 px-1 rounded">
                            EFFICIENTAI_LICENSE
                          </code>{' '}
                          on your server to generate and push metrics from these scenarios.
                        </p>
                      )}
                      {scenarioMetricsEnabled && (
                        <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-4">
                          <div>
                            <h6 className="text-sm font-semibold text-gray-900">
                              Metric generation model
                            </h6>
                            <p className="text-xs text-gray-500 mt-1">
                              Choose a separate AI provider and model for generating metrics (independent
                              from scenario generation).
                            </p>
                          </div>
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                              <label className="block text-sm font-medium text-gray-700 mb-2">
                                AI Provider *
                              </label>
                              <div className="relative" ref={metricProviderDropdownRef}>
                                <button
                                  type="button"
                                  onClick={() =>
                                    setShowMetricProviderDropdown(!showMetricProviderDropdown)
                                  }
                                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white text-left flex items-center justify-between"
                                >
                                  <div className="flex items-center gap-2">
                                    {metricSelectedAIProvider &&
                                    getProviderLogo(metricSelectedAIProvider) ? (
                                      <img
                                        src={getProviderLogo(metricSelectedAIProvider)!}
                                        alt={getProviderLabel(metricSelectedAIProvider)}
                                        className="w-5 h-5 object-contain"
                                      />
                                    ) : metricSelectedAIProvider ? (
                                      <Brain className="h-5 w-5 text-primary-600" />
                                    ) : null}
                                    <span>
                                      {metricSelectedAIProvider
                                        ? getProviderLabel(metricSelectedAIProvider)
                                        : 'Select an AI Provider'}
                                    </span>
                                  </div>
                                  <ChevronDown
                                    className={`h-4 w-4 text-gray-400 transition-transform ${showMetricProviderDropdown ? 'transform rotate-180' : ''}`}
                                  />
                                </button>
                                {showMetricProviderDropdown && (
                                  <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-auto">
                                    {configuredProviders.map((provider: ModelProvider) => (
                                      <button
                                        key={`metric-${provider}`}
                                        type="button"
                                        onClick={() => handleMetricProviderSelect(provider)}
                                        className="w-full px-3 py-2 text-left hover:bg-gray-50 transition-colors flex items-center gap-2"
                                      >
                                        {getProviderLogo(provider) ? (
                                          <img
                                            src={getProviderLogo(provider)!}
                                            alt={getProviderLabel(provider)}
                                            className="w-5 h-5 object-contain"
                                          />
                                        ) : (
                                          <Brain className="h-5 w-5 text-primary-600" />
                                        )}
                                        {getProviderLabel(provider)}
                                      </button>
                                    ))}
                                  </div>
                                )}
                              </div>
                            </div>
                            <div>
                              <label className="block text-sm font-medium text-gray-700 mb-2">
                                Model *
                              </label>
                              {metricGatewayDirectModel ? (
                                <div
                                  className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-gray-50 text-gray-700 truncate"
                                  title={metricGatewayDirectModel}
                                >
                                  {metricGatewayDirectModel}
                                </div>
                              ) : (
                                <select
                                  value={metricSelectedModel}
                                  onChange={(e) => setMetricSelectedModel(e.target.value)}
                                  disabled={
                                    !metricSelectedAIProvider ||
                                    selectableMetricLlmModels.length === 0
                                  }
                                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent disabled:bg-gray-100 disabled:text-gray-500"
                                >
                                  <option value="">
                                    {!metricSelectedAIProvider
                                      ? 'Select provider first'
                                      : selectableMetricLlmModels.length === 0
                                        ? 'No models found'
                                        : 'Select model'}
                                  </option>
                                  {selectableMetricLlmModels.map((model) => (
                                    <option key={`metric-model-${model}`} value={model}>
                                      {model}
                                    </option>
                                  ))}
                                </select>
                              )}
                            </div>
                            {metricSelectedAIProvider && !metricGatewayDirectModel && (
                              <div className="md:col-span-2">
                                <LLMAdvancedOptionsPanel
                                  provider={metricSelectedAIProvider}
                                  value={metricLlmConfig}
                                  onChange={setMetricLlmConfig}
                                />
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                      {generatedScenarioDrafts.map((draft) => (
                        <div key={draft.id} className="border border-gray-200 rounded-lg p-4 bg-gray-50">
                          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 lg:gap-6 items-start">
                            <div className="space-y-3 min-w-0">
                              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                                Scenario
                              </p>
                              <div>
                                <label className="block text-xs font-medium text-gray-700 mb-1">
                                  Name
                                </label>
                                <input
                                  type="text"
                                  value={draft.name}
                                  onChange={(e) =>
                                    updateGeneratedDraft(draft.id, { name: e.target.value })
                                  }
                                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
                                />
                              </div>
                              <div>
                                <label className="block text-xs font-medium text-gray-700 mb-1">
                                  Description
                                </label>
                                <MarkdownEditor
                                  value={draft.description}
                                  onChange={(description) =>
                                    updateGeneratedDraft(draft.id, { description })
                                  }
                                  rows={8}
                                  defaultMode="preview"
                                  placeholder="Scenario description (markdown supported)..."
                                />
                              </div>
                              <div className="flex items-center justify-end gap-2 pt-1">
                                <Button
                                  type="button"
                                  variant="outline"
                                  onClick={() => removeGeneratedDraft(draft.id)}
                                >
                                  Remove
                                </Button>
                                <Button
                                  type="button"
                                  variant="primary"
                                  isLoading={savingDraftIds.has(draft.id)}
                                  onClick={() => {
                                    void saveGeneratedDraft(draft)
                                  }}
                                >
                                  Save Scenario
                                </Button>
                              </div>
                            </div>

                            <div className="space-y-3 min-w-0 lg:border-l lg:border-gray-200 lg:pl-6">
                              <div className="flex items-center justify-between gap-2">
                                <p className="text-xs font-semibold text-primary-700 uppercase tracking-wide">
                                  Metric
                                </p>
                                {draft.metricPushed && (
                                  <span className="text-xs font-medium text-green-700 bg-green-50 border border-green-200 rounded-full px-2 py-0.5">
                                    In Metrics
                                  </span>
                                )}
                              </div>

                              {!draft.metric ? (
                                <div className="rounded-lg border border-dashed border-primary-200 bg-white p-4 space-y-3 min-h-[220px]">
                                  <div>
                                    <label className="block text-xs font-medium text-gray-700 mb-1">
                                      Metric type to generate
                                    </label>
                                    <select
                                      value={draft.plannedMetricType}
                                      disabled={!scenarioMetricsEnabled || draft.metricPushed}
                                      onChange={(e) =>
                                        updateGeneratedDraft(draft.id, {
                                          plannedMetricType: e.target
                                            .value as PlannedScenarioMetricType,
                                        })
                                      }
                                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white text-sm"
                                    >
                                      <option value="auto">Auto (LLM chooses)</option>
                                      <option value="boolean">Boolean</option>
                                      <option value="rating">Rating</option>
                                      <option value="number">Number</option>
                                      <option value="text">Text</option>
                                    </select>
                                  </div>
                                  <p className="text-xs text-gray-500 leading-relaxed">
                                    Pick how this scenario should be scored, then click{' '}
                                    <span className="font-medium">Generate Metrics</span> above. The
                                    generated rubric will appear here beside the scenario.
                                  </p>
                                </div>
                              ) : (
                                <div className="rounded-lg border border-primary-200 bg-white p-3 space-y-3 min-h-[220px]">
                                  <div>
                                    <label className="block text-xs font-medium text-gray-700 mb-1">
                                      Metric name
                                    </label>
                                    <input
                                      type="text"
                                      value={draft.metric.name}
                                      disabled={draft.metricPushed}
                                      onChange={(e) =>
                                        updateGeneratedDraftMetric(draft.id, {
                                          name: e.target.value,
                                        })
                                      }
                                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white disabled:bg-gray-100"
                                    />
                                  </div>
                                  <div>
                                    <label className="block text-xs font-medium text-gray-700 mb-1">
                                      Metric description (rubric)
                                    </label>
                                    <textarea
                                      value={draft.metric.description}
                                      disabled={draft.metricPushed}
                                      onChange={(e) =>
                                        updateGeneratedDraftMetric(draft.id, {
                                          description: e.target.value,
                                        })
                                      }
                                      rows={4}
                                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white disabled:bg-gray-100 text-sm"
                                    />
                                  </div>
                                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                    <div>
                                      <label className="block text-xs font-medium text-gray-700 mb-1">
                                        Type
                                      </label>
                                      <select
                                        value={draft.metric.metric_type}
                                        disabled={draft.metricPushed}
                                        onChange={(e) => {
                                          const metric_type = e.target
                                            .value as GeneratedScenarioMetricDraft['metric_type']
                                          updateGeneratedDraftMetric(draft.id, {
                                            metric_type,
                                            custom_data_type: customDataTypeForMetricType(metric_type),
                                            custom_config:
                                              metric_type === 'text' ? {} : draft.metric?.custom_config,
                                          })
                                        }}
                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white disabled:bg-gray-100 text-sm"
                                      >
                                        <option value="boolean">Boolean</option>
                                        <option value="rating">Rating</option>
                                        <option value="number">Number</option>
                                        <option value="text">Text</option>
                                      </select>
                                    </div>
                                    <div>
                                      <label className="block text-xs font-medium text-gray-700 mb-1">
                                        Tags
                                      </label>
                                      <input
                                        type="text"
                                        value={draft.metric.tags.join(', ')}
                                        disabled={draft.metricPushed}
                                        onChange={(e) =>
                                          updateGeneratedDraftMetric(draft.id, {
                                            tags: e.target.value
                                              .split(',')
                                              .map((t) => t.trim())
                                              .filter(Boolean),
                                          })
                                        }
                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white disabled:bg-gray-100 text-sm"
                                        placeholder="Agent name and auto-generated are always applied"
                                      />
                                    </div>
                                  </div>
                                  {!draft.metricPushed && scenarioMetricsEnabled && (
                                    <div className="flex justify-end">
                                      <Button
                                        type="button"
                                        variant="primary"
                                        isLoading={pushingMetricDraftIds.has(draft.id)}
                                        disabled={!draft.metric.name.trim()}
                                        onClick={() => {
                                          void pushMetricForDraft(draft)
                                        }}
                                      >
                                        Add to Metrics
                                      </Button>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ) : createMode === 'call' ? (
              // Generate from Call
              <div className="p-6 overflow-y-auto flex-1">
                <button
                  onClick={() => setCreateMode(null)}
                  className="mb-4 text-sm text-gray-600 hover:text-gray-900 flex items-center gap-2"
                >
                  <X className="h-4 w-4" />
                  Back
                </button>
                <h4 className="text-lg font-semibold text-gray-900 mb-4">Generate Scenario from Call</h4>
                {renderCreateMediumTabs()}
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Call Transcript or Data *
                    </label>
                    <textarea
                      value={callData}
                      onChange={(e) => setCallData(e.target.value)}
                      rows={8}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent font-mono text-sm"
                      placeholder="Paste call transcript or upload call data here..."
                    />
                  </div>
                  <div className="flex gap-3 pt-4">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleCloseMainModal}
                      className="flex-1"
                    >
                      Cancel
                    </Button>
                    <Button
                      type="button"
                      variant="primary"
                      onClick={handleGenerateFromCall}
                      isLoading={generateFromCallMutation.isPending}
                      disabled={!callData.trim()}
                      className="flex-1"
                    >
                      Generate Scenario
                    </Button>
                  </div>
                </div>
              </div>
            ) : createMode === 'custom' ? (
              // Create Custom Prompt
              <div className="p-6 overflow-y-auto flex-1">
                <button
                  onClick={() => setCreateMode(null)}
                  className="mb-4 text-sm text-gray-600 hover:text-gray-900 flex items-center gap-2"
                >
                  <X className="h-4 w-4" />
                  Back
                </button>
                <h4 className="text-lg font-semibold text-gray-900 mb-4">Create Custom Scenario</h4>
                {renderCreateMediumTabs()}
                <form onSubmit={handleCreate} className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Scenario Name *
                    </label>
                    <input
                      type="text"
                      required
                      value={formData.name}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      placeholder="e.g., Book Appointment"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Linked Agent (Optional)
                    </label>
                    <select
                      value={formData.agent_id}
                      onChange={(e) => setFormData({ ...formData, agent_id: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    >
                      <option value="">No linked agent</option>
                      {agentsForScenarioMedium.map((agent) => (
                        <option key={agent.id} value={agent.id}>
                          {agent.name}
                        </option>
                      ))}
                    </select>
                    {agentsForScenarioMedium.length === 0 ? (
                      <p className="mt-1 text-xs text-amber-700">
                        No {scenarioMediumFilter === 'chat' ? 'chat' : 'voice'} agents to link.
                      </p>
                    ) : null}
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Description
                    </label>
                    <MarkdownEditor
                      value={formData.description}
                      onChange={(description) => setFormData({ ...formData, description })}
                      rows={6}
                      placeholder="Describe what this scenario tests... (markdown supported)"
                    />
                  </div>
                  <div className="flex gap-3 pt-4">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleCloseMainModal}
                      className="flex-1"
                    >
                      Cancel
                    </Button>
                    <Button
                      type="submit"
                      variant="primary"
                      isLoading={createMutation.isPending}
                      className="flex-1"
                    >
                      Create
                    </Button>
                  </div>
                </form>
              </div>
            ) : null}
          </div>
        </div>
      )}

      {/* Scenario Details Modal */}
      {showDetailsModal && selectedScenario && renderModal(
        <div
          className="fixed inset-0 bg-gray-500/75 flex items-center justify-center z-[9999] p-4 sm:p-6"
          onClick={() => setShowDetailsModal(false)}
        >
          <div
            className="bg-white rounded-xl shadow-xl w-full max-w-6xl h-[min(92vh,960px)] flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-start gap-4 shrink-0">
              <div className="min-w-0 flex-1">
                <h3 className="text-lg font-semibold text-gray-900">Scenario Details</h3>
                <h4 className="text-xl font-semibold text-gray-900 mt-1 truncate">{selectedScenario.name}</h4>
                <div className="mt-2">
                  {selectedScenario.agent_id ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700 border border-blue-100">
                      Linked Agent: {agentNameById.get(selectedScenario.agent_id) || 'Unlinked'}
                    </span>
                  ) : (
                    <span className="text-xs text-gray-500">Linked Agent: Unlinked</span>
                  )}
                </div>
              </div>
              <button
                onClick={() => {
                  setShowDetailsModal(false)
                  setSelectedScenario(null)
                }}
                className="text-gray-400 hover:text-gray-600 shrink-0"
                aria-label="Close"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto min-h-0 p-6 space-y-6">
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-5 sm:p-6 min-h-[min(55vh,100%)]">
                <ScenarioMarkdownView
                  content={selectedScenario.description || ''}
                  emptyMessage="No description configured."
                  size="lg"
                />
              </div>

              {Object.keys(selectedScenario.required_info).length > 0 && (
                <div>
                  <div className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-3">
                    <Tag className="w-4 h-4" />
                    Required Information
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {Object.entries(selectedScenario.required_info).map(([key, value]) => (
                      <div key={key} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg border border-gray-100">
                        <span className="text-sm font-medium text-gray-900">{key.replace(/_/g, ' ')}</span>
                        <span className="text-sm text-gray-600 font-mono ml-3 truncate">{value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="px-6 py-4 border-t border-gray-200 bg-gray-50/80 flex flex-wrap items-center justify-end gap-2 shrink-0">
              <Button
                variant="outline"
                onClick={() => {
                  setShowDetailsModal(false)
                }}
              >
                Close
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setShowDetailsModal(false)
                  openScenarioMetricsWorkflow([selectedScenario])
                }}
                leftIcon={
                  !scenarioMetricsEnabled && licenseLoaded ? (
                    <Lock className="h-4 w-4 text-amber-600" />
                  ) : (
                    <BarChart3 className="h-4 w-4" />
                  )
                }
              >
                Generate metric
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setShowDetailsModal(false)
                  handleEdit(selectedScenario)
                }}
              >
                Edit Scenario
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {showEditModal && selectedScenario && renderModal(
        <div className="fixed inset-0 bg-gray-500/75 flex items-center justify-center z-[9999] p-4 sm:p-6">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-6xl h-[min(92vh,960px)] overflow-hidden flex flex-col">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Edit Scenario</h3>
              <button
                onClick={handleCloseEditModal}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6 overflow-y-auto flex-1">
              <form onSubmit={handleUpdate} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Scenario Name *
                  </label>
                  <input
                    type="text"
                    required
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    placeholder="e.g., Book Appointment"
                  />
                </div>
                <div>
                  <p className="text-xs font-medium text-gray-500 mb-2">Agent medium</p>
                  <ScenarioAgentMediumTabs
                    value={scenarioMediumFilter}
                    onChange={handleScenarioMediumFilterChange}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Linked Agent (Optional)
                  </label>
                  <select
                    value={formData.agent_id}
                    onChange={(e) => setFormData({ ...formData, agent_id: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  >
                    <option value="">No linked agent</option>
                    {agentsForScenarioMedium.map((agent) => (
                      <option key={agent.id} value={agent.id}>
                        {agent.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Description
                  </label>
                  <MarkdownEditor
                    value={formData.description}
                    onChange={(description) => setFormData({ ...formData, description })}
                    rows={14}
                    placeholder="Describe what this scenario tests... (markdown supported)"
                  />
                </div>
                <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg space-y-3">
                  <div className="flex items-center gap-2">
                    <Sparkles className="h-4 w-4 text-amber-600" />
                    <p className="text-sm font-medium text-amber-900">AI Regenerate Description</p>
                  </div>
                  <p className="text-xs text-amber-800">
                    Generate a new description and then edit it before saving.
                  </p>
                  <textarea
                    value={editGeneratePrompt}
                    onChange={(e) => setEditGeneratePrompt(e.target.value)}
                    rows={2}
                    className="w-full px-3 py-2 text-sm border border-amber-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
                    placeholder="e.g., Make this more detailed for edge cases and fallback handling"
                  />
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-1">LLM Provider *</label>
                      <div className="relative" ref={providerDropdownRef}>
                        <button
                          type="button"
                          onClick={() => setShowProviderDropdown(!showProviderDropdown)}
                          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white text-left flex items-center justify-between"
                        >
                          <div className="flex items-center gap-2">
                            {selectedAIProvider && getProviderLogo(selectedAIProvider) ? (
                              <img
                                src={getProviderLogo(selectedAIProvider)!}
                                alt={getProviderLabel(selectedAIProvider)}
                                className="w-4 h-4 object-contain"
                              />
                            ) : selectedAIProvider ? (
                              <Brain className="h-4 w-4 text-primary-600" />
                            ) : null}
                            <span>{selectedAIProvider ? getProviderLabel(selectedAIProvider) : 'Select provider'}</span>
                          </div>
                          <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${showProviderDropdown ? 'transform rotate-180' : ''}`} />
                        </button>
                        {showProviderDropdown && (
                          <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-auto">
                            {configuredProviders.map((provider) => (
                              <button
                                key={provider}
                                type="button"
                                onClick={() => handleProviderSelect(provider)}
                                className="w-full px-3 py-2 text-left hover:bg-gray-50 transition-colors flex items-center gap-2 text-sm"
                              >
                                {getProviderLogo(provider) ? (
                                  <img
                                    src={getProviderLogo(provider)!}
                                    alt={getProviderLabel(provider)}
                                    className="w-4 h-4 object-contain"
                                  />
                                ) : (
                                  <Brain className="h-4 w-4 text-primary-600" />
                                )}
                                {getProviderLabel(provider)}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-1">Model *</label>
                      {gatewayDirectModel ? (
                        <div
                          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-gray-50 text-gray-700 truncate"
                          title={gatewayDirectModel}
                        >
                          {gatewayDirectModel}
                        </div>
                      ) : (
                        <select
                          value={selectedModel}
                          onChange={(e) => setSelectedModel(e.target.value)}
                          disabled={!selectedAIProvider || selectableLlmModels.length === 0}
                          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white disabled:bg-gray-100 disabled:text-gray-500"
                        >
                          <option value="">
                            {!selectedAIProvider ? 'Select provider first' : selectableLlmModels.length === 0 ? 'No models found' : 'Select model'}
                          </option>
                          {selectableLlmModels.map((model) => (
                            <option key={model} value={model}>
                              {model}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                    {selectedAIProvider && !gatewayDirectModel && (
                      <div className="md:col-span-2">
                        <LLMAdvancedOptionsPanel
                          provider={selectedAIProvider}
                          value={llmConfig}
                          onChange={setLlmConfig}
                        />
                      </div>
                    )}
                  </div>
                  <div className="flex justify-end">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleGenerateDescriptionForEdit}
                      isLoading={isGeneratingEditDescription}
                      disabled={!editGeneratePrompt.trim() || !selectedAIProvider || !selectedModel || isGeneratingEditDescription}
                      leftIcon={!isGeneratingEditDescription ? <Sparkles className="h-4 w-4" /> : undefined}
                    >
                      Generate Description
                    </Button>
                  </div>
                </div>
                <div className="flex gap-3 pt-4">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={handleCloseEditModal}
                    className="flex-1"
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    variant="primary"
                    isLoading={updateMutation.isPending}
                    className="flex-1"
                  >
                    Update
                  </Button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && selectedScenario && renderModal(
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]" onClick={() => {
          setShowDeleteModal(false)
          setSelectedScenario(null)
          setDeleteDependencies(null)
        }}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Delete Scenario</h3>
              <button
                onClick={() => {
                  setShowDeleteModal(false)
                  setSelectedScenario(null)
                  setDeleteDependencies(null)
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6">
              {deleteDependencies && (
                <div className="mb-4 p-4 bg-amber-50 border border-amber-200 rounded-lg">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <p className="text-sm font-medium text-amber-800 mb-2">
                        This scenario has dependent records
                      </p>
                      <ul className="text-xs text-amber-700 space-y-1 mb-3">
                        {deleteDependencies.evaluators && (
                          <li>{deleteDependencies.evaluators} evaluator{deleteDependencies.evaluators !== 1 ? 's' : ''}</li>
                        )}
                        {deleteDependencies.evaluator_results && (
                          <li>{deleteDependencies.evaluator_results} evaluator result{deleteDependencies.evaluator_results !== 1 ? 's' : ''}</li>
                        )}
                        {deleteDependencies.test_conversations && (
                          <li>{deleteDependencies.test_conversations} test conversation{deleteDependencies.test_conversations !== 1 ? 's' : ''}</li>
                        )}
                      </ul>
                      <p className="text-xs text-amber-700">
                        Force deleting will remove the scenario and all its dependent records.
                      </p>
                    </div>
                  </div>
                </div>
              )}

              <div className="flex items-start gap-4 mb-6">
                <div className="flex-shrink-0">
                  <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
                    <Trash2 className="h-6 w-6 text-red-600" />
                  </div>
                </div>
                <div className="flex-1">
                  <p className="text-sm text-gray-700 mb-2">
                    Are you sure you want to delete <span className="font-semibold text-gray-900">"{selectedScenario.name}"</span>?
                  </p>
                  <p className="text-xs text-gray-500">
                    This action cannot be undone. The scenario will be permanently deleted.
                  </p>
                </div>
              </div>
              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowDeleteModal(false)
                    setSelectedScenario(null)
                    setDeleteDependencies(null)
                  }}
                  className="flex-1"
                >
                  Cancel
                </Button>
                {deleteDependencies ? (
                  <Button
                    variant="danger"
                    onClick={() => confirmDelete(true)}
                    isLoading={deleteMutation.isPending}
                    leftIcon={!deleteMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
                    className="flex-1"
                  >
                    Force Delete All
                  </Button>
                ) : (
                  <Button
                    variant="danger"
                    onClick={() => confirmDelete()}
                    isLoading={deleteMutation.isPending}
                    leftIcon={!deleteMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
                    className="flex-1"
                  >
                    Delete
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <ScenarioMetricsFromScenariosModal
        open={showScenarioMetricsModal}
        onClose={() => {
          setShowScenarioMetricsModal(false)
          setScenarioMetricsModalScenarios([])
        }}
        scenarios={scenarioMetricsModalScenarios}
        agents={availableAgents}
        aiProviders={availableProviders}
        defaultAgentId={scenarioMetricsModalDefaultAgentId}
      />
    </div>
  )
}

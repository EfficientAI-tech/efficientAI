import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import { useAgentStore } from '../../../store/agentStore'
import { ModelProvider, AIProvider, Integration, IntegrationPlatform } from '../../../types/api'
import Button from '../../../components/Button'
import { Plus, Trash2, Play, X, CheckSquare, Square, Sparkles, Brain, ChevronDown } from 'lucide-react'
import { useToast } from '../../../hooks/useToast'
import { getProviderLabel, getProviderLogo } from '../../../config/providers'

const DEFAULT_PERSONA_NAMES = [
  "Grumpy Old Man",
  "Confused Senior",
  "Busy Professional",
  "Friendly Customer",
  "Angry Caller"
]

const DEFAULT_SCENARIO_NAMES = [
  "Cancel Subscription",
  "Check Balance",
  "Technical Support",
  "Make Complaint",
  "Product Inquiry"
]

interface Evaluator {
  id: string
  evaluator_id: string
  name?: string | null
  agent_id?: string | null
  persona_id?: string | null
  scenario_id?: string | null
  custom_prompt?: string | null
  llm_provider?: string | null
  llm_model?: string | null
  tags?: string[]
  created_at: string
  updated_at: string
}

export default function EvaluateTestAgents() {
  const { selectedAgent } = useAgentStore()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [createMode, setCreateMode] = useState<'standard' | 'custom'>('standard')
  const [selectedScenario, setSelectedScenario] = useState<string>('')
  const [selectedPersonas, setSelectedPersonas] = useState<string[]>([])
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [tagInput, setTagInput] = useState('')
  const [standardName, setStandardName] = useState('')
  const [customName, setCustomName] = useState('')
  const [customPrompt, setCustomPrompt] = useState('')
  const [runningEvaluatorIds, setRunningEvaluatorIds] = useState<Set<string>>(new Set())
  const [selectedEvaluatorIds, setSelectedEvaluatorIds] = useState<Set<string>>(new Set())
  const [showRunModal, setShowRunModal] = useState(false)
  const [runCount, setRunCount] = useState(1)
  const [showDeleteSelectedModal, setShowDeleteSelectedModal] = useState(false)
  const [isDeletingSelected, setIsDeletingSelected] = useState(false)
  const [modalAgentId, setModalAgentId] = useState<string>('')
  const [selectedLlmProvider, setSelectedLlmProvider] = useState<ModelProvider | null>(null)
  const [selectedLlmModel, setSelectedLlmModel] = useState<string>('')
  const [showLlmDropdown, setShowLlmDropdown] = useState(false)
  const llmDropdownRef = useRef<HTMLDivElement>(null)

  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => apiClient.listAgents(),
  })

  const { data: personas = [] } = useQuery({
    queryKey: ['personas'],
    queryFn: () => apiClient.listPersonas(),
  })

  const { data: scenarios = [] } = useQuery({
    queryKey: ['scenarios'],
    queryFn: () => apiClient.listScenarios(),
  })

  const { data: evaluators = [], isLoading: loadingEvaluators } = useQuery({
    queryKey: ['evaluators'],
    queryFn: () => apiClient.listEvaluators(),
  })

  const { data: aiproviders = [] } = useQuery({
    queryKey: ['aiproviders'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const { data: integrations = [] } = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
  })

  const { data: modelConfigs = {} } = useQuery({
    queryKey: ['model-configs'],
    queryFn: async () => {
      const providers = Object.values(ModelProvider)
      const configs: Record<string, { stt: string[]; llm: string[]; tts: string[]; s2s: string[] }> = {}
      for (const provider of providers) {
        try {
          const options = await apiClient.getModelOptions(provider)
          configs[provider] = { stt: options.stt || [], llm: options.llm || [], tts: options.tts || [], s2s: options.s2s || [] }
        } catch {
          configs[provider] = { stt: [], llm: [], tts: [], s2s: [] }
        }
      }
      return configs
    },
    staleTime: 5 * 60 * 1000,
  })

  const mapIntegrationToProvider = (platform: IntegrationPlatform | string): ModelProvider | null => {
    const platformLower = (typeof platform === 'string' ? platform : String(platform)).toLowerCase()
    switch (platformLower) {
      case 'deepgram': return ModelProvider.DEEPGRAM
      case 'cartesia': return ModelProvider.CARTESIA
      case 'elevenlabs': return ModelProvider.ELEVENLABS
      case 'murf': return ModelProvider.MURF
      case 'sarvam': return ModelProvider.SARVAM
      case 'voicemaker': return ModelProvider.VOICEMAKER
      default: return null
    }
  }

  const configuredProviders = Array.from(
    new Set([
      ...(aiproviders.filter((p: AIProvider) => p.is_active).map((p: AIProvider) => p.provider as ModelProvider)),
      ...(integrations.filter((i: Integration) => i.is_active).map((i: Integration) => mapIntegrationToProvider(i.platform)).filter((p): p is ModelProvider => Boolean(p))),
    ])
  )

  const llmProviders = configuredProviders.filter(p => {
    const opts = modelConfigs[p]
    return opts && opts.llm && opts.llm.length > 0
  })

  const getModelOptions = (provider: ModelProvider): { stt: string[]; llm: string[]; tts: string[]; s2s: string[] } => {
    return modelConfigs[provider] || { stt: [], llm: [], tts: [], s2s: [] }
  }

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (llmDropdownRef.current && !llmDropdownRef.current.contains(event.target as Node)) {
        setShowLlmDropdown(false)
      }
    }
    if (showLlmDropdown) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showLlmDropdown])

  const filteredPersonas = personas.filter((p: any) => !DEFAULT_PERSONA_NAMES.includes(p.name))
  const filteredScenarios = scenarios.filter((s: any) => !DEFAULT_SCENARIO_NAMES.includes(s.name))

  const createBulkMutation = useMutation({
    mutationFn: (data: { name?: string; agent_id: string; scenario_id: string; persona_ids: string[]; tags?: string[] }) =>
      apiClient.createEvaluatorsBulk(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluators'] })
      setShowCreateModal(false)
      setStandardName('')
      setModalAgentId('')
      setSelectedScenario('')
      setSelectedPersonas([])
      setSelectedTags([])
    },
  })

  const createCustomMutation = useMutation({
    mutationFn: (data: { name: string; custom_prompt: string; llm_provider?: string; llm_model?: string; tags?: string[] }) =>
      apiClient.createEvaluator(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluators'] })
      setShowCreateModal(false)
      setCustomName('')
      setCustomPrompt('')
      setSelectedLlmProvider(null)
      setSelectedLlmModel('')
      setSelectedTags([])
      setCreateMode('standard')
    },
  })

  const [isFormattingPrompt, setIsFormattingPrompt] = useState(false)

  const handleFormatPrompt = async () => {
    if (!customPrompt.trim()) return
    setIsFormattingPrompt(true)
    try {
      const { formatted_prompt } = await apiClient.formatCustomPrompt(customPrompt)
      setCustomPrompt(formatted_prompt)
    } catch (error: any) {
      const msg = error.response?.data?.detail || error.message || 'Formatting failed'
      alert(`Failed to format prompt: ${msg}`)
    } finally {
      setIsFormattingPrompt(false)
    }
  }

  const handleCreate = () => {
    if (createMode === 'custom') {
      if (!customName.trim()) {
        alert('Please enter a name for the custom evaluator')
        return
      }
      if (!customPrompt.trim()) {
        alert('Please enter the agent prompt / instructions')
        return
      }
      createCustomMutation.mutate({
        name: customName.trim(),
        custom_prompt: customPrompt.trim(),
        llm_provider: selectedLlmProvider || undefined,
        llm_model: selectedLlmModel || undefined,
        tags: selectedTags.length > 0 ? selectedTags : undefined,
      })
      return
    }

    if (!modalAgentId) {
      alert('Please select an agent')
      return
    }
    if (!selectedScenario) {
      alert('Please select a scenario')
      return
    }
    if (selectedPersonas.length === 0) {
      alert('Please select at least one persona')
      return
    }

    createBulkMutation.mutate({
      name: standardName.trim() || undefined,
      agent_id: modalAgentId,
      scenario_id: selectedScenario,
      persona_ids: selectedPersonas,
      tags: selectedTags.length > 0 ? selectedTags : undefined,
    })
  }

  const togglePersona = (personaId: string) => {
    if (selectedPersonas.includes(personaId)) {
      setSelectedPersonas(selectedPersonas.filter(id => id !== personaId))
    } else {
      setSelectedPersonas([...selectedPersonas, personaId])
    }
  }

  const addTag = (tags: string[], setTags: (tags: string[]) => void, input: string, setInput: (input: string) => void) => {
    if (input.trim() && !tags.includes(input.trim())) {
      setTags([...tags, input.trim()])
      setInput('')
    }
  }

  const removeTag = (tag: string) => {
    setSelectedTags(selectedTags.filter(t => t !== tag))
  }

  const toggleEvaluatorSelection = (evaluatorId: string) => {
    setSelectedEvaluatorIds(prev => {
      const newSet = new Set(prev)
      if (newSet.has(evaluatorId)) {
        newSet.delete(evaluatorId)
      } else {
        newSet.add(evaluatorId)
      }
      return newSet
    })
  }

  const toggleSelectAllEvaluators = () => {
    const selectableIds = evaluators
      .filter((evaluator: Evaluator) => !runningEvaluatorIds.has(evaluator.id))
      .map((evaluator: Evaluator) => evaluator.id)

    const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selectedEvaluatorIds.has(id))
    if (allSelected) {
      setSelectedEvaluatorIds(new Set())
      return
    }
    setSelectedEvaluatorIds(new Set(selectableIds))
  }

  const handleDeleteSelected = () => {
    if (selectedEvaluatorIds.size === 0) {
      showToast('Please select at least one evaluator to delete', 'error')
      return
    }
    setShowDeleteSelectedModal(true)
  }

  const executeDeleteSelected = async () => {
    if (selectedEvaluatorIds.size === 0) return
    setIsDeletingSelected(true)
    const idsToDelete = Array.from(selectedEvaluatorIds)
    try {
      const results = await Promise.allSettled(idsToDelete.map((id) => apiClient.deleteEvaluator(id)))
      const successCount = results.filter((result) => result.status === 'fulfilled').length
      const failedResults = results.filter((result) => result.status === 'rejected') as PromiseRejectedResult[]

      if (successCount > 0) {
        queryClient.invalidateQueries({ queryKey: ['evaluators'] })
        showToast(`Deleted ${successCount} evaluator${successCount > 1 ? 's' : ''} successfully`, 'success')
      }

      if (failedResults.length > 0) {
        const firstError: any = failedResults[0].reason
        const detail = firstError?.response?.data?.detail
        const errorMessage = typeof detail === 'string'
          ? detail
          : detail?.message || firstError?.message || 'Some evaluators could not be deleted.'
        showToast(`${errorMessage} (${failedResults.length} failed)`, 'error')
      }

      const deletedIds = idsToDelete.filter((_, idx) => results[idx].status === 'fulfilled')
      setSelectedEvaluatorIds((prev) => {
        const next = new Set(prev)
        deletedIds.forEach((id) => next.delete(id))
        return next
      })
      setShowDeleteSelectedModal(false)
    } finally {
      setIsDeletingSelected(false)
    }
  }

  const handleRunSelected = () => {
    if (selectedEvaluatorIds.size === 0) {
      showToast('Please select at least one evaluator to run', 'error')
      return
    }
    // Show the run modal to select how many times to run
    setRunCount(1)
    setShowRunModal(true)
  }

  const executeRuns = async () => {
    try {
      const evaluatorIdsArray = Array.from(selectedEvaluatorIds)
      setRunningEvaluatorIds(new Set(evaluatorIdsArray))
      setShowRunModal(false)

      // Create an array with each evaluator ID repeated runCount times
      const expandedIds: string[] = []
      for (const id of evaluatorIdsArray) {
        for (let i = 0; i < runCount; i++) {
          expandedIds.push(id)
        }
      }

      await apiClient.runEvaluators(expandedIds)

      // Invalidate queries to refresh results
      queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })

      // Clear selection after starting
      setSelectedEvaluatorIds(new Set())

      // Show success toast
      const totalRuns = evaluatorIdsArray.length * runCount
      showToast(`🚀 Queued ${totalRuns} evaluation${totalRuns > 1 ? 's' : ''}! Check Results for progress.`, 'success')
    } catch (error: any) {
      console.error('Failed to run evaluators:', error)
      showToast(`Failed to run evaluators: ${error?.response?.data?.detail || error?.message || 'Unknown error'}`, 'error')
      setRunningEvaluatorIds(new Set())
    }
  }

  return (
    <>
      <ToastContainer />
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Evaluator</h1>
            <p className="mt-2 text-sm text-gray-600">
              Manage evaluator configurations for testing agents with personas and scenarios
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Button
              variant="success"
              onClick={handleRunSelected}
              disabled={selectedEvaluatorIds.size === 0 || runningEvaluatorIds.size > 0}
              leftIcon={<Play className="w-5 h-5" />}
              className="!px-6 !py-3 !text-base font-semibold shadow-lg hover:shadow-xl transition-shadow"
            >
              Run {selectedEvaluatorIds.size > 0 && `(${selectedEvaluatorIds.size})`}
            </Button>
            {selectedEvaluatorIds.size > 0 && (
              <Button
                variant="danger"
                onClick={handleDeleteSelected}
                leftIcon={<Trash2 className="w-4 h-4" />}
              >
                Delete Selected ({selectedEvaluatorIds.size})
              </Button>
            )}
            <Button
              variant="primary"
              onClick={() => {
                setModalAgentId(selectedAgent?.id || '')
                setShowCreateModal(true)
              }}
              leftIcon={<Plus className="w-4 h-4" />}
            >
              Create Evaluator
            </Button>
          </div>
        </div>

        {/* Evaluators List - Table Format */}
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900">Evaluators</h2>
            {evaluators.length > 0 && selectedEvaluatorIds.size > 0 && (
              <div className="text-sm text-gray-600">
                {selectedEvaluatorIds.size} selected
              </div>
            )}
          </div>
          {loadingEvaluators ? (
            <div className="p-6 text-center text-gray-500">Loading...</div>
          ) : evaluators.length === 0 ? (
            <div className="p-12 text-center">
              <p className="text-gray-500 mb-4">No evaluators yet. Create your first evaluator to get started.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-10">
                      <button
                        type="button"
                        onClick={toggleSelectAllEvaluators}
                        className="flex-shrink-0"
                        aria-label="Select all evaluators"
                      >
                        {evaluators.length > 0 && evaluators
                          .filter((evaluator: Evaluator) => !runningEvaluatorIds.has(evaluator.id))
                          .every((evaluator: Evaluator) => selectedEvaluatorIds.has(evaluator.id)) ? (
                          <CheckSquare className="w-5 h-5 text-primary-600" />
                        ) : (
                          <Square className="w-5 h-5 text-gray-400" />
                        )}
                      </button>
                    </th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      ID
                    </th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Name
                    </th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Agent
                    </th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Persona
                    </th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider min-w-[300px]">
                      Scenario
                    </th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Tags
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {evaluators.map((evaluator: Evaluator) => {
                    const isCustom = !!evaluator.custom_prompt
                    const persona = !isCustom ? personas.find((p: any) => p.id === evaluator.persona_id) : null
                    const scenario = !isCustom ? scenarios.find((s: any) => s.id === evaluator.scenario_id) : null
                    const isRunning = runningEvaluatorIds.has(evaluator.id)
                    const isSelected = selectedEvaluatorIds.has(evaluator.id)

                    return (
                      <tr
                        key={evaluator.id}
                        className={`hover:bg-gray-50 transition-colors ${isSelected ? 'bg-blue-50' : ''}`}
                      >
                        {/* Checkbox */}
                        <td className="px-4 py-4 whitespace-nowrap">
                          <button
                            type="button"
                            onClick={() => toggleEvaluatorSelection(evaluator.id)}
                            className="flex-shrink-0"
                            disabled={isRunning}
                          >
                            {isSelected ? (
                              <CheckSquare className="w-5 h-5 text-primary-600" />
                            ) : (
                              <Square className="w-5 h-5 text-gray-400" />
                            )}
                          </button>
                        </td>

                        {/* Evaluator ID */}
                        <td className="px-4 py-4 whitespace-nowrap">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => navigate(`/evaluate-test-agents/${evaluator.id}`)}
                              className="font-mono font-semibold text-primary-600 hover:text-primary-800 hover:underline cursor-pointer"
                            >
                              {evaluator.evaluator_id}
                            </button>
                            {isCustom && (
                              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800">
                                Custom
                              </span>
                            )}
                            {isRunning && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">
                                Running...
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Evaluator Name */}
                        <td className="px-4 py-4">
                          {evaluator.name ? (
                            <span className="text-sm text-gray-900">{evaluator.name}</span>
                          ) : (
                            <span className="text-xs text-gray-400">—</span>
                          )}
                        </td>

                        {/* Agent */}
                        <td className="px-4 py-4 whitespace-nowrap">
                          {evaluator.agent_id ? (
                            <span className="text-sm text-gray-900">
                              {agents.find((a: any) => a.id === evaluator.agent_id)?.name || 'Unknown'}
                            </span>
                          ) : (
                            <span className="text-xs text-gray-400">—</span>
                          )}
                        </td>

                        {/* Persona */}
                        <td className="px-4 py-4 whitespace-nowrap">
                          {isCustom ? (
                            <span className="text-xs text-gray-400 italic">Custom prompt</span>
                          ) : (
                            <div className="flex flex-col">
                              <span className="text-sm font-medium text-gray-900">
                                {persona?.name || 'Unknown'}
                              </span>
                              {persona && (
                                <span className="text-xs text-gray-500">
                                  {persona.language} • {persona.accent} • {persona.gender}
                                </span>
                              )}
                            </div>
                          )}
                        </td>

                        {/* Scenario - Plain Text */}
                        <td className="px-4 py-4">
                          {isCustom ? (
                            <div className="max-w-md">
                              <p className="text-xs text-gray-500 line-clamp-2">
                                {evaluator.custom_prompt}
                              </p>
                            </div>
                          ) : (
                            <div className="max-w-md">
                              <span className="text-sm font-medium text-gray-900">
                                {scenario?.name || 'Unknown Scenario'}
                              </span>
                              {scenario?.description && (
                                <p className="text-xs text-gray-500 mt-1 line-clamp-2">
                                  {scenario.description}
                                </p>
                              )}
                            </div>
                          )}
                        </td>

                        {/* Tags */}
                        <td className="px-4 py-4">
                          <div className="flex flex-wrap gap-1">
                            {evaluator.tags && evaluator.tags.length > 0 ? (
                              <>
                                {evaluator.tags.slice(0, 2).map((tag, idx) => (
                                  <span
                                    key={idx}
                                    className="px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded"
                                  >
                                    {tag}
                                  </span>
                                ))}
                                {evaluator.tags.length > 2 && (
                                  <span className="px-2 py-0.5 text-xs text-gray-500">
                                    +{evaluator.tags.length - 2}
                                  </span>
                                )}
                              </>
                            ) : (
                              <span className="text-xs text-gray-400">—</span>
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

        {/* Create Evaluator Modal */}
        {showCreateModal && (
          <div className="fixed inset-0 z-50 overflow-y-auto">
            <div className="flex min-h-screen items-center justify-center p-4">
              <div
                className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
                onClick={() => setShowCreateModal(false)}
              />
              <div className="relative bg-white rounded-lg shadow-xl max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-2xl font-bold text-gray-900">Create Evaluator</h2>
                  <button
                    onClick={() => setShowCreateModal(false)}
                    className="text-gray-400 hover:text-gray-500"
                  >
                    <X className="h-6 w-6" />
                  </button>
                </div>

                {/* Mode Tabs */}
                <div className="flex border-b border-gray-200 mb-4">
                  <button
                    onClick={() => setCreateMode('standard')}
                    className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${createMode === 'standard'
                      ? 'border-primary-600 text-primary-700'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                      }`}
                  >
                    Standard
                  </button>
                  <button
                    onClick={() => setCreateMode('custom')}
                    className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${createMode === 'custom'
                      ? 'border-primary-600 text-primary-700'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                      }`}
                  >
                    Custom Prompt
                  </button>
                </div>

                <div className="space-y-4">
                  {createMode === 'custom' ? (
                    <>
                      <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
                        <p className="text-xs text-amber-800">
                          Use this mode to evaluate recordings from third-party voice agents. Paste the agent's instructions/prompt below so the evaluator knows what the agent was supposed to do.
                        </p>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Evaluator Name *
                        </label>
                        <input
                          type="text"
                          value={customName}
                          onChange={(e) => setCustomName(e.target.value)}
                          placeholder="e.g. Customer Support Bot v2"
                          className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                        />
                      </div>
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="block text-sm font-medium text-gray-700">
                            Agent Prompt / Instructions *
                          </label>
                          <button
                            type="button"
                            disabled={!customPrompt.trim() || isFormattingPrompt}
                            onClick={() => handleFormatPrompt()}
                            className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md bg-violet-50 text-violet-700 border border-violet-200 hover:bg-violet-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                          >
                            <Sparkles className={`h-3.5 w-3.5 ${isFormattingPrompt ? 'animate-spin' : ''}`} />
                            {isFormattingPrompt ? 'Formatting...' : 'Format with AI'}
                          </button>
                        </div>
                        <textarea
                          value={customPrompt}
                          onChange={(e) => setCustomPrompt(e.target.value)}
                          rows={8}
                          placeholder={"Paste the full system prompt or detailed description of what the agent is supposed to do.\n\nExample:\nYou are a customer support agent for Acme Corp. Your goal is to help customers with billing inquiries, process refunds, and resolve account issues. You should be polite, efficient, and always verify the customer's identity before making changes..."}
                          className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500 text-sm"
                        />
                        <p className="mt-1 text-xs text-gray-500">
                          The more detailed the prompt, the better the evaluation will be. Use "Format with AI" to structure your prompt into clean markdown.
                        </p>
                      </div>

                      {/* Evaluation LLM Model */}
                      <div className="space-y-3 p-4 bg-purple-50 rounded-lg border border-purple-200">
                        <div className="flex items-center gap-2">
                          <Brain className="h-4 w-4 text-purple-600" />
                          <h4 className="text-sm font-semibold text-gray-900">Evaluation Model</h4>
                        </div>
                        <p className="text-xs text-gray-500">
                          Select which LLM to use for evaluating transcripts against your metrics.
                        </p>
                        {llmProviders.length === 0 ? (
                          <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
                            No AI providers with LLM models configured. Add one in Integrations to select a model. Default (gpt-4o) will be used.
                          </div>
                        ) : (
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            <div>
                              <label className="block text-xs font-medium text-gray-700 mb-1">Provider</label>
                              <div className="relative" ref={llmDropdownRef}>
                                <button
                                  type="button"
                                  onClick={() => setShowLlmDropdown(!showLlmDropdown)}
                                  className="w-full px-3 py-2 border border-gray-300 rounded-md bg-white text-left flex items-center justify-between text-sm"
                                >
                                  <div className="flex items-center gap-2">
                                    {selectedLlmProvider && getProviderLogo(selectedLlmProvider) ? (
                                      <img src={getProviderLogo(selectedLlmProvider)!} alt="" className="w-5 h-5 object-contain rounded" />
                                    ) : (
                                      <Brain className="h-4 w-4 text-gray-400" />
                                    )}
                                    <span className={selectedLlmProvider ? 'text-gray-900' : 'text-gray-400'}>
                                      {selectedLlmProvider ? getProviderLabel(selectedLlmProvider) : 'Select provider'}
                                    </span>
                                  </div>
                                  <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${showLlmDropdown ? 'rotate-180' : ''}`} />
                                </button>
                                {showLlmDropdown && (
                                  <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-md shadow-lg max-h-48 overflow-auto">
                                    {llmProviders.map((provider) => (
                                      <button
                                        key={provider}
                                        type="button"
                                        onClick={() => {
                                          setSelectedLlmProvider(provider)
                                          const models = getModelOptions(provider).llm
                                          setSelectedLlmModel(models.length > 0 ? models[0] : '')
                                          setShowLlmDropdown(false)
                                        }}
                                        className="w-full px-3 py-2 text-left hover:bg-gray-50 flex items-center gap-2 text-sm"
                                      >
                                        {getProviderLogo(provider) ? (
                                          <img src={getProviderLogo(provider)!} alt="" className="w-5 h-5 object-contain rounded" />
                                        ) : (
                                          <Brain className="h-4 w-4 text-purple-600" />
                                        )}
                                        <span>{getProviderLabel(provider)}</span>
                                      </button>
                                    ))}
                                  </div>
                                )}
                              </div>
                            </div>
                            <div>
                              <label className="block text-xs font-medium text-gray-700 mb-1">Model</label>
                              <select
                                value={selectedLlmModel}
                                onChange={(e) => setSelectedLlmModel(e.target.value)}
                                disabled={!selectedLlmProvider}
                                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500 disabled:bg-gray-50 disabled:text-gray-400"
                              >
                                {selectedLlmProvider ? (
                                  getModelOptions(selectedLlmProvider).llm.map((model) => (
                                    <option key={model} value={model}>{model}</option>
                                  ))
                                ) : (
                                  <option value="">Select provider first</option>
                                )}
                              </select>
                            </div>
                          </div>
                        )}
                      </div>
                    </>
                  ) : (
                    <>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Agent *
                        </label>
                        <select
                          value={modalAgentId}
                          onChange={(e) => setModalAgentId(e.target.value)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                        >
                          <option value="">Select an agent</option>
                          {agents.map((agent: any) => (
                            <option key={agent.id} value={agent.id}>
                              {agent.name}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Evaluator Name
                        </label>
                        <input
                          type="text"
                          value={standardName}
                          onChange={(e) => setStandardName(e.target.value)}
                          placeholder="Optional: e.g. Billing Resolution - English Personas"
                          className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          Scenario *
                        </label>
                        <select
                          value={selectedScenario}
                          onChange={(e) => setSelectedScenario(e.target.value)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                        >
                          <option value="">Select a scenario</option>
                          {filteredScenarios.map((scenario: any) => (
                            <option key={scenario.id} value={scenario.id}>
                              {scenario.name}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          Personas * ({selectedPersonas.length} selected)
                        </label>
                        <div className="border border-gray-300 rounded-md max-h-48 overflow-y-auto">
                          {filteredPersonas.length === 0 ? (
                            <div className="p-4 text-center text-gray-500">No personas available</div>
                          ) : (
                            <div className="divide-y divide-gray-200">
                              {filteredPersonas.map((persona: any) => (
                                <label
                                  key={persona.id}
                                  className="flex items-center p-3 hover:bg-gray-50 cursor-pointer"
                                >
                                  <input
                                    type="checkbox"
                                    checked={selectedPersonas.includes(persona.id)}
                                    onChange={() => togglePersona(persona.id)}
                                    className="mr-3 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                                  />
                                  <div>
                                    <div className="text-sm font-medium text-gray-900">{persona.name}</div>
                                    <div className="text-xs text-gray-500">
                                      {persona.language} • {persona.accent} • {persona.gender}
                                    </div>
                                  </div>
                                </label>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </>
                  )}

                  {/* Tags (shared between both modes) */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Tags
                    </label>
                    <div className="flex flex-wrap gap-2 mb-2">
                      {selectedTags.map((tag, idx) => (
                        <span
                          key={idx}
                          className="inline-flex items-center px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded"
                        >
                          {tag}
                          <button
                            onClick={() => removeTag(tag)}
                            className="ml-1 text-blue-600 hover:text-blue-800"
                          >
                            <X className="w-3 h-3" />
                          </button>
                        </span>
                      ))}
                    </div>
                    <div className="flex space-x-2">
                      <input
                        type="text"
                        value={tagInput}
                        onChange={(e) => setTagInput(e.target.value)}
                        onKeyPress={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            addTag(selectedTags, setSelectedTags, tagInput, setTagInput)
                          }
                        }}
                        placeholder="Add tag and press Enter"
                        className="flex-1 px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                      />
                      <Button onClick={() => addTag(selectedTags, setSelectedTags, tagInput, setTagInput)}>Add</Button>
                    </div>
                  </div>

                  <div className="flex justify-end space-x-3 pt-4">
                    <Button variant="ghost" onClick={() => setShowCreateModal(false)}>
                      Cancel
                    </Button>
                    <Button
                      variant="primary"
                      onClick={handleCreate}
                      isLoading={createMode === 'custom' ? createCustomMutation.isPending : createBulkMutation.isPending}
                    >
                      {createMode === 'custom' ? 'Create Custom Evaluator' : 'Create Evaluators'}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Running Status Indicator */}
        {runningEvaluatorIds.size > 0 && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 bg-blue-500 rounded-full animate-pulse"></div>
                <span className="text-sm font-medium text-blue-800">
                  Running {runningEvaluatorIds.size} evaluator(s) in the background. Results will appear in the Results section.
                </span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  // Optionally clear running IDs after a delay or keep them until results appear
                  queryClient.invalidateQueries({ queryKey: ['evaluator-results'] })
                }}
              >
                Refresh Results
              </Button>
            </div>
          </div>
        )}

        {/* Run Count Modal */}
        {showRunModal && (
          <div className="fixed inset-0 z-50 overflow-y-auto">
            <div className="flex min-h-screen items-center justify-center p-4">
              <div
                className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
                onClick={() => setShowRunModal(false)}
              />
              <div className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold text-gray-900">Run Evaluators</h2>
                  <button
                    onClick={() => setShowRunModal(false)}
                    className="text-gray-400 hover:text-gray-500"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>

                <div className="space-y-4">
                  <div className="bg-gray-50 rounded-lg p-4">
                    <p className="text-sm text-gray-600">
                      <span className="font-medium text-gray-900">{selectedEvaluatorIds.size}</span> evaluator{selectedEvaluatorIds.size > 1 ? 's' : ''} selected
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      How many times to run each evaluator?
                    </label>
                    <div className="flex items-center space-x-3">
                      <button
                        type="button"
                        onClick={() => setRunCount(Math.max(1, runCount - 1))}
                        className="w-10 h-10 rounded-lg border border-gray-300 flex items-center justify-center text-gray-600 hover:bg-gray-50 transition-colors"
                      >
                        -
                      </button>
                      <input
                        type="number"
                        min="1"
                        max="50"
                        value={runCount}
                        onChange={(e) => {
                          const val = parseInt(e.target.value)
                          if (!isNaN(val) && val >= 1 && val <= 50) {
                            setRunCount(val)
                          }
                        }}
                        className="w-20 text-center px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500 text-lg font-semibold"
                      />
                      <button
                        type="button"
                        onClick={() => setRunCount(Math.min(50, runCount + 1))}
                        className="w-10 h-10 rounded-lg border border-gray-300 flex items-center justify-center text-gray-600 hover:bg-gray-50 transition-colors"
                      >
                        +
                      </button>
                    </div>
                    <p className="text-xs text-gray-500 mt-2">Maximum 50 runs per evaluator</p>
                  </div>

                  <div className="bg-blue-50 border border-blue-100 rounded-lg p-4">
                    <p className="text-sm text-blue-800">
                      <span className="font-semibold">{selectedEvaluatorIds.size * runCount}</span> total evaluation{selectedEvaluatorIds.size * runCount > 1 ? 's' : ''} will be queued and run in parallel.
                    </p>
                  </div>

                  <div className="flex justify-end space-x-3 pt-4 border-t border-gray-200">
                    <Button variant="ghost" onClick={() => setShowRunModal(false)}>
                      Cancel
                    </Button>
                    <Button
                      variant="success"
                      onClick={executeRuns}
                      leftIcon={<Play className="w-4 h-4" />}
                    >
                      Run {selectedEvaluatorIds.size * runCount} Evaluation{selectedEvaluatorIds.size * runCount > 1 ? 's' : ''}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
        {/* Delete Selected Evaluators Confirmation Modal */}
        {showDeleteSelectedModal && (
          <div className="fixed inset-0 z-50 overflow-y-auto">
            <div className="flex min-h-screen items-center justify-center p-4">
              <div
                className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
                onClick={() => {
                  setShowDeleteSelectedModal(false)
                }}
              />
              <div className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-semibold text-gray-900">Delete Selected Evaluators</h3>
                  <button
                    onClick={() => {
                      setShowDeleteSelectedModal(false)
                    }}
                    className="text-gray-400 hover:text-gray-600"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>
                <div className="flex items-start gap-4 mb-6">
                  <div className="flex-shrink-0">
                    <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
                      <Trash2 className="h-6 w-6 text-red-600" />
                    </div>
                  </div>
                  <div className="flex-1">
                    <p className="text-sm text-gray-700 mb-2">
                      Are you sure you want to delete <span className="font-semibold text-gray-900">{selectedEvaluatorIds.size}</span> selected evaluator{selectedEvaluatorIds.size > 1 ? 's' : ''}?
                    </p>
                    <p className="text-xs text-gray-500">
                      This action cannot be undone. Evaluators with dependent results may fail to delete.
                    </p>
                  </div>
                </div>

                <div className="flex gap-3">
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setShowDeleteSelectedModal(false)
                    }}
                    className="flex-1"
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="danger"
                    onClick={executeDeleteSelected}
                    isLoading={isDeletingSelected}
                    leftIcon={!isDeletingSelected ? <Trash2 className="h-4 w-4" /> : undefined}
                    className="flex-1"
                  >
                    Delete Selected
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  )
}

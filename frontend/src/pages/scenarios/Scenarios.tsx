import { useState, useMemo, useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { FileText, Tag, Plus, Sparkles, UserPlus, Trash2, X, Loader, Phone, Edit, Brain, ChevronDown, AlertCircle } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'
import { AIProvider, ModelProvider } from '../../types/api'
import { getProviderLabel, getProviderLogo } from '../../config/providers'

interface Scenario {
  id: string
  name: string
  agent_id?: string | null
  description: string | null
  required_info: Record<string, string>
  created_at: string
  updated_at: string
  created_by?: string | null
}

interface AgentOption {
  id: string
  name: string
  description?: string | null
  language?: string
  call_type?: string
}

interface GeneratedScenarioDraft {
  id: string
  name: string
  description: string
}

type CreateMode = 'agent_prompt' | 'call' | 'custom' | null

export default function Scenarios() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
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
  const [showProviderDropdown, setShowProviderDropdown] = useState(false)
  const providerDropdownRef = useRef<HTMLDivElement>(null)
  const [selectedAgentIdForGeneration, setSelectedAgentIdForGeneration] = useState('')
  const [scenarioCount, setScenarioCount] = useState(3)
  const [additionalAgentPromptContext, setAdditionalAgentPromptContext] = useState('')
  const [generatedScenarioDrafts, setGeneratedScenarioDrafts] = useState<GeneratedScenarioDraft[]>([])
  const [isGeneratingFromAgentPrompt, setIsGeneratingFromAgentPrompt] = useState(false)
  const [savingDraftIds, setSavingDraftIds] = useState<Set<string>>(new Set())
  const [editGeneratePrompt, setEditGeneratePrompt] = useState('')
  const [isGeneratingEditDescription, setIsGeneratingEditDescription] = useState(false)

  // For Generate from Call
  const [callData, setCallData] = useState('')

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

  // Get LLM models for the selected provider
  const llmModels = useMemo(() => {
    return modelOptions?.llm || []
  }, [modelOptions])

  const userScenarios = useMemo(() => scenarios as Scenario[], [scenarios])
  const availableAgents = useMemo(() => agents as AgentOption[], [agents])
  const agentNameById = useMemo(() => {
    const map = new Map<string, string>()
    availableAgents.forEach((agent) => map.set(agent.id, agent.name))
    return map
  }, [availableAgents])

  // Reset model when provider changes
  useEffect(() => {
    if (selectedAIProvider && llmModels.length > 0) {
      setSelectedModel(llmModels[0])
    } else {
      setSelectedModel('')
    }
  }, [selectedAIProvider, llmModels])

  // Handle click outside provider dropdown
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (providerDropdownRef.current && !providerDropdownRef.current.contains(event.target as Node)) {
        setShowProviderDropdown(false)
      }
    }

    if (showProviderDropdown) {
      document.addEventListener('mousedown', handleClickOutside)
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [showProviderDropdown])

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

  const parseScenarioDraftsFromResponse = (text: string): GeneratedScenarioDraft[] => {
    try {
      const direct = JSON.parse(text)
      if (Array.isArray(direct)) {
        return direct
          .filter((item: any) => item?.name && item?.description)
          .map((item: any, index: number) => ({
            id: `draft-${Date.now()}-${index}`,
            name: String(item.name).trim(),
            description: String(item.description).trim(),
          }))
      }
    } catch {
      // fall through to bracket extraction
    }

    const start = text.indexOf('[')
    const end = text.lastIndexOf(']')
    if (start !== -1 && end !== -1 && end > start) {
      try {
        const sliced = JSON.parse(text.slice(start, end + 1))
        if (Array.isArray(sliced)) {
          return sliced
            .filter((item: any) => item?.name && item?.description)
            .map((item: any, index: number) => ({
              id: `draft-${Date.now()}-${index}`,
              name: String(item.name).trim(),
              description: String(item.description).trim(),
            }))
        }
      } catch {
        return []
      }
    }

    return []
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

    const agentPrompt = selectedAgent.description?.trim()
    if (!agentPrompt) {
      showToast('Selected agent has no system prompt/description to generate from', 'error')
      return
    }

    setIsGeneratingFromAgentPrompt(true)
    try {
      const messages = [
        {
          role: 'system',
          content:
            'You generate high-quality test scenarios for voice AI agents. Return ONLY valid JSON array with objects: { "name": string, "description": string }.',
        },
        {
          role: 'user',
          content: [
            `Generate ${scenarioCount} diverse test scenarios from this agent system prompt.`,
            `Agent Name: ${selectedAgent.name}`,
            selectedAgent.language ? `Language: ${selectedAgent.language}` : '',
            selectedAgent.call_type ? `Call Type: ${selectedAgent.call_type}` : '',
            `System Prompt:\n${agentPrompt}`,
            additionalAgentPromptContext.trim()
              ? `Additional Generation Context:\n${additionalAgentPromptContext.trim()}`
              : '',
            'Requirements:',
            '- Each scenario should test a different user intent or edge case.',
            '- Keep name concise.',
            '- Description should be specific and test-oriented.',
            '- Return only JSON array, no markdown, no explanation.',
          ]
            .filter(Boolean)
            .join('\n'),
        },
      ]

      const response = await apiClient.chatCompletion({
        messages: messages as Array<{ role: string; content: string }>,
        provider: selectedAIProvider,
        model: selectedModel,
        temperature: 0.7,
      })

      const drafts = parseScenarioDraftsFromResponse(response.text)
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
        required_info: {},
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
    setShowProviderDropdown(false)
    resetForm()
  }

  const handleProviderSelect = (provider: ModelProvider) => {
    setSelectedAIProvider(provider)
    setShowProviderDropdown(false)
    setSelectedModel('') // Reset model selection when provider changes
  }

  const handleGenerateFromCall = () => {
    if (!callData.trim()) {
      showToast('Please enter call data', 'error')
      return
    }
    generateFromCallMutation.mutate(callData)
  }

  const handleEdit = (scenario: Scenario) => {
    setSelectedScenario(scenario)
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

    setIsGeneratingEditDescription(true)
    try {
      const response = await apiClient.chatCompletion({
        messages: [
          {
            role: 'system',
            content: 'You write concise, practical scenario descriptions for QA test scenarios.',
          },
          {
            role: 'user',
            content: [
              `Scenario Name: ${formData.name || selectedScenario.name}`,
              `Current Description: ${formData.description || selectedScenario.description || 'None'}`,
              `Request: ${editGeneratePrompt.trim()}`,
              'Write only the updated scenario description text.',
            ].join('\n'),
          },
        ],
        provider: selectedAIProvider,
        model: selectedModel,
        temperature: 0.7,
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Test Scenarios</h1>
          <p className="text-gray-600 mt-1">Create and manage conversation scenarios for testing</p>
        </div>
        <Button
          variant="primary"
          onClick={() => setShowMainModal(true)}
          leftIcon={<Plus className="h-5 w-5" />}
        >
          Create Scenario
        </Button>
      </div>

      {/* User-Created Scenarios Section */}
      {userScenarios.length > 0 && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <div className="flex items-center gap-3">
              <UserPlus className="h-5 w-5 text-green-600" />
              <h2 className="text-lg font-semibold text-gray-900">Your Scenarios</h2>
              <span className="px-2 py-1 text-xs font-medium text-green-700 bg-green-100 rounded-full">
                {userScenarios.length}
              </span>
            </div>
            <p className="text-sm text-gray-600 mt-1">Scenarios you've created or generated</p>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Name
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Linked Agent
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Description
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {userScenarios.map((scenario) => (
                  <tr key={scenario.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4 text-gray-400" />
                        <span className="text-sm font-medium text-gray-900">{scenario.name}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {scenario.agent_id ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700 border border-blue-100">
                          {agentNameById.get(scenario.agent_id) || 'Unlinked'}
                        </span>
                      ) : (
                        <span className="text-xs text-gray-400">Unlinked</span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-sm text-gray-500 line-clamp-2">
                        {scenario.description || 'No description'}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleEdit(scenario)}
                          leftIcon={<Edit className="h-4 w-4" />}
                          title="Edit scenario"
                          className="text-blue-600 hover:text-blue-700 hover:bg-blue-50"
                        >
                          Edit
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDelete(scenario)}
                          leftIcon={<Trash2 className="h-4 w-4" />}
                          title="Delete scenario"
                          className="text-red-600 hover:text-red-700 hover:bg-red-50"
                        >
                          Delete
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {scenarios.length === 0 && (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <FileText className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No scenarios yet</h3>
          <p className="text-gray-500 mb-4">Create your first scenario to get started</p>
          <Button
            variant="primary"
            onClick={() => setShowMainModal(true)}
            leftIcon={<Plus className="h-5 w-5" />}
          >
            Create Scenario
          </Button>
        </div>
      )}

      {/* Main Create Scenario Modal */}
      {showMainModal && renderModal(
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[9999]">
          <div className="bg-white rounded-lg shadow-xl w-full mx-4 max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
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
                <div className="mb-5 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3">
                  <p className="text-sm font-medium text-blue-900">Choose how you want to create this scenario</p>
                  <p className="mt-1 text-xs text-blue-700">
                    Fastest option: <span className="font-medium">Generate from Agent Prompt</span>. Most control:
                    <span className="font-medium"> Create Custom Prompt</span>.
                  </p>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {/* Generate from Agent Prompt */}
                  <button
                    onClick={() => setCreateMode('agent_prompt')}
                    className="group relative p-5 bg-gradient-to-br from-blue-50 to-indigo-50 border-2 border-blue-200 rounded-xl hover:border-blue-400 hover:shadow-lg transition-all text-left focus:outline-none focus:ring-2 focus:ring-blue-400"
                  >
                    <div className="flex items-start gap-4">
                      <div className="flex-shrink-0">
                        <div className="w-12 h-12 bg-blue-500 rounded-lg flex items-center justify-center group-hover:bg-blue-600 transition-colors">
                          <Sparkles className="h-6 w-6 text-white" />
                        </div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="mb-2 flex items-center gap-2">
                          <h3 className="text-base font-semibold text-gray-900">Generate from Agent Prompt</h3>
                          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-medium text-blue-700">Recommended</span>
                        </div>
                        <p className="text-sm text-gray-600 leading-relaxed">
                          Select an existing agent and generate multiple scenario drafts from its system prompt.
                        </p>
                        <p className="mt-2 text-xs text-blue-700">Best for: creating many scenarios quickly</p>
                      </div>
                    </div>
                  </button>

                  {/* Generate from Call */}
                  <button
                    onClick={() => setCreateMode('call')}
                    className="group relative p-5 bg-gradient-to-br from-green-50 to-emerald-50 border-2 border-green-200 rounded-xl hover:border-green-400 hover:shadow-lg transition-all text-left focus:outline-none focus:ring-2 focus:ring-green-400"
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

                  {/* Create Custom Prompt */}
                  <button
                    onClick={() => setCreateMode('custom')}
                    className="group relative p-5 bg-gradient-to-br from-orange-50 to-amber-50 border-2 border-orange-200 rounded-xl hover:border-orange-400 hover:shadow-lg transition-all text-left focus:outline-none focus:ring-2 focus:ring-orange-400"
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
                        <p className="mt-2 text-xs text-orange-700">Best for: full control over scenario details</p>
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
                        {availableAgents.map((agent) => (
                          <option key={agent.id} value={agent.id}>
                            {agent.name}
                          </option>
                        ))}
                      </select>
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
                      <select
                        value={selectedModel}
                        onChange={(e) => setSelectedModel(e.target.value)}
                        disabled={!selectedAIProvider || llmModels.length === 0}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent disabled:bg-gray-100 disabled:text-gray-500"
                      >
                        <option value="">
                          {!selectedAIProvider ? 'Select provider first' : llmModels.length === 0 ? 'No models found' : 'Select model'}
                        </option>
                        {llmModels.map((model) => (
                          <option key={model} value={model}>
                            {model}
                          </option>
                        ))}
                      </select>
                    </div>
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
                      placeholder="Add context to combine with agent system prompt (e.g., focus on edge cases, payment failures, escalation paths, compliance checks)."
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
                      <h5 className="text-sm font-semibold text-gray-900">
                        Generated Scenarios ({generatedScenarioDrafts.length})
                      </h5>
                      {generatedScenarioDrafts.map((draft) => (
                        <div key={draft.id} className="border border-gray-200 rounded-lg p-4 bg-gray-50">
                          <div className="space-y-3">
                            <div>
                              <label className="block text-xs font-medium text-gray-700 mb-1">Name</label>
                              <input
                                type="text"
                                value={draft.name}
                                onChange={(e) => updateGeneratedDraft(draft.id, { name: e.target.value })}
                                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
                              />
                            </div>
                            <div>
                              <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
                              <textarea
                                value={draft.description}
                                onChange={(e) => updateGeneratedDraft(draft.id, { description: e.target.value })}
                                rows={4}
                                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
                              />
                            </div>
                            <div className="flex items-center justify-end gap-2">
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
                      {availableAgents.map((agent) => (
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
                    <textarea
                      value={formData.description}
                      onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                      rows={4}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      placeholder="Describe what this scenario tests..."
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
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[9999]" onClick={() => setShowDetailsModal(false)}>
          <div className="bg-white rounded-lg shadow-xl max-w-lg w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Scenario Details</h3>
              <button
                onClick={() => {
                  setShowDetailsModal(false)
                  setSelectedScenario(null)
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6 space-y-6">
              <div>
                <h4 className="text-xl font-semibold text-gray-900 mb-2">{selectedScenario.name}</h4>
                <div className="mb-2">
                  {selectedScenario.agent_id ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700 border border-blue-100">
                      Linked Agent: {agentNameById.get(selectedScenario.agent_id) || 'Unlinked'}
                    </span>
                  ) : (
                    <span className="text-xs text-gray-500">Linked Agent: Unlinked</span>
                  )}
                </div>
                {selectedScenario.description && (
                  <p className="text-gray-600">{selectedScenario.description}</p>
                )}
              </div>

              {Object.keys(selectedScenario.required_info).length > 0 && (
                <div>
                  <div className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-3">
                    <Tag className="w-4 h-4" />
                    Required Information
                  </div>
                  <div className="space-y-2">
                    {Object.entries(selectedScenario.required_info).map(([key, value]) => (
                      <div key={key} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                        <span className="text-sm font-medium text-gray-900">{key.replace(/_/g, ' ')}</span>
                        <span className="text-sm text-gray-600 font-mono">{value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="pt-4 border-t border-gray-200">
                <Button
                  variant="primary"
                  onClick={() => {
                    setShowDetailsModal(false)
                    // TODO: Implement "Use in Test" functionality
                    showToast('Scenario selected for test', 'success')
                  }}
                  className="w-full"
                >
                  Use in Test
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {showEditModal && selectedScenario && renderModal(
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[9999]">
          <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full mx-4 max-h-[90vh] overflow-hidden flex flex-col">
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
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Linked Agent (Optional)
                  </label>
                  <select
                    value={formData.agent_id}
                    onChange={(e) => setFormData({ ...formData, agent_id: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  >
                    <option value="">No linked agent</option>
                    {availableAgents.map((agent) => (
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
                  <textarea
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    rows={4}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    placeholder="Describe what this scenario tests..."
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
                      <select
                        value={selectedModel}
                        onChange={(e) => setSelectedModel(e.target.value)}
                        disabled={!selectedAIProvider || llmModels.length === 0}
                        className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white disabled:bg-gray-100 disabled:text-gray-500"
                      >
                        <option value="">
                          {!selectedAIProvider ? 'Select provider first' : llmModels.length === 0 ? 'No models found' : 'Select model'}
                        </option>
                        {llmModels.map((model) => (
                          <option key={model} value={model}>
                            {model}
                          </option>
                        ))}
                      </select>
                    </div>
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
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[9999]" onClick={() => {
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
    </div>
  )
}

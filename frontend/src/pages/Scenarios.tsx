import { useState, useMemo, useEffect, useRef } from 'react'
import { FileText, Tag, Plus, Sparkles, UserPlus, Trash2, X, Loader, MessageSquare, Phone, Edit, Brain, ChevronDown } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { apiClient } from '../lib/api'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Button from '../components/Button'
import { useToast } from '../hooks/useToast'
import { AIProvider, ModelProvider } from '../types/api'

const PROVIDER_LABELS: Record<ModelProvider, string> = {
  [ModelProvider.OPENAI]: 'OpenAI',
  [ModelProvider.ANTHROPIC]: 'Anthropic',
  [ModelProvider.GOOGLE]: 'Google',
  [ModelProvider.AZURE]: 'Azure',
  [ModelProvider.AWS]: 'AWS',
  [ModelProvider.DEEPGRAM]: 'Deepgram',
  [ModelProvider.CARTESIA]: 'Cartesia',
  [ModelProvider.ELEVENLABS]: 'ElevenLabs',
  [ModelProvider.CUSTOM]: 'Custom',
}

const PROVIDER_LOGOS: Record<ModelProvider, string | null> = {
  [ModelProvider.OPENAI]: '/openai-logo.png',
  [ModelProvider.ANTHROPIC]: '/anthropic.png',
  [ModelProvider.GOOGLE]: '/geminiai.png',
  [ModelProvider.AZURE]: '/azureai.png',
  [ModelProvider.AWS]: '/AWS_logo.png',
  [ModelProvider.DEEPGRAM]: '/deepgram.png',
  [ModelProvider.CARTESIA]: '/cartesia.jpg',
  [ModelProvider.ELEVENLABS]: '/elevenlabs.jpg',
  [ModelProvider.CUSTOM]: null,
}

interface Scenario {
  id: string
  name: string
  description: string | null
  required_info: Record<string, string>
  created_at: string
  updated_at: string
  created_by?: string | null
}

// Default scenario names (heuristic to identify default scenarios)
// These match the seeded scenarios from the backend
const DEFAULT_SCENARIO_NAMES = [
  'Cancel Subscription',
  'Check Balance',
  'Technical Support',
  'Make Complaint',
  'Product Inquiry',
]

type CreateMode = 'default' | 'prompt' | 'call' | 'custom' | null

export default function Scenarios() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showMainModal, setShowMainModal] = useState(false)
  const [createMode, setCreateMode] = useState<CreateMode>(null)
  const [showDetailsModal, setShowDetailsModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(false)
  const [selectedScenario, setSelectedScenario] = useState<Scenario | null>(null)
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    required_info: {} as Record<string, string>,
  })
  
  // For Generate from Prompt
  const [selectedAIProvider, setSelectedAIProvider] = useState<ModelProvider | null>(null)
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [currentPrompt, setCurrentPrompt] = useState('')
  const [chatHistory, setChatHistory] = useState<Array<{ role: 'user' | 'assistant'; content: string }>>([])
  const [isGenerating, setIsGenerating] = useState(false)
  const [showProviderDropdown, setShowProviderDropdown] = useState(false)
  const providerDropdownRef = useRef<HTMLDivElement>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)
  
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
    enabled: !!selectedAIProvider && createMode === 'prompt',
  })

  // Get LLM models for the selected provider
  const llmModels = useMemo(() => {
    return modelOptions?.llm || []
  }, [modelOptions])

  // Separate scenarios into default and user-created
  const { defaultScenarios, userScenarios } = useMemo(() => {
    const defaults: Scenario[] = []
    const userCreated: Scenario[] = []
    const seenDefaultIds = new Set<string>()

    // First pass: identify original default scenarios (ones without created_by and matching default names)
    // These are the seeded scenarios that should appear in the default section
    const originalDefaults: Scenario[] = []
    for (const scenario of scenarios) {
      const isExactDefaultName = DEFAULT_SCENARIO_NAMES.some(
        (defaultName) => scenario.name.toLowerCase() === defaultName.toLowerCase()
      )
      const isCloned = scenario.name.includes('(Copy)') || scenario.name.includes('(Clone)')
      // Original defaults: match name, not cloned, no created_by, and we haven't seen this ID
      const isOriginalDefault = isExactDefaultName && !isCloned && !scenario.created_by && !seenDefaultIds.has(scenario.id)

      if (isOriginalDefault) {
        originalDefaults.push(scenario)
        seenDefaultIds.add(scenario.id)
      }
    }

    // Second pass: categorize all scenarios
    // Only scenarios that are in the originalDefaults list should be in defaults
    // Everything else (including user-created scenarios with default names) goes to userCreated
    const originalDefaultIds = new Set(originalDefaults.map(s => s.id))
    
    for (const scenario of scenarios) {
      if (originalDefaultIds.has(scenario.id)) {
        defaults.push(scenario)
      } else {
        userCreated.push(scenario)
      }
    }

    return { defaultScenarios: defaults, userScenarios: userCreated }
  }, [scenarios])

  // Reset model when provider changes
  useEffect(() => {
    if (selectedAIProvider && llmModels.length > 0) {
      setSelectedModel(llmModels[0])
    } else {
      setSelectedModel('')
    }
  }, [selectedAIProvider, llmModels])

  // Auto-scroll chat to bottom when new messages are added
  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [chatHistory, isGenerating])

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
    mutationFn: (data: { name: string; description?: string; required_info: Record<string, string> }) =>
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

  const createFromGeneratedResponse = () => {
    if (chatHistory.length === 0) {
      showToast('Please generate a response first', 'error')
      return
    }
    // Get the last assistant response
    const lastResponse = chatHistory.filter(msg => msg.role === 'assistant').pop()
    const firstPrompt = chatHistory.find(msg => msg.role === 'user')?.content || ''
    
    if (!lastResponse) {
      showToast('Please generate a response first', 'error')
      return
    }
    
    // Extract scenario name from first prompt or use a default
    const scenarioName = firstPrompt.length > 0 
      ? firstPrompt.substring(0, 50).replace(/\n/g, ' ').trim()
      : 'Generated Scenario'
    
    // Use the full conversation or just the last response as description
    // Option 1: Use just the last assistant response
    const description = lastResponse.content
    
    // Option 2: Use full conversation (uncomment if preferred)
    // const fullConversation = chatHistory.map(msg => 
    //   `${msg.role === 'user' ? 'User' : 'Assistant'}: ${msg.content}`
    // ).join('\n\n')
    // const description = fullConversation
    
    const scenarioData = {
      name: scenarioName.length > 0 ? scenarioName : 'Generated Scenario',
      description: description,
      required_info: {},
    }
    
    // Pre-fill the form and switch to custom mode for review
    setFormData({
      name: scenarioData.name,
      description: scenarioData.description,
      required_info: scenarioData.required_info,
    })
    setCreateMode('custom')
    setChatHistory([]) // Clear chat history after moving to form
  }

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
    mutationFn: ({ id, data }: { id: string; data: { name: string; description?: string; required_info: Record<string, string> } }) =>
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
    mutationFn: (id: string) => apiClient.deleteScenario(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scenarios'] })
      showToast('Scenario deleted successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to delete scenario: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const resetForm = () => {
    setFormData({
      name: '',
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
      description: formData.description || undefined,
      required_info: formData.required_info || {},
    })
  }

  const handleGenerateFromPrompt = async () => {
    if (!currentPrompt.trim()) {
      showToast('Please enter a prompt', 'error')
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
    
    // Add user message to chat history
    const userMessage = { role: 'user' as const, content: currentPrompt.trim() }
    const updatedHistory = [...chatHistory, userMessage]
    setChatHistory(updatedHistory)
    setCurrentPrompt('')
    
    // Generate the response
    setIsGenerating(true)
    try {
      // Build messages array with chat history
      const messages = updatedHistory.map(msg => ({
        role: msg.role,
        content: msg.content
      }))
      
      const response = await apiClient.chatCompletion({
        messages,
        provider: selectedAIProvider,
        model: selectedModel,
        temperature: 0.7,
      })
      
      // Add assistant response to chat history
      const assistantMessage = { role: 'assistant' as const, content: response.text }
      setChatHistory([...updatedHistory, assistantMessage])
    } catch (error: any) {
      showToast(`Failed to generate response: ${error.response?.data?.detail || error.message}`, 'error')
      // Remove the user message if generation failed
      setChatHistory(chatHistory)
    } finally {
      setIsGenerating(false)
    }
  }


  const handleSelectDefaultScenario = (scenario: Scenario) => {
    // When creating from a default scenario, add "(Copy)" to the name to distinguish it
    // This ensures it appears in "Your Scenarios" instead of "Default Scenarios"
    const isDefaultName = DEFAULT_SCENARIO_NAMES.some(
      (defaultName) => scenario.name.toLowerCase() === defaultName.toLowerCase()
    )
    const nameToUse = isDefaultName && !scenario.name.includes('(Copy)') && !scenario.name.includes('(Clone)')
      ? `${scenario.name} (Copy)`
      : scenario.name
    
    setFormData({
      name: nameToUse,
      description: scenario.description || '',
      required_info: scenario.required_info || {},
    })
    setCreateMode('custom') // Switch to custom mode to show the form
  }


  const handleCloseMainModal = () => {
    setShowMainModal(false)
    setCreateMode(null)
    setCurrentPrompt('')
    setChatHistory([])
    setCallData('')
    setSelectedAIProvider(null)
    setSelectedModel('')
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
        description: formData.description || undefined,
        required_info: formData.required_info,
      },
    })
  }

  const handleCloseEditModal = () => {
    setShowEditModal(false)
    setSelectedScenario(null)
    resetForm()
  }

  const handleDelete = (scenario: Scenario) => {
    setSelectedScenario(scenario)
    setShowDeleteModal(true)
  }

  const confirmDelete = () => {
    if (selectedScenario) {
      deleteMutation.mutate(selectedScenario.id)
      setShowDeleteModal(false)
      setSelectedScenario(null)
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
                    Description
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Required Info
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
                    <td className="px-6 py-4">
                      <span className="text-sm text-gray-500 line-clamp-2">
                        {scenario.description || 'No description'}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-wrap gap-1">
                        {Object.keys(scenario.required_info).slice(0, 2).map((key) => (
                          <span
                            key={key}
                            className="px-2 py-0.5 bg-orange-50 text-orange-700 rounded text-xs border border-orange-100"
                          >
                            {key.replace(/_/g, ' ')}
                          </span>
                        ))}
                        {Object.keys(scenario.required_info).length > 2 && (
                          <span className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">
                            +{Object.keys(scenario.required_info).length - 2}
                          </span>
                        )}
                        {Object.keys(scenario.required_info).length === 0 && (
                          <span className="text-xs text-gray-400">None</span>
                        )}
                      </div>
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
      {showMainModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className={`bg-white rounded-lg shadow-xl w-full mx-4 ${createMode === 'prompt' ? 'max-w-6xl h-[85vh]' : 'max-w-4xl max-h-[90vh]'} overflow-hidden flex flex-col`}>
            {createMode !== 'prompt' && (
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                <h3 className="text-lg font-semibold">Create Scenario</h3>
                <button
                  onClick={handleCloseMainModal}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
            )}

            {!createMode ? (
              // Mode Selection
              <div className="p-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Default Scenario */}
                  <button
                    onClick={() => setCreateMode('default')}
                    className="group relative p-6 bg-gradient-to-br from-blue-50 to-indigo-50 border-2 border-blue-200 rounded-xl hover:border-blue-400 hover:shadow-lg transition-all text-left"
                  >
                    <div className="flex items-start gap-4">
                      <div className="flex-shrink-0">
                        <div className="w-12 h-12 bg-blue-500 rounded-lg flex items-center justify-center group-hover:bg-blue-600 transition-colors">
                          <Sparkles className="h-6 w-6 text-white" />
                        </div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-lg font-semibold text-gray-900 mb-2">Default Scenario</h3>
                        <p className="text-sm text-gray-600 leading-relaxed">
                          Choose from pre-configured scenarios like Check Balance, Technical Support, etc.
                        </p>
                      </div>
                    </div>
                  </button>

                  {/* Generate from Prompt */}
                  <button
                    onClick={() => setCreateMode('prompt')}
                    className="group relative p-6 bg-gradient-to-br from-purple-50 to-pink-50 border-2 border-purple-200 rounded-xl hover:border-purple-400 hover:shadow-lg transition-all text-left"
                  >
                    <div className="flex items-start gap-4">
                      <div className="flex-shrink-0">
                        <div className="w-12 h-12 bg-purple-500 rounded-lg flex items-center justify-center group-hover:bg-purple-600 transition-colors">
                          <MessageSquare className="h-6 w-6 text-white" />
                        </div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-lg font-semibold text-gray-900 mb-2">Generate from Prompt</h3>
                        <p className="text-sm text-gray-600 leading-relaxed">
                          Use AI to automatically generate a scenario from a natural language description.
                        </p>
                      </div>
                    </div>
                  </button>

                  {/* Generate from Call */}
                  <button
                    onClick={() => setCreateMode('call')}
                    className="group relative p-6 bg-gradient-to-br from-green-50 to-emerald-50 border-2 border-green-200 rounded-xl hover:border-green-400 hover:shadow-lg transition-all text-left"
                  >
                    <div className="flex items-start gap-4">
                      <div className="flex-shrink-0">
                        <div className="w-12 h-12 bg-green-500 rounded-lg flex items-center justify-center group-hover:bg-green-600 transition-colors">
                          <Phone className="h-6 w-6 text-white" />
                        </div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-lg font-semibold text-gray-900 mb-2">Generate from Call</h3>
                        <p className="text-sm text-gray-600 leading-relaxed">
                          Extract and create a scenario from existing call transcripts or recordings.
                        </p>
                      </div>
                    </div>
                  </button>

                  {/* Create Custom Prompt */}
                  <button
                    onClick={() => setCreateMode('custom')}
                    className="group relative p-6 bg-gradient-to-br from-orange-50 to-amber-50 border-2 border-orange-200 rounded-xl hover:border-orange-400 hover:shadow-lg transition-all text-left"
                  >
                    <div className="flex items-start gap-4">
                      <div className="flex-shrink-0">
                        <div className="w-12 h-12 bg-orange-500 rounded-lg flex items-center justify-center group-hover:bg-orange-600 transition-colors">
                          <Plus className="h-6 w-6 text-white" />
                        </div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-lg font-semibold text-gray-900 mb-2">Create Custom Prompt</h3>
                        <p className="text-sm text-gray-600 leading-relaxed">
                          Manually create a custom scenario with specific requirements and conversation flow.
                        </p>
                      </div>
                    </div>
                  </button>
                </div>
              </div>
            ) : createMode === 'default' ? (
              // Default Scenario Selection
              <div className="p-6 overflow-y-auto flex-1">
                <button
                  onClick={() => setCreateMode(null)}
                  className="mb-4 text-sm text-gray-600 hover:text-gray-900 flex items-center gap-2"
                >
                  <X className="h-4 w-4" />
                  Back
                </button>
                <h4 className="text-lg font-semibold text-gray-900 mb-4">Select a Default Scenario</h4>
                {defaultScenarios.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">
                    <Sparkles className="h-12 w-12 mx-auto mb-4 text-gray-300" />
                    <p>No default scenarios available. Load demo data first.</p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {defaultScenarios.map((scenario) => (
                      <div
                        key={scenario.id}
                        onClick={() => handleSelectDefaultScenario(scenario)}
                        className="p-4 bg-gradient-to-br from-blue-50 to-indigo-50 border-2 border-blue-200 rounded-xl hover:border-blue-400 hover:shadow-lg transition-all cursor-pointer"
                      >
                        <div className="flex items-center gap-3 mb-2">
                          <FileText className="h-5 w-5 text-blue-600" />
                          <h5 className="font-semibold text-gray-900">{scenario.name}</h5>
                        </div>
                        {scenario.description && (
                          <p className="text-sm text-gray-600 mb-3 line-clamp-2">{scenario.description}</p>
                        )}
                        {Object.keys(scenario.required_info).length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {Object.keys(scenario.required_info).slice(0, 3).map((key) => (
                              <span key={key} className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">
                                {key.replace(/_/g, ' ')}
                              </span>
                            ))}
                            {Object.keys(scenario.required_info).length > 3 && (
                              <span className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">
                                +{Object.keys(scenario.required_info).length - 3}
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : createMode === 'prompt' ? (
              // Generate from Prompt - Chat Interface
              <div className="flex flex-col h-full">
                <div className="px-6 py-4 border-b border-gray-200 flex-shrink-0">
                  <div className="flex items-center justify-between mb-4">
                    <h4 className="text-lg font-semibold text-gray-900">Generate Scenario from Prompt</h4>
                    <button
                      onClick={() => setCreateMode(null)}
                      className="text-gray-400 hover:text-gray-600"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>
                  
                  {/* AI Provider and Model Selection */}
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        AI Provider *
                      </label>
                      <div className="relative" ref={providerDropdownRef}>
                        <button
                          type="button"
                          onClick={() => setShowProviderDropdown(!showProviderDropdown)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white text-left flex items-center justify-between"
                        >
                          <div className="flex items-center gap-2">
                            {selectedAIProvider && PROVIDER_LOGOS[selectedAIProvider] ? (
                              <img
                                src={PROVIDER_LOGOS[selectedAIProvider]!}
                                alt={PROVIDER_LABELS[selectedAIProvider]}
                                className="w-5 h-5 object-contain"
                              />
                            ) : selectedAIProvider ? (
                              <Brain className="h-5 w-5 text-primary-600" />
                            ) : null}
                            <span>
                              {selectedAIProvider
                                ? PROVIDER_LABELS[selectedAIProvider]
                                : 'Select an AI Provider'}
                            </span>
                          </div>
                          <ChevronDown
                            className={`h-4 w-4 text-gray-400 transition-transform ${
                              showProviderDropdown ? 'transform rotate-180' : ''
                            }`}
                          />
                        </button>
                        {showProviderDropdown && (
                          <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-auto">
                            {configuredProviders.map((provider: ModelProvider) => {
                              const providerObj = availableProviders.find(
                                (p: AIProvider) => p.provider === provider
                              )
                              if (!providerObj) return null
                              return (
                                <button
                                  key={providerObj.id}
                                  type="button"
                                  onClick={() => handleProviderSelect(provider)}
                                  className="w-full px-3 py-2 text-left hover:bg-gray-50 flex items-center gap-2 transition-colors"
                                >
                                  {PROVIDER_LOGOS[provider] ? (
                                    <img
                                      src={PROVIDER_LOGOS[provider]!}
                                      alt={PROVIDER_LABELS[provider]}
                                      className="w-5 h-5 object-contain"
                                    />
                                  ) : (
                                    <Brain className="h-5 w-5 text-primary-600" />
                                  )}
                                  <span>{PROVIDER_LABELS[provider]}</span>
                                </button>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Model Selection */}
                    {selectedAIProvider && llmModels.length > 0 && (
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          Model *
                        </label>
                        <select
                          value={selectedModel}
                          onChange={(e) => setSelectedModel(e.target.value)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                        >
                          {llmModels.map((model) => (
                            <option key={model} value={model}>
                              {model}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                  </div>
                </div>

                {/* Chat History Display */}
                <div className="flex-1 overflow-y-auto px-6 py-4 bg-gray-50">
                  {chatHistory.length === 0 ? (
                    <div className="flex items-center justify-center h-full text-gray-500">
                      <div className="text-center">
                        <MessageSquare className="h-12 w-12 mx-auto mb-4 text-gray-300" />
                        <p>Start a conversation to generate a scenario</p>
                        <p className="text-sm mt-2">Select a provider and model, then type your prompt below</p>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {chatHistory.map((message, index) => (
                        <div
                          key={index}
                          className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                        >
                          <div
                            className={`max-w-[80%] rounded-lg px-4 py-3 ${
                              message.role === 'user'
                                ? 'bg-primary-600 text-white'
                                : 'bg-white text-gray-900 border border-gray-200'
                            }`}
                          >
                            <div className="text-sm font-medium mb-2 opacity-70">
                              {message.role === 'user' ? 'You' : 'Assistant'}
                            </div>
                            {message.role === 'assistant' ? (
                              <div className="prose prose-sm max-w-none dark:prose-invert">
                                <ReactMarkdown
                                  components={{
                                    p: ({ children }: { children?: React.ReactNode }) => <p className="mb-2 last:mb-0">{children}</p>,
                                    ul: ({ children }: { children?: React.ReactNode }) => <ul className="mb-2 ml-4 list-disc">{children}</ul>,
                                    ol: ({ children }: { children?: React.ReactNode }) => <ol className="mb-2 ml-4 list-decimal">{children}</ol>,
                                    li: ({ children }: { children?: React.ReactNode }) => <li className="mb-1">{children}</li>,
                                    h1: ({ children }: { children?: React.ReactNode }) => <h1 className="text-lg font-bold mb-2">{children}</h1>,
                                    h2: ({ children }: { children?: React.ReactNode }) => <h2 className="text-base font-bold mb-2">{children}</h2>,
                                    h3: ({ children }: { children?: React.ReactNode }) => <h3 className="text-sm font-bold mb-1">{children}</h3>,
                                    code: ({ children, className }: { children?: React.ReactNode; className?: string }) => {
                                      const isInline = !className
                                      return isInline ? (
                                        <code className="bg-gray-100 px-1 py-0.5 rounded text-sm font-mono">{children}</code>
                                      ) : (
                                        <code className="block bg-gray-100 p-2 rounded text-sm font-mono overflow-x-auto">{children}</code>
                                      )
                                    },
                                    pre: ({ children }: { children?: React.ReactNode }) => <pre className="bg-gray-100 p-2 rounded text-sm font-mono overflow-x-auto mb-2">{children}</pre>,
                                    blockquote: ({ children }: { children?: React.ReactNode }) => <blockquote className="border-l-4 border-gray-300 pl-4 italic my-2">{children}</blockquote>,
                                    strong: ({ children }: { children?: React.ReactNode }) => <strong className="font-semibold">{children}</strong>,
                                    em: ({ children }: { children?: React.ReactNode }) => <em className="italic">{children}</em>,
                                  }}
                                >
                                  {message.content}
                                </ReactMarkdown>
                              </div>
                            ) : (
                              <div className="whitespace-pre-wrap">{message.content}</div>
                            )}
                          </div>
                        </div>
                      ))}
                      {isGenerating && (
                        <div className="flex justify-start">
                          <div className="bg-white text-gray-900 border border-gray-200 rounded-lg px-4 py-3">
                            <div className="flex items-center gap-2">
                              <Loader className="h-4 w-4 animate-spin" />
                              <span className="text-sm">Generating response...</span>
                            </div>
                          </div>
                        </div>
                      )}
                      <div ref={chatEndRef} />
                    </div>
                  )}
                </div>

                {/* Input Area */}
                <div className="px-6 py-4 border-t border-gray-200 flex-shrink-0 bg-white">
                  <div className="flex gap-2">
                    <textarea
                      value={currentPrompt}
                      onChange={(e) => setCurrentPrompt(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault()
                          if (currentPrompt.trim() && !isGenerating) {
                            handleGenerateFromPrompt()
                          }
                        }
                      }}
                      rows={3}
                      className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent resize-none"
                      placeholder="Type your prompt here... (Press Enter to send, Shift+Enter for new line)"
                      disabled={!selectedAIProvider || !selectedModel || isGenerating}
                    />
                    <Button
                      type="button"
                      variant="primary"
                      onClick={handleGenerateFromPrompt}
                      isLoading={isGenerating}
                      disabled={!currentPrompt.trim() || !selectedAIProvider || !selectedModel || llmModels.length === 0 || isGenerating}
                      className="self-end"
                    >
                      Send
                    </Button>
                  </div>
                  
                  {/* Action Buttons */}
                  {chatHistory.length > 0 && (
                    <div className="flex gap-3 mt-4 pt-4 border-t border-gray-200">
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
                        onClick={createFromGeneratedResponse}
                        isLoading={createMutation.isPending}
                        className="flex-1"
                      >
                        Create Scenario
                      </Button>
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
                <h4 className="text-lg font-semibold text-gray-900 mb-4">
                  {formData.name && DEFAULT_SCENARIO_NAMES.some(name => name.toLowerCase() === formData.name.toLowerCase())
                    ? 'Create Scenario from Template'
                    : 'Create Custom Scenario'}
                </h4>
                {formData.name && DEFAULT_SCENARIO_NAMES.some(name => name.toLowerCase() === formData.name.toLowerCase()) && (
                  <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
                    <p className="text-sm text-blue-800">
                      You're creating a scenario based on the "{formData.name}" template. You can modify the details below before creating.
                    </p>
                  </div>
                )}
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
      {showDetailsModal && selectedScenario && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setShowDetailsModal(false)}>
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
      {showEditModal && selectedScenario && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
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
      {showDeleteModal && selectedScenario && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setShowDeleteModal(false)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Delete Scenario</h3>
              <button
                onClick={() => {
                  setShowDeleteModal(false)
                  setSelectedScenario(null)
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6">
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
                  }}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  onClick={confirmDelete}
                  isLoading={deleteMutation.isPending}
                  leftIcon={!deleteMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
                  className="flex-1"
                >
                  Delete
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

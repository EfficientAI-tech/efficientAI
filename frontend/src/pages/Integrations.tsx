import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { useState, useEffect, useRef } from 'react'
import { Plus, Trash2, X, AlertCircle, CheckCircle, Plug, Edit, Brain, Key, ChevronDown } from 'lucide-react'
import { IntegrationCreate, IntegrationPlatform, Integration, AIProvider, AIProviderCreate, ModelProvider } from '../types/api'
import Button from '../components/Button'
import { useToast } from '../hooks/useToast'

const PROVIDER_LABELS: Record<ModelProvider, string> = {
  [ModelProvider.OPENAI]: 'OpenAI',
  [ModelProvider.ANTHROPIC]: 'Anthropic',
  [ModelProvider.GOOGLE]: 'Google',
  [ModelProvider.AZURE]: 'Azure',
  [ModelProvider.AWS]: 'AWS',
  [ModelProvider.CUSTOM]: 'Custom',
}

const PROVIDER_LOGOS: Record<ModelProvider, string | null> = {
  [ModelProvider.OPENAI]: '/openai-logo.png',
  [ModelProvider.ANTHROPIC]: '/anthropic.png',
  [ModelProvider.GOOGLE]: '/geminiai.png',
  [ModelProvider.AZURE]: '/azureai.png',
  [ModelProvider.AWS]: '/AWS_logo.png',
  [ModelProvider.CUSTOM]: null,
}

const PROVIDER_DESCRIPTIONS: Record<ModelProvider, string> = {
  [ModelProvider.OPENAI]: 'GPT models, Whisper, TTS',
  [ModelProvider.ANTHROPIC]: 'Claude models',
  [ModelProvider.GOOGLE]: 'Gemini, Google Speech, Google TTS',
  [ModelProvider.AZURE]: 'Azure OpenAI, Azure Speech Services',
  [ModelProvider.AWS]: 'AWS Bedrock, Transcribe, Polly',
  [ModelProvider.CUSTOM]: 'Custom AI provider',
}

type IntegrationType = 'voice_platform' | 'ai_provider' | null

export default function Integrations() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showModal, setShowModal] = useState(false)
  const [isEditMode, setIsEditMode] = useState(false)
  const [integrationType, setIntegrationType] = useState<IntegrationType>(null)
  const [selectedIntegration, setSelectedIntegration] = useState<Integration | null>(null)
  const [selectedAIProvider, setSelectedAIProvider] = useState<AIProvider | null>(null)
  const [selectedPlatform, setSelectedPlatform] = useState<'retell' | 'vapi' | 'cartesia' | 'elevenlabs' | 'deepgram' | null>(null)
  const [selectedProvider, setSelectedProvider] = useState<ModelProvider | null>(null)
  const [showProviderDropdown, setShowProviderDropdown] = useState(false)
  const [showPlatformDropdown, setShowPlatformDropdown] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [name, setName] = useState('')
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showDeleteAIProviderModal, setShowDeleteAIProviderModal] = useState(false)
  const [integrationToDelete, setIntegrationToDelete] = useState<Integration | null>(null)
  const [aiProviderToDelete, setAIProviderToDelete] = useState<AIProvider | null>(null)
  const providerDropdownRef = useRef<HTMLDivElement>(null)
  const platformDropdownRef = useRef<HTMLDivElement>(null)

  const { data: integrations = [] } = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
  })

  const { data: aiproviders = [] } = useQuery({
    queryKey: ['aiproviders'],
    queryFn: () => apiClient.listAIProviders(),
  })

  // Voice Platform Mutations
  const createIntegrationMutation = useMutation({
    mutationFn: (data: IntegrationCreate) => apiClient.createIntegration(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
      showToast('Integration created successfully!', 'success')
      resetForm()
    },
    onError: (error: any) => {
      showToast(`Failed to create integration: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const updateIntegrationMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<IntegrationCreate> }) =>
      apiClient.updateIntegration(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
      showToast('Integration updated successfully!', 'success')
      resetForm()
    },
    onError: (error: any) => {
      showToast(`Failed to update integration: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const deleteIntegrationMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteIntegration(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
      showToast('Integration deleted successfully!', 'success')
      setShowDeleteModal(false)
      setIntegrationToDelete(null)
    },
    onError: (error: any) => {
      showToast(`Failed to delete integration: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  // AI Provider Mutations
  const createAIProviderMutation = useMutation({
    mutationFn: (data: AIProviderCreate) => apiClient.createAIProvider(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['aiproviders'] })
      showToast('AI Provider configured successfully!', 'success')
      resetForm()
    },
    onError: (error: any) => {
      showToast(`Failed to configure provider: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const updateAIProviderMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<AIProviderCreate> }) =>
      apiClient.updateAIProvider(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['aiproviders'] })
      showToast('AI Provider updated successfully!', 'success')
      resetForm()
    },
    onError: (error: any) => {
      showToast(`Failed to update provider: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const deleteAIProviderMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteAIProvider(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['aiproviders'] })
      showToast('AI Provider deleted successfully!', 'success')
      setShowDeleteAIProviderModal(false)
      setAIProviderToDelete(null)
    },
    onError: (error: any) => {
      showToast(`Failed to delete provider: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const testAIProviderMutation = useMutation({
    mutationFn: (id: string) => apiClient.testAIProvider(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['aiproviders'] })
      showToast('API key test completed successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`API key test failed: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (providerDropdownRef.current && !providerDropdownRef.current.contains(event.target as Node)) {
        setShowProviderDropdown(false)
      }
      if (platformDropdownRef.current && !platformDropdownRef.current.contains(event.target as Node)) {
        setShowPlatformDropdown(false)
      }
    }

    if (showProviderDropdown || showPlatformDropdown) {
      document.addEventListener('mousedown', handleClickOutside)
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [showProviderDropdown, showPlatformDropdown])

  const resetForm = () => {
    setShowModal(false)
    setIsEditMode(false)
    setIntegrationType(null)
    setSelectedIntegration(null)
    setSelectedAIProvider(null)
    setSelectedPlatform(null)
    setSelectedProvider(null)
    setShowProviderDropdown(false)
    setShowPlatformDropdown(false)
    setApiKey('')
    setName('')
  }

  const handleEdit = (integration: Integration) => {
    setIntegrationType('voice_platform')
    setSelectedIntegration(integration)
    setSelectedPlatform(integration.platform as 'retell' | 'vapi' | 'cartesia' | 'elevenlabs' | 'deepgram')
    setName(integration.name || '')
    setApiKey('') // Don't pre-fill API key for security
    setIsEditMode(true)
    setShowModal(true)
  }

  const handleEditAIProvider = (provider: AIProvider) => {
    setIntegrationType('ai_provider')
    setSelectedAIProvider(provider)
    setSelectedProvider(provider.provider)
    setName(provider.name || '')
    setApiKey('') // Don't pre-fill API key for security
    setShowProviderDropdown(false)
    setIsEditMode(true)
    setShowModal(true)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    if (integrationType === 'voice_platform') {
      if (isEditMode && selectedIntegration) {
        // Update existing integration
        const updateData: Partial<IntegrationCreate> = {}
        if (name !== (selectedIntegration.name || '')) {
          updateData.name = name || undefined
        }
        if (apiKey) {
          updateData.api_key = apiKey
        }

        if (Object.keys(updateData).length > 0) {
          updateIntegrationMutation.mutate({ id: selectedIntegration.id, data: updateData })
        } else {
          resetForm()
        }
      } else {
        // Create new integration
        if (!selectedPlatform || !apiKey) return

        createIntegrationMutation.mutate({
          platform: selectedPlatform as IntegrationPlatform,
          api_key: apiKey,
          name: name || undefined,
        })
      }
    } else if (integrationType === 'ai_provider') {
      if (isEditMode && selectedAIProvider) {
        // Update existing AI provider
        if (!apiKey.trim()) {
          showToast('Please enter an API key', 'error')
          return
        }
        updateAIProviderMutation.mutate({
          id: selectedAIProvider.id,
          data: {
            api_key: apiKey,
            name: name || null,
          },
        })
      } else {
        // Create new AI provider
        if (!selectedProvider || !apiKey.trim()) {
          showToast('Please select a provider and enter an API key', 'error')
          return
        }
        createAIProviderMutation.mutate({
          provider: selectedProvider,
          api_key: apiKey,
          name: name || null,
        })
      }
    }
  }

  const handleDelete = (integration: Integration) => {
    setIntegrationToDelete(integration)
    setShowDeleteModal(true)
  }

  const handleDeleteAIProvider = (provider: AIProvider) => {
    setAIProviderToDelete(provider)
    setShowDeleteAIProviderModal(true)
  }

  const confirmDeleteIntegration = () => {
    if (integrationToDelete) {
      deleteIntegrationMutation.mutate(integrationToDelete.id)
    }
  }

  const confirmDeleteAIProvider = () => {
    if (aiProviderToDelete) {
      deleteAIProviderMutation.mutate(aiProviderToDelete.id)
    }
  }

  const handleTestAIProvider = (provider: AIProvider) => {
    testAIProviderMutation.mutate(provider.id)
  }

  const platforms = [
    {
      id: IntegrationPlatform.RETELL,
      name: 'Retell AI',
      description: 'Connect your Retell AI voice agents',
      image: '/retellai.png',
    },
    {
      id: IntegrationPlatform.VAPI,
      name: 'Vapi',
      description: 'Connect your Vapi voice AI agents',
      image: '/vapiai.jpg',
    },
    {
      id: IntegrationPlatform.CARTESIA,
      name: 'Cartesia',
      description: 'Connect your Cartesia voice AI agents',
      image: '/cartesia.jpg',
    },
    {
      id: IntegrationPlatform.ELEVENLABS,
      name: 'ElevenLabs',
      description: 'Connect your ElevenLabs voice AI agents',
      image: '/elevenLabs.png',
    },
    {
      id: IntegrationPlatform.DEEPGRAM,
      name: 'Deepgram',
      description: 'Connect your Deepgram voice AI agents',
      image: '/deepgram.png',
    },
  ]

  // Get configured platforms
  const configuredPlatforms = new Set(integrations.map((i: Integration) => i.platform))
  const availablePlatforms = platforms.filter(p => !configuredPlatforms.has(p.id))

  // Get configured AI providers
  const configuredProviders = new Set(aiproviders.map((p: AIProvider) => p.provider))
  const availableProviders = Object.values(ModelProvider).filter(p => !configuredProviders.has(p))

  const getPlatformInfo = (platformId: IntegrationPlatform) => {
    return platforms.find(p => p.id === platformId)
  }

  return (
    <div className="space-y-6">
      <ToastContainer />
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Integrations</h1>
          <p className="text-gray-600 mt-1">
            Connect with voice AI platforms and configure AI providers to test and evaluate agents
          </p>
        </div>
        <Button
          variant="primary"
          onClick={() => setShowModal(true)}
          leftIcon={<Plus className="h-5 w-5" />}
        >
          Add Integration
        </Button>
      </div>

      {/* Configured Integrations */}
      {(integrations.length > 0 || aiproviders.length > 0) && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">Configured Integrations</h2>
            <p className="text-sm text-gray-600 mt-1">These integrations are ready to use</p>
          </div>
          <div className="divide-y divide-gray-200">
            {/* Voice AI Platform Integrations */}
            {integrations.map((integration: Integration) => {
              const platformInfo = getPlatformInfo(integration.platform)
              return (
                <div
                  key={integration.id}
                  className="px-6 py-4 hover:bg-gray-50 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4 flex-1">
                      <div className="flex-shrink-0">
                        {platformInfo?.image ? (
                          <div className="w-12 h-12 bg-white rounded-lg flex items-center justify-center border border-gray-200 p-2">
                            <img
                              src={platformInfo.image}
                              alt={platformInfo.name}
                              className="w-full h-full object-contain"
                            />
                          </div>
                        ) : (
                          <div className="w-12 h-12 bg-gradient-to-br from-primary-100 to-primary-200 rounded-lg flex items-center justify-center">
                            <Plug className="h-6 w-6 text-primary-600" />
                          </div>
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <h3 className="text-lg font-semibold text-gray-900">
                            {platformInfo?.name || integration.platform}
                          </h3>
                          {integration.name && (
                            <span className="text-sm text-gray-500">({integration.name})</span>
                          )}
                          {!integration.is_active && (
                            <span className="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded">
                              Inactive
                            </span>
                          )}
                          {integration.last_tested_at && (
                            <span className="px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 rounded flex items-center gap-1">
                              <CheckCircle className="h-3 w-3" />
                              Tested
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-gray-600 mt-1">
                          {platformInfo?.description || 'Voice AI platform integration'}
                        </p>
                        {integration.last_tested_at && (
                          <p className="text-xs text-gray-500 mt-1">
                            Last tested: {new Date(integration.last_tested_at).toLocaleDateString()}
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleEdit(integration)}
                        leftIcon={<Edit className="h-4 w-4" />}
                      >
                        Edit
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDelete(integration)}
                        leftIcon={<Trash2 className="h-4 w-4" />}
                        className="text-red-600 hover:text-red-700 hover:bg-red-50"
                      >
                        Delete
                      </Button>
                    </div>
                  </div>
                </div>
              )
            })}
            {/* AI Provider Integrations */}
            {aiproviders.map((provider: AIProvider) => (
              <div
                key={provider.id}
                className="px-6 py-4 hover:bg-gray-50 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4 flex-1">
                    <div className="flex-shrink-0">
                      {PROVIDER_LOGOS[provider.provider] ? (
                        <div className="w-12 h-12 bg-white rounded-lg flex items-center justify-center border border-gray-200 p-2">
                            <img
                              src={PROVIDER_LOGOS[provider.provider]!}
                              alt={PROVIDER_LABELS[provider.provider]}
                              className="w-full h-full object-contain"
                            />
                          </div>
                      ) : (
                        <div className="w-12 h-12 bg-gradient-to-br from-primary-100 to-primary-200 rounded-lg flex items-center justify-center">
                          <Brain className="h-6 w-6 text-primary-600" />
                        </div>
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h3 className="text-lg font-semibold text-gray-900">
                          {PROVIDER_LABELS[provider.provider]}
                        </h3>
                        {provider.name && (
                          <span className="text-sm text-gray-500">({provider.name})</span>
                        )}
                        {!provider.is_active && (
                          <span className="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded">
                            Inactive
                          </span>
                        )}
                        {provider.last_tested_at && (
                          <span className="px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 rounded flex items-center gap-1">
                            <CheckCircle className="h-3 w-3" />
                            Tested
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-gray-600 mt-1">
                        {PROVIDER_DESCRIPTIONS[provider.provider]}
                      </p>
                      {provider.last_tested_at && (
                        <p className="text-xs text-gray-500 mt-1">
                          Last tested: {new Date(provider.last_tested_at).toLocaleDateString()}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleTestAIProvider(provider)}
                      isLoading={testAIProviderMutation.isPending && testAIProviderMutation.variables === provider.id}
                      leftIcon={<Key className="h-4 w-4" />}
                    >
                      Test
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleEditAIProvider(provider)}
                      leftIcon={<Edit className="h-4 w-4" />}
                    >
                      Edit
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDeleteAIProvider(provider)}
                      leftIcon={<Trash2 className="h-4 w-4" />}
                      className="text-red-600 hover:text-red-700 hover:bg-red-50"
                    >
                      Delete
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {integrations.length === 0 && aiproviders.length === 0 && (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <Plug className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">All integrations configured</h3>
          <p className="text-gray-500">You have configured all available integration platforms and AI providers</p>
        </div>
      )}

      {/* Add/Edit Integration Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">
                {isEditMode 
                  ? (integrationType === 'ai_provider' ? 'Edit AI Provider' : 'Edit Integration')
                  : 'Add Integration'}
              </h3>
              <button
                onClick={resetForm}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleSubmit} className="p-6 space-y-4">
              {/* Integration Type Selector (only show when creating) */}
              {!isEditMode && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Integration Type *
                  </label>
                  <div className="grid grid-cols-2 gap-3">
                    <button
                      type="button"
                      onClick={() => {
                        setIntegrationType('voice_platform')
                        setSelectedPlatform(null)
                        setSelectedProvider(null)
                      }}
                      className={`p-3 border-2 rounded-lg text-left transition-all ${
                        integrationType === 'voice_platform'
                          ? 'border-primary-500 bg-primary-50'
                          : 'border-gray-200 hover:border-gray-300'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <Plug className="h-5 w-5 text-primary-600" />
                        <span className="font-medium text-gray-900">Voice Platform</span>
                      </div>
                      <p className="text-xs text-gray-600 mt-1">Retell, Vapi, etc.</p>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setIntegrationType('ai_provider')
                        setSelectedPlatform(null)
                        setSelectedProvider(null)
                      }}
                      className={`p-3 border-2 rounded-lg text-left transition-all ${
                        integrationType === 'ai_provider'
                          ? 'border-primary-500 bg-primary-50'
                          : 'border-gray-200 hover:border-gray-300'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <Brain className="h-5 w-5 text-primary-600" />
                        <span className="font-medium text-gray-900">AI Provider</span>
                      </div>
                      <p className="text-xs text-gray-600 mt-1">OpenAI, Anthropic, etc.</p>
                    </button>
                  </div>
                </div>
              )}

              {/* Voice Platform Form */}
              {integrationType === 'voice_platform' && (
                <>
                  <div>
                    <label htmlFor="platform" className="block text-sm font-medium text-gray-700 mb-1">
                      Platform *
                    </label>
                    <div className="relative" ref={platformDropdownRef}>
                      <button
                        type="button"
                        onClick={() => setShowPlatformDropdown(!showPlatformDropdown)}
                        disabled={isEditMode || availablePlatforms.length === 0}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white text-left flex items-center justify-between disabled:bg-gray-100 disabled:cursor-not-allowed"
                      >
                        <div className="flex items-center gap-2">
                          {selectedPlatform ? (
                            (() => {
                              const platformInfo = getPlatformInfo(selectedPlatform as IntegrationPlatform)
                              return (
                                <>
                                  {platformInfo?.image ? (
                                    <img
                                      src={platformInfo.image}
                                      alt={platformInfo.name}
                                      className="w-5 h-5 object-contain"
                                    />
                                  ) : (
                                    <Plug className="h-5 w-5 text-primary-600" />
                                  )}
                                  <span>{platformInfo?.name || selectedPlatform}</span>
                                </>
                              )
                            })()
                          ) : (
                            <span className="text-gray-500">Select a platform</span>
                          )}
                        </div>
                        <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${showPlatformDropdown ? 'transform rotate-180' : ''}`} />
                      </button>
                      {showPlatformDropdown && availablePlatforms.length > 0 && (
                        <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-auto">
                          {availablePlatforms.map((platform) => (
                            <button
                              key={platform.id}
                              type="button"
                              onClick={() => {
                                setSelectedPlatform(platform.id as 'retell' | 'vapi' | 'cartesia' | 'elevenlabs' | 'deepgram')
                                setShowPlatformDropdown(false)
                              }}
                              className="w-full px-3 py-2 text-left hover:bg-gray-50 flex items-center gap-2 transition-colors"
                            >
                              {platform.image ? (
                                <img
                                  src={platform.image}
                                  alt={platform.name}
                                  className="w-5 h-5 object-contain"
                                />
                              ) : (
                                <Plug className="h-5 w-5 text-primary-600" />
                              )}
                              <span>{platform.name}</span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                    {selectedPlatform && (() => {
                      const platformInfo = getPlatformInfo(selectedPlatform as IntegrationPlatform)
                      return platformInfo?.description && (
                        <p className="mt-1 text-xs text-gray-500">{platformInfo.description}</p>
                      )
                    })()}
                    {isEditMode && (
                      <p className="mt-1 text-xs text-gray-500">
                        Platform cannot be changed after creation
                      </p>
                    )}
                  </div>
                  <div>
                    <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
                      Name (Optional)
                    </label>
                    <input
                      id="name"
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      placeholder="My Retell Integration"
                    />
                  </div>
                  <div>
                    <label htmlFor="apiKey" className="block text-sm font-medium text-gray-700 mb-1">
                      API Key {isEditMode && <span className="text-gray-500 font-normal">(leave empty to keep current)</span>}
                    </label>
                    <input
                      id="apiKey"
                      type="password"
                      required={!isEditMode}
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      placeholder={isEditMode ? "Enter new API key (optional)" : "Enter API key"}
                    />
                    <p className="mt-1 text-xs text-gray-500">
                      Your API key will be encrypted and stored securely
                    </p>
                  </div>
                </>
              )}

              {/* AI Provider Form */}
              {integrationType === 'ai_provider' && (
                <>
                  <div>
                    <label htmlFor="provider" className="block text-sm font-medium text-gray-700 mb-1">
                      Provider *
                    </label>
                    <div className="relative" ref={providerDropdownRef}>
                      <button
                        type="button"
                        onClick={() => setShowProviderDropdown(!showProviderDropdown)}
                        disabled={isEditMode || availableProviders.length === 0}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white text-left flex items-center justify-between disabled:bg-gray-100 disabled:cursor-not-allowed"
                      >
                        <div className="flex items-center gap-2">
                          {selectedProvider ? (
                            <>
                              {PROVIDER_LOGOS[selectedProvider] ? (
                                <img
                                  src={PROVIDER_LOGOS[selectedProvider]!}
                                  alt={PROVIDER_LABELS[selectedProvider]}
                                  className="w-5 h-5 object-contain"
                                />
                              ) : (
                                <Brain className="h-5 w-5 text-primary-600" />
                              )}
                              <span>{PROVIDER_LABELS[selectedProvider]}</span>
                            </>
                          ) : (
                            <span className="text-gray-500">Select a provider</span>
                          )}
                        </div>
                        <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${showProviderDropdown ? 'transform rotate-180' : ''}`} />
                      </button>
                      {showProviderDropdown && availableProviders.length > 0 && (
                        <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-auto">
                          {availableProviders.map((provider) => (
                            <button
                              key={provider}
                              type="button"
                              onClick={() => {
                                setSelectedProvider(provider)
                                setShowProviderDropdown(false)
                              }}
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
                          ))}
                        </div>
                      )}
                    </div>
                    {selectedProvider && (
                      <p className="mt-1 text-xs text-gray-500">{PROVIDER_DESCRIPTIONS[selectedProvider]}</p>
                    )}
                    {isEditMode && selectedAIProvider && (
                      <p className="mt-1 text-xs text-gray-500">
                        Provider cannot be changed after creation
                      </p>
                    )}
                  </div>
                  <div>
                    <label htmlFor="ai_provider_name" className="block text-sm font-medium text-gray-700 mb-1">
                      Name (Optional)
                    </label>
                    <input
                      id="ai_provider_name"
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      placeholder="e.g., OpenAI Production Key"
                    />
                  </div>
                  <div>
                    <label htmlFor="ai_provider_apiKey" className="block text-sm font-medium text-gray-700 mb-1">
                      API Key *
                    </label>
                    <input
                      id="ai_provider_apiKey"
                      type="password"
                      required
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      placeholder={isEditMode ? "Enter new API key" : "Enter API key"}
                    />
                    <p className="mt-1 text-xs text-gray-500">
                      Your API key will be encrypted and stored securely
                    </p>
                  </div>
                </>
              )}

              {/* Error Messages */}
              {((integrationType === 'voice_platform' && (createIntegrationMutation.isError || updateIntegrationMutation.isError)) ||
                (integrationType === 'ai_provider' && (createAIProviderMutation.isError || updateAIProviderMutation.isError))) && (
                <div className="rounded-md bg-red-50 p-4">
                  <div className="flex">
                    <AlertCircle className="h-5 w-5 text-red-400" />
                    <div className="ml-3">
                      <p className="text-sm text-red-800">
                        {integrationType === 'voice_platform'
                          ? ((createIntegrationMutation.error || updateIntegrationMutation.error as any)?.response?.data?.detail ||
                            (isEditMode ? 'Failed to update integration' : 'Failed to create integration'))
                          : ((createAIProviderMutation.error || updateAIProviderMutation.error as any)?.response?.data?.detail ||
                            (isEditMode ? 'Failed to update provider' : 'Failed to configure provider'))}
                      </p>
                    </div>
                  </div>
                </div>
              )}

              <div className="flex gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={resetForm}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  isLoading={
                    integrationType === 'voice_platform'
                      ? (isEditMode ? updateIntegrationMutation.isPending : createIntegrationMutation.isPending)
                      : (isEditMode ? updateAIProviderMutation.isPending : createAIProviderMutation.isPending)
                  }
                  disabled={!integrationType}
                  className="flex-1"
                >
                  {isEditMode
                    ? (integrationType === 'ai_provider' ? 'Update Provider' : 'Update Integration')
                    : (integrationType === 'ai_provider' ? 'Configure Provider' : 'Add Integration')}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Integration Confirmation Modal */}
      {showDeleteModal && integrationToDelete && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => {
          setShowDeleteModal(false)
          setIntegrationToDelete(null)
        }}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Confirm Delete</h3>
              <button
                onClick={() => {
                  setShowDeleteModal(false)
                  setIntegrationToDelete(null)
                }}
                className="text-gray-400 hover:text-gray-600"
                disabled={deleteIntegrationMutation.isPending}
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
                    Are you sure you want to delete this integration?
                  </p>
                  <p className="text-sm font-semibold text-gray-900 mb-2">
                    {(() => {
                      const platformInfo = getPlatformInfo(integrationToDelete.platform)
                      return platformInfo?.name || integrationToDelete.platform
                    })()}
                    {integrationToDelete.name && (
                      <span className="text-gray-500 font-normal ml-2">({integrationToDelete.name})</span>
                    )}
                  </p>
                  <p className="text-xs text-gray-500">
                    This action cannot be undone. Any agents using this integration may stop working.
                  </p>
                </div>
              </div>
              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowDeleteModal(false)
                    setIntegrationToDelete(null)
                  }}
                  className="flex-1"
                  disabled={deleteIntegrationMutation.isPending}
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  onClick={confirmDeleteIntegration}
                  isLoading={deleteIntegrationMutation.isPending}
                  leftIcon={!deleteIntegrationMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
                  className="flex-1"
                >
                  Delete
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete AI Provider Confirmation Modal */}
      {showDeleteAIProviderModal && aiProviderToDelete && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => {
          setShowDeleteAIProviderModal(false)
          setAIProviderToDelete(null)
        }}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Confirm Delete</h3>
              <button
                onClick={() => {
                  setShowDeleteAIProviderModal(false)
                  setAIProviderToDelete(null)
                }}
                className="text-gray-400 hover:text-gray-600"
                disabled={deleteAIProviderMutation.isPending}
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
                    Are you sure you want to delete the <span className="font-semibold text-gray-900">{PROVIDER_LABELS[aiProviderToDelete.provider]}</span> configuration?
                  </p>
                  {aiProviderToDelete.name && (
                    <p className="text-sm text-gray-600 mb-2">
                      Name: <span className="font-medium">{aiProviderToDelete.name}</span>
                    </p>
                  )}
                  <p className="text-xs text-gray-500">
                    This action cannot be undone. Any VoiceBundles using this provider may stop working.
                  </p>
                </div>
              </div>
              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowDeleteAIProviderModal(false)
                    setAIProviderToDelete(null)
                  }}
                  className="flex-1"
                  disabled={deleteAIProviderMutation.isPending}
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  onClick={confirmDeleteAIProvider}
                  isLoading={deleteAIProviderMutation.isPending}
                  leftIcon={!deleteAIProviderMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
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


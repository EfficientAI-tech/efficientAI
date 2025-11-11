import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { AIProvider, AIProviderCreate, ModelProvider } from '../types/api'
import { Brain, Plus, Edit, Trash2, X, Loader, Key, CheckCircle, ChevronDown } from 'lucide-react'
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

export default function AIProviders() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showProviderDropdown, setShowProviderDropdown] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState<AIProvider | null>(null)
  const [formData, setFormData] = useState<AIProviderCreate>({
    provider: ModelProvider.OPENAI,
    api_key: '',
    name: '',
  })

  const { data: aiproviders = [], isLoading } = useQuery({
    queryKey: ['aiproviders'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const createMutation = useMutation({
    mutationFn: (data: AIProviderCreate) => apiClient.createAIProvider(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['aiproviders'] })
      setShowCreateModal(false)
      resetForm()
      showToast('AI Provider configured successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to configure provider: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<AIProviderCreate> }) =>
      apiClient.updateAIProvider(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['aiproviders'] })
      setShowEditModal(false)
      setSelectedProvider(null)
      resetForm()
      showToast('AI Provider updated successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to update provider: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteAIProvider(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['aiproviders'] })
      setShowDeleteModal(false)
      setSelectedProvider(null)
      showToast('AI Provider deleted successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to delete provider: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const testMutation = useMutation({
    mutationFn: (id: string) => apiClient.testAIProvider(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['aiproviders'] })
      showToast('API key test completed successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`API key test failed: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const resetForm = () => {
    setFormData({
      provider: ModelProvider.OPENAI,
      api_key: '',
      name: '',
    })
  }

  const dropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
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

  useEffect(() => {
    if (!showCreateModal) {
      setShowProviderDropdown(false)
    }
  }, [showCreateModal])

  const openCreateModal = () => {
    resetForm()
    setShowCreateModal(true)
  }

  const openEditModal = (provider: AIProvider) => {
    setSelectedProvider(provider)
    setFormData({
      provider: provider.provider,
      api_key: '', // Don't populate for security
      name: provider.name || '',
    })
    setShowEditModal(true)
  }

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.api_key.trim()) {
      showToast('Please enter an API key', 'error')
      return
    }
    createMutation.mutate(formData)
  }

  const handleUpdate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedProvider) return
    if (!formData.api_key.trim()) {
      showToast('Please enter an API key', 'error')
      return
    }
    updateMutation.mutate({ id: selectedProvider.id, data: formData })
  }

  const handleDelete = (provider: AIProvider) => {
    setSelectedProvider(provider)
    setShowDeleteModal(true)
  }

  const confirmDelete = () => {
    if (selectedProvider) {
      deleteMutation.mutate(selectedProvider.id)
    }
  }

  const handleTest = (provider: AIProvider) => {
    testMutation.mutate(provider.id)
  }

  // Get configured providers
  const configuredProviders = new Set(aiproviders.map((p: AIProvider) => p.provider))
  const availableProviders = Object.values(ModelProvider).filter(p => !configuredProviders.has(p))

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
          <h1 className="text-3xl font-bold text-gray-900">AI Providers</h1>
          <p className="text-gray-600 mt-1">
            Configure API keys for different AI platforms to use in VoiceBundles
          </p>
        </div>
        {availableProviders.length > 0 && (
          <Button variant="primary" onClick={openCreateModal} leftIcon={<Plus className="h-5 w-5" />}>
            Add Provider
          </Button>
        )}
      </div>

      {/* Configured Providers */}
      {aiproviders.length > 0 && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">Configured Providers</h2>
            <p className="text-sm text-gray-600 mt-1">These providers are available for use in VoiceBundles</p>
          </div>
          <div className="divide-y divide-gray-200">
            {aiproviders.map((provider: AIProvider) => (
              <div
                key={provider.id}
                className="px-6 py-4 hover:bg-gray-50 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4 flex-1">
                    <div className="flex-shrink-0">
                      {PROVIDER_LOGOS[provider.provider as ModelProvider] ? (
                        <div className="w-12 h-12 bg-white rounded-lg flex items-center justify-center border border-gray-200 p-2">
                          <img
                            src={PROVIDER_LOGOS[provider.provider as ModelProvider]!}
                            alt={PROVIDER_LABELS[provider.provider as ModelProvider]}
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
                          {PROVIDER_LABELS[provider.provider as ModelProvider]}
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
                        {PROVIDER_DESCRIPTIONS[provider.provider as ModelProvider]}
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
                      onClick={() => handleTest(provider)}
                      isLoading={testMutation.isPending && testMutation.variables === provider.id}
                      leftIcon={<Key className="h-4 w-4" />}
                    >
                      Test
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openEditModal(provider)}
                      leftIcon={<Edit className="h-4 w-4" />}
                    >
                      Edit
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(provider)}
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

      {/* Available Providers */}
      {availableProviders.length > 0 && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">Available Providers</h2>
            <p className="text-sm text-gray-600 mt-1">Configure these providers to use them in VoiceBundles</p>
          </div>
          <div className="p-6">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {availableProviders.map((provider) => (
                <button
                  key={provider}
                  onClick={() => {
                    setFormData({ ...formData, provider })
                    setShowCreateModal(true)
                  }}
                  className="group p-4 border-2 border-gray-200 rounded-lg hover:border-primary-300 hover:shadow-md transition-all text-left"
                >
                  <div className="flex items-center gap-3 mb-2">
                    {PROVIDER_LOGOS[provider] ? (
                      <div className="w-10 h-10 bg-white rounded-lg flex items-center justify-center border border-gray-200 p-1.5">
                        <img
                          src={PROVIDER_LOGOS[provider]!}
                          alt={PROVIDER_LABELS[provider]}
                          className="w-full h-full object-contain"
                        />
                      </div>
                    ) : (
                      <div className="w-10 h-10 bg-gradient-to-br from-primary-100 to-primary-200 rounded-lg flex items-center justify-center group-hover:from-primary-200 group-hover:to-primary-300 transition-colors">
                        <Brain className="h-5 w-5 text-primary-600" />
                      </div>
                    )}
                    <h3 className="font-semibold text-gray-900">{PROVIDER_LABELS[provider]}</h3>
                  </div>
                  <p className="text-sm text-gray-600">{PROVIDER_DESCRIPTIONS[provider]}</p>
                  <div className="mt-3 flex items-center gap-2 text-sm text-primary-600 group-hover:text-primary-700">
                    <Plus className="h-4 w-4" />
                    <span>Configure</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {aiproviders.length === 0 && availableProviders.length === 0 && (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <Brain className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">All providers configured</h3>
          <p className="text-gray-500">You have configured all available AI providers</p>
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Configure AI Provider</h3>
              <button
                onClick={() => {
                  setShowCreateModal(false)
                  resetForm()
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleCreate} className="p-6 space-y-4">
              <div>
                <label htmlFor="provider" className="block text-sm font-medium text-gray-700 mb-1">
                  Provider *
                </label>
                <div className="relative" ref={dropdownRef}>
                  <button
                    type="button"
                    onClick={() => setShowProviderDropdown(!showProviderDropdown)}
                    disabled={availableProviders.length === 0}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white text-left flex items-center justify-between disabled:bg-gray-100 disabled:cursor-not-allowed"
                  >
                    <div className="flex items-center gap-2">
                      {PROVIDER_LOGOS[formData.provider] ? (
                        <img
                          src={PROVIDER_LOGOS[formData.provider]!}
                          alt={PROVIDER_LABELS[formData.provider]}
                          className="w-5 h-5 object-contain"
                        />
                      ) : (
                        <Brain className="h-5 w-5 text-primary-600" />
                      )}
                      <span>{PROVIDER_LABELS[formData.provider]}</span>
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
                            setFormData({ ...formData, provider })
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
                {formData.provider && (
                  <p className="mt-1 text-xs text-gray-500">{PROVIDER_DESCRIPTIONS[formData.provider]}</p>
                )}
              </div>
              <div>
                <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
                  Name (Optional)
                </label>
                <input
                  id="name"
                  type="text"
                  value={formData.name || ''}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value || null })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="e.g., OpenAI Production Key"
                />
              </div>
              <div>
                <label htmlFor="api_key" className="block text-sm font-medium text-gray-700 mb-1">
                  API Key *
                </label>
                <input
                  id="api_key"
                  type="password"
                  required
                  value={formData.api_key}
                  onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="Enter API key"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Your API key will be encrypted and stored securely
                </p>
              </div>
              <div className="flex gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setShowCreateModal(false)
                    resetForm()
                  }}
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
                  Configure
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {showEditModal && selectedProvider && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Edit AI Provider</h3>
              <button
                onClick={() => {
                  setShowEditModal(false)
                  setSelectedProvider(null)
                  resetForm()
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleUpdate} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Provider
                </label>
                <div className="px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg">
                  <span className="text-gray-900 font-medium">{PROVIDER_LABELS[selectedProvider.provider as ModelProvider]}</span>
                </div>
                <p className="mt-1 text-xs text-gray-500">{PROVIDER_DESCRIPTIONS[selectedProvider.provider as ModelProvider]}</p>
              </div>
              <div>
                <label htmlFor="edit_name" className="block text-sm font-medium text-gray-700 mb-1">
                  Name (Optional)
                </label>
                <input
                  id="edit_name"
                  type="text"
                  value={formData.name || ''}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value || null })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="e.g., OpenAI Production Key"
                />
              </div>
              <div>
                <label htmlFor="edit_api_key" className="block text-sm font-medium text-gray-700 mb-1">
                  API Key *
                </label>
                <input
                  id="edit_api_key"
                  type="password"
                  required
                  value={formData.api_key}
                  onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="Enter new API key"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Enter a new API key to update the existing one
                </p>
              </div>
              <div className="flex gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setShowEditModal(false)
                    setSelectedProvider(null)
                    resetForm()
                  }}
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
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && selectedProvider && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setShowDeleteModal(false)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Delete AI Provider</h3>
              <button
                onClick={() => {
                  setShowDeleteModal(false)
                  setSelectedProvider(null)
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
                    Are you sure you want to delete the <span className="font-semibold text-gray-900">{PROVIDER_LABELS[selectedProvider.provider as ModelProvider]}</span> configuration?
                  </p>
                  <p className="text-xs text-gray-500">
                    This action cannot be undone. Any VoiceBundles using this provider may stop working.
                  </p>
                </div>
              </div>
              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowDeleteModal(false)
                    setSelectedProvider(null)
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


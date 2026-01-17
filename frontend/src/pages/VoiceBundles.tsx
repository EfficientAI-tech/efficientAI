import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { VoiceBundle, VoiceBundleCreate, ModelProvider, AIProvider, VoiceBundleType, Integration, IntegrationPlatform } from '../types/api'
import { Mic, Plus, Edit, Trash2, X, Loader, Volume2, Brain, MessageSquare, AlertCircle, ChevronDown } from 'lucide-react'
import Button from '../components/Button'
import { useToast } from '../hooks/useToast'

const PROVIDER_LABELS: Record<ModelProvider, string> = {
  [ModelProvider.OPENAI]: 'OpenAI',
  [ModelProvider.ANTHROPIC]: 'Anthropic',
  [ModelProvider.GOOGLE]: 'Google',
  [ModelProvider.AZURE]: 'Azure',
  [ModelProvider.AWS]: 'AWS',
  [ModelProvider.DEEPGRAM]: 'Deepgram',
  [ModelProvider.CARTESIA]: 'Cartesia',
  [ModelProvider.CUSTOM]: 'Custom',
}

const PROVIDER_LOGOS: Record<ModelProvider, string | null> = {
  [ModelProvider.OPENAI]: '/openai-logo.png',
  [ModelProvider.ANTHROPIC]: '/anthropic.png',
  [ModelProvider.GOOGLE]: '/geminiai.png',
  [ModelProvider.AZURE]: '/azureai.png',
  [ModelProvider.AWS]: '/AWS_logo.png',
  [ModelProvider.DEEPGRAM]: '/deepgram.png', // add asset if available
  [ModelProvider.CARTESIA]: '/cartesia.jpg', // ensure asset exists in public/
  [ModelProvider.CUSTOM]: null,
}

export default function VoiceBundles() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [selectedBundle, setSelectedBundle] = useState<VoiceBundle | null>(null)
  const [formData, setFormData] = useState<VoiceBundleCreate>({
    name: '',
    description: '',
    bundle_type: VoiceBundleType.STT_LLM_TTS,
    stt_provider: ModelProvider.OPENAI,
    stt_model: 'whisper-1',
    llm_provider: ModelProvider.OPENAI,
    llm_model: 'gpt-4',
    llm_temperature: 0.7,
    llm_max_tokens: null,
    tts_provider: ModelProvider.OPENAI,
    tts_model: 'tts-1',
    tts_voice: '',
    s2s_provider: null,
    s2s_model: null,
  })

  const { data: voicebundles = [], isLoading } = useQuery({
    queryKey: ['voicebundles'],
    queryFn: () => apiClient.listVoiceBundles(),
  })

  const { data: aiproviders = [] } = useQuery({
    queryKey: ['aiproviders'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const { data: integrations = [] } = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
  })

  // Fetch model configurations for all providers
  const { data: modelConfigs = {} } = useQuery({
    queryKey: ['model-configs'],
    queryFn: async () => {
      const providers = Object.values(ModelProvider)
      const configs: Record<string, { stt: string[]; llm: string[]; tts: string[]; s2s: string[] }> = {}
      
      for (const provider of providers) {
        try {
          const options = await apiClient.getModelOptions(provider)
          // Ensure s2s is always present (for backward compatibility)
          configs[provider] = {
            stt: options.stt || [],
            llm: options.llm || [],
            tts: options.tts || [],
            s2s: options.s2s || []
          }
        } catch (error) {
          // If provider not found in config, use empty arrays
          configs[provider] = { stt: [], llm: [], tts: [], s2s: [] }
        }
      }
      return configs
    },
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
  })

  const mapIntegrationToProvider = (platform: IntegrationPlatform): ModelProvider | null => {
    switch (platform) {
      case IntegrationPlatform.DEEPGRAM:
        return ModelProvider.DEEPGRAM
      case IntegrationPlatform.CARTESIA:
        return ModelProvider.CARTESIA
      default:
        return null
    }
  }

  // Get configured providers (union of active AI providers and integrations)
  const configuredProviders = Array.from(
    new Set([
      ...(aiproviders
        .filter((p: AIProvider) => p.is_active)
        .map((p: AIProvider) => p.provider as ModelProvider)),
      ...(integrations
        .filter((i: Integration) => i.is_active)
        .map((i: Integration) => mapIntegrationToProvider(i.platform))
        .filter((p): p is ModelProvider => Boolean(p))),
    ])
  )

  // Helper function to get model options for a provider
  const getModelOptions = (provider: ModelProvider): { stt: string[]; llm: string[]; tts: string[]; s2s: string[] } => {
    return modelConfigs[provider] || { stt: [], llm: [], tts: [], s2s: [] }
  }
  
  // Default to first configured provider if current selection is not configured
  const getDefaultProvider = (current: ModelProvider) => {
    if (configuredProviders.includes(current)) return current
    return configuredProviders[0] || ModelProvider.OPENAI
  }

  const createMutation = useMutation({
    mutationFn: (data: VoiceBundleCreate) => apiClient.createVoiceBundle(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['voicebundles'] })
      setShowCreateModal(false)
      resetForm()
      showToast('VoiceBundle created successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to create VoiceBundle: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<VoiceBundleCreate> }) =>
      apiClient.updateVoiceBundle(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['voicebundles'] })
      setShowEditModal(false)
      setSelectedBundle(null)
      resetForm()
      showToast('VoiceBundle updated successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to update VoiceBundle: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteVoiceBundle(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['voicebundles'] })
      setShowDeleteModal(false)
      setSelectedBundle(null)
      showToast('VoiceBundle deleted successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to delete VoiceBundle: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const resetForm = () => {
    const defaultProvider = configuredProviders[0] || ModelProvider.OPENAI
    const options = getModelOptions(defaultProvider)
    const defaultSttModel = options.stt[0] || ''
    const defaultLlmModel = options.llm[0] || ''
    const defaultTtsModel = options.tts[0] || ''
    
    setFormData({
      name: '',
      description: '',
      bundle_type: VoiceBundleType.STT_LLM_TTS,
      stt_provider: defaultProvider,
      stt_model: defaultSttModel,
      llm_provider: defaultProvider,
      llm_model: defaultLlmModel,
      llm_temperature: 0.7,
      llm_max_tokens: null,
      tts_provider: defaultProvider,
      tts_model: defaultTtsModel,
      tts_voice: '',
      s2s_provider: null,
      s2s_model: null,
    })
  }

  const openCreateModal = () => {
    resetForm()
    setShowCreateModal(true)
  }

  const openEditModal = (bundle: VoiceBundle) => {
    setSelectedBundle(bundle)
    setFormData({
      name: bundle.name,
      description: bundle.description || '',
      bundle_type: bundle.bundle_type || VoiceBundleType.STT_LLM_TTS,
      stt_provider: bundle.stt_provider ? getDefaultProvider(bundle.stt_provider as ModelProvider) : null,
      stt_model: bundle.stt_model || null,
      llm_provider: bundle.llm_provider ? getDefaultProvider(bundle.llm_provider as ModelProvider) : null,
      llm_model: bundle.llm_model || null,
      llm_temperature: bundle.llm_temperature || 0.7,
      llm_max_tokens: bundle.llm_max_tokens || null,
      tts_provider: bundle.tts_provider ? getDefaultProvider(bundle.tts_provider as ModelProvider) : null,
      tts_model: bundle.tts_model || null,
      tts_voice: bundle.tts_voice || '',
      s2s_provider: bundle.s2s_provider ? getDefaultProvider(bundle.s2s_provider as ModelProvider) : null,
      s2s_model: bundle.s2s_model || null,
    })
    setShowEditModal(true)
  }

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.name.trim()) {
      showToast('Please enter a VoiceBundle name', 'error')
      return
    }
    createMutation.mutate(formData)
  }

  const handleUpdate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedBundle) return
    if (!formData.name.trim()) {
      showToast('Please enter a VoiceBundle name', 'error')
      return
    }
    updateMutation.mutate({ id: selectedBundle.id, data: formData })
  }

  const handleDelete = (bundle: VoiceBundle) => {
    setSelectedBundle(bundle)
    setShowDeleteModal(true)
  }

  const confirmDelete = () => {
    if (selectedBundle) {
      deleteMutation.mutate(selectedBundle.id)
    }
  }

  const updateModelOptions = (type: 'stt' | 'llm' | 'tts' | 's2s', provider: ModelProvider) => {
    const options = getModelOptions(provider)
    const models = options[type]
    if (models.length > 0) {
      if (type === 'stt') {
        setFormData({ ...formData, stt_provider: provider, stt_model: models[0] })
      } else if (type === 'llm') {
        setFormData({ ...formData, llm_provider: provider, llm_model: models[0] })
      } else if (type === 'tts') {
        setFormData({ ...formData, tts_provider: provider, tts_model: models[0] })
      } else if (type === 's2s') {
        setFormData({ ...formData, s2s_provider: provider, s2s_model: models[0] })
      }
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader className="h-8 w-8 animate-spin text-primary-600" />
      </div>
    )
  }

  // Show message if no providers configured
  if (configuredProviders.length === 0) {
    return (
      <div className="space-y-6">
        <ToastContainer />
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-yellow-600 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="text-sm font-semibold text-yellow-900 mb-1">No AI Providers Configured</h3>
              <p className="text-sm text-yellow-700 mb-3">
                You need to configure at least one AI provider before creating VoiceBundles.
              </p>
              <Button
                variant="primary"
                onClick={() => window.location.href = '/integrations'}
                leftIcon={<Brain className="h-4 w-4" />}
              >
                Configure AI Providers
              </Button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <ToastContainer />

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">VoiceBundles</h1>
          <p className="text-gray-600 mt-1">
            Composable units combining STT, LLM, and TTS for voice AI testing, or Speech-to-Speech models
          </p>
        </div>
        <Button variant="primary" onClick={openCreateModal} leftIcon={<Plus className="h-5 w-5" />}>
          Create VoiceBundle
        </Button>
      </div>

      {/* VoiceBundles List */}
      {voicebundles.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <Mic className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No VoiceBundles yet</h3>
          <p className="text-gray-500 mb-4">Create your first VoiceBundle to get started</p>
          <Button variant="primary" onClick={openCreateModal}>
            Create VoiceBundle
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {voicebundles.map((bundle: VoiceBundle) => (
            <div
              key={bundle.id}
              className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition-shadow border border-gray-100 flex flex-col h-full"
            >
              <div className="flex items-start justify-between mb-4 flex-shrink-0">
                <div className="flex-1 min-w-0">
                  <h3 className="text-xl font-bold text-gray-900 mb-1 truncate">{bundle.name}</h3>
                  {bundle.description && (
                    <p className="text-sm text-gray-600 mb-3 line-clamp-2">{bundle.description}</p>
                  )}
                </div>
                {!bundle.is_active && (
                  <span className="px-2 py-1 text-xs font-medium bg-gray-100 text-gray-600 rounded flex-shrink-0 ml-2">
                    Inactive
                  </span>
                )}
              </div>

              <div className="flex-1 flex flex-col justify-between">
                {bundle.bundle_type === VoiceBundleType.S2S ? (
                  /* S2S Configuration */
                  <div className="mb-4 p-3 bg-orange-50 rounded-lg">
                    <div className="flex items-center gap-2 mb-1">
                      <Mic className="h-4 w-4 text-orange-600" />
                      <span className="text-xs font-semibold text-orange-900 uppercase">Speech-to-Speech</span>
                    </div>
                    <div className="text-sm text-gray-700">
                      {bundle.s2s_provider && bundle.s2s_model ? (
                        <div className="flex items-center gap-2">
                          {PROVIDER_LOGOS[bundle.s2s_provider as ModelProvider] ? (
                            <img
                              src={PROVIDER_LOGOS[bundle.s2s_provider as ModelProvider]!}
                              alt={PROVIDER_LABELS[bundle.s2s_provider as ModelProvider]}
                              className="w-4 h-4 object-contain"
                            />
                          ) : null}
                          <span className="font-medium">{PROVIDER_LABELS[bundle.s2s_provider as ModelProvider]}</span>
                          <span className="text-gray-500"> • </span>
                          <span>{bundle.s2s_model}</span>
                        </div>
                      ) : (
                        <span className="text-gray-500">Not configured</span>
                      )}
                    </div>
                  </div>
                ) : (
                  <>
                    {/* STT Configuration */}
                    <div className="mb-3 p-3 bg-blue-50 rounded-lg">
                      <div className="flex items-center gap-2 mb-1">
                        <MessageSquare className="h-4 w-4 text-blue-600" />
                        <span className="text-xs font-semibold text-blue-900 uppercase">STT</span>
                      </div>
                      <div className="text-sm text-gray-700">
                        {bundle.stt_provider && bundle.stt_model ? (
                          <div className="flex items-center gap-2">
                            {PROVIDER_LOGOS[bundle.stt_provider as ModelProvider] ? (
                              <img
                                src={PROVIDER_LOGOS[bundle.stt_provider as ModelProvider]!}
                                alt={PROVIDER_LABELS[bundle.stt_provider as ModelProvider]}
                                className="w-4 h-4 object-contain"
                              />
                            ) : null}
                            <span className="font-medium">{PROVIDER_LABELS[bundle.stt_provider as ModelProvider]}</span>
                            <span className="text-gray-500"> • </span>
                            <span>{bundle.stt_model}</span>
                          </div>
                        ) : (
                          <span className="text-gray-500">Not configured</span>
                        )}
                      </div>
                    </div>

                    {/* LLM Configuration */}
                    <div className="mb-3 p-3 bg-purple-50 rounded-lg">
                      <div className="flex items-center gap-2 mb-1">
                        <Brain className="h-4 w-4 text-purple-600" />
                        <span className="text-xs font-semibold text-purple-900 uppercase">LLM</span>
                      </div>
                      <div className="text-sm text-gray-700">
                        {bundle.llm_provider && bundle.llm_model ? (
                          <div className="flex items-center gap-2 flex-wrap">
                            {PROVIDER_LOGOS[bundle.llm_provider as ModelProvider] ? (
                              <img
                                src={PROVIDER_LOGOS[bundle.llm_provider as ModelProvider]!}
                                alt={PROVIDER_LABELS[bundle.llm_provider as ModelProvider]}
                                className="w-4 h-4 object-contain"
                              />
                            ) : null}
                            <span className="font-medium">{PROVIDER_LABELS[bundle.llm_provider as ModelProvider]}</span>
                            <span className="text-gray-500"> • </span>
                            <span>{bundle.llm_model}</span>
                            {bundle.llm_temperature && (
                              <>
                                <span className="text-gray-500"> • </span>
                                <span>Temp: {bundle.llm_temperature}</span>
                              </>
                            )}
                          </div>
                        ) : (
                          <span className="text-gray-500">Not configured</span>
                        )}
                      </div>
                    </div>

                    {/* TTS Configuration */}
                    <div className="mb-4 p-3 bg-green-50 rounded-lg">
                      <div className="flex items-center gap-2 mb-1">
                        <Volume2 className="h-4 w-4 text-green-600" />
                        <span className="text-xs font-semibold text-green-900 uppercase">TTS</span>
                      </div>
                      <div className="text-sm text-gray-700">
                        {bundle.tts_provider && bundle.tts_model ? (
                          <div className="flex items-center gap-2 flex-wrap">
                            {PROVIDER_LOGOS[bundle.tts_provider as ModelProvider] ? (
                              <img
                                src={PROVIDER_LOGOS[bundle.tts_provider as ModelProvider]!}
                                alt={PROVIDER_LABELS[bundle.tts_provider as ModelProvider]}
                                className="w-4 h-4 object-contain"
                              />
                            ) : null}
                            <span className="font-medium">{PROVIDER_LABELS[bundle.tts_provider as ModelProvider]}</span>
                            <span className="text-gray-500"> • </span>
                            <span>{bundle.tts_model}</span>
                            {bundle.tts_voice && (
                              <>
                                <span className="text-gray-500"> • </span>
                                <span>Voice: {bundle.tts_voice}</span>
                              </>
                            )}
                          </div>
                        ) : (
                          <span className="text-gray-500">Not configured</span>
                        )}
                      </div>
                    </div>
                  </>
                )}
              </div>

              {/* Actions */}
              <div className="flex gap-2 pt-4 border-t border-gray-100 mt-auto">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => openEditModal(bundle)}
                  leftIcon={<Edit className="h-4 w-4" />}
                  className="flex-1"
                >
                  Edit
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleDelete(bundle)}
                  leftIcon={<Trash2 className="h-4 w-4" />}
                  className="text-red-600 hover:text-red-700 hover:bg-red-50"
                >
                  Delete
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <VoiceBundleModal
          title="Create VoiceBundle"
          formData={formData}
          setFormData={setFormData}
          onSubmit={handleCreate}
          onClose={() => {
            setShowCreateModal(false)
            resetForm()
          }}
          isLoading={createMutation.isPending}
          updateModelOptions={updateModelOptions}
          configuredProviders={configuredProviders}
          getModelOptions={getModelOptions}
        />
      )}

      {/* Edit Modal */}
      {showEditModal && selectedBundle && (
        <VoiceBundleModal
          title="Edit VoiceBundle"
          formData={formData}
          setFormData={setFormData}
          onSubmit={handleUpdate}
          onClose={() => {
            setShowEditModal(false)
            setSelectedBundle(null)
            resetForm()
          }}
          isLoading={updateMutation.isPending}
          updateModelOptions={updateModelOptions}
          configuredProviders={configuredProviders}
          getModelOptions={getModelOptions}
        />
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && selectedBundle && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setShowDeleteModal(false)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Delete VoiceBundle</h3>
              <button
                onClick={() => {
                  setShowDeleteModal(false)
                  setSelectedBundle(null)
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
                    Are you sure you want to delete <span className="font-semibold text-gray-900">"{selectedBundle.name}"</span>?
                  </p>
                  <p className="text-xs text-gray-500">
                    This action cannot be undone. The VoiceBundle will be permanently deleted.
                  </p>
                </div>
              </div>
              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowDeleteModal(false)
                    setSelectedBundle(null)
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

// VoiceBundle Form Modal Component
function VoiceBundleModal({
  title,
  formData,
  setFormData,
  onSubmit,
  onClose,
  isLoading,
  updateModelOptions,
  configuredProviders,
  getModelOptions,
}: {
  title: string
  formData: VoiceBundleCreate
  setFormData: (data: VoiceBundleCreate) => void
  onSubmit: (e: React.FormEvent) => void
  onClose: () => void
  isLoading: boolean
  updateModelOptions: (type: 'stt' | 'llm' | 'tts' | 's2s', provider: ModelProvider) => void
  configuredProviders: ModelProvider[]
  getModelOptions: (provider: ModelProvider) => { stt: string[]; llm: string[]; tts: string[]; s2s: string[] }
}) {
  const [showSttDropdown, setShowSttDropdown] = useState(false)
  const [showLlmDropdown, setShowLlmDropdown] = useState(false)
  const [showTtsDropdown, setShowTtsDropdown] = useState(false)
  const [showS2sDropdown, setShowS2sDropdown] = useState(false)
  const sttDropdownRef = useRef<HTMLDivElement>(null)
  const llmDropdownRef = useRef<HTMLDivElement>(null)
  const ttsDropdownRef = useRef<HTMLDivElement>(null)
  const s2sDropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleSttClickOutside = (event: MouseEvent) => {
      if (sttDropdownRef.current && !sttDropdownRef.current.contains(event.target as Node)) {
        setShowSttDropdown(false)
      }
    }

    const handleLlmClickOutside = (event: MouseEvent) => {
      if (llmDropdownRef.current && !llmDropdownRef.current.contains(event.target as Node)) {
        setShowLlmDropdown(false)
      }
    }

    const handleTtsClickOutside = (event: MouseEvent) => {
      if (ttsDropdownRef.current && !ttsDropdownRef.current.contains(event.target as Node)) {
        setShowTtsDropdown(false)
      }
    }

    const handleS2sClickOutside = (event: MouseEvent) => {
      if (s2sDropdownRef.current && !s2sDropdownRef.current.contains(event.target as Node)) {
        setShowS2sDropdown(false)
      }
    }

    if (showSttDropdown) {
      document.addEventListener('mousedown', handleSttClickOutside)
    }
    if (showLlmDropdown) {
      document.addEventListener('mousedown', handleLlmClickOutside)
    }
    if (showTtsDropdown) {
      document.addEventListener('mousedown', handleTtsClickOutside)
    }
    if (showS2sDropdown) {
      document.addEventListener('mousedown', handleS2sClickOutside)
    }

    return () => {
      document.removeEventListener('mousedown', handleSttClickOutside)
      document.removeEventListener('mousedown', handleLlmClickOutside)
      document.removeEventListener('mousedown', handleTtsClickOutside)
      document.removeEventListener('mousedown', handleS2sClickOutside)
    }
  }, [showSttDropdown, showLlmDropdown, showTtsDropdown, showS2sDropdown])
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 overflow-y-auto">
      <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full mx-4 my-8">
        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center sticky top-0 bg-white z-10">
          <h3 className="text-lg font-semibold">{title}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="h-5 w-5" />
          </button>
        </div>
        <form onSubmit={onSubmit} className="p-6 space-y-6 max-h-[calc(100vh-200px)] overflow-y-auto">
          {/* Basic Info */}
          <div className="space-y-4">
            <h4 className="text-sm font-semibold text-gray-900 uppercase tracking-wide">Basic Information</h4>
            <div>
              <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
                Name *
              </label>
              <input
                id="name"
                type="text"
                required
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                placeholder="e.g., OpenAI Premium Bundle"
              />
            </div>
            <div>
              <label htmlFor="description" className="block text-sm font-medium text-gray-700 mb-1">
                Description
              </label>
              <textarea
                id="description"
                value={formData.description || ''}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                rows={2}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                placeholder="Describe this VoiceBundle..."
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Bundle Type *
              </label>
              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => {
                    const defaultProvider = configuredProviders[0] || ModelProvider.OPENAI
                    const options = getModelOptions(defaultProvider)
                    setFormData({
                      ...formData,
                      bundle_type: VoiceBundleType.STT_LLM_TTS,
                      stt_provider: defaultProvider,
                      stt_model: options.stt[0] || '',
                      llm_provider: defaultProvider,
                      llm_model: options.llm[0] || '',
                      tts_provider: defaultProvider,
                      tts_model: options.tts[0] || '',
                      s2s_provider: null,
                      s2s_model: null,
                    })
                  }}
                  className={`p-3 border-2 rounded-lg text-left transition-all ${
                    formData.bundle_type === VoiceBundleType.STT_LLM_TTS
                      ? 'border-primary-500 bg-primary-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <Brain className="h-5 w-5 text-primary-600" />
                    <span className="font-medium text-gray-900">STT + LLM + TTS</span>
                  </div>
                  <p className="text-xs text-gray-600 mt-1">Traditional pipeline</p>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const defaultProvider = configuredProviders[0] || ModelProvider.OPENAI
                    const options = getModelOptions(defaultProvider)
                    setFormData({
                      ...formData,
                      bundle_type: VoiceBundleType.S2S,
                      s2s_provider: defaultProvider,
                      s2s_model: options.s2s[0] || '',
                      stt_provider: null,
                      stt_model: null,
                      llm_provider: null,
                      llm_model: null,
                      tts_provider: null,
                      tts_model: null,
                    })
                  }}
                  className={`p-3 border-2 rounded-lg text-left transition-all ${
                    formData.bundle_type === VoiceBundleType.S2S
                      ? 'border-primary-500 bg-primary-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <Mic className="h-5 w-5 text-primary-600" />
                    <span className="font-medium text-gray-900">Speech-to-Speech</span>
                  </div>
                  <p className="text-xs text-gray-600 mt-1">Single S2S model</p>
                </button>
              </div>
            </div>
          </div>

          {/* STT Configuration - Only show for STT_LLM_TTS type */}
          {formData.bundle_type === VoiceBundleType.STT_LLM_TTS && (
          <div className="space-y-4 p-4 bg-blue-50 rounded-lg border border-blue-200">
            <div className="flex items-center gap-2 mb-2">
              <MessageSquare className="h-5 w-5 text-blue-600" />
              <h4 className="text-sm font-semibold text-gray-900 uppercase tracking-wide">Speech-to-Text (STT)</h4>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label htmlFor="stt_provider" className="block text-sm font-medium text-gray-700 mb-1">
                  Provider *
                </label>
                <div className="relative" ref={sttDropdownRef}>
                  <button
                    type="button"
                    onClick={() => setShowSttDropdown(!showSttDropdown)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white text-left flex items-center justify-between"
                  >
                    <div className="flex items-center gap-2">
                      {formData.stt_provider && PROVIDER_LOGOS[formData.stt_provider] ? (
                        <img
                          src={PROVIDER_LOGOS[formData.stt_provider]!}
                          alt={PROVIDER_LABELS[formData.stt_provider]}
                          className="w-5 h-5 object-contain"
                        />
                      ) : (
                        <Brain className="h-5 w-5 text-primary-600" />
                      )}
                      <span>{formData.stt_provider ? PROVIDER_LABELS[formData.stt_provider] : 'Select provider'}</span>
                    </div>
                    <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${showSttDropdown ? 'transform rotate-180' : ''}`} />
                  </button>
                  {showSttDropdown && (
                    <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-auto">
                      {configuredProviders.map((provider: ModelProvider) => (
                        <button
                          key={provider}
                          type="button"
                          onClick={() => {
                            updateModelOptions('stt', provider)
                            setShowSttDropdown(false)
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
              </div>
              <div>
                <label htmlFor="stt_model" className="block text-sm font-medium text-gray-700 mb-1">
                  Model *
                </label>
                <select
                  id="stt_model"
                  required={formData.bundle_type === VoiceBundleType.STT_LLM_TTS}
                  value={formData.stt_model || ''}
                  onChange={(e) => setFormData({ ...formData, stt_model: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  disabled={!formData.stt_provider}
                >
                  {formData.stt_provider ? (
                    getModelOptions(formData.stt_provider).stt.map((model: string) => (
                      <option key={model} value={model}>
                        {model}
                      </option>
                    ))
                  ) : (
                    <option value="">Select provider first</option>
                  )}
                </select>
              </div>
            </div>
          </div>
          )}

          {/* LLM Configuration - Only show for STT_LLM_TTS type */}
          {formData.bundle_type === VoiceBundleType.STT_LLM_TTS && (
          <div className="space-y-4 p-4 bg-purple-50 rounded-lg border border-purple-200">
            <div className="flex items-center gap-2 mb-2">
              <Brain className="h-5 w-5 text-purple-600" />
              <h4 className="text-sm font-semibold text-gray-900 uppercase tracking-wide">Large Language Model (LLM)</h4>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label htmlFor="llm_provider" className="block text-sm font-medium text-gray-700 mb-1">
                  Provider *
                </label>
                <div className="relative" ref={llmDropdownRef}>
                  <button
                    type="button"
                    onClick={() => setShowLlmDropdown(!showLlmDropdown)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white text-left flex items-center justify-between"
                  >
                    <div className="flex items-center gap-2">
                      {formData.llm_provider && PROVIDER_LOGOS[formData.llm_provider] ? (
                        <img
                          src={PROVIDER_LOGOS[formData.llm_provider]!}
                          alt={PROVIDER_LABELS[formData.llm_provider]}
                          className="w-5 h-5 object-contain"
                        />
                      ) : (
                        <Brain className="h-5 w-5 text-primary-600" />
                      )}
                      <span>{formData.llm_provider ? PROVIDER_LABELS[formData.llm_provider] : 'Select provider'}</span>
                    </div>
                    <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${showLlmDropdown ? 'transform rotate-180' : ''}`} />
                  </button>
                  {showLlmDropdown && (
                    <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-auto">
                      {configuredProviders.map((provider: ModelProvider) => (
                        <button
                          key={provider}
                          type="button"
                          onClick={() => {
                            updateModelOptions('llm', provider)
                            setShowLlmDropdown(false)
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
              </div>
              <div>
                <label htmlFor="llm_model" className="block text-sm font-medium text-gray-700 mb-1">
                  Model *
                </label>
                <select
                  id="llm_model"
                  required={formData.bundle_type === VoiceBundleType.STT_LLM_TTS}
                  value={formData.llm_model || ''}
                  onChange={(e) => setFormData({ ...formData, llm_model: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  disabled={!formData.llm_provider}
                >
                  {formData.llm_provider ? (
                    getModelOptions(formData.llm_provider).llm.map((model: string) => (
                      <option key={model} value={model}>
                        {model}
                      </option>
                    ))
                  ) : (
                    <option value="">Select provider first</option>
                  )}
                </select>
              </div>
              <div>
                <label htmlFor="llm_temperature" className="block text-sm font-medium text-gray-700 mb-1">
                  Temperature (0-2)
                </label>
                <input
                  id="llm_temperature"
                  type="number"
                  min="0"
                  max="2"
                  step="0.1"
                  value={formData.llm_temperature || 0.7}
                  onChange={(e) => setFormData({ ...formData, llm_temperature: parseFloat(e.target.value) || 0.7 })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                />
              </div>
              <div>
                <label htmlFor="llm_max_tokens" className="block text-sm font-medium text-gray-700 mb-1">
                  Max Tokens (Optional)
                </label>
                <input
                  id="llm_max_tokens"
                  type="number"
                  min="1"
                  value={formData.llm_max_tokens || ''}
                  onChange={(e) => setFormData({ ...formData, llm_max_tokens: e.target.value ? parseInt(e.target.value) : null })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="Leave empty for default"
                />
              </div>
            </div>
          </div>
          )}

          {/* TTS Configuration - Only show for STT_LLM_TTS type */}
          {formData.bundle_type === VoiceBundleType.STT_LLM_TTS && (
          <div className="space-y-4 p-4 bg-green-50 rounded-lg border border-green-200">
            <div className="flex items-center gap-2 mb-2">
              <Volume2 className="h-5 w-5 text-green-600" />
              <h4 className="text-sm font-semibold text-gray-900 uppercase tracking-wide">Text-to-Speech (TTS)</h4>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label htmlFor="tts_provider" className="block text-sm font-medium text-gray-700 mb-1">
                  Provider *
                </label>
                <div className="relative" ref={ttsDropdownRef}>
                  <button
                    type="button"
                    onClick={() => setShowTtsDropdown(!showTtsDropdown)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white text-left flex items-center justify-between"
                  >
                    <div className="flex items-center gap-2">
                      {formData.tts_provider && PROVIDER_LOGOS[formData.tts_provider] ? (
                        <img
                          src={PROVIDER_LOGOS[formData.tts_provider]!}
                          alt={PROVIDER_LABELS[formData.tts_provider]}
                          className="w-5 h-5 object-contain"
                        />
                      ) : (
                        <Brain className="h-5 w-5 text-primary-600" />
                      )}
                      <span>{formData.tts_provider ? PROVIDER_LABELS[formData.tts_provider] : 'Select provider'}</span>
                    </div>
                    <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${showTtsDropdown ? 'transform rotate-180' : ''}`} />
                  </button>
                  {showTtsDropdown && (
                    <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-auto">
                      {configuredProviders.map((provider: ModelProvider) => (
                        <button
                          key={provider}
                          type="button"
                          onClick={() => {
                            updateModelOptions('tts', provider)
                            setShowTtsDropdown(false)
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
              </div>
              <div>
                <label htmlFor="tts_model" className="block text-sm font-medium text-gray-700 mb-1">
                  Model *
                </label>
                <select
                  id="tts_model"
                  required={formData.bundle_type === VoiceBundleType.STT_LLM_TTS}
                  value={formData.tts_model || ''}
                  onChange={(e) => setFormData({ ...formData, tts_model: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  disabled={!formData.tts_provider}
                >
                  {formData.tts_provider ? (
                    getModelOptions(formData.tts_provider).tts.map((model: string) => (
                      <option key={model} value={model}>
                        {model}
                      </option>
                    ))
                  ) : (
                    <option value="">Select provider first</option>
                  )}
                </select>
              </div>
              <div>
                <label htmlFor="tts_voice" className="block text-sm font-medium text-gray-700 mb-1">
                  Voice (Optional)
                </label>
                <input
                  id="tts_voice"
                  type="text"
                  value={formData.tts_voice || ''}
                  onChange={(e) => setFormData({ ...formData, tts_voice: e.target.value || null })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="e.g., alloy, echo, fable"
                />
              </div>
            </div>
          </div>
          )}

          {/* S2S Configuration - Only show for S2S type */}
          {formData.bundle_type === VoiceBundleType.S2S && (
          <div className="space-y-4 p-4 bg-orange-50 rounded-lg border border-orange-200">
            <div className="flex items-center gap-2 mb-2">
              <Mic className="h-5 w-5 text-orange-600" />
              <h4 className="text-sm font-semibold text-gray-900 uppercase tracking-wide">Speech-to-Speech (S2S)</h4>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label htmlFor="s2s_provider" className="block text-sm font-medium text-gray-700 mb-1">
                  Provider *
                </label>
                <div className="relative" ref={s2sDropdownRef}>
                  <button
                    type="button"
                    onClick={() => setShowS2sDropdown(!showS2sDropdown)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white text-left flex items-center justify-between"
                  >
                    <div className="flex items-center gap-2">
                      {formData.s2s_provider && PROVIDER_LOGOS[formData.s2s_provider] ? (
                        <img
                          src={PROVIDER_LOGOS[formData.s2s_provider]!}
                          alt={PROVIDER_LABELS[formData.s2s_provider]}
                          className="w-5 h-5 object-contain"
                        />
                      ) : (
                        <Brain className="h-5 w-5 text-primary-600" />
                      )}
                      <span>{formData.s2s_provider ? PROVIDER_LABELS[formData.s2s_provider] : 'Select provider'}</span>
                    </div>
                    <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${showS2sDropdown ? 'transform rotate-180' : ''}`} />
                  </button>
                  {showS2sDropdown && (
                    <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-auto">
                      {configuredProviders.map((provider: ModelProvider) => (
                        <button
                          key={provider}
                          type="button"
                          onClick={() => {
                            updateModelOptions('s2s', provider)
                            setShowS2sDropdown(false)
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
              </div>
              <div>
                <label htmlFor="s2s_model" className="block text-sm font-medium text-gray-700 mb-1">
                  Model *
                </label>
                {formData.s2s_provider ? (
                  getModelOptions(formData.s2s_provider).s2s.length > 0 ? (
                    <select
                      id="s2s_model"
                      required={formData.bundle_type === VoiceBundleType.S2S}
                      value={formData.s2s_model || ''}
                      onChange={(e) => setFormData({ ...formData, s2s_model: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    >
                      {getModelOptions(formData.s2s_provider).s2s.map((model: string) => (
                        <option key={model} value={model}>
                          {model}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <div className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-gray-50 text-gray-500 text-sm">
                      No S2S models available for {PROVIDER_LABELS[formData.s2s_provider]}
                    </div>
                  )
                ) : (
                  <select
                    id="s2s_model"
                    disabled
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-gray-50 text-gray-500"
                  >
                    <option value="">Select provider first</option>
                  </select>
                )}
              </div>
            </div>
          </div>
          )}

          {/* Form Actions */}
          <div className="flex gap-3 pt-4 border-t border-gray-200">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              className="flex-1"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              isLoading={isLoading}
              className="flex-1"
            >
              {title.includes('Create') ? 'Create' : 'Update'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}


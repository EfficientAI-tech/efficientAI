import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { VoiceBundle, VoiceBundleCreate, ModelProvider } from '../types/api'
import { Mic, Plus, Edit, Trash2, X, Loader, Volume2, Brain, MessageSquare, AlertCircle } from 'lucide-react'
import Button from '../components/Button'
import { useToast } from '../hooks/useToast'

// Model options for each provider (extensible)
const MODEL_OPTIONS: Record<ModelProvider, { stt: string[]; llm: string[]; tts: string[] }> = {
  [ModelProvider.OPENAI]: {
    stt: ['whisper-1'],
    llm: ['gpt-4', 'gpt-4-turbo', 'gpt-3.5-turbo', 'gpt-4o'],
    tts: ['tts-1', 'tts-1-hd'],
  },
  [ModelProvider.ANTHROPIC]: {
    stt: [],
    llm: ['claude-3-opus', 'claude-3-sonnet', 'claude-3-haiku'],
    tts: [],
  },
  [ModelProvider.GOOGLE]: {
    stt: ['google-speech-v2'],
    llm: ['gemini-pro', 'gemini-ultra'],
    tts: ['google-tts-v1'],
  },
  [ModelProvider.AZURE]: {
    stt: ['azure-speech-v1'],
    llm: ['azure-openai-gpt4'],
    tts: ['azure-tts-v1'],
  },
  [ModelProvider.AWS]: {
    stt: ['aws-transcribe'],
    llm: ['aws-bedrock-claude'],
    tts: ['aws-polly'],
  },
  [ModelProvider.CUSTOM]: {
    stt: ['custom-stt'],
    llm: ['custom-llm'],
    tts: ['custom-tts'],
  },
}

const PROVIDER_LABELS: Record<ModelProvider, string> = {
  [ModelProvider.OPENAI]: 'OpenAI',
  [ModelProvider.ANTHROPIC]: 'Anthropic',
  [ModelProvider.GOOGLE]: 'Google',
  [ModelProvider.AZURE]: 'Azure',
  [ModelProvider.AWS]: 'AWS',
  [ModelProvider.CUSTOM]: 'Custom',
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
    stt_provider: ModelProvider.OPENAI,
    stt_model: 'whisper-1',
    llm_provider: ModelProvider.OPENAI,
    llm_model: 'gpt-4',
    llm_temperature: 0.7,
    llm_max_tokens: null,
    tts_provider: ModelProvider.OPENAI,
    tts_model: 'tts-1',
    tts_voice: '',
  })

  const { data: voicebundles = [], isLoading } = useQuery({
    queryKey: ['voicebundles'],
    queryFn: () => apiClient.listVoiceBundles(),
  })

  const { data: aiproviders = [] } = useQuery({
    queryKey: ['aiproviders'],
    queryFn: () => apiClient.listAIProviders(),
  })

  // Get configured providers (only show these in dropdowns)
  const configuredProviders = aiproviders
    .filter(p => p.is_active)
    .map(p => p.provider as ModelProvider)
  
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
    const defaultSttModel = MODEL_OPTIONS[defaultProvider]?.stt[0] || 'whisper-1'
    const defaultLlmModel = MODEL_OPTIONS[defaultProvider]?.llm[0] || 'gpt-4'
    const defaultTtsModel = MODEL_OPTIONS[defaultProvider]?.tts[0] || 'tts-1'
    
    setFormData({
      name: '',
      description: '',
      stt_provider: defaultProvider,
      stt_model: defaultSttModel,
      llm_provider: defaultProvider,
      llm_model: defaultLlmModel,
      llm_temperature: 0.7,
      llm_max_tokens: null,
      tts_provider: defaultProvider,
      tts_model: defaultTtsModel,
      tts_voice: '',
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
      stt_provider: getDefaultProvider(bundle.stt_provider as ModelProvider),
      stt_model: bundle.stt_model,
      llm_provider: getDefaultProvider(bundle.llm_provider as ModelProvider),
      llm_model: bundle.llm_model,
      llm_temperature: bundle.llm_temperature || 0.7,
      llm_max_tokens: bundle.llm_max_tokens || null,
      tts_provider: getDefaultProvider(bundle.tts_provider as ModelProvider),
      tts_model: bundle.tts_model,
      tts_voice: bundle.tts_voice || '',
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

  const updateModelOptions = (type: 'stt' | 'llm' | 'tts', provider: ModelProvider) => {
    const models = MODEL_OPTIONS[provider][type]
    if (models.length > 0) {
      if (type === 'stt') {
        setFormData({ ...formData, stt_provider: provider, stt_model: models[0] })
      } else if (type === 'llm') {
        setFormData({ ...formData, llm_provider: provider, llm_model: models[0] })
      } else {
        setFormData({ ...formData, tts_provider: provider, tts_model: models[0] })
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
                onClick={() => window.location.href = '/ai-providers'}
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
            Composable units combining STT, LLM, and TTS for voice AI testing
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
          {voicebundles.map((bundle) => (
            <div
              key={bundle.id}
              className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition-shadow border border-gray-100"
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex-1">
                  <h3 className="text-xl font-bold text-gray-900 mb-1">{bundle.name}</h3>
                  {bundle.description && (
                    <p className="text-sm text-gray-600 mb-3">{bundle.description}</p>
                  )}
                </div>
                {!bundle.is_active && (
                  <span className="px-2 py-1 text-xs font-medium bg-gray-100 text-gray-600 rounded">
                    Inactive
                  </span>
                )}
              </div>

              {/* STT Configuration */}
              <div className="mb-3 p-3 bg-blue-50 rounded-lg">
                <div className="flex items-center gap-2 mb-1">
                  <MessageSquare className="h-4 w-4 text-blue-600" />
                  <span className="text-xs font-semibold text-blue-900 uppercase">STT</span>
                </div>
                <div className="text-sm text-gray-700">
                  <span className="font-medium">{PROVIDER_LABELS[bundle.stt_provider as ModelProvider]}</span>
                  <span className="text-gray-500"> • </span>
                  <span>{bundle.stt_model}</span>
                </div>
              </div>

              {/* LLM Configuration */}
              <div className="mb-3 p-3 bg-purple-50 rounded-lg">
                <div className="flex items-center gap-2 mb-1">
                  <Brain className="h-4 w-4 text-purple-600" />
                  <span className="text-xs font-semibold text-purple-900 uppercase">LLM</span>
                </div>
                <div className="text-sm text-gray-700">
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
              </div>

              {/* TTS Configuration */}
              <div className="mb-4 p-3 bg-green-50 rounded-lg">
                <div className="flex items-center gap-2 mb-1">
                  <Volume2 className="h-4 w-4 text-green-600" />
                  <span className="text-xs font-semibold text-green-900 uppercase">TTS</span>
                </div>
                <div className="text-sm text-gray-700">
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
              </div>

              {/* Actions */}
              <div className="flex gap-2 pt-4 border-t border-gray-100">
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
}: {
  title: string
  formData: VoiceBundleCreate
  setFormData: (data: VoiceBundleCreate) => void
  onSubmit: (e: React.FormEvent) => void
  onClose: () => void
  isLoading: boolean
  updateModelOptions: (type: 'stt' | 'llm' | 'tts', provider: ModelProvider) => void
  configuredProviders: ModelProvider[]
}) {
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
          </div>

          {/* STT Configuration */}
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
                <select
                  id="stt_provider"
                  required
                  value={formData.stt_provider}
                  onChange={(e) => updateModelOptions('stt', e.target.value as ModelProvider)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                >
                  {configuredProviders.map((provider: ModelProvider) => (
                    <option key={provider} value={provider}>
                      {PROVIDER_LABELS[provider as ModelProvider]}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="stt_model" className="block text-sm font-medium text-gray-700 mb-1">
                  Model *
                </label>
                <select
                  id="stt_model"
                  required
                  value={formData.stt_model}
                  onChange={(e) => setFormData({ ...formData, stt_model: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                >
                  {MODEL_OPTIONS[formData.stt_provider].stt.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {/* LLM Configuration */}
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
                <select
                  id="llm_provider"
                  required
                  value={formData.llm_provider}
                  onChange={(e) => updateModelOptions('llm', e.target.value as ModelProvider)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                >
                  {configuredProviders.map((provider: ModelProvider) => (
                    <option key={provider} value={provider}>
                      {PROVIDER_LABELS[provider as ModelProvider]}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="llm_model" className="block text-sm font-medium text-gray-700 mb-1">
                  Model *
                </label>
                <select
                  id="llm_model"
                  required
                  value={formData.llm_model}
                  onChange={(e) => setFormData({ ...formData, llm_model: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                >
                  {MODEL_OPTIONS[formData.llm_provider].llm.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
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

          {/* TTS Configuration */}
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
                <select
                  id="tts_provider"
                  required
                  value={formData.tts_provider}
                  onChange={(e) => updateModelOptions('tts', e.target.value as ModelProvider)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                >
                  {configuredProviders.map((provider: ModelProvider) => (
                    <option key={provider} value={provider}>
                      {PROVIDER_LABELS[provider as ModelProvider]}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="tts_model" className="block text-sm font-medium text-gray-700 mb-1">
                  Model *
                </label>
                <select
                  id="tts_model"
                  required
                  value={formData.tts_model}
                  onChange={(e) => setFormData({ ...formData, tts_model: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                >
                  {MODEL_OPTIONS[formData.tts_provider].tts.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
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


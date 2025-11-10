import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { useState } from 'react'
import { Plus, Trash2, X, AlertCircle, CheckCircle, Plug, Edit } from 'lucide-react'
import { IntegrationCreate, IntegrationPlatform, Integration } from '../types/api'
import Button from '../components/Button'

export default function Integrations() {
  const queryClient = useQueryClient()
  const [showModal, setShowModal] = useState(false)
  const [isEditMode, setIsEditMode] = useState(false)
  const [selectedIntegration, setSelectedIntegration] = useState<Integration | null>(null)
  const [selectedPlatform, setSelectedPlatform] = useState<'retell' | 'vapi' | 'cartesia' | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [name, setName] = useState('')

  const { data: integrations = [] } = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
  })

  const createMutation = useMutation({
    mutationFn: (data: IntegrationCreate) => apiClient.createIntegration(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
      resetForm()
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<IntegrationCreate> }) =>
      apiClient.updateIntegration(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
      resetForm()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteIntegration(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
    },
  })

  const resetForm = () => {
    setShowModal(false)
    setIsEditMode(false)
    setSelectedIntegration(null)
    setSelectedPlatform(null)
    setApiKey('')
    setName('')
  }

  const handleEdit = (integration: Integration) => {
    setSelectedIntegration(integration)
    setSelectedPlatform(integration.platform as 'retell' | 'vapi' | 'cartesia')
    setName(integration.name || '')
    setApiKey('') // Don't pre-fill API key for security
    setIsEditMode(true)
    setShowModal(true)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    
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
        updateMutation.mutate({ id: selectedIntegration.id, data: updateData })
      } else {
        resetForm()
      }
    } else {
      // Create new integration
      if (!selectedPlatform || !apiKey) return

      createMutation.mutate({
        platform: selectedPlatform as IntegrationPlatform,
        api_key: apiKey,
        name: name || undefined,
      })
    }
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
  ]

  // Get configured platforms
  const configuredPlatforms = new Set(integrations.map(i => i.platform))
  const availablePlatforms = platforms.filter(p => !configuredPlatforms.has(p.id))

  const getPlatformInfo = (platformId: IntegrationPlatform) => {
    return platforms.find(p => p.id === platformId)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Integrations</h1>
          <p className="text-gray-600 mt-1">
            Connect with voice AI platforms to test and evaluate agents
          </p>
        </div>
        {availablePlatforms.length > 0 && (
          <Button
            variant="primary"
            onClick={() => setShowModal(true)}
            leftIcon={<Plus className="h-5 w-5" />}
          >
            Add Integration
          </Button>
        )}
      </div>

      {/* Configured Integrations */}
      {integrations.length > 0 && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">Configured Integrations</h2>
            <p className="text-sm text-gray-600 mt-1">These integrations are ready to use</p>
          </div>
          <div className="divide-y divide-gray-200">
            {integrations.map((integration) => {
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
                        onClick={() => {
                          if (confirm('Are you sure you want to delete this integration?')) {
                            deleteMutation.mutate(integration.id)
                          }
                        }}
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
          </div>
        </div>
      )}

      {/* Available Platforms */}
      {availablePlatforms.length > 0 && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">Available Platforms</h2>
            <p className="text-sm text-gray-600 mt-1">Configure these platforms to connect with voice AI services</p>
          </div>
          <div className="p-6">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {availablePlatforms.map((platform) => (
                <button
                  key={platform.id}
                  onClick={() => {
                    setSelectedPlatform(platform.id as 'retell' | 'vapi' | 'cartesia')
                    setShowModal(true)
                  }}
                  className="group p-4 border-2 border-gray-200 rounded-lg hover:border-primary-300 hover:shadow-md transition-all text-left"
                >
                  <div className="border border-gray-200 rounded-lg p-3 mb-3 bg-white">
                    <img 
                      src={platform.image} 
                      alt={platform.name}
                      className="w-full h-20 object-contain"
                    />
                  </div>
                  <h3 className="font-semibold text-gray-900 mb-1">{platform.name}</h3>
                  <p className="text-sm text-gray-600 mb-3">{platform.description}</p>
                  <div className="flex items-center gap-2 text-sm text-primary-600 group-hover:text-primary-700">
                    <Plus className="h-4 w-4" />
                    <span>Configure</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {integrations.length === 0 && availablePlatforms.length === 0 && (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <Plug className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">All platforms configured</h3>
          <p className="text-gray-500">You have configured all available integration platforms</p>
        </div>
      )}

      {/* Add/Edit Integration Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">
                {isEditMode ? 'Edit Integration' : 'Add Integration'}
              </h3>
              <button
                onClick={resetForm}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleSubmit} className="p-6 space-y-4">
              <div>
                <label htmlFor="platform" className="block text-sm font-medium text-gray-700 mb-1">
                  Platform
                </label>
                <select
                  id="platform"
                  required
                  disabled={isEditMode}
                  value={selectedPlatform || ''}
                  onChange={(e) => setSelectedPlatform(e.target.value as 'retell' | 'vapi' | 'cartesia')}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed"
                >
                  <option value="">Select a platform</option>
                  <option value="retell">Retell AI</option>
                  <option value="vapi">Vapi</option>
                  <option value="cartesia">Cartesia</option>
                </select>
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
              {(createMutation.isError || updateMutation.isError) && (
                <div className="rounded-md bg-red-50 p-4">
                  <div className="flex">
                    <AlertCircle className="h-5 w-5 text-red-400" />
                    <div className="ml-3">
                      <p className="text-sm text-red-800">
                        {(createMutation.error || updateMutation.error as any)?.response?.data?.detail || 
                         (isEditMode ? 'Failed to update integration' : 'Failed to create integration')}
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
                  isLoading={isEditMode ? updateMutation.isPending : createMutation.isPending}
                  className="flex-1"
                >
                  {isEditMode ? 'Update Integration' : 'Add Integration'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}


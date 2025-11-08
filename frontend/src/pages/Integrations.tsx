import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import { useState } from 'react'
import { Key, Plus, Trash2, X, AlertCircle } from 'lucide-react'
import { IntegrationCreate, IntegrationPlatform } from '../types/api'
import Button from '../components/Button'

export default function Integrations() {
  const queryClient = useQueryClient()
  const [showModal, setShowModal] = useState(false)
  const [selectedPlatform, setSelectedPlatform] = useState<'retell' | 'vapi' | null>(null)
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
      setShowModal(false)
      setSelectedPlatform(null)
      setApiKey('')
      setName('')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteIntegration(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedPlatform || !apiKey) return

    createMutation.mutate({
      platform: selectedPlatform as IntegrationPlatform,
      api_key: apiKey,
      name: name || undefined,
    })
  }

  const platforms = [
    {
      id: IntegrationPlatform.RETELL,
      name: 'Retell AI',
      description: 'Connect your Retell AI voice agents',
      icon: '🔊',
      color: 'bg-blue-500',
    },
    {
      id: IntegrationPlatform.VAPI,
      name: 'Vapi',
      description: 'Connect your Vapi voice AI agents',
      icon: '🎙️',
      color: 'bg-purple-500',
    },
  ]

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Integrations</h1>
          <p className="mt-2 text-sm text-gray-600">
            Connect with voice AI platforms to test and evaluate agents
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

      {/* Platform Cards */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        {platforms.map((platform) => {
          const platformIntegrations = integrations.filter(i => i.platform === platform.id)
          return (
            <div key={platform.id} className="bg-white shadow rounded-lg overflow-hidden">
              <div className={`${platform.color} px-6 py-4`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-2xl">{platform.icon}</span>
                    <div>
                      <h3 className="text-lg font-semibold text-white">{platform.name}</h3>
                      <p className="text-sm text-white/80">{platform.description}</p>
                    </div>
                  </div>
                </div>
              </div>
              <div className="p-6">
                {platformIntegrations.length > 0 ? (
                  <div className="space-y-3">
                    {platformIntegrations.map((integration) => (
                      <div
                        key={integration.id}
                        className="flex items-center justify-between p-3 border border-gray-200 rounded-lg"
                      >
                        <div className="flex items-center gap-3">
                          <Key className="h-5 w-5 text-gray-400" />
                          <div>
                            <div className="font-medium text-gray-900">
                              {integration.name || integration.platform}
                            </div>
                            <div className="text-sm text-gray-500">
                              {integration.last_tested_at 
                                ? `Last tested: ${new Date(integration.last_tested_at).toLocaleDateString()}`
                                : 'Not tested yet'}
                            </div>
                          </div>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            if (confirm('Are you sure you want to delete this integration?')) {
                              deleteMutation.mutate(integration.id)
                            }
                          }}
                          leftIcon={<Trash2 className="h-5 w-5" />}
                          title="Delete integration"
                          className="text-red-600 hover:bg-red-50 hover:text-red-700"
                        >
                          Delete
                        </Button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center py-8 text-gray-500">
                    <Key className="h-12 w-12 mx-auto mb-3 text-gray-300" />
                    <p>No integrations configured</p>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setSelectedPlatform(platform.id)
                        setShowModal(true)
                      }}
                      className="mt-3"
                    >
                      Add Integration
                    </Button>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Add Integration Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Add Integration</h3>
              <button
                onClick={() => {
                  setShowModal(false)
                  setSelectedPlatform(null)
                  setApiKey('')
                  setName('')
                }}
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
                  value={selectedPlatform || ''}
                  onChange={(e) => setSelectedPlatform(e.target.value as 'retell' | 'vapi')}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                >
                  <option value="">Select a platform</option>
                  <option value="retell">Retell AI</option>
                  <option value="vapi">Vapi</option>
                </select>
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
                  API Key
                </label>
                <input
                  id="apiKey"
                  type="password"
                  required
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="Enter API key"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Your API key will be encrypted and stored securely
                </p>
              </div>
              {createMutation.isError && (
                <div className="rounded-md bg-red-50 p-4">
                  <div className="flex">
                    <AlertCircle className="h-5 w-5 text-red-400" />
                    <div className="ml-3">
                      <p className="text-sm text-red-800">
                        {(createMutation.error as any)?.response?.data?.detail || 'Failed to create integration'}
                      </p>
                    </div>
                  </div>
                </div>
              )}
              <div className="flex gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setShowModal(false)
                    setSelectedPlatform(null)
                    setApiKey('')
                    setName('')
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
                  Add Integration
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}


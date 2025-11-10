import { useState, useMemo } from 'react'
import { FileText, Tag, Plus, Sparkles, UserPlus, Trash2, X, Loader, MessageSquare, Phone } from 'lucide-react'
import { apiClient } from '../lib/api'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Button from '../components/Button'
import { useToast } from '../hooks/useToast'

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

export default function Scenarios() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showPromptModal, setShowPromptModal] = useState(false)
  const [showCallModal, setShowCallModal] = useState(false)
  const [showDetailsModal, setShowDetailsModal] = useState(false)
  const [selectedScenario, setSelectedScenario] = useState<Scenario | null>(null)
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    required_info: {} as Record<string, string>,
  })
  const [promptText, setPromptText] = useState('')
  const [callData, setCallData] = useState('')

  const { data: scenarios = [], isLoading } = useQuery({
    queryKey: ['scenarios'],
    queryFn: () => apiClient.listScenarios(),
  })

  // Separate scenarios into default and user-created
  const { defaultScenarios, userScenarios } = useMemo(() => {
    const defaults: Scenario[] = []
    const userCreated: Scenario[] = []
    const seenDefaultIds = new Set<string>()

    for (const scenario of scenarios) {
      const isExactDefaultName = DEFAULT_SCENARIO_NAMES.some(
        (defaultName) => scenario.name.toLowerCase() === defaultName.toLowerCase()
      )
      const isCloned = scenario.name.includes('(Copy)') || scenario.name.includes('(Clone)')
      const isDefault = isExactDefaultName && !isCloned && !scenario.created_by && !seenDefaultIds.has(scenario.id)

      if (isDefault) {
        defaults.push(scenario)
        seenDefaultIds.add(scenario.id)
      } else {
        userCreated.push(scenario)
      }
    }

    return { defaultScenarios: defaults, userScenarios: userCreated }
  }, [scenarios])

  const createMutation = useMutation({
    mutationFn: (data: { name: string; description?: string; required_info: Record<string, string> }) =>
      apiClient.createScenario(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scenarios'] })
      setShowCreateModal(false)
      resetForm()
      showToast('Scenario created successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to create scenario: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const generateFromPromptMutation = useMutation({
    mutationFn: async (prompt: string) => {
      // TODO: Implement API endpoint for generating scenario from prompt
      // For now, we'll create a basic scenario structure
      // This should call an AI endpoint to generate scenario from prompt
      const scenarioData = {
        name: `Generated: ${prompt.substring(0, 50)}`,
        description: `Scenario generated from prompt: ${prompt}`,
        required_info: {},
      }
      return apiClient.createScenario(scenarioData)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scenarios'] })
      setShowPromptModal(false)
      setPromptText('')
      showToast('Scenario generated successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to generate scenario: ${error.response?.data?.detail || error.message}`, 'error')
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
      setShowCallModal(false)
      setCallData('')
      showToast('Scenario generated from call successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to generate scenario: ${error.response?.data?.detail || error.message}`, 'error')
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

  const seedMutation = useMutation({
    mutationFn: () => apiClient.seedDemoData(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scenarios'] })
      queryClient.invalidateQueries({ queryKey: ['personas'] })
      showToast('Demo data loaded successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to load demo data: ${error.response?.data?.detail || error.message}`, 'error')
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
      required_info: formData.required_info,
    })
  }

  const handleGenerateFromPrompt = (e: React.FormEvent) => {
    e.preventDefault()
    if (!promptText.trim()) {
      showToast('Please enter a prompt', 'error')
      return
    }
    generateFromPromptMutation.mutate(promptText)
  }

  const handleGenerateFromCall = (e: React.FormEvent) => {
    e.preventDefault()
    if (!callData.trim()) {
      showToast('Please enter call data', 'error')
      return
    }
    generateFromCallMutation.mutate(callData)
  }

  const handleDelete = (scenario: Scenario) => {
    if (window.confirm(`Are you sure you want to delete "${scenario.name}"?`)) {
      deleteMutation.mutate(scenario.id)
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
        {scenarios.length === 0 && (
          <Button
            variant="secondary"
            onClick={() => seedMutation.mutate()}
            isLoading={seedMutation.isPending}
            leftIcon={!seedMutation.isPending ? <Sparkles className="h-5 w-5" /> : undefined}
          >
            Load Demo Scenarios
          </Button>
        )}
      </div>

      {/* Action Buttons Section */}
      <div className="bg-white rounded-lg shadow-lg p-6 border border-gray-200">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Create New Scenario</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Create Your Own Button */}
          <button
            onClick={() => setShowCreateModal(true)}
            className="group relative p-6 bg-gradient-to-br from-blue-50 to-indigo-50 border-2 border-blue-200 rounded-xl hover:border-blue-400 hover:shadow-lg transition-all text-left"
          >
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0">
                <div className="w-12 h-12 bg-blue-500 rounded-lg flex items-center justify-center group-hover:bg-blue-600 transition-colors">
                  <Plus className="h-6 w-6 text-white" />
                </div>
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-lg font-semibold text-gray-900 mb-2">Create Your Own</h3>
                <p className="text-sm text-gray-600 leading-relaxed">
                  Manually create a custom scenario with specific requirements and conversation flow.
                </p>
              </div>
            </div>
          </button>

          {/* Generate from Prompt Button */}
          <button
            onClick={() => setShowPromptModal(true)}
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

          {/* Generate from Call Button */}
          <button
            onClick={() => setShowCallModal(true)}
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
        </div>
      </div>

      {/* Default Scenarios Section */}
      {defaultScenarios.length > 0 && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="px-6 py-4 bg-gradient-to-r from-blue-50 to-indigo-50 border-b border-blue-200">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Sparkles className="h-5 w-5 text-blue-600" />
                <h2 className="text-lg font-semibold text-gray-900">Default Scenarios</h2>
                <span className="px-2 py-1 text-xs font-medium text-blue-700 bg-blue-100 rounded-full">
                  {defaultScenarios.length}
                </span>
              </div>
              <p className="text-sm text-gray-600">Pre-configured scenarios ready to use</p>
            </div>
          </div>
          <div className="p-6">
            <div className="flex gap-4 overflow-x-auto pb-4 -mx-6 px-6">
              {defaultScenarios.map((scenario) => (
                <div
                  key={scenario.id}
                  onClick={() => {
                    setSelectedScenario(scenario)
                    setShowDetailsModal(true)
                  }}
                  className="flex-shrink-0 w-80 bg-gradient-to-br from-blue-50 to-indigo-50 border-2 border-blue-200 rounded-xl p-5 hover:shadow-lg hover:border-blue-300 transition-all cursor-pointer group"
                >
                  <div className="flex flex-col h-full">
                    <div className="flex items-center gap-3 mb-4">
                      <div className="w-12 h-12 bg-blue-500 rounded-lg flex items-center justify-center">
                        <FileText className="h-6 w-6 text-white" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-lg font-semibold text-gray-900 truncate">{scenario.name}</h3>
                        {scenario.description && (
                          <p className="text-xs text-gray-500 line-clamp-2 mt-1">{scenario.description}</p>
                        )}
                      </div>
                    </div>

                    {Object.keys(scenario.required_info).length > 0 && (
                      <div className="mt-auto pt-4 border-t border-blue-200">
                        <div className="flex items-center gap-2 text-xs font-medium text-gray-700 mb-2">
                          <Tag className="w-3 h-3" />
                          Required Info:
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {Object.keys(scenario.required_info).slice(0, 3).map((key) => (
                            <span
                              key={key}
                              className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs"
                            >
                              {key.replace(/_/g, ' ')}
                            </span>
                          ))}
                          {Object.keys(scenario.required_info).length > 3 && (
                            <span className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">
                              +{Object.keys(scenario.required_info).length - 3}
                            </span>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

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
          <p className="text-gray-500 mb-4">Load demo scenarios or create your first scenario to get started</p>
          <div className="flex gap-3 justify-center">
            <Button
              variant="primary"
              onClick={() => seedMutation.mutate()}
              isLoading={seedMutation.isPending}
              leftIcon={!seedMutation.isPending ? <Sparkles className="h-5 w-5" /> : undefined}
            >
              Load Demo Scenarios
            </Button>
            <Button
              variant="outline"
              onClick={() => setShowCreateModal(true)}
            >
              Create Your Own
            </Button>
          </div>
        </div>
      )}

      {/* Create Scenario Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Create New Scenario</h3>
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
                <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
                  Scenario Name *
                </label>
                <input
                  id="name"
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="e.g., Book Appointment"
                />
              </div>
              <div>
                <label htmlFor="description" className="block text-sm font-medium text-gray-700 mb-1">
                  Description
                </label>
                <textarea
                  id="description"
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  rows={3}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="Describe what this scenario tests..."
                />
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
                  Create
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Generate from Prompt Modal */}
      {showPromptModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Generate Scenario from Prompt</h3>
              <button
                onClick={() => {
                  setShowPromptModal(false)
                  setPromptText('')
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleGenerateFromPrompt} className="p-6 space-y-4">
              <div>
                <label htmlFor="prompt" className="block text-sm font-medium text-gray-700 mb-1">
                  Describe the scenario *
                </label>
                <textarea
                  id="prompt"
                  required
                  value={promptText}
                  onChange={(e) => setPromptText(e.target.value)}
                  rows={6}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="e.g., A customer wants to book a dental appointment for next week. They need to provide their name, phone number, preferred date and time, and reason for visit."
                />
                <p className="mt-2 text-xs text-gray-500">
                  Describe the conversation scenario in natural language. AI will generate the scenario structure.
                </p>
              </div>
              <div className="flex gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setShowPromptModal(false)
                    setPromptText('')
                  }}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  isLoading={generateFromPromptMutation.isPending}
                  className="flex-1"
                >
                  Generate Scenario
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Generate from Call Modal */}
      {showCallModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Generate Scenario from Call</h3>
              <button
                onClick={() => {
                  setShowCallModal(false)
                  setCallData('')
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleGenerateFromCall} className="p-6 space-y-4">
              <div>
                <label htmlFor="callData" className="block text-sm font-medium text-gray-700 mb-1">
                  Call Transcript or Data *
                </label>
                <textarea
                  id="callData"
                  required
                  value={callData}
                  onChange={(e) => setCallData(e.target.value)}
                  rows={8}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent font-mono text-sm"
                  placeholder="Paste call transcript or upload call data here..."
                />
                <p className="mt-2 text-xs text-gray-500">
                  Paste the call transcript or data. AI will analyze and extract the scenario structure.
                </p>
              </div>
              <div className="flex gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setShowCallModal(false)
                    setCallData('')
                  }}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  isLoading={generateFromCallMutation.isPending}
                  className="flex-1"
                >
                  Generate Scenario
                </Button>
              </div>
            </form>
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
    </div>
  )
}

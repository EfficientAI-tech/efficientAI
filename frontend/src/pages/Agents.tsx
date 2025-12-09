import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Plus, Phone, Edit2, Trash2, X, AlertCircle } from 'lucide-react'
import { apiClient } from '../lib/api'
import { format } from 'date-fns'
import Button from '../components/Button'
import { useAgentStore } from '../store/agentStore'
import { useToast } from '../hooks/useToast'
import { TestAgentConversation } from '../types/api'

interface Agent {
  id: string
  agent_id?: string | null
  name: string
  phone_number?: string | null
  language: string
  description: string | null
  call_type: string
  call_medium: string
  voice_bundle_id?: string | null
  ai_provider_id?: string | null
  created_at: string
  updated_at: string
}

export default function Agents() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { selectedAgent: globalSelectedAgent, setSelectedAgent: setGlobalSelectedAgent } = useAgentStore()
  const { showToast, ToastContainer } = useToast()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null)
  const [blockingConversations, setBlockingConversations] = useState<TestAgentConversation[]>([])
  const [showConversationsList, setShowConversationsList] = useState(false)
  const [selectedAgents, setSelectedAgents] = useState<Set<string>>(new Set())
  const [formData, setFormData] = useState({
    name: '',
    phone_number: '',
    language: 'en',
    description: '',
    call_type: 'outbound',
    call_medium: 'phone_call' as 'phone_call' | 'web_call',
    voice_config_type: 'voice_bundle' as 'voice_bundle' | 'ai_provider',
    voice_bundle_id: '',
    ai_provider_id: ''
  })

  const { data: agents = [], isLoading: loading } = useQuery({
    queryKey: ['agents'],
    queryFn: () => apiClient.listAgents(),
  })

  const { data: voiceBundles = [] } = useQuery({
    queryKey: ['voicebundles'],
    queryFn: () => apiClient.listVoiceBundles(),
  })

  const { data: aiProviders = [] } = useQuery({
    queryKey: ['aiproviders'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const resetForm = () => {
    setFormData({
      name: '',
      phone_number: '',
      language: 'en',
      description: '',
      call_type: 'outbound',
      call_medium: 'phone_call',
      voice_config_type: 'voice_bundle',
      voice_bundle_id: '',
      ai_provider_id: ''
    })
  }

  const openEditPage = (agent: Agent) => {
    navigate(`/agents/${agent.agent_id || agent.id}`)
  }

  const handleSelectAgent = (agentId: string, checked: boolean) => {
    const newSelected = new Set(selectedAgents)
    if (checked) {
      newSelected.add(agentId)
    } else {
      newSelected.delete(agentId)
    }
    setSelectedAgents(newSelected)
  }

  const handleSelectAll = () => {
    if (selectedAgents.size === agents.length && agents.length > 0) {
      setSelectedAgents(new Set())
    } else {
      setSelectedAgents(new Set(agents.map((a: Agent) => a.id)))
    }
  }

  const openCreateModal = () => {
    resetForm()
    setSelectedAgent(null)
    setShowCreateModal(true)
  }

  const closeModals = () => {
    setShowCreateModal(false)
    setShowDeleteModal(false)
    setSelectedAgent(null)
    resetForm()
  }

  const createMutation = useMutation({
    mutationFn: (data: typeof formData) => apiClient.createAgent({
      name: data.name,
      phone_number: data.call_medium === 'phone_call' ? data.phone_number : undefined,
      language: data.language,
      description: data.description || null,
      call_type: data.call_type,
      call_medium: data.call_medium,
      voice_bundle_id: data.voice_config_type === 'voice_bundle' ? data.voice_bundle_id || undefined : undefined,
      ai_provider_id: data.voice_config_type === 'ai_provider' ? data.ai_provider_id || undefined : undefined
    } as any),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      closeModals()
      showToast('Agent created successfully!', 'success')
    },
    onError: (error: any) => {
      console.error('Error creating agent:', error)
      showToast(`Failed to create agent: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })


  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteAgent(id),
    onSuccess: (_, deletedId) => {
      // Clear global selection if the deleted agent was selected
      if (globalSelectedAgent?.id === deletedId) {
        setGlobalSelectedAgent(null)
      }
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      setShowDeleteModal(false)
      setSelectedAgent(null)
      setBlockingConversations([])
      setShowConversationsList(false)
      showToast('Agent deleted successfully!', 'success')
    },
    onError: async (error: any) => {
      console.error('Error deleting agent:', error)
      const errorMessage = error.response?.data?.detail || error.message || 'Failed to delete agent. Please try again.'
      
      // If error mentions test conversations, fetch them
      if (errorMessage.includes('test conversation') && selectedAgent) {
        try {
          const conversations = await apiClient.listTestAgentConversations()
          const blocking = conversations.filter((conv: TestAgentConversation) => conv.agent_id === selectedAgent.id)
          setBlockingConversations(blocking)
          setShowConversationsList(true)
        } catch (err) {
          console.error('Error fetching conversations:', err)
        }
      }
      
      showToast(errorMessage, 'error')
    },
  })

  // Delete conversation mutation
  const deleteConversationMutation = useMutation({
    mutationFn: (conversationId: string) => apiClient.deleteTestAgentConversation(conversationId),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['test-agent-conversations'] })
      // Refresh the blocking conversations list
      if (selectedAgent) {
        try {
          const conversations = await apiClient.listTestAgentConversations()
          const blocking = conversations.filter((conv: TestAgentConversation) => conv.agent_id === selectedAgent.id)
          setBlockingConversations(blocking)
          if (blocking.length === 0) {
            setShowConversationsList(false)
            showToast('All blocking conversations deleted. You can now delete the agent.', 'success')
          } else {
            showToast('Conversation deleted successfully!', 'success')
          }
        } catch (err) {
          showToast('Conversation deleted successfully!', 'success')
        }
      }
    },
    onError: (error: any) => {
      showToast(`Failed to delete conversation: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const createAgent = async (e: React.FormEvent) => {
    e.preventDefault()
    createMutation.mutate(formData)
  }

  const handleDelete = async (agent: Agent, event?: React.MouseEvent) => {
    if (event) {
      event.stopPropagation()
    }
    setSelectedAgent(agent)
    setShowDeleteModal(true)
    setShowConversationsList(false)
    setBlockingConversations([])
    
    // Pre-fetch conversations to check if there are any
    try {
      const conversations = await apiClient.listTestAgentConversations()
      const blocking = conversations.filter((conv: TestAgentConversation) => conv.agent_id === agent.id)
      if (blocking.length > 0) {
        setBlockingConversations(blocking)
      }
    } catch (err) {
      console.error('Error fetching conversations:', err)
    }
  }

  const confirmDelete = async () => {
    if (!selectedAgent) return
    deleteMutation.mutate(selectedAgent.id)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Loading agents...</div>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Test Agents</h1>
          <p className="text-gray-600 mt-1">Manage your voice AI test agents</p>
        </div>
        <Button variant="primary" onClick={openCreateModal} leftIcon={<Plus className="w-4 h-4" />}>
          Create Agent
        </Button>
      </div>

      {agents.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <Phone className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No agents yet</h3>
          <p className="text-gray-500 mb-4">Create your first test agent to get started</p>
          <Button variant="ghost" onClick={openCreateModal}>
            Create your first agent →
          </Button>
        </div>
      ) : (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    <input
                      type="checkbox"
                      checked={selectedAgents.size === agents.length && agents.length > 0}
                      onChange={handleSelectAll}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    ID
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Name
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Call Medium
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Phone Number
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Language
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Type
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {agents.map((agent: Agent) => (
                  <tr key={agent.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selectedAgents.has(agent.id)}
                        onChange={(e) => {
                          e.stopPropagation()
                          handleSelectAgent(agent.id, e.target.checked)
                        }}
                        className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                      />
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {agent.agent_id ? (
                        <span 
                          className="font-mono font-semibold text-sm text-blue-600 hover:text-blue-800 hover:underline cursor-pointer"
                          onClick={() => navigate(`/agents/${agent.agent_id || agent.id}`)}
                        >
                          {agent.agent_id}
                        </span>
                      ) : (
                        <span className="text-sm text-gray-400">-</span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <span className="text-sm font-medium text-gray-900">{agent.name}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-gray-500 capitalize">
                          {agent.call_medium === 'phone_call' ? 'Phone Call' : 'Web Call'}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {agent.call_medium === 'web_call' ? (
                        <span className="text-sm text-gray-500 italic">Not applicable</span>
                      ) : agent.phone_number ? (
                        <div className="flex items-center gap-2 text-sm text-gray-500">
                          <Phone className="w-4 h-4" />
                          {agent.phone_number}
                        </div>
                      ) : (
                        <span className="text-sm text-gray-400">-</span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      <span className="font-medium">{agent.language.toUpperCase()}</span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      <span className="font-medium capitalize">{agent.call_type}</span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <div className="flex items-center gap-3">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => openEditPage(agent)}
                          leftIcon={<Edit2 className="h-4 w-4" />}
                          title="Edit"
                        >
                          Edit
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => handleDelete(agent, e)}
                          leftIcon={<Trash2 className="h-4 w-4" />}
                          title="Delete"
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
          <div className="px-6 py-3 bg-gray-50 border-t border-gray-200">
            <p className="text-sm text-gray-600">
              Showing {agents.length} agent{agents.length !== 1 ? 's' : ''}
            </p>
          </div>
        </div>
      )}

      {/* Create Agent Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={closeModals}>
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold text-gray-900">Create Test Agent</h2>
              <button
                onClick={closeModals}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={createAgent} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Name *
                </label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  placeholder="Customer Support Bot"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Call Medium *
                </label>
                <div className="flex items-center gap-4">
                  <span className={`text-sm ${formData.call_medium === 'phone_call' ? 'text-gray-500' : 'text-gray-700'}`}>
                    Web Call
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      const newMedium = formData.call_medium === 'phone_call' ? 'web_call' : 'phone_call'
                      setFormData({ 
                        ...formData, 
                        call_medium: newMedium,
                        phone_number: newMedium === 'web_call' ? '' : formData.phone_number
                      })
                    }}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 ${
                      formData.call_medium === 'phone_call' ? 'bg-primary-600' : 'bg-gray-200'
                    }`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        formData.call_medium === 'phone_call' ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                  <span className={`text-sm ${formData.call_medium === 'phone_call' ? 'text-gray-700' : 'text-gray-500'}`}>
                    Phone Call
                  </span>
                </div>
              </div>

              {formData.call_medium === 'phone_call' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Phone Number *
                  </label>
                  <input
                    type="text"
                    required={formData.call_medium === 'phone_call'}
                    value={formData.phone_number}
                    onChange={(e) => setFormData({ ...formData, phone_number: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    placeholder="+1234567890"
                  />
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Language
                </label>
                <select
                  value={formData.language}
                  onChange={(e) => setFormData({ ...formData, language: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                >
                  <option value="en">English</option>
                  <option value="es">Spanish</option>
                  <option value="fr">French</option>
                  <option value="de">German</option>
                  <option value="zh">Chinese</option>
                  <option value="hi">Hindi</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Call Type
                </label>
                <select
                  value={formData.call_type}
                  onChange={(e) => setFormData({ ...formData, call_type: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                >
                  <option value="outbound">Outbound</option>
                  <option value="inbound">Inbound</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Description
                </label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  rows={3}
                  placeholder="Optional description"
                />
              </div>

              {/* Voice Configuration */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Voice Configuration *
                </label>
                <div className="space-y-3">
                  <div className="flex gap-4">
                    <label className="flex items-center">
                      <input
                        type="radio"
                        name="voice_config_type"
                        value="voice_bundle"
                        checked={formData.voice_config_type === 'voice_bundle'}
                        onChange={() => setFormData({
                          ...formData,
                          voice_config_type: 'voice_bundle',
                          ai_provider_id: ''
                        })}
                        className="mr-2"
                      />
                      <span className="text-sm text-gray-700">Voice Bundle</span>
                    </label>
                    <label className="flex items-center">
                      <input
                        type="radio"
                        name="voice_config_type"
                        value="ai_provider"
                        checked={formData.voice_config_type === 'ai_provider'}
                        onChange={() => setFormData({
                          ...formData,
                          voice_config_type: 'ai_provider',
                          voice_bundle_id: ''
                        })}
                        className="mr-2"
                      />
                      <span className="text-sm text-gray-700">AI Provider</span>
                    </label>
                  </div>
                  
                  {formData.voice_config_type === 'voice_bundle' ? (
                    <div>
                      <select
                        value={formData.voice_bundle_id}
                        onChange={(e) => setFormData({ ...formData, voice_bundle_id: e.target.value })}
                        required
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      >
                        <option value="">Select a Voice Bundle</option>
                        {voiceBundles.filter((vb: any) => vb.is_active).map((vb: any) => (
                          <option key={vb.id} value={vb.id}>
                            {vb.name}
                          </option>
                        ))}
                      </select>
                      {voiceBundles.filter((vb: any) => vb.is_active).length === 0 && (
                        <p className="mt-1 text-xs text-gray-500">
                          No active voice bundles available. Create one in VoiceBundle section.
                        </p>
                      )}
                    </div>
                  ) : (
                    <div>
                      <select
                        value={formData.ai_provider_id}
                        onChange={(e) => setFormData({ ...formData, ai_provider_id: e.target.value })}
                        required
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      >
                        <option value="">Select an AI Provider</option>
                        {aiProviders.filter((ap: any) => ap.is_active).map((ap: any) => (
                          <option key={ap.id} value={ap.id}>
                            {ap.name} ({ap.provider})
                          </option>
                        ))}
                      </select>
                      {aiProviders.filter((ap: any) => ap.is_active).length === 0 && (
                        <p className="mt-1 text-xs text-gray-500">
                          No active AI providers available. Create one in AI Providers section.
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </div>

              <div className="flex gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={closeModals}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  className="flex-1"
                >
                  Create Agent
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && selectedAgent && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => {
          setShowDeleteModal(false)
          setSelectedAgent(null)
          setBlockingConversations([])
          setShowConversationsList(false)
        }}>
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Delete Agent</h3>
              <button
                onClick={() => {
                  setShowDeleteModal(false)
                  setSelectedAgent(null)
                  setBlockingConversations([])
                  setShowConversationsList(false)
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6">
              {blockingConversations.length > 0 && (
                <div className="mb-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="h-5 w-5 text-yellow-600 flex-shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <p className="text-sm font-medium text-yellow-800 mb-2">
                        Cannot delete agent - {blockingConversations.length} test conversation{blockingConversations.length !== 1 ? 's' : ''} found
                      </p>
                      <p className="text-xs text-yellow-700 mb-3">
                        This agent is being used by test conversations. Please delete them first before deleting the agent.
                      </p>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setShowConversationsList(!showConversationsList)}
                        className="text-xs"
                      >
                        {showConversationsList ? 'Hide' : 'Show'} Conversations ({blockingConversations.length})
                      </Button>
                    </div>
                  </div>
                </div>
              )}

              {showConversationsList && blockingConversations.length > 0 && (
                <div className="mb-6 border border-gray-200 rounded-lg overflow-hidden">
                  <div className="bg-gray-50 px-4 py-2 border-b border-gray-200">
                    <h4 className="text-sm font-medium text-gray-900">Test Conversations</h4>
                  </div>
                  <div className="max-h-64 overflow-y-auto">
                    {blockingConversations.map((conv) => (
                      <div key={conv.id} className="px-4 py-3 border-b border-gray-100 last:border-b-0 flex items-center justify-between">
                        <div className="flex-1">
                          <p className="text-sm text-gray-900">
                            Conversation {conv.id.substring(0, 8)}...
                          </p>
                          <p className="text-xs text-gray-500 mt-1">
                            Status: <span className="capitalize">{conv.status}</span>
                            {conv.started_at && (
                              <> • Started: {format(new Date(conv.started_at), 'MMM d, yyyy HH:mm')}</>
                            )}
                          </p>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            if (confirm('Are you sure you want to delete this conversation?')) {
                              deleteConversationMutation.mutate(conv.id)
                            }
                          }}
                          isLoading={deleteConversationMutation.isPending}
                          className="text-red-600 hover:text-red-700 hover:bg-red-50"
                          leftIcon={<Trash2 className="h-3 w-3" />}
                        >
                          Delete
                        </Button>
                      </div>
                    ))}
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
                    Are you sure you want to delete <span className="font-semibold text-gray-900">"{selectedAgent.name}"</span>?
                  </p>
                  <p className="text-xs text-gray-500">
                    This action cannot be undone. The agent will be permanently deleted.
                  </p>
                </div>
              </div>
              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowDeleteModal(false)
                    setSelectedAgent(null)
                    setBlockingConversations([])
                    setShowConversationsList(false)
                  }}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  onClick={confirmDelete}
                  isLoading={deleteMutation.isPending}
                  disabled={blockingConversations.length > 0}
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
      <ToastContainer />
    </div>
  )
}
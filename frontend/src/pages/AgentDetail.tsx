import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Trash2, X, AlertCircle, Edit2, Save } from 'lucide-react'
import { apiClient } from '../lib/api'
import { format } from 'date-fns'
import Button from '../components/Button'
import { useToast } from '../hooks/useToast'
import { TestAgentConversation } from '../types/api'

export default function AgentDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [isEditMode, setIsEditMode] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [blockingConversations, setBlockingConversations] = useState<TestAgentConversation[]>([])
  const [showConversationsList, setShowConversationsList] = useState(false)
  const [formData, setFormData] = useState({
    name: '',
    phone_number: '',
    language: 'en',
    description: '',
    call_type: 'outbound',
    call_medium: 'phone_call' as 'phone_call' | 'web_call',
    voice_bundle_id: '',
    voice_ai_integration_id: '',
    voice_ai_agent_id: ''
  })

  const { data: agent, isLoading } = useQuery({
    queryKey: ['agent', id],
    queryFn: () => apiClient.getAgent(id!),
    enabled: !!id,
  })

  const { data: voiceBundles = [] } = useQuery({
    queryKey: ['voicebundles'],
    queryFn: () => apiClient.listVoiceBundles(),
  })

  const { data: integrations = [] } = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
  })

  // Populate form when agent data is loaded
  useEffect(() => {
    if (agent) {
      setFormData({
        name: agent.name,
        phone_number: agent.phone_number || '',
        language: agent.language,
        description: agent.description || '',
        call_type: agent.call_type,
        call_medium: agent.call_medium || 'phone_call',
        voice_bundle_id: agent.voice_bundle_id || '',
        voice_ai_integration_id: agent.voice_ai_integration_id || '',
        voice_ai_agent_id: agent.voice_ai_agent_id || ''
      })
    }
  }, [agent])

  const updateMutation = useMutation({
    mutationFn: (data: typeof formData) => {
      // Build the request payload - only include fields that have values
      const payload: any = {
        name: data.name,
        language: data.language,
        call_type: data.call_type,
        call_medium: data.call_medium,
      }
      
      // Add description if provided
      if (data.description && data.description.trim() !== '') {
        payload.description = data.description.trim()
      } else {
        payload.description = null
      }
      
      // Handle phone_number based on call_medium
      if (data.call_medium === 'phone_call') {
        if (data.phone_number && data.phone_number.trim() !== '') {
          payload.phone_number = data.phone_number.trim()
        } else {
          payload.phone_number = null
        }
      } else {
        // For web_call, set phone_number to null
        payload.phone_number = null
      }
      
      // Add voice_bundle_id if provided (Test Voice AI Agent section)
      // Only send if it's a non-empty string, otherwise send null to clear it
      const voiceBundleId = data.voice_bundle_id?.trim()
      payload.voice_bundle_id = voiceBundleId && voiceBundleId !== '' ? voiceBundleId : null
      
      // Add voice_ai_integration_id and voice_ai_agent_id if provided (Voice AI Agent section)
      const integrationId = data.voice_ai_integration_id?.trim()
      payload.voice_ai_integration_id = integrationId && integrationId !== '' ? integrationId : null
      
      const agentId = data.voice_ai_agent_id?.trim()
      payload.voice_ai_agent_id = agentId && agentId !== '' ? agentId : null
      
      return apiClient.updateAgent(id!, payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent', id] })
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      setIsEditMode(false)
      showToast('Agent updated successfully!', 'success')
    },
    onError: (error: any) => {
      console.error('Error updating agent:', error)
      showToast(`Failed to update agent: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => apiClient.deleteAgent(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      navigate('/agents')
      showToast('Agent deleted successfully!', 'success')
    },
    onError: async (error: any) => {
      console.error('Error deleting agent:', error)
      const errorMessage = error.response?.data?.detail || error.message || 'Failed to delete agent. Please try again.'
      
      // If error mentions test conversations, fetch them
      if (errorMessage.includes('test conversation') && agent) {
        try {
          const conversations = await apiClient.listTestAgentConversations()
          const blocking = conversations.filter((conv: TestAgentConversation) => conv.agent_id === agent.id)
          setBlockingConversations(blocking)
          setShowConversationsList(true)
        } catch (err) {
          console.error('Error fetching conversations:', err)
        }
      }
      
      showToast(errorMessage, 'error')
    },
  })

  const deleteConversationMutation = useMutation({
    mutationFn: (conversationId: string) => apiClient.deleteTestAgentConversation(conversationId),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ['test-agent-conversations'] })
      if (agent) {
        try {
          const conversations = await apiClient.listTestAgentConversations()
          const blocking = conversations.filter((conv: TestAgentConversation) => conv.agent_id === agent.id)
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

  const handleDelete = async () => {
    if (!agent) return
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
    deleteMutation.mutate()
  }

  const updateAgent = async (e: React.FormEvent) => {
    e.preventDefault()
    
    // Validate that at least one voice configuration is selected
    const hasVoiceBundle = formData.voice_bundle_id && formData.voice_bundle_id.trim() !== ''
    const hasVoiceAIIntegration = formData.voice_ai_integration_id && formData.voice_ai_integration_id.trim() !== '' && 
                                  formData.voice_ai_agent_id && formData.voice_ai_agent_id.trim() !== ''
    
    if (!hasVoiceBundle && !hasVoiceAIIntegration) {
      showToast('Please configure at least one: Voice Bundle (Test Voice AI Agents) or Voice AI Integration (Provider + Agent ID)', 'error')
      return
    }
    
    // Validate Voice AI Integration fields
    if (formData.voice_ai_integration_id && !formData.voice_ai_agent_id) {
      showToast('Agent ID is required when Integration Provider is selected', 'error')
      return
    }
    
    if (formData.voice_ai_agent_id && !formData.voice_ai_integration_id) {
      showToast('Integration Provider is required when Agent ID is provided', 'error')
      return
    }
    
    updateMutation.mutate(formData)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Loading agent...</div>
      </div>
    )
  }

  if (!agent) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">Agent not found</p>
        <Button onClick={() => navigate('/agents')} variant="outline" className="mt-4">
          Back to Agents
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button
            onClick={() => navigate('/agents')}
            variant="outline"
          >
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back to Agents
          </Button>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{isEditMode ? 'Edit Agent' : 'Agent Details'}</h1>
            {agent.agent_id && (
              <p className="text-sm text-gray-500 mt-1">
                Agent ID: <span className="font-mono font-semibold text-blue-600">{agent.agent_id}</span>
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {!isEditMode ? (
            <Button
              onClick={() => setIsEditMode(true)}
              variant="primary"
              leftIcon={<Edit2 className="w-4 h-4" />}
            >
              Edit
            </Button>
          ) : (
            <>
              <Button
                onClick={() => {
                  // Reset form data to original agent data
                  if (agent) {
                    setFormData({
                      name: agent.name,
                      phone_number: agent.phone_number || '',
                      language: agent.language,
                      description: agent.description || '',
                      call_type: agent.call_type,
                      call_medium: agent.call_medium || 'phone_call',
                      voice_bundle_id: agent.voice_bundle_id || '',
                      voice_ai_integration_id: agent.voice_ai_integration_id || '',
                      voice_ai_agent_id: agent.voice_ai_agent_id || ''
                    })
                  }
                  setIsEditMode(false)
                }}
                variant="outline"
              >
                Cancel
              </Button>
              <Button
                onClick={updateAgent}
                variant="primary"
                leftIcon={<Save className="w-4 h-4" />}
                isLoading={updateMutation.isPending}
              >
                Save Changes
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Agent Info Section */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="grid grid-cols-2 gap-4 text-sm mb-6 pb-6 border-b border-gray-200">
          <div>
            <span className="text-gray-500">Created:</span>
            <p className="text-gray-900 font-medium">
              {format(new Date(agent.created_at), 'PPpp')}
            </p>
          </div>
          <div>
            <span className="text-gray-500">Last Updated:</span>
            <p className="text-gray-900 font-medium">
              {format(new Date(agent.updated_at), 'PPpp')}
            </p>
          </div>
        </div>

        <form onSubmit={updateAgent} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Name *
            </label>
            <input
              type="text"
              required
              disabled={!isEditMode}
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className={`w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent ${
                !isEditMode ? 'bg-gray-50 text-gray-700 cursor-not-allowed' : ''
              }`}
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
                disabled={!isEditMode}
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
                } ${!isEditMode ? 'opacity-50 cursor-not-allowed' : ''}`}
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
                disabled={!isEditMode}
                value={formData.phone_number}
                onChange={(e) => setFormData({ ...formData, phone_number: e.target.value })}
                className={`w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent ${
                  !isEditMode ? 'bg-gray-50 text-gray-700 cursor-not-allowed' : ''
                }`}
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
              disabled={!isEditMode}
              onChange={(e) => setFormData({ ...formData, language: e.target.value })}
              className={`w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent ${
                !isEditMode ? 'bg-gray-50 text-gray-700 cursor-not-allowed' : ''
              }`}
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
              disabled={!isEditMode}
              onChange={(e) => setFormData({ ...formData, call_type: e.target.value })}
              className={`w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent ${
                !isEditMode ? 'bg-gray-50 text-gray-700 cursor-not-allowed' : ''
              }`}
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
              disabled={!isEditMode}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className={`w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent ${
                !isEditMode ? 'bg-gray-50 text-gray-700 cursor-not-allowed' : ''
              }`}
              rows={3}
              placeholder="Optional description"
            />
          </div>

          {/* Voice Configuration - Two Sections */}
          <div className="space-y-6">
            {/* Section 1: Test Voice AI Agents */}
            <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
              <h3 className="text-lg font-semibold text-gray-900 mb-3">1. Test Voice AI Agents</h3>
              <p className="text-sm text-gray-600 mb-4">Configure agents using Voice Bundles for testing purposes</p>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Voice Bundle *
                </label>
                <select
                  value={formData.voice_bundle_id}
                  disabled={!isEditMode}
                  onChange={(e) => {
                    setFormData({
                      ...formData,
                      voice_bundle_id: e.target.value
                    })
                  }}
                  className={`w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent ${
                    !isEditMode ? 'bg-gray-50 text-gray-700 cursor-not-allowed' : 'bg-white'
                  }`}
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
            </div>

            {/* Section 2: Voice AI Agent */}
            <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
              <h3 className="text-lg font-semibold text-gray-900 mb-3">2. Voice AI Agent</h3>
              <p className="text-sm text-gray-600 mb-4">Configure agents using external Voice AI integrations (Retell, Vapi)</p>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Integration Provider *
                  </label>
                  <select
                    value={formData.voice_ai_integration_id}
                    disabled={!isEditMode}
                    onChange={(e) => {
                      setFormData({
                        ...formData,
                        voice_ai_integration_id: e.target.value
                      })
                    }}
                    className={`w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent ${
                      !isEditMode ? 'bg-gray-50 text-gray-700 cursor-not-allowed' : 'bg-white'
                    }`}
                  >
                    <option value="">Select an Integration</option>
                    {integrations
                      .filter((integration: any) => 
                        integration.is_active && 
                        (integration.platform === 'retell' || integration.platform === 'vapi')
                      )
                      .map((integration: any) => (
                        <option key={integration.id} value={integration.id}>
                          {integration.name || integration.platform} ({integration.platform === 'retell' ? 'Retell' : 'Vapi'})
                        </option>
                      ))}
                  </select>
                  {integrations.filter((integration: any) => 
                    integration.is_active && 
                    (integration.platform === 'retell' || integration.platform === 'vapi')
                  ).length === 0 && (
                    <p className="mt-1 text-xs text-gray-500">
                      No active Retell or Vapi integrations available. Create one in Integrations section.
                    </p>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Agent ID *
                  </label>
                  <input
                    type="text"
                    value={formData.voice_ai_agent_id}
                    disabled={!isEditMode}
                    onChange={(e) => {
                      setFormData({
                        ...formData,
                        voice_ai_agent_id: e.target.value
                      })
                    }}
                    className={`w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent ${
                      !isEditMode ? 'bg-gray-50 text-gray-700 cursor-not-allowed' : 'bg-white'
                    }`}
                    placeholder="Enter agent ID from Retell/Vapi"
                  />
                  <p className="mt-1 text-xs text-gray-500">
                    Enter the agent ID you received from your Retell or Vapi provider
                  </p>
                </div>
              </div>
            </div>
          </div>

          {isEditMode && (
            <div className="flex gap-3 pt-4 border-t border-gray-200">
              <Button
                type="button"
                variant="outline"
                onClick={handleDelete}
                leftIcon={<Trash2 className="w-4 h-4" />}
                className="border-red-300 text-red-700 hover:bg-red-50 hover:border-red-400"
              >
                Delete
              </Button>
            </div>
          )}
        </form>
      </div>

      {/* Delete Confirmation Modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => {
          setShowDeleteModal(false)
          setBlockingConversations([])
          setShowConversationsList(false)
        }}>
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Delete Agent</h3>
              <button
                onClick={() => {
                  setShowDeleteModal(false)
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
                    Are you sure you want to delete <span className="font-semibold text-gray-900">"{agent.name}"</span>?
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


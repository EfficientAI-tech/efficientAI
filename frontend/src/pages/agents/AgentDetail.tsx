import { useState, useEffect, type ReactNode } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { createPortal } from 'react-dom'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'
import { TestAgentConversation, VoiceBundle, Integration } from '../../types/api'
import { AgentDetailHeader, AgentInfoView, DeleteAgentModal } from './components'
import AgentEditForm from './components/AgentEditForm'
import { Save, X } from 'lucide-react'

interface FormData {
  name: string
  phone_number: string
  language: string
  description: string
  call_type: string
  call_medium: 'phone_call' | 'web_call'
  voice_bundle_id: string
  voice_ai_integration_id: string
  voice_ai_agent_id: string
}

export default function AgentDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  
  const [isEditMode, setIsEditMode] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [blockingConversations, setBlockingConversations] = useState<TestAgentConversation[]>([])
  const [showSavePromptModal, setShowSavePromptModal] = useState(false)
  const [savePromptName, setSavePromptName] = useState('')
  const [savePromptDescription, setSavePromptDescription] = useState('')
  const [savePromptTags, setSavePromptTags] = useState('agents, system-prompt')
  const [savePromptContent, setSavePromptContent] = useState('')
  const [formData, setFormData] = useState<FormData>({
    name: '',
    phone_number: '',
    language: 'en',
    description: '',
    call_type: 'outbound',
    call_medium: 'phone_call',
    voice_bundle_id: '',
    voice_ai_integration_id: '',
    voice_ai_agent_id: ''
  })

  const { data: agent, isLoading } = useQuery({
    queryKey: ['agent', id],
    queryFn: () => apiClient.getAgent(id!),
    enabled: !!id,
  })

  const { data: voiceBundles = [] } = useQuery<VoiceBundle[]>({
    queryKey: ['voicebundles'],
    queryFn: () => apiClient.listVoiceBundles(),
  })

  const { data: integrations = [] } = useQuery<Integration[]>({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
  })

  const renderModal = (content: ReactNode) => {
    if (typeof document === 'undefined') return null
    return createPortal(content, document.body)
  }

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
    mutationFn: (data: FormData) => {
      const payload: any = {
        name: data.name,
        language: data.language,
        call_type: data.call_type,
        call_medium: data.call_medium,
      }

      payload.description = data.description?.trim() || null

      if (data.call_medium === 'phone_call') {
        payload.phone_number = data.phone_number?.trim() || null
      } else {
        payload.phone_number = null
      }

      const voiceBundleId = data.voice_bundle_id?.trim()
      payload.voice_bundle_id = voiceBundleId || null

      const integrationId = data.voice_ai_integration_id?.trim()
      payload.voice_ai_integration_id = integrationId || null

      const agentId = data.voice_ai_agent_id?.trim()
      payload.voice_ai_agent_id = agentId || null

      return apiClient.updateAgent(id!, payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent', id] })
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      setIsEditMode(false)
      showToast('Agent updated successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to update agent: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const syncPromptMutation = useMutation({
    mutationFn: () => apiClient.syncProviderPrompt(id!),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['agent', id] })
      queryClient.invalidateQueries({ queryKey: ['agents'] })

      if (data.synced) {
        showToast('Provider prompt synced successfully!', 'success')
        return
      }

      showToast(
        'No prompt returned from provider. Verify the provider agent has a system prompt configured.',
        'error'
      )
    },
    onError: (error: any) => {
      showToast(
        `Failed to sync provider prompt: ${error.response?.data?.detail || error.message}`,
        'error'
      )
    },
  })

  const savePromptPartialMutation = useMutation({
    mutationFn: (data: { name: string; description?: string; content: string; tags?: string[] }) =>
      apiClient.createPromptPartial(data),
    onSuccess: () => {
      showToast('System prompt saved to Prompt Partials', 'success')
      setShowSavePromptModal(false)
      setSavePromptName('')
      setSavePromptDescription('')
      setSavePromptTags('agents, system-prompt')
      setSavePromptContent('')
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || 'Failed to save prompt partial', 'error')
    },
  })

  const handleDelete = async () => {
    if (!agent) return
    setShowDeleteModal(true)
    setBlockingConversations([])

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

  const handleDeleteSuccess = () => {
    setShowDeleteModal(false)
    navigate('/agents')
  }

  const handleSave = (e?: React.FormEvent) => {
    if (e) e.preventDefault()

    const hasVoiceBundle = formData.voice_bundle_id?.trim()
    const hasVoiceAIIntegration =
      formData.voice_ai_integration_id?.trim() && formData.voice_ai_agent_id?.trim()

    if (!hasVoiceBundle && !hasVoiceAIIntegration) {
      showToast(
        'Please configure at least one: Voice Bundle (Test Voice AI Agents) or Voice AI Integration (Provider + Agent ID)',
        'error'
      )
      return
    }

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

  const handleCancelEdit = () => {
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
  }

  const openSavePromptModal = (content: string, suggestedName?: string) => {
    const trimmedContent = (content || '').trim()
    if (!trimmedContent) {
      showToast('No system prompt available to save', 'error')
      return
    }

    setSavePromptContent(trimmedContent)
    setSavePromptName(suggestedName || `${agent?.name || 'Agent'} System Prompt`)
    setSavePromptDescription(`Saved from agent ${agent?.name || ''}`.trim())
    setSavePromptTags('agents, system-prompt')
    setShowSavePromptModal(true)
  }

  const handleSavePromptPartial = () => {
    if (!savePromptName.trim()) {
      showToast('Prompt name is required', 'error')
      return
    }
    if (!savePromptContent.trim()) {
      showToast('Prompt content is required', 'error')
      return
    }

    const tags = savePromptTags
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean)

    savePromptPartialMutation.mutate({
      name: savePromptName.trim(),
      description: savePromptDescription.trim() || undefined,
      content: savePromptContent.trim(),
      tags: tags.length > 0 ? tags : undefined,
    })
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
      <AgentDetailHeader
        agentId={agent.agent_id}
        isEditMode={isEditMode}
        isPending={updateMutation.isPending}
        onEditClick={() => setIsEditMode(true)}
        onCancelEdit={handleCancelEdit}
        onSave={handleSave}
      />

      <div className="bg-white rounded-lg shadow p-6">
        {!isEditMode ? (
          <AgentInfoView
            agent={agent}
            voiceBundles={voiceBundles}
            integrations={integrations}
            onSyncProviderPrompt={() => syncPromptMutation.mutate()}
            isSyncingPrompt={syncPromptMutation.isPending}
          />
        ) : (
          <AgentEditForm
            formData={formData}
            onChange={setFormData}
            onSubmit={handleSave}
            onDelete={handleDelete}
            voiceBundles={voiceBundles}
            integrations={integrations}
            showToast={showToast}
            createdAt={agent.created_at}
            updatedAt={agent.updated_at}
            onSaveSystemPrompt={() =>
              openSavePromptModal(
                formData.description || '',
                `${formData.name || agent.name} System Prompt`
              )
            }
          />
        )}
      </div>

      <DeleteAgentModal
        isOpen={showDeleteModal}
        agent={agent}
        blockingConversations={blockingConversations}
        onClose={() => {
          setShowDeleteModal(false)
          setBlockingConversations([])
        }}
        onSuccess={handleDeleteSuccess}
        showToast={showToast}
      />

      {showSavePromptModal && renderModal(
        <div className="fixed inset-0 z-[9999] bg-black/40 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-2xl rounded-xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
              <h3 className="text-lg font-semibold text-gray-900">Save System Prompt</h3>
              <button
                onClick={() => setShowSavePromptModal(false)}
                className="text-gray-400 hover:text-gray-600"
                aria-label="Close save prompt modal"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4 px-5 py-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Name</label>
                <input
                  type="text"
                  value={savePromptName}
                  onChange={(e) => setSavePromptName(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
                  placeholder="Prompt partial name"
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  Description <span className="text-gray-400">(optional)</span>
                </label>
                <input
                  type="text"
                  value={savePromptDescription}
                  onChange={(e) => setSavePromptDescription(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
                  placeholder="Brief description"
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  Tags <span className="text-gray-400">(comma-separated, optional)</span>
                </label>
                <input
                  type="text"
                  value={savePromptTags}
                  onChange={(e) => setSavePromptTags(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
                  placeholder="agents, system-prompt"
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Content</label>
                <textarea
                  value={savePromptContent}
                  onChange={(e) => setSavePromptContent(e.target.value)}
                  rows={8}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 border-t border-gray-200 px-5 py-4">
              <Button
                variant="outline"
                onClick={() => setShowSavePromptModal(false)}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleSavePromptPartial}
                isLoading={savePromptPartialMutation.isPending}
                leftIcon={<Save className="h-4 w-4" />}
              >
                Save Prompt
              </Button>
            </div>
          </div>
        </div>
      )}

      <ToastContainer />
    </div>
  )
}

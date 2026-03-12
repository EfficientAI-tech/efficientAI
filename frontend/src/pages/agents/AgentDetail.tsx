import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'
import { TestAgentConversation, VoiceBundle, Integration } from '../../types/api'
import { AgentDetailHeader, AgentInfoView, AgentEditForm, DeleteAgentModal } from './components'

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

      <ToastContainer />
    </div>
  )
}

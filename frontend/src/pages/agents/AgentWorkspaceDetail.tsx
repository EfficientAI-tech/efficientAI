import { useState, useEffect, useCallback, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { createPortal } from 'react-dom'
import { apiClient } from '../../lib/api'
import Button from '../../components/Button'
import { useAgentStore } from '../../store/agentStore'
import { useToast } from '../../hooks/useToast'
import { TestAgentConversation, VoiceBundle, Integration } from '../../types/api'
import { AgentDetailHeader, AgentInfoView, DeleteAgentModal } from './components'
import type { AgentDetailTab } from './components/AgentInfoView'
import AgentEditForm from './components/AgentEditForm'
import AgentTalkSidebar, { type AgentTalkMode } from './components/AgentTalkSidebar'
import { Save, X } from 'lucide-react'
import { extractPhoneConflictDetail } from './components/agentPhoneValidation'

const VALID_TABS: AgentDetailTab[] = ['overview', 'test_agent', 'voice_ai_agent']

function parseTabFromSearch(params: URLSearchParams): AgentDetailTab {
  const tab = params.get('tab')
  if (tab && VALID_TABS.includes(tab as AgentDetailTab)) {
    return tab as AgentDetailTab
  }
  return 'overview'
}

function normalizeCallMedium(value: string | undefined | null): 'phone_call' | 'web_call' {
  return value === 'web_call' ? 'web_call' : 'phone_call'
}

function agentToFormData(agent: NonNullable<Awaited<ReturnType<typeof apiClient.getAgent>>>): FormData {
  return {
    name: agent.name,
    phone_number: agent.phone_number || '',
    language: agent.language,
    description: agent.description || '',
    prompt_variables: agent.prompt_variables || {},
    silence_hangup_secs: agent.silence_hangup_secs ?? 15,
    call_type: agent.call_type,
    call_medium: normalizeCallMedium(agent.call_medium),
    telephony_phone_number_id: agent.telephony_phone_number_id || '',
    voice_bundle_id: agent.voice_bundle_id || '',
    voice_ai_integration_id: agent.voice_ai_integration_id || '',
    voice_ai_agent_id: agent.voice_ai_agent_id || '',
    provider_prompt: agent.provider_prompt || '',
  }
}

interface FormData {
  name: string
  phone_number: string
  language: string
  description: string
  prompt_variables: Record<string, string>
  silence_hangup_secs: number
  call_type: string
  call_medium: 'phone_call' | 'web_call'
  telephony_phone_number_id: string
  voice_bundle_id: string
  voice_ai_integration_id: string
  voice_ai_agent_id: string
  provider_prompt: string
}

interface AgentWorkspaceDetailProps {
  agentRouteId: string | undefined
  onAgentDeleted: () => void
  onEditModeChange?: (isEditMode: boolean) => void
}

export default function AgentWorkspaceDetail({
  agentRouteId,
  onAgentDeleted,
  onEditModeChange,
}: AgentWorkspaceDetailProps) {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const { selectedAgent: globalSelectedAgent, setSelectedAgent: setGlobalSelectedAgent } = useAgentStore()
  const { showToast, ToastContainer } = useToast()

  const activeTab = parseTabFromSearch(searchParams)

  const setActiveTab = useCallback(
    (tab: AgentDetailTab) => {
      const next = new URLSearchParams(searchParams)
      if (tab === 'overview') {
        next.delete('tab')
      } else {
        next.set('tab', tab)
      }
      setSearchParams(next, { replace: true })
    },
    [searchParams, setSearchParams]
  )

  const [isEditMode, setIsEditMode] = useState(false)
  const [talkSidebarOpen, setTalkSidebarOpen] = useState(false)
  const [talkMode, setTalkMode] = useState<AgentTalkMode>('test_agent')
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
    prompt_variables: {},
    silence_hangup_secs: 15,
    call_type: 'outbound',
    call_medium: 'phone_call',
    telephony_phone_number_id: '',
    voice_bundle_id: '',
    voice_ai_integration_id: '',
    voice_ai_agent_id: '',
    provider_prompt: '',
  })

  useEffect(() => {
    setIsEditMode(false)
    setTalkSidebarOpen(false)
    onEditModeChange?.(false)
  }, [agentRouteId, onEditModeChange])

  useEffect(() => {
    onEditModeChange?.(isEditMode)
  }, [isEditMode, onEditModeChange])

  const { data: agent, isLoading } = useQuery({
    queryKey: ['agent', agentRouteId],
    queryFn: () => apiClient.getAgent(agentRouteId!),
    enabled: Boolean(agentRouteId),
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
    if (agent && !isEditMode) {
      setFormData(agentToFormData(agent))
    }
  }, [agent, isEditMode])

  const updateMutation = useMutation({
    mutationFn: (data: FormData) => {
      const payload: Record<string, unknown> = {
        name: data.name,
        language: data.language,
        call_type: data.call_type,
        call_medium: data.call_medium,
        description: data.description?.trim() || null,
        prompt_variables: data.prompt_variables || {},
        silence_hangup_secs: data.silence_hangup_secs ?? 15,
      }

      if (data.call_medium === 'phone_call') {
        payload.phone_number = data.phone_number?.trim() || null
        payload.telephony_phone_number_id = data.telephony_phone_number_id?.trim() || null
      } else {
        payload.phone_number = null
        payload.telephony_phone_number_id = null
      }

      payload.voice_bundle_id = data.voice_bundle_id?.trim() || null
      payload.voice_ai_integration_id = data.voice_ai_integration_id?.trim() || null
      payload.voice_ai_agent_id = data.voice_ai_agent_id?.trim() || null
      payload.provider_prompt = data.provider_prompt?.trim() || null

      return apiClient.updateAgent(agentRouteId!, payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent', agentRouteId] })
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      queryClient.invalidateQueries({ queryKey: ['telephony-numbers'] })
      setIsEditMode(false)
      showToast('Agent updated successfully!', 'success')
    },
    onError: (error: { response?: { data?: { detail?: unknown } }; message?: string }) => {
      const conflictMessage = extractPhoneConflictDetail(error.response?.data?.detail)
      showToast(
        conflictMessage || `Failed to update agent: ${error.message || 'Unknown error'}`,
        'error',
      )
    },
  })

  const syncPromptMutation = useMutation({
    mutationFn: () => apiClient.syncProviderPrompt(agentRouteId!),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['agent', agentRouteId] })
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
    onError: (error: { response?: { data?: { detail?: string } }; message?: string }) => {
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
    onError: (error: { response?: { data?: { detail?: string } } }) => {
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
    onAgentDeleted()
  }

  const handleSave = (e?: React.FormEvent) => {
    if (e) e.preventDefault()

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

  const handleEditClick = () => {
    if (agent) {
      setFormData(agentToFormData(agent))
    }
    setIsEditMode(true)
  }

  const handleCancelEdit = () => {
    if (agent) {
      setFormData(agentToFormData(agent))
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

  const openTalkSidebar = (mode: AgentTalkMode) => {
    setTalkMode(mode)
    setTalkSidebarOpen(true)
  }

  const handleEditVoiceBundle = (bundleId: string) => {
    const returnPath = agentRouteId ? `/agents/${agentRouteId}` : '/agents'
    const tabQuery = activeTab !== 'overview' ? `?tab=${activeTab}` : ''
    navigate(`/voicebundles?edit=${bundleId}&return=${encodeURIComponent(`${returnPath}${tabQuery}`)}`)
  }

  if (!agentRouteId) {
    return (
      <div className="flex-1 rounded-xl border border-dashed border-gray-200 bg-gray-50/50 flex items-center justify-center min-h-[20rem] p-8">
        <p className="text-sm text-gray-500 text-center">Select an agent from the list to view details.</p>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center min-h-[20rem] rounded-xl border border-gray-200 bg-white">
        <div className="text-gray-500">Loading agent…</div>
      </div>
    )
  }

  if (!agent) {
    return (
      <div className="flex-1 rounded-xl border border-gray-200 bg-white flex flex-col items-center justify-center min-h-[20rem] p-8">
        <p className="text-gray-500">Agent not found</p>
        <Button onClick={() => navigate('/agents')} variant="outline" className="mt-4">
          Clear selection
        </Button>
      </div>
    )
  }

  return (
    <div
      className={`flex-1 min-w-0 transition-[margin] ${talkSidebarOpen ? 'lg:mr-[28rem]' : ''}`}
    >
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
        <div className="border-b border-gray-200 px-4 pt-3 pb-0">
          <div className="flex flex-wrap items-start justify-between gap-2 mb-2">
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold text-gray-900 truncate">
                {isEditMode ? 'Editing' : agent.name}
              </h2>
              {agent.agent_id && (
                <p className="text-xs text-gray-500 mt-0.5">
                  Agent ID:{' '}
                  <span className="font-mono font-semibold text-primary-600">{agent.agent_id}</span>
                </p>
              )}
            </div>
            <AgentDetailHeader
              hideTitle
              agentName={agent.name}
              agentId={agent.agent_id}
              isEditMode={isEditMode}
              isPending={updateMutation.isPending}
              onEditClick={handleEditClick}
              onCancelEdit={handleCancelEdit}
              onSave={handleSave}
            />
          </div>
          <nav className="-mb-px flex space-x-6 overflow-x-auto" aria-label="Agent detail tabs">
            {(
              [
                { id: 'overview' as const, label: 'Overview' },
                { id: 'test_agent' as const, label: 'Test Agent' },
                { id: 'voice_ai_agent' as const, label: 'Voice AI Agent' },
              ] as const
            ).map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`whitespace-nowrap py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
                  activeTab === tab.id
                    ? 'border-primary-500 text-primary-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        <div className="p-4">
          {!isEditMode ? (
            <AgentInfoView
              agent={agent}
              voiceBundles={voiceBundles}
              integrations={integrations}
              activeTab={activeTab}
              onSyncProviderPrompt={() => syncPromptMutation.mutate()}
              isSyncingPrompt={syncPromptMutation.isPending}
              onTalk={openTalkSidebar}
              onEditVoiceBundle={handleEditVoiceBundle}
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
              activeTab={activeTab}
              onSaveSystemPrompt={() =>
                openSavePromptModal(
                  formData.description || '',
                  `${formData.name || agent.name} System Prompt`
                )
              }
              agentId={agent.id}
            />
          )}
        </div>
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
        onGlobalAgentDeleted={(deletedId) => {
          if (globalSelectedAgent?.id === deletedId) {
            setGlobalSelectedAgent(null)
          }
        }}
      />

      {showSavePromptModal &&
        renderModal(
          <div className="fixed inset-0 z-[9999] bg-gray-500 bg-opacity-75 flex items-center justify-center p-4">
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
                <Button variant="outline" onClick={() => setShowSavePromptModal(false)}>
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

      <AgentTalkSidebar
        isOpen={talkSidebarOpen}
        mode={talkMode}
        agent={agent}
        integrations={integrations}
        onClose={() => setTalkSidebarOpen(false)}
        showToast={showToast}
      />

      <ToastContainer />
    </div>
  )
}

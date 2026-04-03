import { useState, useEffect } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { X, Sparkles, Loader2, Bot, Eye, Code, FileText, PhoneOutgoing, PhoneIncoming } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import Button from '../../../components/Button'
import { apiClient } from '../../../lib/api'
import { AIProvider, VoiceBundle, Integration, ModelProvider } from '../../../types/api'
import { getProviderLabel } from '../../../config/providers'

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

interface CreateAgentModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
  showToast: (message: string, type: 'success' | 'error') => void
}

interface PromptPartial {
  id: string
  name: string
  description?: string | null
}

export default function CreateAgentModal({
  isOpen,
  onClose,
  onSuccess,
  showToast,
}: CreateAgentModalProps) {
  const [descriptionEditorMode, setDescriptionEditorMode] = useState<'write' | 'preview'>('write')
  const [showAIGeneratePanel, setShowAIGeneratePanel] = useState(false)
  const [aiDescription, setAiDescription] = useState('')
  const [aiTone, setAiTone] = useState('professional')
  const [aiFormat, setAiFormat] = useState('structured')
  const [aiProvider, setAiProvider] = useState('')
  const [aiModel, setAiModel] = useState('')
  const [showUseSavedModal, setShowUseSavedModal] = useState(false)
  const [savedPromptSearch, setSavedPromptSearch] = useState('')
  const [selectedSavedPromptId, setSelectedSavedPromptId] = useState('')
  
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

  const { data: voiceBundles = [] } = useQuery<VoiceBundle[]>({
    queryKey: ['voicebundles'],
    queryFn: () => apiClient.listVoiceBundles(),
  })

  const { data: integrations = [] } = useQuery<Integration[]>({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
  })

  const { data: aiProviders = [] } = useQuery<AIProvider[]>({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const { data: modelOptions } = useQuery({
    queryKey: ['model-options', aiProvider],
    queryFn: () => apiClient.getModelOptions(aiProvider),
    enabled: !!aiProvider,
  })
  const { data: savedPromptPartials = [], isLoading: isLoadingSavedPromptPartials } = useQuery<PromptPartial[]>({
    queryKey: ['create-agent-prompt-partials', savedPromptSearch],
    queryFn: () => apiClient.listPromptPartials(0, 100, savedPromptSearch.trim() || undefined),
    enabled: showUseSavedModal,
  })

  const llmModels = modelOptions?.llm || []

  useEffect(() => {
    if (aiProvider && llmModels.length > 0 && !llmModels.includes(aiModel)) {
      setAiModel(llmModels[0])
    }
  }, [aiProvider, llmModels, aiModel])

  const generateDescriptionMutation = useMutation({
    mutationFn: (data: { description: string; tone?: string; format_style?: string; provider?: string; model?: string }) =>
      apiClient.generateAgentDescription(data),
    onSuccess: (data) => {
      setFormData(prev => ({ ...prev, description: data.content }))
      setShowAIGeneratePanel(false)
      setAiDescription('')
      setDescriptionEditorMode('preview')
      showToast('Description generated successfully!', 'success')
    },
    onError: (err: any) => {
      showToast(err?.response?.data?.detail || 'Failed to generate description with AI', 'error')
    },
  })

  const useSavedPromptMutation = useMutation({
    mutationFn: (promptPartialId: string) => apiClient.getPromptPartial(promptPartialId),
    onSuccess: (data) => {
      const content = (data?.content || '').trim()
      if (!content) {
        showToast('Selected prompt partial has no content', 'error')
        return
      }
      setFormData((prev) => ({ ...prev, description: content }))
      setDescriptionEditorMode('preview')
      setShowUseSavedModal(false)
      setSavedPromptSearch('')
      setSelectedSavedPromptId('')
      showToast('Saved prompt applied to Test Agent Prompt', 'success')
    },
    onError: (err: any) => {
      showToast(err?.response?.data?.detail || 'Failed to load saved prompt', 'error')
    },
  })

  const createMutation = useMutation({
    mutationFn: (data: FormData) => {
      const payload: any = {
        name: data.name,
        language: data.language,
        description: data.description || null,
        call_type: data.call_type,
        call_medium: data.call_medium,
      }

      if (data.call_medium === 'phone_call' && data.phone_number) {
        payload.phone_number = data.phone_number
      }

      if (data.voice_bundle_id && data.voice_bundle_id.trim() !== '') {
        payload.voice_bundle_id = data.voice_bundle_id.trim()
      }

      if (data.voice_ai_integration_id && data.voice_ai_integration_id.trim() !== '') {
        payload.voice_ai_integration_id = data.voice_ai_integration_id.trim()
      }
      if (data.voice_ai_agent_id && data.voice_ai_agent_id.trim() !== '') {
        payload.voice_ai_agent_id = data.voice_ai_agent_id.trim()
      }

      return apiClient.createAgent(payload)
    },
    onSuccess: () => {
      onSuccess()
      resetForm()
      showToast('Agent created successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to create agent: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const resetForm = () => {
    setFormData({
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
    setDescriptionEditorMode('write')
    setShowAIGeneratePanel(false)
    setAiDescription('')
    setAiTone('professional')
    setAiFormat('structured')
    setAiProvider('')
    setAiModel('')
    setShowUseSavedModal(false)
    setSavedPromptSearch('')
    setSelectedSavedPromptId('')
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    const descriptionWords = formData.description.trim().split(/\s+/).filter(Boolean)
    if (descriptionWords.length < 10) {
      showToast('Description must be at least 10 words.', 'error')
      return
    }

    if (formData.call_medium === 'phone_call') {
      if (!formData.phone_number || formData.phone_number.trim() === '') {
        showToast('Phone number is required for phone calls.', 'error')
        return
      }
      if (!/^[\d+]+$/.test(formData.phone_number)) {
        showToast('Phone number must contain only digits and the + character.', 'error')
        return
      }
    }

    if (!formData.voice_ai_integration_id || formData.voice_ai_integration_id.trim() === '') {
      showToast('Voice AI Integration Provider is required.', 'error')
      return
    }
    if (!formData.voice_ai_agent_id || formData.voice_ai_agent_id.trim() === '') {
      showToast('Voice AI Agent ID is required.', 'error')
      return
    }

    createMutation.mutate(formData)
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-4xl max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-gray-900">Create Test Agent</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>
        
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
            <input
              type="text"
              required
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              placeholder="Customer Support Bot"
            />
          </div>

          {/* Call Medium */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Call Medium *</label>
            <div className="inline-flex rounded-lg border border-gray-300 overflow-hidden">
              {(['web_call', 'phone_call'] as const).map((medium) => (
                <button
                  key={medium}
                  type="button"
                  onClick={() => setFormData({
                    ...formData,
                    call_medium: medium,
                    phone_number: medium === 'web_call' ? '' : formData.phone_number
                  })}
                  className={`px-4 py-2 text-sm font-medium transition-colors focus:outline-none ${
                    formData.call_medium === medium
                      ? 'bg-primary-600 text-white'
                      : 'bg-white text-gray-700 hover:bg-gray-50'
                  } ${medium === 'web_call' ? 'border-r border-gray-300' : ''}`}
                >
                  {medium === 'web_call' ? 'Web Call' : 'Phone Call'}
                </button>
              ))}
            </div>
          </div>

          {/* Phone Number */}
          {formData.call_medium === 'phone_call' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Phone Number *</label>
              <input
                type="text"
                required
                value={formData.phone_number}
                onChange={(e) => setFormData({ ...formData, phone_number: e.target.value.replace(/[^\d+]/g, '') })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                placeholder="+1234567890"
              />
            </div>
          )}

          {/* Language */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Language</label>
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

          {/* Call Type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Call Type *</label>
            <div className="inline-flex rounded-lg border border-gray-300 overflow-hidden">
              {(['outbound', 'inbound'] as const).map((type) => (
                <button
                  key={type}
                  type="button"
                  onClick={() => setFormData({ ...formData, call_type: type })}
                  className={`inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium transition-colors focus:outline-none ${
                    formData.call_type === type
                      ? 'bg-primary-600 text-white'
                      : 'bg-white text-gray-700 hover:bg-gray-50'
                  } ${type === 'outbound' ? 'border-r border-gray-300' : ''}`}
                >
                  {type === 'outbound' ? <PhoneOutgoing className="h-3.5 w-3.5" /> : <PhoneIncoming className="h-3.5 w-3.5" />}
                  {type === 'outbound' ? 'Outbound' : 'Inbound'}
                </button>
              ))}
            </div>
          </div>

          {/* Description with AI Generate */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-sm font-medium text-gray-700">Test Agent Prompt *</label>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setShowAIGeneratePanel(!showAIGeneratePanel)}
                  disabled={generateDescriptionMutation.isPending}
                  className={`inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-lg border transition-colors ${
                    showAIGeneratePanel
                      ? 'bg-amber-100 text-amber-800 border-amber-300'
                      : 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100'
                  }`}
                >
                  {generateDescriptionMutation.isPending ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Sparkles className="h-3 w-3" />
                  )}
                  {generateDescriptionMutation.isPending ? 'Generating...' : 'AI Generate'}
                </button>
                <button
                  type="button"
                  onClick={() => setShowUseSavedModal(true)}
                  className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-lg border border-primary-300 bg-primary-50 text-primary-700 hover:bg-primary-100"
                >
                  <FileText className="h-3 w-3" />
                  Use Saved
                </button>
                <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
                  <button
                    type="button"
                    onClick={() => setDescriptionEditorMode('write')}
                    className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                      descriptionEditorMode === 'write'
                        ? 'bg-white text-gray-900 shadow-sm'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    <Code className="h-3 w-3" />
                    Write
                  </button>
                  <button
                    type="button"
                    onClick={() => setDescriptionEditorMode('preview')}
                    className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                      descriptionEditorMode === 'preview'
                        ? 'bg-white text-gray-900 shadow-sm'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    <Eye className="h-3 w-3" />
                    Preview
                  </button>
                </div>
              </div>
            </div>

            {/* AI Generate Panel */}
            {showAIGeneratePanel && (
              <div className="mb-2 p-3 bg-amber-50 rounded-lg border border-amber-200">
                <div className="flex items-center gap-2 mb-2">
                  <Sparkles className="h-4 w-4 text-amber-600" />
                  <span className="text-sm font-medium text-amber-900">Generate Description with AI</span>
                </div>
                <p className="text-xs text-amber-700 mb-3">
                  Describe what this agent should do and AI will generate a rich markdown description.
                </p>
                <textarea
                  value={aiDescription}
                  onChange={(e) => setAiDescription(e.target.value)}
                  placeholder="e.g., A customer support agent that handles refund requests, tracks orders, and escalates complex issues..."
                  rows={3}
                  className="w-full px-3 py-2 text-sm border border-amber-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white mb-2"
                />
                <div className="grid grid-cols-2 gap-3 mb-2">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Tone</label>
                    <select
                      value={aiTone}
                      onChange={(e) => setAiTone(e.target.value)}
                      className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
                    >
                      <option value="professional">Professional</option>
                      <option value="casual">Casual / Friendly</option>
                      <option value="technical">Technical</option>
                      <option value="concise">Concise / Direct</option>
                      <option value="detailed">Detailed / Thorough</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Format Style</label>
                    <select
                      value={aiFormat}
                      onChange={(e) => setAiFormat(e.target.value)}
                      className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
                    >
                      <option value="structured">Structured (sections & bullet points)</option>
                      <option value="narrative">Narrative (flowing text)</option>
                      <option value="template">Template (with placeholders)</option>
                      <option value="step-by-step">Step-by-step Instructions</option>
                    </select>
                  </div>
                </div>
                <div className="flex gap-3 mb-2">
                  <div className="flex-1">
                    <label className="block text-xs font-medium text-gray-600 mb-1">
                      <Bot className="w-3 h-3 inline mr-1" />
                      LLM Provider
                    </label>
                    <select
                      value={aiProvider}
                      onChange={(e) => { setAiProvider(e.target.value); setAiModel('') }}
                      className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
                    >
                      <option value="">Auto-detect (use first available)</option>
                      {aiProviders.filter((p) => p.is_active).map((p) => (
                        <option key={p.id} value={p.provider}>
                          {getProviderLabel(p.provider as ModelProvider)}
                          {p.name ? ` — ${p.name}` : ''}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex-1">
                    <label className="block text-xs font-medium text-gray-600 mb-1">Model</label>
                    <select
                      value={aiModel}
                      onChange={(e) => setAiModel(e.target.value)}
                      disabled={!aiProvider}
                      className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white disabled:bg-gray-50 disabled:text-gray-400"
                    >
                      {!aiProvider ? (
                        <option value="">Select a provider first</option>
                      ) : llmModels.length === 0 ? (
                        <option value="">Loading models...</option>
                      ) : (
                        llmModels.map((m: string) => (
                          <option key={m} value={m}>{m}</option>
                        ))
                      )}
                    </select>
                  </div>
                </div>
                <div className="flex items-center gap-2 justify-end">
                  <button
                    type="button"
                    onClick={() => setShowAIGeneratePanel(false)}
                    className="px-3 py-1.5 text-xs font-medium text-gray-600 hover:text-gray-800"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => generateDescriptionMutation.mutate({
                      description: aiDescription,
                      tone: aiTone,
                      format_style: aiFormat,
                      ...(aiProvider ? { provider: aiProvider } : {}),
                      ...(aiModel ? { model: aiModel } : {}),
                    })}
                    disabled={generateDescriptionMutation.isPending || !aiDescription.trim()}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50"
                  >
                    {generateDescriptionMutation.isPending ? (
                      <><Loader2 className="h-3 w-3 animate-spin" /> Generating...</>
                    ) : (
                      <><Sparkles className="h-3 w-3" /> Generate</>
                    )}
                  </button>
                </div>
              </div>
            )}

            {/* Editor / Preview */}
            {descriptionEditorMode === 'write' ? (
              <textarea
                required
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent font-mono text-sm"
                rows={6}
                placeholder="Describe the agent's purpose, behavior, and expected interactions... Markdown is supported (at least 10 words)"
              />
            ) : (
              <div className="min-h-[150px] max-h-[300px] overflow-y-auto border border-gray-300 rounded-lg p-4 prose prose-sm max-w-none">
                {formData.description ? (
                  <ReactMarkdown>{formData.description}</ReactMarkdown>
                ) : (
                  <p className="text-gray-400 italic">Nothing to preview yet...</p>
                )}
              </div>
            )}
            <p className={`mt-1 text-xs ${formData.description.trim().split(/\s+/).filter(Boolean).length >= 10 ? 'text-green-600' : 'text-gray-500'}`}>
              {formData.description.trim().split(/\s+/).filter(Boolean).length}/10 words minimum
            </p>
          </div>

          {/* Voice Configuration */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Test Voice AI Agents */}
            <div className="border border-gray-200 rounded-lg p-4 bg-gray-50 flex flex-col h-full">
              <h3 className="text-lg font-semibold text-gray-900 mb-3">1. Configure your test agent</h3>
              <p className="text-sm text-gray-600 mb-4 flex-grow">Configure agents using Voice Bundles for testing purposes</p>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Voice Bundle *</label>
                <select
                  value={formData.voice_bundle_id}
                  onChange={(e) => setFormData({ ...formData, voice_bundle_id: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
                >
                  <option value="">Select a Voice Bundle</option>
                  {voiceBundles.filter((vb) => vb.is_active).map((vb) => (
                    <option key={vb.id} value={vb.id}>{vb.name}</option>
                  ))}
                </select>
                {voiceBundles.filter((vb) => vb.is_active).length === 0 && (
                  <p className="mt-1 text-xs text-gray-500">No active voice bundles available.</p>
                )}
              </div>
            </div>

            {/* Voice AI Agent */}
            <div className="border border-blue-200 rounded-lg p-4 bg-blue-50 flex flex-col h-full">
              <h3 className="text-lg font-semibold text-gray-900 mb-3">2. Voice AI Agent *</h3>
              <p className="text-sm text-gray-600 mb-4 flex-grow">Configure agents using external Voice AI integrations (Retell, Vapi, ElevenLabs)</p>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Integration Provider *</label>
                  <div className="flex items-center gap-3">
                    <select
                      value={formData.voice_ai_integration_id}
                      onChange={(e) => setFormData({ ...formData, voice_ai_integration_id: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
                    >
                      <option value="">Select an Integration</option>
                      {integrations
                        .filter((i) => i.is_active && ['retell', 'vapi', 'elevenlabs'].includes(i.platform))
                        .map((integration) => (
                          <option key={integration.id} value={integration.id}>
                            {integration.name || integration.platform} ({integration.platform === 'retell' ? 'Retell' : integration.platform === 'vapi' ? 'Vapi' : 'ElevenLabs'})
                          </option>
                        ))}
                    </select>
                    {formData.voice_ai_integration_id && (
                      <div className="flex-shrink-0">
                        {(() => {
                          const selected = integrations.find((i) => i.id === formData.voice_ai_integration_id)
                          if (selected?.platform === 'retell') return <img src="/retellai.png" alt="Retell AI" className="h-8 w-8 object-contain" />
                          if (selected?.platform === 'vapi') return <img src="/vapiai.jpg" alt="Vapi AI" className="h-8 w-8 rounded-full object-contain" />
                          if (selected?.platform === 'elevenlabs') return <img src="/elevenlabs.jpg" alt="ElevenLabs" className="h-8 w-8 rounded-full object-contain" />
                          return null
                        })()}
                      </div>
                    )}
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Agent ID *</label>
                  <input
                    type="text"
                    value={formData.voice_ai_agent_id}
                    onChange={(e) => setFormData({ ...formData, voice_ai_agent_id: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
                    placeholder="Enter agent ID from Retell/Vapi/ElevenLabs"
                  />
                  <p className="mt-1 text-xs text-gray-500">Enter the agent ID from your voice AI provider</p>
                </div>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-3 pt-4">
            <Button type="button" variant="outline" onClick={onClose} className="flex-1">
              Cancel
            </Button>
            <Button type="submit" variant="primary" className="flex-1" isLoading={createMutation.isPending}>
              Create Agent
            </Button>
          </div>
        </form>
      </div>

      {showUseSavedModal && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[9999]" onClick={() => {
          setShowUseSavedModal(false)
          setSavedPromptSearch('')
          setSelectedSavedPromptId('')
        }}>
          <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full mx-4 max-h-[85vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Use Saved Prompt Partials</h3>
              <button
                onClick={() => {
                  setShowUseSavedModal(false)
                  setSavedPromptSearch('')
                  setSelectedSavedPromptId('')
                }}
                className="text-gray-400 hover:text-gray-600"
                aria-label="Close use saved prompts modal"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6 space-y-4 overflow-y-auto flex-1">
              <input
                type="text"
                value={savedPromptSearch}
                onChange={(e) => setSavedPromptSearch(e.target.value)}
                placeholder="Search saved prompts..."
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              />

              {isLoadingSavedPromptPartials ? (
                <div className="flex items-center justify-center py-8 text-sm text-gray-500">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Loading saved prompts...
                </div>
              ) : savedPromptPartials.length === 0 ? (
                <div className="rounded-lg border border-gray-200 p-8 text-center text-sm text-gray-500">
                  No saved prompt partials found.
                </div>
              ) : (
                <div className="space-y-2">
                  {savedPromptPartials.map((partial) => {
                    const isSelected = selectedSavedPromptId === partial.id
                    return (
                      <label
                        key={partial.id}
                        className={`block cursor-pointer rounded-lg border p-3 transition-colors ${
                          isSelected ? 'border-primary-300 bg-primary-50' : 'border-gray-200 hover:bg-gray-50'
                        }`}
                      >
                        <div className="flex items-start gap-3">
                          <input
                            type="radio"
                            name="saved-prompt-partial"
                            checked={isSelected}
                            onChange={() => setSelectedSavedPromptId(partial.id)}
                            className="mt-1 h-4 w-4 border-gray-300 text-primary-600 focus:ring-primary-500"
                          />
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-semibold text-gray-900">{partial.name}</p>
                            {partial.description && (
                              <p className="mt-0.5 text-xs text-gray-500">{partial.description}</p>
                            )}
                          </div>
                        </div>
                      </label>
                    )
                  })}
                </div>
              )}
            </div>
            <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setShowUseSavedModal(false)
                  setSavedPromptSearch('')
                  setSelectedSavedPromptId('')
                }}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="primary"
                onClick={() => useSavedPromptMutation.mutate(selectedSavedPromptId)}
                isLoading={useSavedPromptMutation.isPending}
                disabled={!selectedSavedPromptId}
              >
                Use Selected Prompt
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

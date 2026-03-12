import { useState, useEffect } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Sparkles, Loader2, Bot, Eye, Code, Trash2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import Button from '../../../components/Button'
import { apiClient } from '../../../lib/api'
import { VoiceBundle, Integration, AIProvider, ModelProvider } from '../../../types/api'
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

interface AgentEditFormProps {
  formData: FormData
  onChange: (data: FormData) => void
  onSubmit: (e: React.FormEvent) => void
  onDelete: () => void
  voiceBundles: VoiceBundle[]
  integrations: Integration[]
  showToast: (message: string, type: 'success' | 'error') => void
  createdAt?: string
  updatedAt?: string
}

export default function AgentEditForm({
  formData,
  onChange,
  onSubmit,
  onDelete,
  voiceBundles,
  integrations,
  showToast,
}: AgentEditFormProps) {
  const [descriptionEditorMode, setDescriptionEditorMode] = useState<'write' | 'preview'>('write')
  const [showAIGeneratePanel, setShowAIGeneratePanel] = useState(false)
  const [aiDescription, setAiDescription] = useState('')
  const [aiTone, setAiTone] = useState('professional')
  const [aiFormat, setAiFormat] = useState('structured')
  const [aiProvider, setAiProvider] = useState('')
  const [aiModel, setAiModel] = useState('')

  const { data: aiProviders = [] } = useQuery<AIProvider[]>({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const { data: modelOptions } = useQuery({
    queryKey: ['model-options', aiProvider],
    queryFn: () => apiClient.getModelOptions(aiProvider),
    enabled: !!aiProvider,
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
      onChange({ ...formData, description: data.content })
      setShowAIGeneratePanel(false)
      setAiDescription('')
      setDescriptionEditorMode('preview')
      showToast('Description generated successfully!', 'success')
    },
    onError: (err: any) => {
      showToast(err?.response?.data?.detail || 'Failed to generate description with AI', 'error')
    },
  })

  return (
    <form onSubmit={onSubmit}>
      <div className="overflow-x-auto">
        <div className="grid grid-cols-2 gap-6 min-w-[1280px]">
          <div className="min-w-0 space-y-4">
            {/* Name */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
              <input
                type="text"
                required
                value={formData.name}
                onChange={(e) => onChange({ ...formData, name: e.target.value })}
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
                    onClick={() =>
                      onChange({
                        ...formData,
                        call_medium: medium,
                        phone_number: medium === 'web_call' ? '' : formData.phone_number,
                      })
                    }
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
                  onChange={(e) => onChange({ ...formData, phone_number: e.target.value })}
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
                onChange={(e) => onChange({ ...formData, language: e.target.value })}
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
              <label className="block text-sm font-medium text-gray-700 mb-1">Call Type</label>
              <div className="inline-flex rounded-lg border border-gray-300 overflow-hidden">
                {(['outbound', 'inbound'] as const).map((type) => (
                  <button
                    key={type}
                    type="button"
                    onClick={() => onChange({ ...formData, call_type: type })}
                    className={`px-4 py-2 text-sm font-medium transition-colors focus:outline-none ${
                      formData.call_type === type
                        ? 'bg-primary-600 text-white'
                        : 'bg-white text-gray-700 hover:bg-gray-50'
                    } ${type === 'outbound' ? 'border-r border-gray-300' : ''}`}
                  >
                    {type === 'outbound' ? 'Outbound' : 'Inbound'}
                  </button>
                ))}
              </div>
            </div>

            {/* Voice Configuration */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Test Voice Agent */}
              <div className="border border-gray-200 rounded-lg p-4 bg-gray-50 flex flex-col h-full">
                <h3 className="text-lg font-semibold text-gray-900 mb-3">1. Configure your test agent</h3>
                <p className="text-sm text-gray-600 mb-4 flex-grow">
                  Configure agents using Voice Bundles for testing purposes
                </p>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Voice Bundle *</label>
                  <select
                    value={formData.voice_bundle_id}
                    onChange={(e) => onChange({ ...formData, voice_bundle_id: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
                  >
                    <option value="">Select a Voice Bundle</option>
                    {voiceBundles
                      .filter((vb) => vb.is_active)
                      .map((vb) => (
                        <option key={vb.id} value={vb.id}>
                          {vb.name}
                        </option>
                      ))}
                  </select>
                  {voiceBundles.filter((vb) => vb.is_active).length === 0 && (
                    <p className="mt-1 text-xs text-gray-500">
                      No active voice bundles available. Create one in VoiceBundle section.
                    </p>
                  )}
                </div>
              </div>

              {/* Voice AI Agent */}
              <div className="border border-gray-200 rounded-lg p-4 bg-gray-50 flex flex-col h-full">
                <h3 className="text-lg font-semibold text-gray-900 mb-3">2. Voice AI Agent</h3>
                <p className="text-sm text-gray-600 mb-4 flex-grow">
                  Configure agents using external Voice AI integrations (Retell, Vapi, ElevenLabs)
                </p>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Integration Provider *
                    </label>
                    <div className="flex items-center gap-3">
                      <select
                        value={formData.voice_ai_integration_id}
                        onChange={(e) => onChange({ ...formData, voice_ai_integration_id: e.target.value })}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
                      >
                        <option value="">Select an Integration</option>
                        {integrations
                          .filter(
                            (i) =>
                              i.is_active &&
                              ['retell', 'vapi', 'elevenlabs'].includes(i.platform)
                          )
                          .map((integration) => (
                            <option key={integration.id} value={integration.id}>
                              {integration.name || integration.platform} (
                              {integration.platform === 'retell'
                                ? 'Retell'
                                : integration.platform === 'vapi'
                                ? 'Vapi'
                                : 'ElevenLabs'}
                              )
                            </option>
                          ))}
                      </select>
                      {formData.voice_ai_integration_id && (
                        <div className="flex-shrink-0">
                          {(() => {
                            const selected = integrations.find(
                              (i) => i.id === formData.voice_ai_integration_id
                            )
                            if (selected?.platform === 'retell')
                              return (
                                <img
                                  src="/retellai.png"
                                  alt="Retell AI"
                                  className="h-8 w-8 object-contain"
                                />
                              )
                            if (selected?.platform === 'vapi')
                              return (
                                <img
                                  src="/vapiai.jpg"
                                  alt="Vapi AI"
                                  className="h-8 w-8 rounded-full object-contain"
                                />
                              )
                            if (selected?.platform === 'elevenlabs')
                              return (
                                <img
                                  src="/elevenlabs.jpg"
                                  alt="ElevenLabs"
                                  className="h-8 w-8 rounded-full object-contain"
                                />
                              )
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
                      onChange={(e) => onChange({ ...formData, voice_ai_agent_id: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
                      placeholder="Enter agent ID from Retell/Vapi/ElevenLabs"
                    />
                    <p className="mt-1 text-xs text-gray-500">
                      Enter the agent ID you received from your Retell, Vapi, or ElevenLabs provider
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Delete Button */}
            <div className="flex gap-3 pt-4 border-t border-gray-200">
              <Button
                type="button"
                variant="outline"
                onClick={onDelete}
                leftIcon={<Trash2 className="w-4 h-4" />}
                className="border-red-300 text-red-700 hover:bg-red-50 hover:border-red-400"
              >
                Delete
              </Button>
            </div>
          </div>

          {/* System Prompt / Description */}
          <div className="min-w-0">
            <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
              <div className="flex items-center justify-between mb-3">
                <label className="block text-sm font-medium text-gray-700">System Prompt</label>
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
                <div className="mb-3 p-3 bg-amber-50 rounded-lg border border-amber-200">
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
                        onChange={(e) => {
                          setAiProvider(e.target.value)
                          setAiModel('')
                        }}
                        className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
                      >
                        <option value="">Auto-detect (use first available)</option>
                        {aiProviders
                          .filter((p) => p.is_active)
                          .map((p) => (
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
                            <option key={m} value={m}>
                              {m}
                            </option>
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
                      onClick={() =>
                        generateDescriptionMutation.mutate({
                          description: aiDescription,
                          tone: aiTone,
                          format_style: aiFormat,
                          ...(aiProvider ? { provider: aiProvider } : {}),
                          ...(aiModel ? { model: aiModel } : {}),
                        })
                      }
                      disabled={generateDescriptionMutation.isPending || !aiDescription.trim()}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50"
                    >
                      {generateDescriptionMutation.isPending ? (
                        <>
                          <Loader2 className="h-3 w-3 animate-spin" /> Generating...
                        </>
                      ) : (
                        <>
                          <Sparkles className="h-3 w-3" /> Generate
                        </>
                      )}
                    </button>
                  </div>
                </div>
              )}

              {descriptionEditorMode === 'write' ? (
                <textarea
                  value={formData.description}
                  onChange={(e) => onChange({ ...formData, description: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent font-mono text-sm min-h-[380px]"
                  rows={18}
                  placeholder="Write your agent description here... Markdown is supported."
                />
              ) : (
                <div className="min-h-[380px] max-h-[70vh] overflow-y-auto border border-gray-300 rounded-lg p-4 prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-code:text-gray-800 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100">
                  {formData.description ? (
                    <ReactMarkdown>{formData.description}</ReactMarkdown>
                  ) : (
                    <p className="text-gray-400 italic">Nothing to preview yet...</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </form>
  )
}

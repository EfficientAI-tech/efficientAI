import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Sparkles, Loader2, Bot, Eye, Code, Trash2, Save, PhoneOutgoing, PhoneIncoming } from 'lucide-react'
import ParamSlider from './ParamSlider'
import { OverviewSection, formatSilenceHangupLabel } from './AgentOverviewLayout'
import ReactMarkdown from 'react-markdown'
import Button from '../../../components/Button'
import { apiClient } from '../../../lib/api'
import { VoiceBundle, Integration, AIProvider, IntegrationPlatform } from '../../../types/api'
import { getIntegrationPlatformLabel, getIntegrationPlatformLogo, getTelephonyProviderLabel } from '../../../config/providers'
import { useOrgTelephony } from '../../../hooks/useOrgTelephony'
import { TelephonyProvider } from '../../../types/api'
import type { AgentDetailTab } from './AgentInfoView'
import TestAgentSubTabNav, { type TestAgentSubTab } from './TestAgentSubTabNav'
import VoiceBundleDetailCard from './VoiceBundleDetailCard'
import AgentPromptComposer from './AgentPromptComposer'
import {
  formatGatewayCredentialLabel,
  resolveLLMModelsForCredential,
} from '../../../lib/llmModelOptions'
import { useAgentPhoneAssignmentCheck } from './useAgentPhoneAssignmentCheck'
import { formatAgentPhoneConflictMessage } from './agentPhoneValidation'

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

interface AgentEditFormProps {
  formData: FormData
  onChange: (data: FormData) => void
  onSubmit: (e: React.FormEvent) => void
  onDelete: () => void
  voiceBundles: VoiceBundle[]
  integrations: Integration[]
  showToast: (message: string, type: 'success' | 'error') => void
  activeTab: AgentDetailTab
  onSaveSystemPrompt: () => void
  agentId?: string
}

const SUPPORTED_VOICE_AI_PLATFORMS: IntegrationPlatform[] = [
  IntegrationPlatform.RETELL,
  IntegrationPlatform.VAPI,
  IntegrationPlatform.ELEVENLABS,
  IntegrationPlatform.SMALLEST,
]

export default function AgentEditForm({
  formData,
  onChange,
  onSubmit,
  onDelete,
  voiceBundles,
  integrations,
  showToast,
  activeTab,
  onSaveSystemPrompt,
  agentId,
}: AgentEditFormProps) {
  const navigate = useNavigate()
  const [descriptionEditorMode, setDescriptionEditorMode] = useState<'write' | 'preview'>('write')
  const [providerPromptEditorMode, setProviderPromptEditorMode] = useState<'write' | 'preview'>('write')
  const [showAIGeneratePanel, setShowAIGeneratePanel] = useState(false)
  const [includeLinkedScenarios, setIncludeLinkedScenarios] = useState(true)
  const [aiDescription, setAiDescription] = useState('')
  const [aiTone, setAiTone] = useState('professional')
  const [aiFormat, setAiFormat] = useState('structured')
  const [aiCredentialId, setAiCredentialId] = useState('')
  const [aiModel, setAiModel] = useState('')
  const [phoneNumberInputMode, setPhoneNumberInputMode] = useState<'provider' | 'custom'>('provider')
  const [testAgentSubTab, setTestAgentSubTab] = useState<TestAgentSubTab>('prompt')

  const { data: aiProviders = [] } = useQuery<AIProvider[]>({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const selectedAiProviderRow = aiCredentialId
    ? aiProviders.find((p) => p.id === aiCredentialId)
    : undefined
  const aiProvider = selectedAiProviderRow?.provider ?? ''

  const { data: modelOptions } = useQuery({
    queryKey: ['model-options', aiProvider],
    queryFn: () => apiClient.getModelOptions(aiProvider),
    enabled: !!aiProvider,
  })
  const {
    canUseProviderNumbers,
    numbersForCallType,
  } = useOrgTelephony(formData.call_medium === 'phone_call')
  const telephonyNumbers = numbersForCallType(formData.call_type)
  const isTelephonyConfigError = !canUseProviderNumbers
  const { conflict: phoneConflict, isChecking: isCheckingPhoneAssignment, hasConflict: hasPhoneConflict } =
    useAgentPhoneAssignmentCheck({
      enabled: formData.call_medium === 'phone_call',
      callMedium: formData.call_medium,
      phoneNumber: formData.phone_number,
      telephonyPhoneNumberId:
        phoneNumberInputMode === 'provider' ? formData.telephony_phone_number_id : undefined,
      excludeAgentId: agentId,
    })

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (formData.call_medium === 'phone_call') {
      if (isCheckingPhoneAssignment) {
        showToast('Checking phone number availability…', 'error')
        return
      }
      if (hasPhoneConflict && phoneConflict) {
        showToast(formatAgentPhoneConflictMessage(phoneConflict), 'error')
        return
      }
    }
    onSubmit(e)
  }

  const llmModels = modelOptions?.llm || []
  const modelResolution = selectedAiProviderRow
    ? resolveLLMModelsForCredential(selectedAiProviderRow, llmModels)
    : { mode: 'catalog' as const, models: llmModels }
  const gatewayDirectModel =
    modelResolution.mode === 'gateway_direct' ? modelResolution.model : null
  const selectableModels =
    modelResolution.mode === 'catalog' ? modelResolution.models : []

  useEffect(() => {
    if (gatewayDirectModel) {
      if (aiModel) setAiModel('')
      return
    }
    if (aiProvider && selectableModels.length > 0 && !selectableModels.includes(aiModel)) {
      setAiModel(selectableModels[0])
    }
  }, [aiProvider, selectableModels, aiModel, gatewayDirectModel])

  useEffect(() => {
    if (formData.call_medium !== 'phone_call') {
      return
    }

    if (formData.telephony_phone_number_id) {
      setPhoneNumberInputMode('provider')
      return
    }

    if (!canUseProviderNumbers || telephonyNumbers.length === 0) {
      if (phoneNumberInputMode === 'provider') {
        setPhoneNumberInputMode('custom')
      }
    }
  }, [
    formData.call_medium,
    formData.telephony_phone_number_id,
    phoneNumberInputMode,
    canUseProviderNumbers,
    telephonyNumbers.length,
  ])

  const generateDescriptionMutation = useMutation({
    mutationFn: (data: {
      description: string
      tone?: string
      format_style?: string
      provider?: string
      model?: string
      agent_id?: string
      include_linked_scenarios?: boolean
      append_scenarios_to_output?: boolean
    }) => apiClient.generateAgentDescription(data),
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

  const voiceAgentIntegrations = integrations.filter(
    (integration) =>
      integration.is_active &&
      SUPPORTED_VOICE_AI_PLATFORMS.includes(integration.platform as IntegrationPlatform),
  )

  const selectedVoiceIntegration = voiceAgentIntegrations.find(
    (integration) => integration.id === formData.voice_ai_integration_id,
  )

  const linkedVoiceBundle = formData.voice_bundle_id
    ? voiceBundles.find((vb) => vb.id === formData.voice_bundle_id)
    : undefined

  const hasPlatformLink = Boolean(formData.voice_ai_integration_id || formData.voice_ai_agent_id)

  const productionPromptProse =
    'prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-code:text-gray-800 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-ul:text-gray-700 prose-ol:text-gray-700'

  return (
    <form onSubmit={handleFormSubmit}>
      {activeTab === 'overview' && (
        <div className="space-y-5 max-w-3xl">
          <OverviewSection title="Agent profile" description="Name and language shown to evaluators and logs.">
            <div className="space-y-4">
              <div>
                <label htmlFor="agent-name" className="block text-sm font-medium text-gray-700 mb-1.5">
                  Name *
                </label>
                <input
                  id="agent-name"
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => onChange({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2.5 border border-gray-200 rounded-lg bg-white shadow-sm focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400"
                  placeholder="Customer Support Bot"
                />
              </div>

              <div>
                <label htmlFor="agent-language" className="block text-sm font-medium text-gray-700 mb-1.5">
                  Language
                </label>
                <select
                  id="agent-language"
                  value={formData.language}
                  onChange={(e) => onChange({ ...formData, language: e.target.value })}
                  className="w-full px-3 py-2.5 border border-gray-200 rounded-lg bg-white shadow-sm focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400"
                >
                  <option value="en">English</option>
                  <option value="es">Spanish</option>
                  <option value="fr">French</option>
                  <option value="de">German</option>
                  <option value="zh">Chinese</option>
                  <option value="hi">Hindi</option>
                </select>
              </div>
            </div>
          </OverviewSection>

          <OverviewSection title="Call setup" description="How sessions are placed and routed.">
            <div className="space-y-5">
              <div>
                <span className="block text-sm font-medium text-gray-700 mb-2">Call medium *</span>
                <div className="inline-flex rounded-xl border border-gray-200 bg-gray-50/80 p-1 shadow-sm">
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
                      className={`rounded-lg px-4 py-2 text-sm font-medium transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 ${
                        formData.call_medium === medium
                          ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200/80'
                          : 'text-gray-600 hover:text-gray-900'
                      }`}
                    >
                      {medium === 'web_call' ? 'Web call' : 'Phone call'}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <span className="block text-sm font-medium text-gray-700 mb-2">Call type</span>
                <div className="inline-flex rounded-xl border border-gray-200 bg-gray-50/80 p-1 shadow-sm">
                  {(['outbound', 'inbound'] as const).map((type) => (
                    <button
                      key={type}
                      type="button"
                      onClick={() => {
                        const nextType = type
                        const nextNumbers = numbersForCallType(nextType)
                        const stillValid = nextNumbers.some((n) => n.id === formData.telephony_phone_number_id)
                        onChange({
                          ...formData,
                          call_type: nextType,
                          ...(stillValid
                            ? {}
                            : { telephony_phone_number_id: '', phone_number: '' }),
                        })
                      }}
                      className={`inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 ${
                        formData.call_type === type
                          ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200/80'
                          : 'text-gray-600 hover:text-gray-900'
                      }`}
                    >
                      {type === 'outbound' ? (
                        <PhoneOutgoing className="h-3.5 w-3.5" />
                      ) : (
                        <PhoneIncoming className="h-3.5 w-3.5" />
                      )}
                      {type === 'outbound' ? 'Outbound' : 'Inbound'}
                    </button>
                  ))}
                </div>
              </div>

              {formData.call_medium === 'phone_call' && (
                <div className="space-y-3 rounded-lg border border-gray-100 bg-gray-50/50 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <label className="text-sm font-medium text-gray-700">Phone number *</label>
                    <div className="inline-flex rounded-lg border border-gray-200 bg-white p-0.5 text-xs">
                      <button
                        type="button"
                        onClick={() => {
                          setPhoneNumberInputMode('provider')
                          onChange({ ...formData, phone_number: '' })
                        }}
                        disabled={!canUseProviderNumbers || telephonyNumbers.length === 0}
                        className={`rounded-md px-2.5 py-1 font-medium ${
                          phoneNumberInputMode === 'provider'
                            ? 'bg-primary-600 text-white'
                            : 'text-gray-600 hover:bg-gray-50'
                        } disabled:opacity-40`}
                      >
                        From provider
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setPhoneNumberInputMode('custom')
                          onChange({ ...formData, telephony_phone_number_id: '' })
                        }}
                        className={`rounded-md px-2.5 py-1 font-medium ${
                          phoneNumberInputMode === 'custom'
                            ? 'bg-primary-600 text-white'
                            : 'text-gray-600 hover:bg-gray-50'
                        }`}
                      >
                        Custom
                      </button>
                    </div>
                  </div>

                  {isTelephonyConfigError && (
                    <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200/80 rounded-lg px-3 py-2">
                      No synced telephony numbers found yet. Import numbers on the Telephony Numbers page,
                      configure a provider in Integrations, or enter a custom number below.
                    </p>
                  )}

                  {phoneNumberInputMode === 'provider' ? (
                    <select
                      required
                      value={formData.telephony_phone_number_id}
                      onChange={(e) => {
                        const selected = telephonyNumbers.find((n) => n.id === e.target.value)
                        onChange({
                          ...formData,
                          telephony_phone_number_id: e.target.value,
                          phone_number: selected?.phone_number || '',
                        })
                      }}
                      className="w-full px-3 py-2.5 border border-gray-200 rounded-lg bg-white shadow-sm focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400"
                      disabled={!canUseProviderNumbers || telephonyNumbers.length === 0}
                    >
                      <option value="">Select a synced telephony number</option>
                      {telephonyNumbers.map((number) => {
                        const assignedToOtherAgent =
                          !!number.agent_id && number.agent_id !== agentId
                        return (
                          <option
                            key={number.id}
                            value={number.id}
                            disabled={assignedToOtherAgent}
                          >
                            {number.phone_number}
                            {number.provider
                              ? ` [${getTelephonyProviderLabel(number.provider as TelephonyProvider)}]`
                              : ''}
                            {number.region ? ` - ${number.region}` : ''}
                            {number.country_iso2 ? ` (${number.country_iso2})` : ''}
                            {assignedToOtherAgent
                              ? ` [Assigned to ${number.linked_agent_name || 'another agent'}]`
                              : ''}
                          </option>
                        )
                      })}
                    </select>
                  ) : (
                    <input
                      type="text"
                      required
                      value={formData.phone_number}
                      onChange={(e) =>
                        onChange({
                          ...formData,
                          phone_number: e.target.value.replace(/[^\d+]/g, ''),
                        })
                      }
                      className={`w-full px-3 py-2.5 border rounded-lg bg-white shadow-sm focus:ring-2 focus:ring-primary-500/30 focus:border-primary-400 ${
                        hasPhoneConflict ? 'border-red-300' : 'border-gray-200'
                      }`}
                      placeholder="+1234567890"
                    />
                  )}
                  {formData.call_medium === 'phone_call' && hasPhoneConflict && phoneConflict && (
                    <p className="text-xs text-red-600 mt-1">
                      {formatAgentPhoneConflictMessage(phoneConflict)}
                    </p>
                  )}
                  {formData.call_medium === 'phone_call' && isCheckingPhoneAssignment && (
                    <p className="text-xs text-gray-500 mt-1">Checking number availability…</p>
                  )}
                </div>
              )}
            </div>
          </OverviewSection>

          <OverviewSection title="Live session" description="Hang up when neither side speaks for too long.">
            <ParamSlider
              label="End call after silence"
              helpText={`${formatSilenceHangupLabel(formData.silence_hangup_secs)} · Resets on voice activity. Default 15. Set to 0 to disable.`}
              min={0}
              max={600}
              step={1}
              integer
              value={formData.silence_hangup_secs}
              onChange={(next) =>
                onChange({
                  ...formData,
                  silence_hangup_secs: next ?? 0,
                })
              }
            />
          </OverviewSection>

          <div className="flex gap-3 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={onDelete}
              leftIcon={<Trash2 className="w-4 h-4" />}
              className="border-red-200 text-red-700 hover:bg-red-50 hover:border-red-300"
            >
              Delete agent
            </Button>
          </div>
        </div>
      )}

      {activeTab === 'test_agent' && (
        <div className="max-w-4xl space-y-4">
          <TestAgentSubTabNav value={testAgentSubTab} onChange={setTestAgentSubTab} />

          {testAgentSubTab === 'configuration' && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Voice Bundle</label>
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
                    No active voice bundles available. Create one in Voice Bundles.
                  </p>
                )}
              </div>
              {linkedVoiceBundle && (
                <VoiceBundleDetailCard
                  bundle={linkedVoiceBundle}
                  allowParamTuning
                  onEdit={() => {
                    const returnPath = agentId ? `/agents/${agentId}?tab=test_agent` : '/agents'
                    navigate(
                      `/voicebundles?edit=${linkedVoiceBundle.id}&return=${encodeURIComponent(returnPath)}`
                    )
                  }}
                  onManageInVoiceBundles={() => navigate('/voicebundles')}
                />
              )}
            </div>
          )}

          {testAgentSubTab === 'prompt' && (
            <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
              <div className="flex items-center justify-between mb-3">
                <label className="block text-sm font-medium text-gray-700">EfficientAI Test Agent Prompt</label>
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
                    onClick={onSaveSystemPrompt}
                    disabled={!formData.description?.trim()}
                    className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
                  >
                    <Save className="h-3 w-3" />
                    Save Prompt
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
                  {agentId ? (
                    <label className="flex items-center gap-2 text-xs text-gray-700 mb-2">
                      <input
                        type="checkbox"
                        checked={includeLinkedScenarios}
                        onChange={(e) => setIncludeLinkedScenarios(e.target.checked)}
                        className="rounded border-gray-300 text-amber-600 focus:ring-amber-500"
                      />
                      Include linked scenarios as AI context (does not append to prompt)
                    </label>
                  ) : null}
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
                        value={aiCredentialId}
                        onChange={(e) => {
                          setAiCredentialId(e.target.value)
                          setAiModel('')
                        }}
                        className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
                      >
                        <option value="">Auto-detect (use first available)</option>
                        {aiProviders
                          .filter((p) => p.is_active)
                          .map((p) => (
                            <option key={p.id} value={p.id}>
                              {formatGatewayCredentialLabel(p, {
                                custom: 'Custom',
                                openai: 'OpenAI',
                                anthropic: 'Anthropic',
                                google: 'Google',
                              })}
                            </option>
                          ))}
                      </select>
                    </div>
                    <div className="flex-1">
                      <label className="block text-xs font-medium text-gray-600 mb-1">Model</label>
                      {gatewayDirectModel ? (
                        <div
                          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-gray-50 text-gray-700 truncate"
                          title={gatewayDirectModel}
                        >
                          {gatewayDirectModel}
                        </div>
                      ) : (
                        <select
                          value={aiModel}
                          onChange={(e) => setAiModel(e.target.value)}
                          disabled={!aiCredentialId}
                          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white disabled:bg-gray-50 disabled:text-gray-400"
                        >
                          {!aiCredentialId ? (
                            <option value="">Select a provider first</option>
                          ) : selectableModels.length === 0 ? (
                            <option value="">Loading models...</option>
                          ) : (
                            selectableModels.map((m: string) => (
                              <option key={m} value={m}>
                                {m}
                              </option>
                            ))
                          )}
                        </select>
                      )}
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
                          ...(agentId
                            ? {
                                agent_id: agentId,
                                include_linked_scenarios: includeLinkedScenarios,
                                append_scenarios_to_output: false,
                              }
                            : {}),
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

              <div className="mb-4 rounded-lg border border-gray-200 bg-white p-3">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <label className="text-sm font-medium text-gray-700">Custom prompt variables</label>
                  <button
                    type="button"
                    className="text-xs font-medium text-primary-600 hover:text-primary-800"
                    onClick={() => {
                      const base = { ...(formData.prompt_variables || {}) }
                      let n = 1
                      let key = 'custom_var'
                      while (base[key]) {
                        n += 1
                        key = `custom_var_${n}`
                      }
                      base[key] = ''
                      onChange({ ...formData, prompt_variables: base })
                    }}
                  >
                    + Add variable
                  </button>
                </div>
                <p className="text-xs text-gray-500 mb-2">
                  Define keys you can insert with <code className="text-gray-700">{'{'}</code> or{' '}
                  <code className="text-gray-700">@</code>. Values are optional descriptions for your team.
                </p>
                {Object.keys(formData.prompt_variables || {}).length === 0 ? (
                  <p className="text-xs text-gray-400 italic">No custom variables yet.</p>
                ) : (
                  <div className="space-y-2">
                    {Object.entries(formData.prompt_variables || {}).map(([key, desc]) => (
                      <div key={key} className="flex flex-wrap items-center gap-2">
                        <input
                          type="text"
                          value={key}
                          onChange={(e) => {
                            const nextKey = e.target.value.replace(/\s+/g, '_')
                            const vars = { ...(formData.prompt_variables || {}) }
                            delete vars[key]
                            if (nextKey) vars[nextKey] = desc
                            onChange({ ...formData, prompt_variables: vars })
                          }}
                          className="w-36 px-2 py-1.5 text-xs font-mono border border-gray-300 rounded-md"
                          placeholder="variable_key"
                        />
                        <input
                          type="text"
                          value={desc}
                          onChange={(e) =>
                            onChange({
                              ...formData,
                              prompt_variables: {
                                ...(formData.prompt_variables || {}),
                                [key]: e.target.value,
                              },
                            })
                          }
                          className="flex-1 min-w-[120px] px-2 py-1.5 text-xs border border-gray-300 rounded-md"
                          placeholder="Description (optional)"
                        />
                        <button
                          type="button"
                          className="text-xs text-red-600 hover:text-red-800"
                          onClick={() => {
                            const vars = { ...(formData.prompt_variables || {}) }
                            delete vars[key]
                            onChange({ ...formData, prompt_variables: vars })
                          }}
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {descriptionEditorMode === 'write' ? (
                <AgentPromptComposer
                  value={formData.description}
                  onChange={(description) => onChange({ ...formData, description })}
                  customVariables={formData.prompt_variables}
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
          )}
        </div>
      )}

      {activeTab === 'voice_ai_agent' && hasPlatformLink && (
        <div className="max-w-2xl space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Integration Provider</label>
            <div className="flex items-center gap-3">
              <select
                value={formData.voice_ai_integration_id}
                onChange={(e) => onChange({ ...formData, voice_ai_integration_id: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
              >
                <option value="">Select an Integration</option>
                {voiceAgentIntegrations.map((integration) => {
                  const platformLabel = getIntegrationPlatformLabel(
                    integration.platform as IntegrationPlatform,
                  )
                  return (
                    <option key={integration.id} value={integration.id}>
                      {integration.name || platformLabel} ({platformLabel})
                    </option>
                  )
                })}
              </select>
              {selectedVoiceIntegration && (
                <div className="flex-shrink-0">
                  {(() => {
                    const logo = getIntegrationPlatformLogo(
                      selectedVoiceIntegration.platform as IntegrationPlatform,
                    )
                    const label = getIntegrationPlatformLabel(
                      selectedVoiceIntegration.platform as IntegrationPlatform,
                    )
                    return logo ? (
                      <img src={logo} alt={label} className="h-8 w-8 rounded-full object-contain" />
                    ) : null
                  })()}
                </div>
              )}
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Agent ID</label>
            <input
              type="text"
              value={formData.voice_ai_agent_id}
              onChange={(e) => onChange({ ...formData, voice_ai_agent_id: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
              placeholder="Enter agent ID from Retell/Vapi/ElevenLabs/Smallest"
            />
          </div>
        </div>
      )}

      {activeTab === 'voice_ai_agent' && !hasPlatformLink && (
        <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
          <div className="flex items-center justify-between mb-3">
            <label className="block text-sm font-medium text-gray-700">Production Agent Prompt</label>
            <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
              <button
                type="button"
                onClick={() => setProviderPromptEditorMode('write')}
                className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                  providerPromptEditorMode === 'write'
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                <Code className="h-3 w-3" />
                Write
              </button>
              <button
                type="button"
                onClick={() => setProviderPromptEditorMode('preview')}
                className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                  providerPromptEditorMode === 'preview'
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                <Eye className="h-3 w-3" />
                Preview
              </button>
            </div>
          </div>
          {providerPromptEditorMode === 'write' ? (
            <textarea
              value={formData.provider_prompt}
              onChange={(e) => onChange({ ...formData, provider_prompt: e.target.value })}
              className="w-full min-h-[380px] px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent font-mono text-sm resize-y"
              rows={16}
              placeholder="Paste or edit the production system prompt…"
            />
          ) : (
            <div className="min-h-[380px] max-h-[70vh] overflow-y-auto border border-gray-300 rounded-lg p-4 bg-white">
              {formData.provider_prompt?.trim() ? (
                <div className={productionPromptProse}>
                  <ReactMarkdown>{formData.provider_prompt}</ReactMarkdown>
                </div>
              ) : (
                <p className="text-gray-400 italic">Nothing to preview yet…</p>
              )}
            </div>
          )}
        </div>
      )}
    </form>
  )
}

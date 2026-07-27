import { useState, useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { X, Sparkles, Loader2, Bot, Eye, Code, FileText, PhoneOutgoing, PhoneIncoming } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import Button from '../../../components/Button'
import { apiClient } from '../../../lib/api'
import { AIProvider, VoiceBundle, Integration, IntegrationPlatform, TelephonyProvider } from '../../../types/api'
import { getIntegrationPlatformLabel, getIntegrationPlatformLogo, getTelephonyProviderLabel } from '../../../config/providers'
import { useOrgTelephony } from '../../../hooks/useOrgTelephony'
import { resolveLLMModelsForCredential, formatGatewayCredentialLabel } from '../../../lib/llmModelOptions'
import { useAgentPhoneAssignmentCheck } from './useAgentPhoneAssignmentCheck'
import { extractPhoneConflictDetail, formatAgentPhoneConflictMessage } from './agentPhoneValidation'
import {
  assembleTestAgentPrompt,
  emptyPromptSections,
  type ScenarioDraftItem,
  type TestPromptSectionDraft,
} from './agentTestSetupConstants'

interface FormData {
  name: string
  phone_number: string
  language: string
  description: string
  call_type: string
  call_medium: 'phone_call' | 'web_call'
  telephony_phone_number_id: string
  voice_bundle_id: string
  voice_ai_integration_id: string
  voice_ai_agent_id: string
  silence_hangup_secs: number
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

const CREATE_STEPS = [
  { id: 1, title: 'Basics', description: 'Name, call settings, and telephony' },
  { id: 2, title: 'Prompt', description: 'Describe what this agent does' },
  { id: 3, title: 'Voice setup', description: 'Optional integrations' },
] as const

type CreateStep = (typeof CREATE_STEPS)[number]['id']

const SUPPORTED_VOICE_AI_PLATFORMS: IntegrationPlatform[] = [
  IntegrationPlatform.RETELL,
  IntegrationPlatform.VAPI,
  IntegrationPlatform.ELEVENLABS,
  IntegrationPlatform.SMALLEST,
]

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
  const [aiCredentialId, setAiCredentialId] = useState('')
  const [aiModel, setAiModel] = useState('')
  const [showUseSavedModal, setShowUseSavedModal] = useState(false)
  const [savedPromptSearch, setSavedPromptSearch] = useState('')
  const [selectedSavedPromptId, setSelectedSavedPromptId] = useState('')
  const [phoneNumberInputMode, setPhoneNumberInputMode] = useState<'provider' | 'custom'>('provider')
  const [currentStep, setCurrentStep] = useState<CreateStep>(1)
  const [promptInputMode, setPromptInputMode] = useState<'production' | 'manual'>('production')
  const [productionPrompt, setProductionPrompt] = useState('')
  const [promptSections, setPromptSections] = useState<TestPromptSectionDraft[]>(emptyPromptSections())
  const [scenarioDrafts, setScenarioDrafts] = useState<ScenarioDraftItem[]>([])
  const [scenarioCount, setScenarioCount] = useState(5)
  const [setupAdditionalContext, setSetupAdditionalContext] = useState('')
  const [formData, setFormData] = useState<FormData>({
    name: '',
    phone_number: '',
    language: 'en',
    description: '',
    call_type: 'outbound',
    call_medium: 'phone_call',
    telephony_phone_number_id: '',
    voice_bundle_id: '',
    voice_ai_integration_id: '',
    voice_ai_agent_id: '',
    silence_hangup_secs: 15,
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
  const {
    canUseProviderNumbers,
    numbersForCallType,
  } = useOrgTelephony(isOpen && formData.call_medium === 'phone_call')
  const telephonyNumbers = numbersForCallType(formData.call_type)
  const isTelephonyConfigError = !canUseProviderNumbers
  const { conflict: phoneConflict, isChecking: isCheckingPhoneAssignment, hasConflict: hasPhoneConflict } =
    useAgentPhoneAssignmentCheck({
      enabled: isOpen,
      callMedium: formData.call_medium,
      phoneNumber: phoneNumberInputMode === 'custom' ? formData.phone_number : formData.phone_number,
      telephonyPhoneNumberId:
        phoneNumberInputMode === 'provider' ? formData.telephony_phone_number_id : undefined,
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

  const { data: savedPromptPartials = [], isLoading: isLoadingSavedPromptPartials } = useQuery<PromptPartial[]>({
    queryKey: ['create-agent-prompt-partials', savedPromptSearch],
    queryFn: () => apiClient.listPromptPartials(0, 100, savedPromptSearch.trim() || undefined),
    enabled: showUseSavedModal,
  })

  useEffect(() => {
    if (formData.call_medium !== 'phone_call') {
      return
    }
    const hasProviderNumbers = canUseProviderNumbers && telephonyNumbers.length > 0
    if (!hasProviderNumbers && phoneNumberInputMode !== 'custom') {
      setPhoneNumberInputMode('custom')
      setFormData((prev) => ({ ...prev, telephony_phone_number_id: '' }))
    }
    if (
      phoneNumberInputMode === 'provider' &&
      formData.telephony_phone_number_id &&
      !telephonyNumbers.some((n) => n.id === formData.telephony_phone_number_id && !n.agent_id)
    ) {
      setFormData((prev) => ({ ...prev, telephony_phone_number_id: '', phone_number: '' }))
    }
  }, [
    formData.call_medium,
    formData.call_type,
    formData.telephony_phone_number_id,
    phoneNumberInputMode,
    canUseProviderNumbers,
    telephonyNumbers,
  ])

  const buildGenerationParams = () => ({
    ...(aiProvider ? { provider: aiProvider } : {}),
    ...(aiCredentialId ? { credential_id: aiCredentialId } : {}),
    ...(aiModel ? { model: aiModel } : {}),
  })

  const syncDescriptionFromSections = (sections: TestPromptSectionDraft[]) => {
    const assembled = assembleTestAgentPrompt(sections)
    setFormData((prev) => ({ ...prev, description: assembled }))
    return assembled
  }

  const updatePromptSection = (key: TestPromptSectionDraft['key'], content: string) => {
    setPromptSections((prev) => {
      const next = prev.map((section) =>
        section.key === key ? { ...section, content } : section,
      )
      syncDescriptionFromSections(next)
      return next
    })
  }

  const generateTestPromptMutation = useMutation({
    mutationFn: () => {
      if (!formData.name.trim()) {
        throw new Error('Agent name is required before generating a test prompt')
      }
      if (!productionPrompt.trim()) {
        throw new Error('Production prompt is required')
      }
      return apiClient.generateTestPromptFromProduction({
        production_prompt: productionPrompt,
        agent_name: formData.name.trim(),
        language: formData.language,
        call_type: formData.call_type,
        additional_context: setupAdditionalContext.trim() || undefined,
        ...buildGenerationParams(),
      })
    },
    onSuccess: (data) => {
      const sections = data.sections.map((section) => ({
        key: section.key as TestPromptSectionDraft['key'],
        title: section.title,
        content: section.content,
      }))
      setPromptSections(sections)
      setFormData((prev) => ({ ...prev, description: data.test_agent_prompt }))
      setDescriptionEditorMode('preview')
      showToast('Test agent prompt generated from production prompt', 'success')
    },
    onError: (err: any) => {
      showToast(err?.message || err?.response?.data?.detail || 'Failed to generate test prompt', 'error')
    },
  })

  const generateScenariosMutation = useMutation({
    mutationFn: () => {
      if (!formData.name.trim()) {
        throw new Error('Agent name is required before generating scenarios')
      }
      const testAgentPrompt = formData.description.trim()
      if (!testAgentPrompt) {
        throw new Error('Generate or enter a test agent prompt first')
      }
      return apiClient.generateScenariosFromPrompt({
        test_agent_prompt: testAgentPrompt,
        agent_name: formData.name.trim(),
        scenario_count: scenarioCount,
        language: formData.language,
        call_type: formData.call_type,
        additional_context: setupAdditionalContext.trim() || undefined,
        ...buildGenerationParams(),
      })
    },
    onSuccess: (data) => {
      setScenarioDrafts(
        data.scenarios.map((scenario, index) => ({
          id: `draft-${Date.now()}-${index}`,
          name: scenario.name,
          description: scenario.description,
          goal: scenario.goal || undefined,
          selected: true,
        })),
      )
      showToast(`Generated ${data.scenarios.length} scenario drafts`, 'success')
    },
    onError: (err: any) => {
      showToast(err?.message || err?.response?.data?.detail || 'Failed to generate scenarios', 'error')
    },
  })

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
    mutationFn: async (data: FormData) => {
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
      if (data.call_medium === 'phone_call' && data.telephony_phone_number_id) {
        payload.telephony_phone_number_id = data.telephony_phone_number_id
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

      payload.silence_hangup_secs = data.silence_hangup_secs ?? 15

      const agent = await apiClient.createAgent(payload)

      const selectedDrafts = scenarioDrafts.filter((draft) => draft.selected)
      let scenarioWarning: string | undefined
      if (selectedDrafts.length > 0) {
        const results = await Promise.allSettled(
          selectedDrafts.map((draft) =>
            apiClient.createScenario({
              name: draft.name,
              description: draft.description,
              agent_id: agent.id,
              required_info: draft.goal ? { goal: draft.goal } : {},
            }),
          ),
        )
        const failed = results.filter((result) => result.status === 'rejected').length
        if (failed > 0) {
          scenarioWarning = `${failed} of ${selectedDrafts.length} scenarios failed to save`
        }
      }

      return { agent, scenarioWarning }
    },
    onSuccess: (result) => {
      const hadSelectedScenarios = scenarioDrafts.some((draft) => draft.selected)
      onSuccess()
      resetForm()
      if (result.scenarioWarning) {
        showToast(`Agent created. ${result.scenarioWarning}.`, 'error')
      } else {
        showToast(
          hadSelectedScenarios ? 'Agent and scenarios created successfully!' : 'Agent created successfully!',
          'success',
        )
      }
    },
    onError: (error: any) => {
      const conflictMessage = extractPhoneConflictDetail(error.response?.data?.detail)
      showToast(conflictMessage || `Failed to create agent: ${error.message}`, 'error')
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
      telephony_phone_number_id: '',
      voice_bundle_id: '',
      voice_ai_integration_id: '',
      voice_ai_agent_id: '',
      silence_hangup_secs: 15,
    })
    setDescriptionEditorMode('write')
    setShowAIGeneratePanel(false)
    setAiDescription('')
    setAiTone('professional')
    setAiFormat('structured')
    setAiCredentialId('')
    setAiModel('')
    setPhoneNumberInputMode('provider')
    setShowUseSavedModal(false)
    setSavedPromptSearch('')
    setSelectedSavedPromptId('')
    setCurrentStep(1)
    setPromptInputMode('production')
    setProductionPrompt('')
    setPromptSections(emptyPromptSections())
    setScenarioDrafts([])
    setScenarioCount(5)
    setSetupAdditionalContext('')
  }

  const validateStep1 = (): boolean => {
    if (!formData.name.trim()) {
      showToast('Name is required.', 'error')
      return false
    }
    if (formData.call_medium === 'phone_call') {
      if (phoneNumberInputMode === 'provider') {
        if (!formData.telephony_phone_number_id) {
          showToast('Please select a telephony number from your provider.', 'error')
          return false
        }
      } else if (!formData.phone_number?.trim()) {
        showToast('Phone number is required for phone calls.', 'error')
        return false
      } else if (!/^[\d+]+$/.test(formData.phone_number)) {
        showToast('Phone number must contain only digits and the + character.', 'error')
        return false
      }
      if (isCheckingPhoneAssignment) {
        showToast('Checking phone number availability…', 'error')
        return false
      }
      if (hasPhoneConflict && phoneConflict) {
        showToast(formatAgentPhoneConflictMessage(phoneConflict), 'error')
        return false
      }
    }
    return true
  }

  const validateStep2 = (): boolean => {
    const descriptionWords = formData.description.trim().split(/\s+/).filter(Boolean)
    if (descriptionWords.length < 10) {
      showToast('Description must be at least 10 words.', 'error')
      return false
    }
    return true
  }

  const validateStep3 = (): boolean => {
    if (formData.voice_ai_integration_id && !formData.voice_ai_agent_id?.trim()) {
      showToast('Agent ID is required when Integration Provider is selected', 'error')
      return false
    }
    if (formData.voice_ai_agent_id?.trim() && !formData.voice_ai_integration_id) {
      showToast('Integration Provider is required when Agent ID is provided', 'error')
      return false
    }
    return true
  }

  const handleNext = (e?: React.MouseEvent | React.SyntheticEvent) => {
    e?.preventDefault?.()
    e?.stopPropagation?.()
    if (currentStep === 1 && !validateStep1()) return
    if (currentStep === 2 && !validateStep2()) return
    // Defer so the same click cannot land on the submit button that replaces Next.
    window.setTimeout(() => {
      setCurrentStep((step) => Math.min(step + 1, 3) as CreateStep)
    }, 0)
  }

  const handleBack = () => {
    setCurrentStep((step) => Math.max(step - 1, 1) as CreateStep)
  }

  const handleCreate = () => {
    if (currentStep !== 3) return
    if (!validateStep1() || !validateStep2() || !validateStep3()) return
    createMutation.mutate(formData)
  }

  const voiceAgentIntegrations = integrations.filter(
    (integration) =>
      integration.is_active &&
      SUPPORTED_VOICE_AI_PLATFORMS.includes(integration.platform as IntegrationPlatform),
  )

  const selectedVoiceIntegration = voiceAgentIntegrations.find(
    (integration) => integration.id === formData.voice_ai_integration_id,
  )

  const renderPortal = (content: ReactNode) => {
    if (typeof document === 'undefined') return null
    return createPortal(content, document.body)
  }

  useEffect(() => {
    if (!isOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [isOpen])

  if (!isOpen) return null

  return renderPortal(
    <>
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-4 sm:p-6 bg-gray-900/50 backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="bg-white rounded-2xl shadow-2xl ring-1 ring-gray-200/80 w-[min(96vw,88rem)] h-[min(92vh,920px)] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-agent-modal-title"
      >
        <div className="flex items-center justify-between shrink-0 px-6 py-5 border-b border-gray-100">
          <div>
            <h2 id="create-agent-modal-title" className="text-2xl font-bold text-gray-900 tracking-tight">
              Create Test Agent
            </h2>
            <p className="text-sm text-gray-500 mt-1">
              Step {currentStep} of {CREATE_STEPS.length} · {CREATE_STEPS[currentStep - 1]?.title}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="shrink-0 px-6 py-4 border-b border-gray-100 bg-gray-50/50">
          <div className="flex items-center">
            {CREATE_STEPS.map((step, index) => {
              const isComplete = currentStep > step.id
              const isCurrent = currentStep === step.id
              return (
                <div key={step.id} className={`flex items-center ${index < CREATE_STEPS.length - 1 ? 'flex-1' : ''}`}>
                  <div className="flex items-center gap-2 min-w-0">
                    <div
                      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${
                        isComplete
                          ? 'bg-primary-600 text-white'
                          : isCurrent
                            ? 'border-2 border-primary-600 text-primary-600 bg-white'
                            : 'border-2 border-gray-300 text-gray-400 bg-white'
                      }`}
                    >
                      {step.id}
                    </div>
                    <div className="hidden sm:block min-w-0">
                      <p className={`text-sm font-medium ${isCurrent ? 'text-gray-900' : 'text-gray-500'}`}>
                        {step.title}
                      </p>
                      <p className="text-xs text-gray-400 truncate">{step.description}</p>
                    </div>
                  </div>
                  {index < CREATE_STEPS.length - 1 && (
                    <div className={`mx-3 h-0.5 flex-1 ${isComplete ? 'bg-primary-600' : 'bg-gray-200'}`} />
                  )}
                </div>
              )
            })}
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5">
        <div className="space-y-4 w-full">
          {currentStep === 1 && (
            <>
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
                    phone_number: medium === 'web_call' ? '' : formData.phone_number,
                    telephony_phone_number_id: medium === 'web_call' ? '' : formData.telephony_phone_number_id,
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
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="block text-sm font-medium text-gray-700">Phone Number *</label>
                <div className="inline-flex rounded-lg border border-gray-300 overflow-hidden">
                  <button
                    type="button"
                    onClick={() => {
                      setPhoneNumberInputMode('provider')
                      setFormData((prev) => ({ ...prev, phone_number: '' }))
                    }}
                    disabled={!canUseProviderNumbers || telephonyNumbers.length === 0}
                    className={`px-3 py-1 text-xs font-medium ${
                      phoneNumberInputMode === 'provider'
                        ? 'bg-primary-600 text-white'
                        : 'bg-white text-gray-700 hover:bg-gray-50'
                    } disabled:bg-gray-100 disabled:text-gray-400`}
                  >
                    Select from provider
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setPhoneNumberInputMode('custom')
                      setFormData((prev) => ({ ...prev, telephony_phone_number_id: '' }))
                    }}
                    className={`px-3 py-1 text-xs font-medium border-l border-gray-300 ${
                      phoneNumberInputMode === 'custom'
                        ? 'bg-primary-600 text-white'
                        : 'bg-white text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    Enter custom
                  </button>
                </div>
              </div>

              {isTelephonyConfigError && (
                <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
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
                    setFormData((prev) => ({
                      ...prev,
                      telephony_phone_number_id: e.target.value,
                      phone_number: selected?.phone_number || '',
                    }))
                  }}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
                  disabled={!canUseProviderNumbers || telephonyNumbers.length === 0}
                >
                  <option value="">Select a synced telephony number</option>
                  {telephonyNumbers.map((number) => (
                    <option key={number.id} value={number.id} disabled={!!number.agent_id}>
                      {number.phone_number}
                      {number.provider
                        ? ` [${getTelephonyProviderLabel(number.provider as TelephonyProvider)}]`
                        : ''}
                      {number.region ? ` - ${number.region}` : ''}
                      {number.country_iso2 ? ` (${number.country_iso2})` : ''}
                      {number.agent_id
                        ? ` [Assigned to ${number.linked_agent_name || 'another agent'}]`
                        : ''}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  required
                  value={formData.phone_number}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      phone_number: e.target.value.replace(/[^\d+]/g, ''),
                    })
                  }
                  className={`w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent ${
                    hasPhoneConflict ? 'border-red-300' : 'border-gray-300'
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
                  onClick={() => {
                    const nextNumbers = numbersForCallType(type)
                    const stillValid = nextNumbers.some((n) => n.id === formData.telephony_phone_number_id)
                    setFormData({
                      ...formData,
                      call_type: type,
                      ...(stillValid
                        ? {}
                        : { telephony_phone_number_id: '', phone_number: '' }),
                    })
                  }}
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

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              End call after silence (seconds)
            </label>
            <input
              type="number"
              min={0}
              max={600}
              step={1}
              value={formData.silence_hangup_secs}
              onChange={(e) => {
                const parsed = parseInt(e.target.value, 10)
                setFormData((prev) => ({
                  ...prev,
                  silence_hangup_secs: Number.isFinite(parsed) ? parsed : 15,
                }))
              }}
              className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
            />
            <p className="mt-1 text-xs text-gray-500">
              Default 15. Set 0 to disable automatic hangup on silence.
            </p>
          </div>
            </>
          )}

          {currentStep === 2 && (
            <>
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPromptInputMode('production')}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg border ${
                  promptInputMode === 'production'
                    ? 'bg-primary-600 text-white border-primary-600'
                    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                }`}
              >
                From production prompt
              </button>
              <button
                type="button"
                onClick={() => setPromptInputMode('manual')}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg border ${
                  promptInputMode === 'manual'
                    ? 'bg-primary-600 text-white border-primary-600'
                    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                }`}
              >
                Write manually
              </button>
            </div>

            {promptInputMode === 'production' ? (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Production Agent Prompt
                  </label>
                  <textarea
                    value={productionPrompt}
                    onChange={(e) => setProductionPrompt(e.target.value)}
                    rows={8}
                    placeholder="Paste the production system prompt from Retell, Vapi, or your voice platform..."
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent font-mono text-sm"
                  />
                </div>

                <div className="p-3 bg-gray-50 rounded-lg border border-gray-200 space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">AI Provider</label>
                      <select
                        value={aiCredentialId}
                        onChange={(e) => {
                          setAiCredentialId(e.target.value)
                          setAiModel('')
                        }}
                        className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-white"
                      >
                        <option value="">Auto-detect</option>
                        {aiProviders.filter((p) => p.is_active).map((p) => (
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
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Model</label>
                      <select
                        value={aiModel}
                        onChange={(e) => setAiModel(e.target.value)}
                        disabled={!aiProvider || !!gatewayDirectModel}
                        className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-white disabled:bg-gray-100"
                      >
                        {gatewayDirectModel ? (
                          <option value="">{gatewayDirectModel}</option>
                        ) : (
                          selectableModels.map((model) => (
                            <option key={model} value={model}>{model}</option>
                          ))
                        )}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Scenario count</label>
                      <input
                        type="number"
                        min={1}
                        max={10}
                        value={scenarioCount}
                        onChange={(e) => setScenarioCount(Math.min(10, Math.max(1, Number(e.target.value) || 1)))}
                        className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-white"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Additional context (optional)</label>
                    <textarea
                      value={setupAdditionalContext}
                      onChange={(e) => setSetupAdditionalContext(e.target.value)}
                      rows={2}
                      placeholder="Industry, compliance notes, or test priorities..."
                      className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-white"
                    />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => generateTestPromptMutation.mutate()}
                      disabled={generateTestPromptMutation.isPending || !productionPrompt.trim() || !formData.name.trim()}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50"
                    >
                      {generateTestPromptMutation.isPending ? (
                        <><Loader2 className="h-3 w-3 animate-spin" /> Generating test prompt...</>
                      ) : (
                        <><Sparkles className="h-3 w-3" /> Generate test prompt</>
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => generateScenariosMutation.mutate()}
                      disabled={generateScenariosMutation.isPending || !formData.description.trim() || !formData.name.trim()}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
                    >
                      {generateScenariosMutation.isPending ? (
                        <><Loader2 className="h-3 w-3 animate-spin" /> Generating scenarios...</>
                      ) : (
                        <><Sparkles className="h-3 w-3" /> Generate scenarios</>
                      )}
                    </button>
                  </div>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="block text-sm font-medium text-gray-700">Test Agent Prompt Sections</label>
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
                        Edit sections
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

                  {descriptionEditorMode === 'write' ? (
                    <div className="space-y-3 max-h-[320px] overflow-y-auto pr-1">
                      {promptSections.map((section) => (
                        <div key={section.key}>
                          <label className="block text-xs font-semibold text-gray-600 mb-1">{section.title}</label>
                          <textarea
                            value={section.content}
                            onChange={(e) => updatePromptSection(section.key, e.target.value)}
                            rows={3}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono"
                            placeholder={`Content for ${section.title}...`}
                          />
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="min-h-[240px] max-h-[320px] overflow-y-auto border border-gray-300 rounded-lg p-4 prose prose-sm max-w-none">
                      {formData.description ? (
                        <ReactMarkdown>{formData.description}</ReactMarkdown>
                      ) : (
                        <p className="text-gray-400 italic">Generate a test prompt to preview...</p>
                      )}
                    </div>
                  )}
                </div>

                {scenarioDrafts.length > 0 && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Generated Scenarios ({scenarioDrafts.filter((d) => d.selected).length}/{scenarioDrafts.length} selected)
                    </label>
                    <div className="space-y-2 max-h-[240px] overflow-y-auto">
                      {scenarioDrafts.map((draft) => (
                        <div key={draft.id} className="border border-gray-200 rounded-lg p-3 bg-white">
                          <label className="flex items-start gap-2">
                            <input
                              type="checkbox"
                              checked={draft.selected}
                              onChange={(e) =>
                                setScenarioDrafts((prev) =>
                                  prev.map((item) =>
                                    item.id === draft.id ? { ...item, selected: e.target.checked } : item,
                                  ),
                                )
                              }
                              className="mt-1"
                            />
                            <div className="flex-1 min-w-0">
                              <input
                                type="text"
                                value={draft.name}
                                onChange={(e) =>
                                  setScenarioDrafts((prev) =>
                                    prev.map((item) =>
                                      item.id === draft.id ? { ...item, name: e.target.value } : item,
                                    ),
                                  )
                                }
                                className="w-full text-sm font-medium border border-gray-200 rounded px-2 py-1 mb-1"
                              />
                              <textarea
                                value={draft.description}
                                onChange={(e) =>
                                  setScenarioDrafts((prev) =>
                                    prev.map((item) =>
                                      item.id === draft.id ? { ...item, description: e.target.value } : item,
                                    ),
                                  )
                                }
                                rows={3}
                                className="w-full text-xs border border-gray-200 rounded px-2 py-1 font-mono"
                              />
                            </div>
                          </label>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <>
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
                      value={aiCredentialId}
                      onChange={(e) => {
                        setAiCredentialId(e.target.value)
                        setAiModel('')
                      }}
                      className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
                    >
                      <option value="">Auto-detect (use first available)</option>
                      {aiProviders.filter((p) => p.is_active).map((p) => (
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
                            <option key={m} value={m}>{m}</option>
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
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                className="w-full min-h-[420px] px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent font-mono text-sm resize-y"
                rows={18}
                placeholder="Describe the agent's purpose, behavior, and expected interactions... Markdown is supported (at least 10 words)"
              />
            ) : (
              <div className="min-h-[420px] max-h-[560px] overflow-y-auto border border-gray-300 rounded-lg p-4 prose prose-sm max-w-none">
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
              </>
            )}

            {promptInputMode === 'production' && (
              <p className={`text-xs ${formData.description.trim().split(/\s+/).filter(Boolean).length >= 10 ? 'text-green-600' : 'text-gray-500'}`}>
                {formData.description.trim().split(/\s+/).filter(Boolean).length}/10 words minimum in assembled test prompt
              </p>
            )}
          </div>
            </>
          )}

          {currentStep === 3 && (
            <>
          <p className="text-sm text-gray-600">
            Voice configuration is optional. Skip this step if you have not integrated a platform yet — you can add it later from the agent detail page.
          </p>

          {/* Voice Configuration */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Test Voice AI Agents */}
            <div className="border border-gray-200 rounded-lg p-4 bg-gray-50 flex flex-col h-full">
              <h3 className="text-lg font-semibold text-gray-900 mb-3">1. Configure your test agent</h3>
              <p className="text-sm text-gray-600 mb-4 flex-grow">Optional — for simulated test caller in evaluator runs and playground</p>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Voice Bundle</label>
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
              <h3 className="text-lg font-semibold text-gray-900 mb-3">2. Voice AI Agent</h3>
              <p className="text-sm text-gray-600 mb-4 flex-grow">Optional — for supported platforms (Retell, Vapi, ElevenLabs, Smallest)</p>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Integration Provider</label>
                  <div className="flex items-center gap-3">
                    <select
                      value={formData.voice_ai_integration_id}
                      onChange={(e) => setFormData({ ...formData, voice_ai_integration_id: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
                    >
                      <option value="">Select an Integration</option>
                      {voiceAgentIntegrations.map((integration) => {
                        const platformLabel = getIntegrationPlatformLabel(integration.platform as IntegrationPlatform)
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
                    onChange={(e) => setFormData({ ...formData, voice_ai_agent_id: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white"
                    placeholder="Enter agent ID from Retell/Vapi/ElevenLabs/Smallest"
                  />
                  <p className="mt-1 text-xs text-gray-500">Enter the agent ID from your voice AI provider</p>
                </div>
              </div>
            </div>
          </div>
            </>
          )}

        </div>
        </div>

        <div className="shrink-0 px-6 py-4 border-t border-gray-100 bg-gray-50/80 flex gap-3">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          {currentStep > 1 && (
            <Button type="button" variant="outline" onClick={handleBack}>
              Back
            </Button>
          )}
          <div className="flex-1" />
          {currentStep < 3 ? (
            <Button
              type="button"
              variant="primary"
              onClick={(e) => handleNext(e as React.MouseEvent)}
            >
              Next
            </Button>
          ) : (
            <Button
              type="button"
              variant="primary"
              onClick={handleCreate}
              isLoading={createMutation.isPending}
            >
              Create Agent
            </Button>
          )}
        </div>
      </div>
    </div>

      {showUseSavedModal && (
        <div className="fixed inset-0 z-[10000] flex items-center justify-center p-4 bg-gray-900/55 backdrop-blur-sm" onClick={() => {
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
    </>
  )
}

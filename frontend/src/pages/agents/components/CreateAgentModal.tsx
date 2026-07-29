import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { X } from 'lucide-react'
import Button from '../../../components/Button'
import { apiClient } from '../../../lib/api'
import { AIProvider, VoiceBundle, Integration, IntegrationPlatform } from '../../../types/api'
import { resolveLLMModelsForCredential } from '../../../lib/llmModelOptions'
import { useAgentPhoneAssignmentCheck } from './useAgentPhoneAssignmentCheck'
import { extractPhoneConflictDetail } from './agentPhoneValidation'
import CreateAgentPathSelector from './create/CreateAgentPathSelector'
import TelephonyBasicsStep, { validateTelephonyBasics } from './create/TelephonyBasicsStep'
import PlatformConnectStep, { isPlatformConnectValid } from './create/PlatformConnectStep'
import VoiceBundleStep from './create/VoiceBundleStep'
import ProductionPromptStep, { isPromptStepValid } from './create/ProductionPromptStep'
import {
  type CreateAgentPath,
  type CreateAgentFormData,
  type CreateStepId,
  DEFAULT_CREATE_AGENT_FORM,
  TELEPHONY_STEPS,
  PLATFORM_STEPS,
} from './create/createAgentTypes'

interface CreateAgentModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
  showToast: (message: string, type: 'success' | 'error') => void
}

export default function CreateAgentModal({
  isOpen,
  onClose,
  onSuccess,
  showToast,
}: CreateAgentModalProps) {
  const [createPath, setCreatePath] = useState<CreateAgentPath>('telephony')
  const [currentStep, setCurrentStep] = useState<CreateStepId>(1)
  const [formData, setFormData] = useState<CreateAgentFormData>(DEFAULT_CREATE_AGENT_FORM)
  const [productionPrompt, setProductionPrompt] = useState('')
  const [setupAdditionalContext, setSetupAdditionalContext] = useState('')
  const [phoneNumberInputMode, setPhoneNumberInputMode] = useState<'provider' | 'custom'>('provider')
  const [selectedPlatform, setSelectedPlatform] = useState<IntegrationPlatform | null>(null)
  const [aiCredentialId, setAiCredentialId] = useState('')
  const [aiModel, setAiModel] = useState('')
  const [promptFetchError, setPromptFetchError] = useState<string | null>(null)
  const [hasFetchedPlatformPrompt, setHasFetchedPlatformPrompt] = useState(false)

  const steps = createPath === 'telephony' ? TELEPHONY_STEPS : PLATFORM_STEPS

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

  const { isChecking: isCheckingPhoneAssignment, hasConflict: hasPhoneConflict } =
    useAgentPhoneAssignmentCheck({
      enabled: isOpen && createPath === 'telephony',
      callMedium: 'phone_call',
      phoneNumber: formData.phone_number,
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

  useEffect(() => {
    if (!isOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [isOpen])

  const buildGenerationParams = () => ({
    ...(aiProvider ? { provider: aiProvider } : {}),
    ...(aiCredentialId ? { credential_id: aiCredentialId } : {}),
    ...(aiModel ? { model: aiModel } : {}),
  })

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
      setFormData((prev) => ({ ...prev, description: data.test_agent_prompt }))
      showToast('Test agent prompt generated from production prompt', 'success')
    },
    onError: (err: any) => {
      showToast(err?.message || err?.response?.data?.detail || 'Failed to generate test prompt', 'error')
    },
  })

  const fetchPlatformPromptMutation = useMutation({
    mutationFn: () => {
      if (!formData.voice_ai_integration_id || !formData.voice_ai_agent_id) {
        throw new Error('Integration and Agent ID are required')
      }
      return apiClient.previewIntegrationAgentPrompt(
        formData.voice_ai_integration_id,
        formData.voice_ai_agent_id.trim(),
      )
    },
    onSuccess: (data) => {
      setProductionPrompt(data.provider_prompt)
      setPromptFetchError(null)
      setHasFetchedPlatformPrompt(true)
    },
    onError: (err: any) => {
      const message = err?.response?.data?.detail || err?.message || 'Failed to fetch production prompt'
      setPromptFetchError(typeof message === 'string' ? message : 'Failed to fetch production prompt')
      setProductionPrompt('')
    },
  })

  const createMutation = useMutation({
    mutationFn: async (data: CreateAgentFormData) => {
      const payload: Record<string, unknown> = {
        name: data.name,
        language: data.language,
        description: data.description || null,
        call_type: data.call_type,
        call_medium: createPath === 'platform' ? 'web_call' : 'phone_call',
        voice_bundle_id: data.voice_bundle_id.trim(),
        silence_hangup_secs: data.silence_hangup_secs ?? 15,
      }

      if (createPath === 'telephony') {
        if (data.phone_number) payload.phone_number = data.phone_number
        if (data.telephony_phone_number_id) {
          payload.telephony_phone_number_id = data.telephony_phone_number_id
        }
        if (productionPrompt.trim()) {
          payload.provider_prompt = productionPrompt.trim()
        }
      }

      if (createPath === 'platform') {
        payload.voice_ai_integration_id = data.voice_ai_integration_id.trim()
        payload.voice_ai_agent_id = data.voice_ai_agent_id.trim()
        if (productionPrompt.trim()) {
          payload.provider_prompt = productionPrompt.trim()
        }
      }

      return apiClient.createAgent(payload as Parameters<typeof apiClient.createAgent>[0])
    },
    onSuccess: () => {
      onSuccess()
      resetForm()
      showToast('Agent created successfully!', 'success')
    },
    onError: (error: any) => {
      const conflictMessage = extractPhoneConflictDetail(error.response?.data?.detail)
      showToast(conflictMessage || `Failed to create agent: ${error.message}`, 'error')
    },
  })

  const resetForm = () => {
    setFormData(DEFAULT_CREATE_AGENT_FORM)
    setCreatePath('telephony')
    setCurrentStep(1)
    setProductionPrompt('')
    setSetupAdditionalContext('')
    setPhoneNumberInputMode('provider')
    setSelectedPlatform(null)
    setAiCredentialId('')
    setAiModel('')
    setPromptFetchError(null)
    setHasFetchedPlatformPrompt(false)
  }

  const handlePathChange = (path: CreateAgentPath) => {
    setCreatePath(path)
    setCurrentStep(1)
    setFormData(DEFAULT_CREATE_AGENT_FORM)
    setProductionPrompt('')
    setSetupAdditionalContext('')
    setSelectedPlatform(null)
    setPromptFetchError(null)
    setHasFetchedPlatformPrompt(false)
  }

  const validateCurrentStep = (): boolean => {
    if (createPath === 'telephony') {
      if (currentStep === 1) {
        if (!validateTelephonyBasics(formData, phoneNumberInputMode, isCheckingPhoneAssignment, hasPhoneConflict)) {
          if (!formData.name.trim()) showToast('Name is required.', 'error')
          else if (phoneNumberInputMode === 'provider' && !formData.telephony_phone_number_id) {
            showToast('Please select a telephony number from your provider.', 'error')
          } else if (phoneNumberInputMode === 'custom' && !formData.phone_number?.trim()) {
            showToast('Phone number is required for phone calls.', 'error')
          } else if (isCheckingPhoneAssignment) {
            showToast('Checking phone number availability…', 'error')
          } else if (hasPhoneConflict) {
            showToast('This phone number is already assigned to another agent.', 'error')
          }
          return false
        }
        return true
      }
      if (currentStep === 2) {
        if (!isPromptStepValid(productionPrompt, formData.description)) {
          if (!productionPrompt.trim()) showToast('Production prompt is required.', 'error')
          else showToast('Test agent prompt must be at least 10 words.', 'error')
          return false
        }
        return true
      }
      if (currentStep === 3) {
        if (!formData.voice_bundle_id?.trim()) {
          showToast('Voice bundle is required.', 'error')
          return false
        }
        return true
      }
    }

    if (createPath === 'platform') {
      if (currentStep === 1) {
        if (!isPlatformConnectValid(formData.name, selectedPlatform, formData.voice_ai_integration_id, formData.voice_ai_agent_id)) {
          if (!formData.name.trim()) showToast('Name is required.', 'error')
          else if (!selectedPlatform) showToast('Please connect a platform.', 'error')
          else showToast('Integration and Agent ID are required.', 'error')
          return false
        }
        return true
      }
      if (currentStep === 2) {
        if (!formData.voice_bundle_id?.trim()) {
          showToast('Voice bundle is required.', 'error')
          return false
        }
        return true
      }
      if (currentStep === 3) {
        if (!isPromptStepValid(productionPrompt, formData.description)) {
          if (!productionPrompt.trim()) showToast('Production prompt must be fetched from the provider.', 'error')
          else showToast('Test agent prompt must be at least 10 words.', 'error')
          return false
        }
        return true
      }
    }

    return true
  }

  const handleNext = () => {
    if (!validateCurrentStep()) return

    if (createPath === 'platform' && currentStep === 2) {
      setCurrentStep(3)
      if (!hasFetchedPlatformPrompt) {
        fetchPlatformPromptMutation.mutate()
      }
      return
    }

    setCurrentStep((step) => Math.min(step + 1, 3) as CreateStepId)
  }

  const handleBack = () => {
    setCurrentStep((step) => Math.max(step - 1, 1) as CreateStepId)
  }

  const handleCreate = () => {
    if (currentStep !== 3 || !validateCurrentStep()) return
    if (createPath === 'telephony') {
      if (!validateTelephonyBasics(formData, phoneNumberInputMode, isCheckingPhoneAssignment, hasPhoneConflict)) {
        showToast('Please fix telephony settings.', 'error')
        return
      }
    }
    if (!isPromptStepValid(productionPrompt, formData.description)) {
      showToast('Production and test agent prompts are required.', 'error')
      return
    }
    if (!formData.voice_bundle_id?.trim()) {
      showToast('Voice bundle is required.', 'error')
      return
    }
    createMutation.mutate(formData)
  }

  const handlePlatformSelect = (platform: IntegrationPlatform | null) => {
    setSelectedPlatform(platform)
    setFormData((prev) => ({
      ...prev,
      voice_ai_integration_id: '',
      voice_ai_agent_id: '',
    }))
    setProductionPrompt('')
    setPromptFetchError(null)
    setHasFetchedPlatformPrompt(false)
  }

  const handlePlatformIntegrationChange = (integrationId: string) => {
    setFormData((prev) => ({ ...prev, voice_ai_integration_id: integrationId }))
    setProductionPrompt('')
    setPromptFetchError(null)
    setHasFetchedPlatformPrompt(false)
  }

  const handlePlatformAgentIdChange = (agentId: string) => {
    setFormData((prev) => ({ ...prev, voice_ai_agent_id: agentId }))
    setProductionPrompt('')
    setPromptFetchError(null)
    setHasFetchedPlatformPrompt(false)
  }

  if (!isOpen) return null

  const renderStepContent = () => {
    if (createPath === 'telephony') {
      if (currentStep === 1) {
        return (
          <TelephonyBasicsStep
            formData={formData}
            onChange={setFormData}
            isOpen={isOpen}
            phoneNumberInputMode={phoneNumberInputMode}
            onPhoneNumberInputModeChange={setPhoneNumberInputMode}
          />
        )
      }
      if (currentStep === 2) {
        return (
          <ProductionPromptStep
            agentName={formData.name}
            language={formData.language}
            callType={formData.call_type}
            productionPrompt={productionPrompt}
            onProductionPromptChange={setProductionPrompt}
            testAgentPrompt={formData.description}
            onTestAgentPromptChange={(description) => setFormData((prev) => ({ ...prev, description }))}
            additionalContext={setupAdditionalContext}
            onAdditionalContextChange={setSetupAdditionalContext}
            aiProviders={aiProviders}
            aiCredentialId={aiCredentialId}
            onAiCredentialIdChange={setAiCredentialId}
            aiModel={aiModel}
            onAiModelChange={setAiModel}
            selectableModels={selectableModels}
            gatewayDirectModel={gatewayDirectModel}
            aiProvider={aiProvider}
            onGenerateTestPrompt={() => generateTestPromptMutation.mutate()}
            isGenerating={generateTestPromptMutation.isPending}
            canGenerate={Boolean(formData.name.trim() && productionPrompt.trim())}
          />
        )
      }
      return (
        <VoiceBundleStep
          voiceBundles={voiceBundles}
          value={formData.voice_bundle_id}
          onChange={(voiceBundleId) => setFormData((prev) => ({ ...prev, voice_bundle_id: voiceBundleId }))}
        />
      )
    }

    if (currentStep === 1) {
      return (
        <PlatformConnectStep
          integrations={integrations}
          agentName={formData.name}
          onAgentNameChange={(name) => setFormData((prev) => ({ ...prev, name }))}
          selectedPlatform={selectedPlatform}
          onSelectPlatform={handlePlatformSelect}
          voiceAiIntegrationId={formData.voice_ai_integration_id}
          voiceAiAgentId={formData.voice_ai_agent_id}
          onIntegrationChange={handlePlatformIntegrationChange}
          onAgentIdChange={handlePlatformAgentIdChange}
        />
      )
    }
    if (currentStep === 2) {
      return (
        <VoiceBundleStep
          voiceBundles={voiceBundles}
          value={formData.voice_bundle_id}
          onChange={(voiceBundleId) => setFormData((prev) => ({ ...prev, voice_bundle_id: voiceBundleId }))}
        />
      )
    }
    return (
      <ProductionPromptStep
        agentName={formData.name}
        language={formData.language}
        callType={formData.call_type}
        productionPrompt={productionPrompt}
        onProductionPromptChange={setProductionPrompt}
        productionPromptReadOnly
        isFetchingProductionPrompt={fetchPlatformPromptMutation.isPending}
        fetchError={promptFetchError}
        testAgentPrompt={formData.description}
        onTestAgentPromptChange={(description) => setFormData((prev) => ({ ...prev, description }))}
        additionalContext={setupAdditionalContext}
        onAdditionalContextChange={setSetupAdditionalContext}
        aiProviders={aiProviders}
        aiCredentialId={aiCredentialId}
        onAiCredentialIdChange={setAiCredentialId}
        aiModel={aiModel}
        onAiModelChange={setAiModel}
        selectableModels={selectableModels}
        gatewayDirectModel={gatewayDirectModel}
        aiProvider={aiProvider}
        onGenerateTestPrompt={() => generateTestPromptMutation.mutate()}
        isGenerating={generateTestPromptMutation.isPending}
        canGenerate={Boolean(formData.name.trim() && productionPrompt.trim())}
      />
    )
  }

  return createPortal(
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
              Step {currentStep} of {steps.length} · {steps[currentStep - 1]?.title}
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

        <div className="shrink-0 px-6 py-4 border-b border-gray-100 bg-gray-50/50 space-y-4">
          <CreateAgentPathSelector value={createPath} onChange={handlePathChange} />
          <div className="flex items-center">
            {steps.map((step, index) => {
              const isComplete = currentStep > step.id
              const isCurrent = currentStep === step.id
              return (
                <div key={step.id} className={`flex items-center ${index < steps.length - 1 ? 'flex-1' : ''}`}>
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
                  {index < steps.length - 1 && (
                    <div className={`mx-3 h-0.5 flex-1 ${isComplete ? 'bg-primary-600' : 'bg-gray-200'}`} />
                  )}
                </div>
              )
            })}
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5">
          {renderStepContent()}
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
            <Button type="button" variant="primary" onClick={handleNext}>
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
    </div>,
    document.body,
  )
}

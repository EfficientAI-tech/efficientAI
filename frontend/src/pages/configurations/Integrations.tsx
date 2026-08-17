import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../lib/api'
import type { TelephonyIntegrationResponse } from '../../lib/api'
import { useState, useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Plus, Trash2, X, AlertCircle, Plug, Edit, Brain, ChevronDown, Phone, Star, Network } from 'lucide-react'
import { IntegrationCreate, IntegrationPlatform, Integration, AIProvider, AIProviderCreate, AIProviderUpdate, ModelProvider, TelephonyProvider, CredentialRoutingMode, GatewayInterfaceMode } from '../../types/api'
import type {
  LLMGatewayMode,
  LLMGatewaySettings,
  LLMGatewayType,
} from '../../lib/api'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'
import {
  getProviderLabel,
  getProviderLogo,
  getProviderDescription,
  TELEPHONY_PROVIDER_CONFIG,
  getTelephonyProviderLabel,
  getTelephonyProviderLogo,
} from '../../config/providers'
import WalkthroughToggleButton from '../../components/walkthrough/WalkthroughToggleButton'
import AIProviderEnabledModelsStep from './AIProviderEnabledModelsStep'

type IntegrationType = 'voice_platform' | 'ai_provider' | 'telephony_provider' | null

const AI_INTEGRATION_PROVIDERS: ModelProvider[] = [
  ModelProvider.OPENAI,
  ModelProvider.ANTHROPIC,
  ModelProvider.GOOGLE,
  ModelProvider.XAI,
  ModelProvider.FIREWORKS,
  ModelProvider.COHERE,
  ModelProvider.MISTRAL,
  ModelProvider.META,
  ModelProvider.TOGETHER,
  ModelProvider.PERPLEXITY,
  ModelProvider.AZURE,
  ModelProvider.AWS,
  ModelProvider.CUSTOM,
]

export default function Integrations() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showModal, setShowModal] = useState(false)
  const [isEditMode, setIsEditMode] = useState(false)
  const [integrationType, setIntegrationType] = useState<IntegrationType>(null)
  const [selectedIntegration, setSelectedIntegration] = useState<Integration | null>(null)
  const [selectedAIProvider, setSelectedAIProvider] = useState<AIProvider | null>(null)
  const [selectedPlatform, setSelectedPlatform] = useState<'retell' | 'vapi' | 'cartesia' | 'elevenlabs' | 'deepgram' | 'murf' | 'sarvam' | 'voicemaker' | 'smallest' | null>(null)
  const [selectedProvider, setSelectedProvider] = useState<ModelProvider | null>(null)
  const [showProviderDropdown, setShowProviderDropdown] = useState(false)
  const [showPlatformDropdown, setShowPlatformDropdown] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [publicKey, setPublicKey] = useState('')
  const [name, setName] = useState('')
  const [azureEndpointUrl, setAzureEndpointUrl] = useState('')
  const [credentialRoutingMode, setCredentialRoutingMode] = useState<CredentialRoutingMode>('inherit')
  const [gatewayModel, setGatewayModel] = useState('')
  const [gatewayInterface, setGatewayInterface] = useState<GatewayInterfaceMode>('inherit')
  const [gatewayBaseUrl, setGatewayBaseUrl] = useState('')
  const [gatewayAuthHeader, setGatewayAuthHeader] = useState('')
  const [gatewayAuthSecretEnv, setGatewayAuthSecretEnv] = useState('')
  const [gatewayAuthSecret, setGatewayAuthSecret] = useState('')
  const [clearGatewayAuthSecret, setClearGatewayAuthSecret] = useState(false)
  const [gatewayExtraHeadersJson, setGatewayExtraHeadersJson] = useState('')
  const [aiProviderWizardStep, setAiProviderWizardStep] = useState<1 | 2>(1)
  const [enabledModels, setEnabledModels] = useState<string[]>([])
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showDeleteAIProviderModal, setShowDeleteAIProviderModal] = useState(false)
  const [showDeleteTelephonyModal, setShowDeleteTelephonyModal] = useState(false)
  const [integrationToDelete, setIntegrationToDelete] = useState<Integration | null>(null)
  const [aiProviderToDelete, setAIProviderToDelete] = useState<AIProvider | null>(null)
  const [telephonyToDelete, setTelephonyToDelete] = useState<TelephonyIntegrationResponse | null>(null)
  const [deleteDependencies, setDeleteDependencies] = useState<Record<string, number> | null>(null)
  const providerDropdownRef = useRef<HTMLDivElement>(null)
  const platformDropdownRef = useRef<HTMLDivElement>(null)

  // Telephony-specific state
  const [selectedTelephonyProvider, setSelectedTelephonyProvider] = useState<TelephonyProvider | null>(null)
  const [telephonyAuthId, setTelephonyAuthId] = useState('')
  const [telephonyAuthToken, setTelephonyAuthToken] = useState('')
  const [telephonyVerifyAppUuid, setTelephonyVerifyAppUuid] = useState('')
  const [telephonyVoiceAppId, setTelephonyVoiceAppId] = useState('')
  const [telephonySipDomain, setTelephonySipDomain] = useState('')
  const [telephonyProviderFilter, setTelephonyProviderFilter] = useState<TelephonyProvider>(TelephonyProvider.PLIVO)

  const [llmGatewayMode, setLlmGatewayMode] = useState<LLMGatewayMode>('inherit')
  const [llmGatewayType, setLlmGatewayType] = useState<LLMGatewayType>('inherit')
  const [llmGatewayInterface, setLlmGatewayInterface] = useState<GatewayInterfaceMode>('inherit')
  const [llmGatewayBaseUrl, setLlmGatewayBaseUrl] = useState('')
  const [llmGatewayVirtualKey, setLlmGatewayVirtualKey] = useState('')
  const [llmGatewayMasterKey, setLlmGatewayMasterKey] = useState('')
  const [clearLlmGatewayVirtualKey, setClearLlmGatewayVirtualKey] = useState(false)
  const [clearLlmGatewayMasterKey, setClearLlmGatewayMasterKey] = useState(false)
  const [showLlmGatewayModal, setShowLlmGatewayModal] = useState(false)

  const syncLlmGatewayFormFromSettings = () => {
    if (!llmGatewaySettings) return
    setLlmGatewayMode(llmGatewaySettings.mode)
    setLlmGatewayType(llmGatewaySettings.gateway_type)
    setLlmGatewayInterface(llmGatewaySettings.gateway_interface || 'inherit')
    setLlmGatewayBaseUrl(llmGatewaySettings.base_url || '')
    setLlmGatewayVirtualKey('')
    setLlmGatewayMasterKey('')
    setClearLlmGatewayVirtualKey(false)
    setClearLlmGatewayMasterKey(false)
  }

  const openLlmGatewayModal = () => {
    syncLlmGatewayFormFromSettings()
    setShowLlmGatewayModal(true)
  }

  const closeLlmGatewayModal = () => {
    setShowLlmGatewayModal(false)
    syncLlmGatewayFormFromSettings()
  }

  const llmGatewayInterfaceLabel = (iface?: string) => {
    if (iface === 'native_openai') return 'Native OpenAI'
    if (iface === 'litellm_shim') return 'LiteLLM shim'
    return 'Inherit'
  }

  const llmGatewayRoutingLabel = (routing: LLMGatewaySettings['effective_routing']) => {
    if (routing === 'bifrost') return 'Bifrost'
    if (routing === 'litellm_proxy') return 'LiteLLM Proxy'
    return 'Direct'
  }

  const credentialRoutingLabel = (routing?: string) => {
    if (routing === 'bifrost') return 'Bifrost'
    if (routing === 'litellm_proxy') return 'LiteLLM Proxy'
    if (routing === 'gateway') return 'Gateway'
    if (routing === 'direct') return 'Direct'
    return 'Inherit'
  }

  const formatGatewayExtraHeadersJson = (headers?: Record<string, string> | null) => {
    if (!headers || Object.keys(headers).length === 0) return ''
    return JSON.stringify(headers, null, 2)
  }

  const parseGatewayExtraHeadersJson = (
    json: string,
  ): Record<string, string> | null => {
    const trimmed = json.trim()
    if (!trimmed) return null
    const parsed = JSON.parse(trimmed) as unknown
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      throw new Error('Gateway extra headers must be a JSON object')
    }
    const result: Record<string, string> = {}
    for (const [key, value] of Object.entries(parsed)) {
      if (typeof value !== 'string' || !value.trim()) {
        throw new Error(`Header "${key}" must have a non-empty string value`)
      }
      result[key] = value.trim()
    }
    return Object.keys(result).length > 0 ? result : null
  }

  const renderModal = (content: ReactNode) => {
    if (typeof document === 'undefined') return null
    return createPortal(content, document.body)
  }

  const { data: integrations = [] } = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
  })

  const { data: aiproviders = [] } = useQuery({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const { data: allTelephonyConfigs = [] } = useQuery<TelephonyIntegrationResponse[]>({
    queryKey: ['telephony-configs'],
    queryFn: () => apiClient.listTelephonyConfigs(),
    retry: false,
  })

  const { data: llmGatewaySettings } = useQuery<LLMGatewaySettings>({
    queryKey: ['llm-gateway-settings'],
    queryFn: () => apiClient.getLLMGatewaySettings(),
  })

  const effectiveLlmGatewayType =
    llmGatewayType !== 'inherit'
      ? llmGatewayType
      : llmGatewaySettings?.platform_gateway_type || 'bifrost'

  const activeAIProvider =
    selectedProvider ||
    (selectedAIProvider?.provider as ModelProvider | undefined) ||
    null
  const isCustomAIProvider =
    integrationType === 'ai_provider' &&
    String(activeAIProvider || '').toLowerCase() === ModelProvider.CUSTOM
  const aiProviderUsesModelsStep = integrationType === 'ai_provider' && !isCustomAIProvider
  const showGatewayModelField =
    integrationType === 'ai_provider' &&
    (isCustomAIProvider ||
      credentialRoutingMode === 'gateway' ||
      (credentialRoutingMode === 'inherit' &&
        llmGatewaySettings?.effective_routing &&
        llmGatewaySettings.effective_routing !== 'direct'))
  const showGatewayOptionalApiKeyUi = isCustomAIProvider
  const aiProviderRequiresApiKey = isCustomAIProvider
    ? credentialRoutingMode === 'direct'
    : !isEditMode

  const showLlmGatewayConfigOptions = llmGatewayMode !== 'disabled'

  useEffect(() => {
    if (!llmGatewaySettings || showLlmGatewayModal) return
    syncLlmGatewayFormFromSettings()
  }, [llmGatewaySettings, showLlmGatewayModal])

  const updateLlmGatewayMutation = useMutation({
    mutationFn: () =>
      apiClient.updateLLMGatewaySettings({
        mode: llmGatewayMode,
        gateway_type: llmGatewayType,
        gateway_interface: llmGatewayInterface,
        base_url: llmGatewayBaseUrl.trim() || null,
        virtual_key: llmGatewayVirtualKey.trim() || undefined,
        master_key: llmGatewayMasterKey.trim() || undefined,
        clear_virtual_key: clearLlmGatewayVirtualKey,
        clear_master_key: clearLlmGatewayMasterKey,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['llm-gateway-settings'] })
      showToast('LLM gateway settings saved', 'success')
      setLlmGatewayVirtualKey('')
      setLlmGatewayMasterKey('')
      setClearLlmGatewayVirtualKey(false)
      setClearLlmGatewayMasterKey(false)
      setShowLlmGatewayModal(false)
    },
    onError: (error: any) => {
      showToast(
        `Failed to save LLM gateway settings: ${error.response?.data?.detail || error.message}`,
        'error',
      )
    },
  })

  // Pick the visible config: default-row preferred, then any row, scoped to
  // the dropdown filter at the top of the section.
  const telephonyConfigsForFilter = allTelephonyConfigs.filter(
    (cfg) => cfg.provider === telephonyProviderFilter,
  )
  const telephonyConfig: TelephonyIntegrationResponse | undefined =
    telephonyConfigsForFilter.find((c) => c.is_default) ||
    telephonyConfigsForFilter[0] ||
    allTelephonyConfigs[0]

  const hasTelephony = allTelephonyConfigs.length > 0 && Boolean(telephonyConfig)

  useEffect(() => {
    if (!telephonyConfig && allTelephonyConfigs.length > 0) {
      setTelephonyProviderFilter(allTelephonyConfigs[0].provider as TelephonyProvider)
    }
  }, [telephonyConfig, allTelephonyConfigs])

  const createIntegrationMutation = useMutation({
    mutationFn: (data: IntegrationCreate) => apiClient.createIntegration(data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['integrations'] }); showToast('Integration created successfully!', 'success'); resetForm() },
    onError: (error: any) => { showToast(`Failed to create integration: ${error.response?.data?.detail || error.message}`, 'error') },
  })

  const updateIntegrationMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<IntegrationCreate> }) => apiClient.updateIntegration(id, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['integrations'] }); showToast('Integration updated successfully!', 'success'); resetForm() },
    onError: (error: any) => { showToast(`Failed to update integration: ${error.response?.data?.detail || error.message}`, 'error') },
  })

  const deleteIntegrationMutation = useMutation({
    mutationFn: ({ id, force }: { id: string; force?: boolean }) => apiClient.deleteIntegration(id, force),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['integrations'] }); showToast('Integration deleted successfully!', 'success'); setShowDeleteModal(false); setIntegrationToDelete(null); setDeleteDependencies(null) },
    onError: (error: any) => {
      const status = error.response?.status; const detail = error.response?.data?.detail
      if (status === 409 && detail?.dependencies) { setDeleteDependencies(detail.dependencies); return }
      showToast(typeof detail === 'string' ? detail : detail?.message || error.message || 'Failed to delete integration.', 'error')
    },
  })

  const createAIProviderMutation = useMutation({
    mutationFn: (data: AIProviderCreate) => apiClient.createAIProvider(data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['ai-providers'] }); showToast('AI Provider configured successfully!', 'success'); resetForm() },
    onError: (error: any) => { showToast(`Failed to configure provider: ${error.response?.data?.detail || error.message}`, 'error') },
  })

  const updateAIProviderMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<AIProviderUpdate> }) => apiClient.updateAIProvider(id, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['ai-providers'] }); showToast('AI Provider updated successfully!', 'success'); resetForm() },
    onError: (error: any) => { showToast(`Failed to update provider: ${error.response?.data?.detail || error.message}`, 'error') },
  })

  const deleteAIProviderMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteAIProvider(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['ai-providers'] }); showToast('AI Provider deleted successfully!', 'success'); setShowDeleteAIProviderModal(false); setAIProviderToDelete(null) },
    onError: (error: any) => { showToast(`Failed to delete provider: ${error.response?.data?.detail || error.message}`, 'error') },
  })

  // Track which existing telephony config we are editing (vs creating new).
  const [editingTelephonyConfigId, setEditingTelephonyConfigId] = useState<string | null>(null)
  const [telephonyName, setTelephonyName] = useState<string>('')

  const saveTelephonyConfigMutation = useMutation({
    mutationFn: async () => {
      const payload: Record<string, any> = { provider: selectedTelephonyProvider || 'plivo' }
      if (telephonyName.trim()) payload.name = telephonyName.trim()
      if (telephonyAuthId.trim()) payload.auth_id = telephonyAuthId.trim()
      if (telephonyAuthToken.trim()) payload.auth_token = telephonyAuthToken.trim()
      if (telephonyVerifyAppUuid.trim()) payload.verify_app_uuid = telephonyVerifyAppUuid.trim()
      if (telephonyVoiceAppId.trim()) payload.voice_app_id = telephonyVoiceAppId.trim()
      if (telephonySipDomain.trim()) payload.sip_domain = telephonySipDomain.trim()
      if (editingTelephonyConfigId) {
        return apiClient.updateTelephonyConfig({ ...payload, id: editingTelephonyConfigId })
      }
      // Creating a new credential row. First-time setup requires both halves.
      if (!payload.auth_id || !payload.auth_token) {
        throw new Error('Auth ID and Auth Token are required when adding a new credential')
      }
      if (payload.provider === 'exotel' && !payload.voice_app_id) {
        throw new Error('Account SID is required for Exotel')
      }
      return apiClient.createTelephonyConfig(payload as any)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['telephony-configs'] })
      showToast('Telephony configuration saved successfully!', 'success')
      resetForm()
    },
    onError: (error: any) => { showToast(error?.response?.data?.detail || error?.message || 'Failed to save telephony config', 'error') },
  })

  const setDefaultIntegrationMutation = useMutation({
    mutationFn: (id: string) => apiClient.setDefaultIntegration(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['integrations'] }); showToast('Default integration updated', 'success') },
    onError: (error: any) => { showToast(error?.response?.data?.detail || error?.message || 'Failed to set default', 'error') },
  })

  const setDefaultAIProviderMutation = useMutation({
    mutationFn: (id: string) => apiClient.setDefaultAIProvider(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['ai-providers'] }); showToast('Default AI provider updated', 'success') },
    onError: (error: any) => { showToast(error?.response?.data?.detail || error?.message || 'Failed to set default', 'error') },
  })

  const setDefaultTelephonyMutation = useMutation({
    mutationFn: (id: string) => apiClient.setDefaultTelephonyConfig(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['telephony-configs'] }); showToast('Default telephony provider updated', 'success') },
    onError: (error: any) => { showToast(error?.response?.data?.detail || error?.message || 'Failed to set default', 'error') },
  })

  const deleteTelephonyMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteTelephonyConfig(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['telephony-configs'] })
      showToast('Telephony credential deleted', 'success')
      setShowDeleteTelephonyModal(false)
      setTelephonyToDelete(null)
    },
    onError: (error: any) => { showToast(error?.response?.data?.detail || error?.message || 'Failed to delete', 'error') },
  })

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (providerDropdownRef.current && !providerDropdownRef.current.contains(event.target as Node)) setShowProviderDropdown(false)
      if (platformDropdownRef.current && !platformDropdownRef.current.contains(event.target as Node)) setShowPlatformDropdown(false)
    }
    if (showProviderDropdown || showPlatformDropdown) document.addEventListener('mousedown', handleClickOutside)
    return () => { document.removeEventListener('mousedown', handleClickOutside) }
  }, [showProviderDropdown, showPlatformDropdown])

  const resetForm = () => {
    setShowModal(false); setIsEditMode(false); setIntegrationType(null); setSelectedIntegration(null); setSelectedAIProvider(null)
    setSelectedPlatform(null); setSelectedProvider(null); setShowProviderDropdown(false); setShowPlatformDropdown(false)
    setApiKey(''); setPublicKey(''); setName(''); setAzureEndpointUrl('')
    setCredentialRoutingMode('inherit'); setGatewayModel(''); setGatewayInterface('inherit'); setGatewayBaseUrl('')
    setGatewayAuthHeader(''); setGatewayAuthSecretEnv(''); setGatewayAuthSecret(''); setClearGatewayAuthSecret(false)
    setGatewayExtraHeadersJson('')
    setAiProviderWizardStep(1); setEnabledModels([])
    setSelectedTelephonyProvider(null); setTelephonyAuthId(''); setTelephonyAuthToken(''); setTelephonyVerifyAppUuid(''); setTelephonyVoiceAppId(''); setTelephonySipDomain('')
    setEditingTelephonyConfigId(null); setTelephonyName('')
  }

  const handleEdit = (integration: Integration) => {
    setIntegrationType('voice_platform')
    setSelectedIntegration(integration)
    setSelectedPlatform(integration.platform as 'retell' | 'vapi' | 'cartesia' | 'elevenlabs' | 'deepgram' | 'murf' | 'sarvam' | 'voicemaker' | 'smallest')
    setName(integration.name || '')
    setApiKey('') // Don't pre-fill API key for security
    setPublicKey(integration.public_key || '')
    setCredentialRoutingMode(integration.routing_mode || 'inherit')
    setIsEditMode(true)
    setShowModal(true)
  }

  const handleEditAIProvider = (provider: AIProvider) => {
    setIntegrationType('ai_provider'); setSelectedAIProvider(provider); setSelectedProvider(provider.provider)
    setName(provider.name || ''); setApiKey(''); setCredentialRoutingMode(provider.routing_mode || 'inherit')
    setAzureEndpointUrl(provider.endpoint_url || '')
    setGatewayModel(provider.gateway_model || ''); setGatewayInterface(provider.gateway_interface || 'inherit')
    setGatewayBaseUrl(provider.gateway_base_url || ''); setGatewayAuthHeader(provider.gateway_auth_header || '')
    setGatewayAuthSecretEnv(provider.gateway_auth_secret_env || ''); setGatewayAuthSecret(''); setClearGatewayAuthSecret(false)
    setGatewayExtraHeadersJson(formatGatewayExtraHeadersJson(provider.gateway_extra_headers))
    setEnabledModels(provider.enabled_models || [])
    setAiProviderWizardStep(1)
    setShowProviderDropdown(false); setIsEditMode(true); setShowModal(true)
  }

  const handleEditTelephony = (config?: TelephonyIntegrationResponse) => {
    const target = config || telephonyConfig
    setIntegrationType('telephony_provider')
    setSelectedTelephonyProvider((target?.provider as TelephonyProvider) || telephonyProviderFilter)
    setEditingTelephonyConfigId(target?.id || null)
    setTelephonyName(target?.name || '')
    setTelephonyVerifyAppUuid(target?.verify_app_uuid || '')
    setTelephonyVoiceAppId(target?.voice_app_id || '')
    setTelephonySipDomain(target?.sip_domain || '')
    setTelephonyAuthId(''); setTelephonyAuthToken(''); setIsEditMode(true); setShowModal(true)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (integrationType === 'voice_platform') {
      if (isEditMode && selectedIntegration) {
        const updateData: Partial<IntegrationCreate> = {}
        if (name !== (selectedIntegration.name || '')) updateData.name = name || undefined
        if (apiKey) updateData.api_key = apiKey
        if (publicKey !== (selectedIntegration.public_key || '')) updateData.public_key = publicKey || undefined
        if (credentialRoutingMode !== (selectedIntegration.routing_mode || 'inherit')) {
          updateData.routing_mode = credentialRoutingMode
        }
        if (Object.keys(updateData).length > 0) updateIntegrationMutation.mutate({ id: selectedIntegration.id, data: updateData })
        else resetForm()
      } else {
        if (!selectedPlatform || !apiKey) return
        createIntegrationMutation.mutate({
          platform: selectedPlatform as IntegrationPlatform,
          api_key: apiKey,
          public_key: publicKey || undefined,
          name: name || undefined,
          routing_mode: credentialRoutingMode,
        })
      }
    } else if (integrationType === 'ai_provider') {
      let parsedGatewayExtraHeaders: Record<string, string> | null = null
      try {
        parsedGatewayExtraHeaders = parseGatewayExtraHeadersJson(gatewayExtraHeadersJson)
      } catch (error: any) {
        showToast(error?.message || 'Invalid gateway extra headers JSON', 'error')
        return
      }

      const resolvedEnabledModels = enabledModels.length > 0 ? enabledModels : null

      if (aiProviderWizardStep === 1) {
        if (!isEditMode && !selectedProvider) {
          showToast('Please select a provider', 'error')
          return
        }
        if (!isEditMode && aiProviderRequiresApiKey && !apiKey.trim()) {
          showToast('Please enter an API key', 'error')
          return
        }
        if (!isEditMode && selectedProvider === ModelProvider.AZURE && !azureEndpointUrl.trim()) {
          showToast('Please enter your Azure OpenAI endpoint URL', 'error')
          return
        }
        if (!isCustomAIProvider) {
          setAiProviderWizardStep(2)
          return
        }
      }

      if (isEditMode && selectedAIProvider) {
        const updateData: Partial<AIProviderUpdate> = {
          enabled_models: resolvedEnabledModels,
        }
        if (apiKey.trim()) updateData.api_key = apiKey
        if (name !== (selectedAIProvider.name || '')) updateData.name = name || null
        const trimmedAzureEndpointUrl = azureEndpointUrl.trim()
        if (trimmedAzureEndpointUrl !== (selectedAIProvider.endpoint_url || '')) {
          updateData.endpoint_url = trimmedAzureEndpointUrl || null
        }
        if (credentialRoutingMode !== (selectedAIProvider.routing_mode || 'inherit')) {
          updateData.routing_mode = credentialRoutingMode
        }
        const trimmedGatewayModel = gatewayModel.trim()
        if (trimmedGatewayModel !== (selectedAIProvider.gateway_model || '')) {
          updateData.gateway_model = trimmedGatewayModel || null
        }
        if (gatewayInterface !== (selectedAIProvider.gateway_interface || 'inherit')) {
          updateData.gateway_interface = gatewayInterface
        }
        const trimmedGatewayBaseUrl = gatewayBaseUrl.trim()
        if (trimmedGatewayBaseUrl !== (selectedAIProvider.gateway_base_url || '')) {
          updateData.gateway_base_url = trimmedGatewayBaseUrl || null
        }
        const trimmedGatewayAuthHeader = gatewayAuthHeader.trim()
        if (trimmedGatewayAuthHeader !== (selectedAIProvider.gateway_auth_header || '')) {
          updateData.gateway_auth_header = trimmedGatewayAuthHeader || null
        }
        const trimmedGatewayAuthSecretEnv = gatewayAuthSecretEnv.trim()
        if (trimmedGatewayAuthSecretEnv !== (selectedAIProvider.gateway_auth_secret_env || '')) {
          updateData.gateway_auth_secret_env = trimmedGatewayAuthSecretEnv || null
        }
        if (clearGatewayAuthSecret) {
          updateData.clear_gateway_auth_secret = true
        } else if (gatewayAuthSecret.trim()) {
          updateData.gateway_auth_secret = gatewayAuthSecret.trim()
        }
        const existingExtraHeadersJson = formatGatewayExtraHeadersJson(
          selectedAIProvider.gateway_extra_headers,
        )
        if (gatewayExtraHeadersJson.trim() !== existingExtraHeadersJson.trim()) {
          updateData.gateway_extra_headers = parsedGatewayExtraHeaders
        }
        updateAIProviderMutation.mutate({ id: selectedAIProvider.id, data: updateData })
      } else {
        if (!selectedProvider) {
          showToast('Please select a provider', 'error')
          return
        }
        if (aiProviderRequiresApiKey && !apiKey.trim()) {
          showToast('Please enter an API key', 'error')
          return
        }
        if (selectedProvider === ModelProvider.AZURE && !azureEndpointUrl.trim()) {
          showToast('Please enter your Azure OpenAI endpoint URL', 'error')
          return
        }
        createAIProviderMutation.mutate({
          provider: selectedProvider,
          api_key: apiKey.trim() || undefined,
          name: name || null,
          routing_mode: credentialRoutingMode,
          endpoint_url: selectedProvider === ModelProvider.AZURE ? azureEndpointUrl.trim() : undefined,
          gateway_model: gatewayModel.trim() || undefined,
          gateway_interface: gatewayInterface,
          gateway_base_url: gatewayBaseUrl.trim() || undefined,
          gateway_auth_header: gatewayAuthHeader.trim() || undefined,
          gateway_auth_secret_env: gatewayAuthSecretEnv.trim() || undefined,
          gateway_auth_secret: gatewayAuthSecret.trim() || undefined,
          gateway_extra_headers: parsedGatewayExtraHeaders || undefined,
          enabled_models: resolvedEnabledModels || undefined,
        })
      }
    } else if (integrationType === 'telephony_provider') {
      saveTelephonyConfigMutation.mutate()
    }
  }

  const handleDelete = (integration: Integration) => { setIntegrationToDelete(integration); setDeleteDependencies(null); setShowDeleteModal(true) }
  const handleDeleteAIProvider = (provider: AIProvider) => { setAIProviderToDelete(provider); setShowDeleteAIProviderModal(true) }
  const handleDeleteTelephony = (config: TelephonyIntegrationResponse) => { setTelephonyToDelete(config); setShowDeleteTelephonyModal(true) }
  const confirmDeleteIntegration = (force?: boolean) => { if (integrationToDelete) deleteIntegrationMutation.mutate({ id: integrationToDelete.id, force }) }
  const confirmDeleteAIProvider = () => { if (aiProviderToDelete) deleteAIProviderMutation.mutate(aiProviderToDelete.id) }
  const confirmDeleteTelephony = () => { if (telephonyToDelete) deleteTelephonyMutation.mutate(telephonyToDelete.id) }

  const platforms = [
    {
      id: IntegrationPlatform.RETELL,
      name: 'Retell AI',
      description: 'Connect your Retell AI voice agents',
      image: '/retellai.png',
    },
    {
      id: IntegrationPlatform.VAPI,
      name: 'Vapi',
      description: 'Connect your Vapi voice AI agents',
      image: '/vapiai.jpg',
    },
    {
      id: IntegrationPlatform.CARTESIA,
      name: 'Cartesia',
      description: 'Connect your Cartesia voice AI agents',
      image: '/cartesia.jpg',
    },
    {
      id: IntegrationPlatform.ELEVENLABS,
      name: 'ElevenLabs',
      description: 'Connect your ElevenLabs voice AI agents',
      image: '/elevenlabs.jpg',
    },
    {
      id: IntegrationPlatform.DEEPGRAM,
      name: 'Deepgram',
      description: 'Connect your Deepgram voice AI agents',
      image: '/deepgram.png',
    },
    {
      id: IntegrationPlatform.MURF,
      name: 'Murf',
      description: 'Connect your Murf TTS voice AI',
      image: '/murf.png',
    },
    {
      id: IntegrationPlatform.SARVAM,
      name: 'Sarvam',
      description: 'Connect your Sarvam STT, TTS & LLM voice AI',
      image: '/sarvam.png',
    },
    {
      id: IntegrationPlatform.VOICEMAKER,
      name: 'VoiceMaker',
      description: 'Connect your VoiceMaker TTS voice AI',
      image: '/voiceMaker.png',
    },
    {
      id: IntegrationPlatform.SMALLEST,
      name: 'Smallest.ai',
      description: 'Connect your Smallest Atoms, Pulse STT, and Lightning TTS',
      image: '/smallest.jpeg',
    },
  ]

  // Multiple credentials per platform are supported. When editing we lock
  // the platform field; when creating we always show every platform so the
  // user can add additional keys for an already-configured platform.
  const availablePlatforms = platforms

  // AI Integration section should only show LLM providers.
  // Voice vendors belong under Voice Platform integrations.
  const availableProviders = AI_INTEGRATION_PROVIDERS
  const aiIntegrationProviders = (aiproviders as AIProvider[]).filter((p) =>
    AI_INTEGRATION_PROVIDERS.includes(p.provider as ModelProvider)
  )
  const hasConfiguredIntegrations =
    integrations.length > 0 ||
    aiIntegrationProviders.length > 0 ||
    hasTelephony

  const getPlatformInfo = (platformId: IntegrationPlatform) => {
    return platforms.find(p => p.id === platformId)
  }

  return (
    <div className="space-y-6">
      <ToastContainer />
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-3xl font-bold text-gray-900">Integrations</h1>
          <p className="text-gray-600 mt-1">Connect with voice AI platforms, AI providers, and telephony providers</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 pr-2">
          <Button
            variant="outline"
            onClick={openLlmGatewayModal}
            leftIcon={<Network className="h-5 w-5" />}
          >
            LLM Gateway
            {llmGatewaySettings && (
              <span
                className={`ml-1.5 px-1.5 py-0.5 text-xs font-medium rounded ${
                  llmGatewaySettings.effective_routing !== 'direct'
                    ? 'bg-indigo-100 text-indigo-700'
                    : 'bg-gray-100 text-gray-600'
                }`}
              >
                {llmGatewayRoutingLabel(llmGatewaySettings.effective_routing)}
              </span>
            )}
          </Button>
          <Button variant="primary" onClick={() => setShowModal(true)} leftIcon={<Plus className="h-5 w-5" />}>Add Integration</Button>
          <WalkthroughToggleButton />
        </div>
      </div>

      {/* Configured Integrations */}
      {hasConfiguredIntegrations && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">Configured Integrations</h2>
            <p className="text-sm text-gray-600 mt-1">These integrations are ready to use</p>
          </div>
          <div>
            {integrations.length > 0 && (
              <div className="border-b border-gray-200">
                <div className="px-6 py-3 bg-blue-50 border-b border-blue-100">
                  <div className="flex items-center gap-2">
                    <Plug className="h-4 w-4 text-blue-600" />
                    <h3 className="text-sm font-semibold text-blue-900">Voice Platforms</h3>
                    <span className="px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 rounded-full">{integrations.length}</span>
                  </div>
                </div>
                <div className="divide-y divide-gray-200">
                  {integrations.map((integration: Integration) => {
                    const platformInfo = getPlatformInfo(integration.platform)
                    return (
                      <div key={integration.id} className="px-6 py-4 hover:bg-gray-50 transition-colors">
                        <div className="flex items-center gap-4">
                          {/* Name */}
                          <div className="flex flex-col min-w-[160px] max-w-[240px] flex-shrink-0">
                            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Name</span>
                            <span className={`text-sm mt-0.5 truncate ${integration.name ? 'font-semibold text-gray-900' : 'text-gray-400 italic'}`} title={integration.name || ''}>
                              {integration.name || '—'}
                            </span>
                          </div>
                          {/* Type */}
                          <div className="flex-shrink-0 min-w-[120px]">
                            <span className="px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 rounded-full whitespace-nowrap">Voice Platform</span>
                          </div>
                          {/* Logo + Provider */}
                          <div className="flex items-center gap-3 flex-1 min-w-0">
                            <div className="flex-shrink-0">
                              {platformInfo?.image ? (
                                <div className="w-10 h-10 bg-white rounded-lg flex items-center justify-center border border-gray-200 p-1.5"><img src={platformInfo.image} alt={platformInfo.name} className="w-full h-full object-contain" /></div>
                              ) : (
                                <div className="w-10 h-10 bg-gradient-to-br from-primary-100 to-primary-200 rounded-lg flex items-center justify-center"><Plug className="h-5 w-5 text-primary-600" /></div>
                              )}
                            </div>
                            <div className="flex items-center gap-2 flex-wrap min-w-0">
                              <h3 className="text-base font-semibold text-gray-900 truncate">{platformInfo?.name || integration.platform}</h3>
                              {integration.is_default && (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-700 rounded">
                                  <Star className="h-3 w-3 fill-current" /> Default
                                </span>
                              )}
                              {integration.routing_mode && integration.routing_mode !== 'inherit' && (
                                <span className="px-2 py-0.5 text-xs font-medium bg-slate-100 text-slate-700 rounded">
                                  {integration.routing_mode === 'gateway' ? 'Gateway' : 'Direct'}
                                </span>
                              )}
                              {integration.effective_routing && integration.effective_routing !== 'direct' && (
                                <span className="px-2 py-0.5 text-xs font-medium bg-indigo-100 text-indigo-700 rounded">
                                  {credentialRoutingLabel(integration.effective_routing)}
                                </span>
                              )}
                              {!integration.is_active && <span className="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded">Inactive</span>}
                            </div>
                          </div>
                          {/* Actions */}
                          <div className="flex items-center gap-2 flex-shrink-0">
                            {!integration.is_default && integration.is_active && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => setDefaultIntegrationMutation.mutate(integration.id)}
                                isLoading={setDefaultIntegrationMutation.isPending && setDefaultIntegrationMutation.variables === integration.id}
                                leftIcon={<Star className="h-4 w-4" />}
                              >
                                Set Default
                              </Button>
                            )}
                            <Button variant="ghost" size="sm" onClick={() => handleEdit(integration)} leftIcon={<Edit className="h-4 w-4" />}>Edit</Button>
                            <Button variant="ghost" size="sm" onClick={() => handleDelete(integration)} leftIcon={<Trash2 className="h-4 w-4" />} className="text-red-600 hover:text-red-700 hover:bg-red-50">Delete</Button>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* AI Provider Integrations */}
            {aiIntegrationProviders.length > 0 && (
              <div>
                <div className="px-6 py-3 bg-purple-50 border-b border-purple-100">
                  <div className="flex items-center gap-2">
                    <Brain className="h-4 w-4 text-purple-600" />
                    <h3 className="text-sm font-semibold text-purple-900">AI Providers</h3>
                    <span className="px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-700 rounded-full">
                      {aiIntegrationProviders.length}
                    </span>
                  </div>
                </div>
                <div className="divide-y divide-gray-200">
                  {aiIntegrationProviders.map((provider: AIProvider) => (
                    <div
                      key={provider.id}
                      className="px-6 py-4 hover:bg-gray-50 transition-colors"
                    >
                      <div className="flex items-center gap-4">
                        {/* Name */}
                        <div className="flex flex-col min-w-[160px] max-w-[240px] flex-shrink-0">
                          <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Name</span>
                          <span className={`text-sm mt-0.5 truncate ${provider.name ? 'font-semibold text-gray-900' : 'text-gray-400 italic'}`} title={provider.name || ''}>
                            {provider.name || '—'}
                          </span>
                        </div>
                        {/* Type */}
                        <div className="flex-shrink-0 min-w-[120px]">
                          <span className="px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-700 rounded-full whitespace-nowrap">AI Provider</span>
                        </div>
                        {/* Logo + Provider */}
                        <div className="flex items-center gap-3 flex-1 min-w-0">
                          <div className="flex-shrink-0">
                            {getProviderLogo(provider.provider) ? (
                              <div className="w-10 h-10 bg-white rounded-lg flex items-center justify-center border border-gray-200 p-1.5"><img src={getProviderLogo(provider.provider)!} alt={getProviderLabel(provider.provider)} className="w-full h-full object-contain" /></div>
                            ) : (
                              <div className="w-10 h-10 bg-gradient-to-br from-primary-100 to-primary-200 rounded-lg flex items-center justify-center"><Brain className="h-5 w-5 text-primary-600" /></div>
                            )}
                          </div>
                          <div className="flex items-center gap-2 flex-wrap min-w-0">
                            <h3 className="text-base font-semibold text-gray-900 truncate">{getProviderLabel(provider.provider)}</h3>
                            {provider.provider === ModelProvider.AZURE && provider.endpoint_url && (
                              <span
                                className="text-xs text-gray-500 truncate max-w-[280px]"
                                title={provider.endpoint_url}
                              >
                                {provider.endpoint_url}
                              </span>
                            )}
                            {provider.is_default && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-700 rounded">
                                <Star className="h-3 w-3 fill-current" /> Default
                              </span>
                            )}
                            {provider.gateway_managed && (
                              <span className="px-2 py-0.5 text-xs font-medium bg-indigo-100 text-indigo-700 rounded">
                                Gateway managed
                              </span>
                            )}
                            {provider.routing_mode && provider.routing_mode !== 'inherit' && (
                              <span className="px-2 py-0.5 text-xs font-medium bg-slate-100 text-slate-700 rounded">
                                {provider.routing_mode === 'gateway' ? 'Gateway' : 'Direct'}
                              </span>
                            )}
                            {provider.effective_routing && provider.effective_routing !== 'direct' && (
                              <span className="px-2 py-0.5 text-xs font-medium bg-indigo-100 text-indigo-700 rounded">
                                {credentialRoutingLabel(provider.effective_routing)}
                              </span>
                            )}
                            {provider.effective_gateway_interface === 'native_openai' && (
                              <span className="px-2 py-0.5 text-xs font-medium bg-teal-100 text-teal-700 rounded">
                                Native API
                              </span>
                            )}
                            {provider.gateway_model && (
                              <span className="px-2 py-0.5 text-xs font-medium bg-violet-100 text-violet-700 rounded truncate max-w-[180px]" title={provider.gateway_model}>
                                {provider.gateway_model}
                              </span>
                            )}
                            {provider.enabled_models && provider.enabled_models.length > 0 && (
                              <span
                                className="px-2 py-0.5 text-xs font-medium bg-sky-100 text-sky-700 rounded"
                                title={provider.enabled_models.join(', ')}
                              >
                                {provider.enabled_models.length} model{provider.enabled_models.length === 1 ? '' : 's'}
                              </span>
                            )}
                            {!provider.is_active && <span className="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded">Inactive</span>}
                          </div>
                        </div>
                        {/* Actions */}
                        <div className="flex items-center gap-2 flex-shrink-0">
                          {!provider.is_default && provider.is_active && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setDefaultAIProviderMutation.mutate(provider.id)}
                              isLoading={setDefaultAIProviderMutation.isPending && setDefaultAIProviderMutation.variables === provider.id}
                              leftIcon={<Star className="h-4 w-4" />}
                            >
                              Set Default
                            </Button>
                          )}
                          <Button variant="ghost" size="sm" onClick={() => handleEditAIProvider(provider)} leftIcon={<Edit className="h-4 w-4" />}>Edit</Button>
                          <Button variant="ghost" size="sm" onClick={() => handleDeleteAIProvider(provider)} leftIcon={<Trash2 className="h-4 w-4" />} className="text-red-600 hover:text-red-700 hover:bg-red-50">Delete</Button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {hasTelephony && (
              <div>
                <div className="px-6 py-3 bg-green-50 border-b border-green-100">
                  <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-center gap-2">
                      <Phone className="h-4 w-4 text-green-600" />
                      <h3 className="text-sm font-semibold text-green-900">Telephony Providers</h3>
                      <span className="px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 rounded-full">{allTelephonyConfigs.length}</span>
                    </div>
                    <p className="text-xs text-green-800">
                      Phone numbers are managed on the Telephony Numbers page.
                    </p>
                  </div>
                </div>
                <div className="divide-y divide-gray-200">
                  {allTelephonyConfigs.map((cfg) => (
                  <div key={cfg.id} className="px-6 py-4 hover:bg-gray-50 transition-colors">
                    <div className="flex items-center gap-4">
                      {/* Name */}
                      <div className="flex flex-col min-w-[160px] max-w-[240px] flex-shrink-0">
                        <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Name</span>
                        <span className={`text-sm mt-0.5 truncate ${cfg.name ? 'font-semibold text-gray-900' : 'text-gray-400 italic'}`} title={cfg.name || ''}>
                          {cfg.name || '—'}
                        </span>
                      </div>
                      {/* Type */}
                      <div className="flex-shrink-0 min-w-[120px]">
                        <span className="px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 rounded-full whitespace-nowrap">Telephony</span>
                      </div>
                      {/* Logo + Provider */}
                      <div className="flex items-center gap-3 flex-1 min-w-0">
                        <div className="flex-shrink-0">
                          {getTelephonyProviderLogo(cfg.provider as TelephonyProvider) ? (
                            <div className="w-12 h-12 bg-white rounded-lg flex items-center justify-center border border-gray-200 p-2">
                              <img
                                src={getTelephonyProviderLogo(cfg.provider as TelephonyProvider)!}
                                alt={getTelephonyProviderLabel(cfg.provider as TelephonyProvider)}
                                className="w-full h-full object-contain"
                              />
                            </div>
                          ) : (
                            <div className="w-12 h-12 bg-gradient-to-br from-green-100 to-green-200 rounded-lg flex items-center justify-center"><Phone className="h-6 w-6 text-green-600" /></div>
                          )}
                        </div>
                        <div className="flex items-center gap-2 flex-wrap min-w-0">
                          <h3 className="text-base font-semibold text-gray-900 truncate">{getTelephonyProviderLabel(cfg.provider as TelephonyProvider)}</h3>
                          {cfg.is_default && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-700 rounded">
                              <Star className="h-3 w-3 fill-current" /> Default
                            </span>
                          )}
                          <span className={`px-2 py-0.5 text-xs font-medium rounded ${cfg.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}>{cfg.is_active ? 'Active' : 'Inactive'}</span>
                        </div>
                      </div>
                      {/* Actions */}
                      <div className="flex items-center gap-2 flex-shrink-0">
                        {!cfg.is_default && cfg.is_active && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setDefaultTelephonyMutation.mutate(cfg.id)}
                            isLoading={setDefaultTelephonyMutation.isPending && setDefaultTelephonyMutation.variables === cfg.id}
                            leftIcon={<Star className="h-4 w-4" />}
                          >
                            Set Default
                          </Button>
                        )}
                        <Button variant="ghost" size="sm" onClick={() => handleEditTelephony(cfg)} leftIcon={<Edit className="h-4 w-4" />}>Edit</Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDeleteTelephony(cfg)}
                          leftIcon={<Trash2 className="h-4 w-4" />}
                          className="text-red-600 hover:text-red-700 hover:bg-red-50"
                        >
                          Delete
                        </Button>
                      </div>
                    </div>
                  </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {!hasConfiguredIntegrations && (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <Plug className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No integrations configured</h3>
          <p className="text-gray-500">Get started by adding a voice platform, AI provider, or telephony provider</p>
        </div>
      )}

      {showLlmGatewayModal && renderModal(
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
          <div className="bg-white rounded-lg shadow-xl max-w-lg w-full mx-4 max-h-[90vh] overflow-y-auto">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <div className="flex items-center gap-2 min-w-0">
                <Network className="h-5 w-5 text-indigo-600 flex-shrink-0" />
                <h3 className="text-lg font-semibold text-gray-900 truncate">LLM Gateway</h3>
              </div>
              <button onClick={closeLlmGatewayModal} className="text-gray-400 hover:text-gray-600">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <p className="text-sm text-gray-600">
                Route batch and evaluation LLM calls through Bifrost or a self-hosted LiteLLM Proxy. Real-time voice agents are unaffected.
              </p>

              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`px-2.5 py-1 text-xs font-medium rounded-full ${
                    llmGatewaySettings?.effective_routing !== 'direct'
                      ? 'bg-indigo-100 text-indigo-800'
                      : 'bg-gray-100 text-gray-700'
                  }`}
                >
                  Effective routing: {llmGatewayRoutingLabel(llmGatewaySettings?.effective_routing || 'direct')}
                </span>
                {llmGatewaySettings?.effective_base_url && (
                  <span className="text-xs text-gray-500 truncate max-w-full">
                    {llmGatewaySettings.effective_base_url}
                  </span>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Organization mode</label>
                <select
                  value={llmGatewayMode}
                  onChange={(e) => setLlmGatewayMode(e.target.value as LLMGatewayMode)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                >
                  <option value="inherit">Inherit platform default</option>
                  <option value="enabled">Enabled (use gateway)</option>
                  <option value="disabled">Disabled (direct to providers)</option>
                </select>
              </div>

              {showLlmGatewayConfigOptions ? (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Gateway type</label>
                    <select
                      value={llmGatewayType}
                      onChange={(e) => setLlmGatewayType(e.target.value as LLMGatewayType)}
                      className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                    >
                      <option value="inherit">
                        Inherit platform ({llmGatewaySettings?.platform_gateway_type === 'litellm_proxy' ? 'LiteLLM Proxy' : 'Bifrost'})
                      </option>
                      <option value="bifrost">Bifrost</option>
                      <option value="litellm_proxy">LiteLLM Proxy</option>
                    </select>
                  </div>

                  {effectiveLlmGatewayType === 'bifrost' && (
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Bifrost API surface</label>
                      <select
                        value={llmGatewayInterface}
                        onChange={(e) => setLlmGatewayInterface(e.target.value as GatewayInterfaceMode)}
                        className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                      >
                        <option value="inherit">
                          Inherit platform ({llmGatewayInterfaceLabel(llmGatewaySettings?.platform_gateway_interface)})
                        </option>
                        <option value="litellm_shim">LiteLLM shim (/litellm)</option>
                        <option value="native_openai">Native OpenAI-compatible</option>
                      </select>
                      <p className="text-xs text-gray-500 mt-1">
                        Use native OpenAI-compatible for custom Bifrost models (e.g. Gemma) that do not work through the /litellm shim.
                      </p>
                    </div>
                  )}

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Base URL override</label>
                    <input
                      type="url"
                      value={llmGatewayBaseUrl}
                      onChange={(e) => setLlmGatewayBaseUrl(e.target.value)}
                      placeholder={
                        llmGatewaySettings?.platform_base_url ||
                        (effectiveLlmGatewayType === 'litellm_proxy'
                          ? 'http://localhost:4000'
                          : (llmGatewayInterface === 'native_openai' || llmGatewaySettings?.effective_gateway_interface === 'native_openai')
                            ? 'http://localhost:8080'
                            : 'http://localhost:8080/litellm')
                      }
                      className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                    />
                    <p className="text-xs text-gray-500 mt-1">
                      {effectiveLlmGatewayType === 'litellm_proxy'
                        ? 'LiteLLM Proxy base URL (e.g. http://localhost:4000). Leave blank to inherit the platform URL.'
                        : (llmGatewayInterface === 'native_openai' || llmGatewaySettings?.effective_gateway_interface === 'native_openai')
                          ? 'Bifrost host root only (e.g. http://localhost:8080). /v1 is added automatically. Do not include /v1/chat/completions.'
                          : 'Bifrost URL with /litellm path. Leave blank to inherit the platform URL.'}
                    </p>
                  </div>

                  {effectiveLlmGatewayType === 'bifrost' && (
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Virtual key (x-bf-vk)</label>
                      <input
                        type="password"
                        value={llmGatewayVirtualKey}
                        onChange={(e) => setLlmGatewayVirtualKey(e.target.value)}
                        placeholder={
                          llmGatewaySettings?.has_virtual_key
                            ? '•••••••• (stored — enter new value to replace)'
                            : 'Optional Bifrost virtual key'
                        }
                        className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                      />
                      {llmGatewaySettings?.has_virtual_key && (
                        <label className="mt-2 flex items-center gap-2 text-sm text-gray-600">
                          <input
                            type="checkbox"
                            checked={clearLlmGatewayVirtualKey}
                            onChange={(e) => setClearLlmGatewayVirtualKey(e.target.checked)}
                          />
                          Remove stored virtual key
                        </label>
                      )}
                    </div>
                  )}

                  {effectiveLlmGatewayType === 'litellm_proxy' && (
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Master key</label>
                      <input
                        type="password"
                        value={llmGatewayMasterKey}
                        onChange={(e) => setLlmGatewayMasterKey(e.target.value)}
                        placeholder={
                          llmGatewaySettings?.has_master_key
                            ? '•••••••• (stored — enter new value to replace)'
                            : 'Optional LiteLLM Proxy master key'
                        }
                        className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                      />
                      {llmGatewaySettings?.has_master_key && (
                        <label className="mt-2 flex items-center gap-2 text-sm text-gray-600">
                          <input
                            type="checkbox"
                            checked={clearLlmGatewayMasterKey}
                            onChange={(e) => setClearLlmGatewayMasterKey(e.target.checked)}
                          />
                          Remove stored master key
                        </label>
                      )}
                    </div>
                  )}

                  {llmGatewaySettings?.gateway_managed_credentials && (
                    <p className="text-xs text-indigo-700 bg-indigo-50 border border-indigo-100 rounded-md px-3 py-2">
                      Gateway-managed credentials are enabled. AI provider integrations can omit API keys when the gateway is active.
                    </p>
                  )}
                </>
              ) : (
                <p className="text-sm text-gray-500">
                  This organization will call LLM providers directly. Enable the gateway or inherit the platform default to configure gateway type, URL, and keys.
                </p>
              )}

              <div className="flex gap-3 pt-2">
                <Button type="button" variant="outline" onClick={closeLlmGatewayModal} className="flex-1">
                  Cancel
                </Button>
                <Button
                  type="button"
                  variant="primary"
                  onClick={() => updateLlmGatewayMutation.mutate()}
                  isLoading={updateLlmGatewayMutation.isPending}
                  className="flex-1"
                >
                  Save Gateway Settings
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showModal && renderModal(
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
          <div className={`bg-white rounded-lg shadow-xl w-full mx-4 max-h-[90vh] overflow-y-auto ${aiProviderUsesModelsStep && aiProviderWizardStep === 2 ? 'max-w-2xl' : 'max-w-md'}`}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <div>
                <h3 className="text-lg font-semibold">
                  {isEditMode
                    ? integrationType === 'ai_provider'
                      ? 'Edit AI Provider'
                      : integrationType === 'telephony_provider'
                        ? 'Edit Telephony Provider'
                        : 'Edit Integration'
                    : 'Add Integration'}
                </h3>
                {aiProviderUsesModelsStep ? (
                  <p className="mt-0.5 text-xs text-gray-500">
                    Step {aiProviderWizardStep} of 2 —{' '}
                    {aiProviderWizardStep === 1 ? 'Credentials' : 'Enabled models'}
                  </p>
                ) : isCustomAIProvider ? (
                  <p className="mt-0.5 text-xs text-gray-500">Custom Bifrost model integration</p>
                ) : null}
              </div>
              <button onClick={resetForm} className="text-gray-400 hover:text-gray-600"><X className="h-5 w-5" /></button>
            </div>
            <form onSubmit={handleSubmit} className="p-6 space-y-4">
              {!isEditMode && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Integration Type *</label>
                  <div className="grid grid-cols-3 gap-3">
                    <button type="button" onClick={() => { setIntegrationType('voice_platform'); setSelectedPlatform(null); setSelectedProvider(null); setSelectedTelephonyProvider(null) }}
                      className={`p-3 border-2 rounded-lg text-left transition-all ${integrationType === 'voice_platform' ? 'border-primary-500 bg-primary-50' : 'border-gray-200 hover:border-gray-300'}`}>
                      <div className="flex items-center gap-2"><Plug className="h-5 w-5 text-primary-600" /><span className="font-medium text-gray-900 text-sm">Voice Platform</span></div>
                      <p className="text-xs text-gray-600 mt-1">Retell, Vapi, etc.</p>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setIntegrationType('ai_provider')
                        setSelectedPlatform(null)
                        setSelectedProvider(null)
                        setAiProviderWizardStep(1)
                      }}
                      className={`p-3 border-2 rounded-lg text-left transition-all ${integrationType === 'ai_provider'
                        ? 'border-primary-500 bg-primary-50'
                        : 'border-gray-200 hover:border-gray-300'
                        }`}
                    >
                      <div className="flex items-center gap-2">
                        <Brain className="h-5 w-5 text-primary-600" />
                        <span className="font-medium text-gray-900">AI Provider</span>
                      </div>
                      <p className="text-xs text-gray-600 mt-1">OpenAI, Claude, Gemini, etc.</p>
                    </button>
                    <button type="button" onClick={() => { setIntegrationType('telephony_provider'); setSelectedPlatform(null); setSelectedProvider(null); setSelectedTelephonyProvider(null) }}
                      className={`p-3 border-2 rounded-lg text-left transition-all ${integrationType === 'telephony_provider' ? 'border-green-500 bg-green-50' : 'border-gray-200 hover:border-gray-300'}`}>
                      <div className="flex items-center gap-2"><Phone className="h-5 w-5 text-green-600" /><span className="font-medium text-gray-900 text-sm">Telephony</span></div>
                      <p className="text-xs text-gray-600 mt-1">Plivo, Twilio, etc.</p>
                    </button>
                  </div>
                </div>
              )}

              {integrationType === 'voice_platform' && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Platform *</label>
                    <div className="relative" ref={platformDropdownRef}>
                      <button type="button" onClick={() => setShowPlatformDropdown(!showPlatformDropdown)} disabled={isEditMode || availablePlatforms.length === 0}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white text-left flex items-center justify-between disabled:bg-gray-100 disabled:cursor-not-allowed">
                        <div className="flex items-center gap-2">
                          {selectedPlatform ? (() => { const pi = getPlatformInfo(selectedPlatform as IntegrationPlatform); return (<>{pi?.image ? <img src={pi.image} alt={pi.name} className="w-5 h-5 object-contain" /> : <Plug className="h-5 w-5 text-primary-600" />}<span>{pi?.name || selectedPlatform}</span></>)})() : <span className="text-gray-500">Select a platform</span>}
                        </div>
                        <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${showPlatformDropdown ? 'transform rotate-180' : ''}`} />
                      </button>
                      {showPlatformDropdown && availablePlatforms.length > 0 && (
                        <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-auto">
                          {availablePlatforms.map((platform) => (
                            <button
                              key={platform.id}
                              type="button"
                              onClick={() => {
                                setSelectedPlatform(platform.id as 'retell' | 'vapi' | 'cartesia' | 'elevenlabs' | 'deepgram' | 'murf' | 'sarvam' | 'voicemaker' | 'smallest')
                                setShowPlatformDropdown(false)
                              }}
                              className="w-full px-3 py-2 text-left hover:bg-gray-50 flex items-center gap-2 transition-colors"
                            >
                              {platform.image ? (
                                <img
                                  src={platform.image}
                                  alt={platform.name}
                                  className="w-5 h-5 object-contain"
                                />
                              ) : (
                                <Plug className="h-5 w-5 text-primary-600" />
                              )}
                              <span>{platform.name}</span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                    {isEditMode && <p className="mt-1 text-xs text-gray-500">Platform cannot be changed after creation</p>}
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Name (Optional)</label>
                    <input type="text" value={name} onChange={(e) => setName(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500" placeholder="Integration name" />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">LLM Routing</label>
                    <select
                      value={credentialRoutingMode}
                      onChange={(e) => setCredentialRoutingMode(e.target.value as CredentialRoutingMode)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white"
                    >
                      <option value="inherit">Inherit org default</option>
                      <option value="gateway">Route via gateway</option>
                      <option value="direct">Direct API key</option>
                    </select>
                    <p className="mt-1 text-xs text-gray-500">
                      Applies to batch LLM workloads when this credential is used. Real-time voice agents always use direct API keys.
                    </p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">{selectedPlatform === IntegrationPlatform.VAPI ? 'Private API Key' : 'API Key'} {isEditMode && <span className="text-gray-500 font-normal">(leave empty to keep current)</span>}</label>
                    <input type="password" required={!isEditMode} value={apiKey} onChange={(e) => setApiKey(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                      placeholder={isEditMode ? "Enter new API key (optional)" : `Enter ${selectedPlatform === IntegrationPlatform.VAPI ? 'private ' : ''}API key`} />
                    {selectedPlatform === IntegrationPlatform.VAPI && (
                      <div className="mt-4">
                        <label className="block text-sm font-medium text-gray-700 mb-1">Public API Key {isEditMode && <span className="text-gray-500 font-normal">(leave empty to keep current)</span>}</label>
                        <input type="text" required={!isEditMode} value={publicKey} onChange={(e) => setPublicKey(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                          placeholder={isEditMode ? "Enter new public API key (optional)" : "Enter public API key"} />
                      </div>
                    )}
                    <p className="mt-1 text-xs text-gray-500">Your {selectedPlatform === IntegrationPlatform.VAPI ? 'API keys' : 'API key'} will be encrypted and stored securely</p>
                  </div>
                </>
              )}

              {integrationType === 'ai_provider' && aiProviderWizardStep === 1 && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Provider *</label>
                    <div className="relative" ref={providerDropdownRef}>
                      <button type="button" onClick={() => setShowProviderDropdown(!showProviderDropdown)} disabled={isEditMode || availableProviders.length === 0}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white text-left flex items-center justify-between disabled:bg-gray-100 disabled:cursor-not-allowed">
                        <div className="flex items-center gap-2">
                          {selectedProvider ? (<>{getProviderLogo(selectedProvider) ? <img src={getProviderLogo(selectedProvider)!} alt={getProviderLabel(selectedProvider)} className="w-5 h-5 object-contain" /> : <Brain className="h-5 w-5 text-primary-600" />}<span>{getProviderLabel(selectedProvider)}</span></>) : <span className="text-gray-500">Select a provider</span>}
                        </div>
                        <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${showProviderDropdown ? 'transform rotate-180' : ''}`} />
                      </button>
                      {showProviderDropdown && availableProviders.length > 0 && (
                        <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-auto">
                          {availableProviders.map((provider) => (
                            <button key={provider} type="button" onClick={() => { setSelectedProvider(provider); setShowProviderDropdown(false) }}
                              className="w-full px-3 py-2 text-left hover:bg-gray-50 flex items-center gap-2">
                              {getProviderLogo(provider) ? <img src={getProviderLogo(provider)!} alt={getProviderLabel(provider)} className="w-5 h-5 object-contain" /> : <Brain className="h-5 w-5 text-primary-600" />}
                              <span>{getProviderLabel(provider)}</span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                    {selectedProvider && <p className="mt-1 text-xs text-gray-500">{getProviderDescription(selectedProvider)}</p>}
                    {isEditMode && selectedAIProvider && <p className="mt-1 text-xs text-gray-500">Provider cannot be changed after creation</p>}
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Name (Optional)</label>
                    <input type="text" value={name} onChange={(e) => setName(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500" placeholder="e.g., OpenAI Production Key" />
                  </div>
                  {selectedProvider === ModelProvider.AZURE && (
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        Azure Endpoint URL *
                      </label>
                      <input
                        type="url"
                        required={!isEditMode}
                        value={azureEndpointUrl}
                        onChange={(e) => setAzureEndpointUrl(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                        placeholder="https://your-resource.openai.azure.com"
                      />
                      <p className="mt-1 text-xs text-gray-500">
                        Your Azure OpenAI resource root URL. You can also paste a full v1 URL — we normalize it automatically.
                      </p>
                    </div>
                  )}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">LLM Routing</label>
                    <select
                      value={credentialRoutingMode}
                      onChange={(e) => setCredentialRoutingMode(e.target.value as CredentialRoutingMode)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white"
                    >
                      <option value="inherit">Inherit org default</option>
                      <option value="gateway">Route via gateway</option>
                      <option value="direct">Direct API key</option>
                    </select>
                    <p className="mt-1 text-xs text-gray-500">
                      Controls whether batch/eval LLM calls use your org gateway or call the provider directly.
                    </p>
                  </div>
                  {showGatewayModelField && (
                    <>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        {isCustomAIProvider ? 'Custom model ID (Optional)' : 'Gateway Model (Optional)'}
                      </label>
                      <input
                        type="text"
                        value={gatewayModel}
                        onChange={(e) => setGatewayModel(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                        placeholder={isCustomAIProvider ? 'e.g. openai/gpt-4o or production-gpt4' : 'e.g., production-gpt4 or openai/gpt-4o'}
                      />
                      <p className="mt-1 text-xs text-gray-500">
                        {isCustomAIProvider
                          ? 'Bifrost model ID for this integration. Each custom credential pins one model.'
                          : 'Bifrost custom model ID sent when routing via gateway. Leave blank to use the workload-selected model.'}
                      </p>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Bifrost API surface</label>
                      <select
                        value={gatewayInterface}
                        onChange={(e) => setGatewayInterface(e.target.value as GatewayInterfaceMode)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white"
                      >
                        <option value="inherit">Inherit org default</option>
                        <option value="litellm_shim">LiteLLM shim (/litellm)</option>
                        <option value="native_openai">Native OpenAI-compatible</option>
                      </select>
                      <p className="mt-1 text-xs text-gray-500">
                        Override how this credential reaches Bifrost. Use native for custom models that fail through /litellm.
                      </p>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Gateway Base URL (Optional)</label>
                      <input
                        type="url"
                        value={gatewayBaseUrl}
                        onChange={(e) => setGatewayBaseUrl(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                        placeholder="e.g. http://localhost:8080"
                      />
                      {gatewayInterface === 'native_openai' && (
                        <p className="mt-1 text-xs text-gray-500">
                          Host root only. /v1 is added automatically — do not include /v1/chat/completions.
                        </p>
                      )}
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Gateway Auth Header (Optional)</label>
                      <input
                        type="text"
                        value={gatewayAuthHeader}
                        onChange={(e) => setGatewayAuthHeader(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                        placeholder="x-bf-vk"
                      />
                      <p className="mt-1 text-xs text-gray-500">
                        Header name for Bifrost auth. Defaults to <code>x-bf-vk</code> when blank.
                      </p>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Gateway Auth Secret Env Var (Optional)</label>
                      <input
                        type="text"
                        value={gatewayAuthSecretEnv}
                        onChange={(e) => setGatewayAuthSecretEnv(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                        placeholder="BIFROST_VIRTUAL_KEY"
                      />
                      <p className="mt-1 text-xs text-gray-500">
                        Read the auth secret from this environment variable at runtime (e.g. K8s secret). Overrides org virtual key.
                      </p>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        Gateway Auth Secret{' '}
                        {isEditMode && selectedAIProvider?.has_gateway_auth_secret ? (
                          <span className="text-gray-500 font-normal">(stored — enter new value to replace)</span>
                        ) : (
                          <span className="text-gray-500 font-normal">(optional inline secret)</span>
                        )}
                      </label>
                      <input
                        type="password"
                        value={gatewayAuthSecret}
                        onChange={(e) => setGatewayAuthSecret(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                        placeholder="Alternative to env var — encrypted at rest"
                      />
                      {isEditMode && selectedAIProvider?.has_gateway_auth_secret && (
                        <label className="mt-2 flex items-center gap-2 text-sm text-gray-600">
                          <input
                            type="checkbox"
                            checked={clearGatewayAuthSecret}
                            onChange={(e) => setClearGatewayAuthSecret(e.target.checked)}
                          />
                          Remove stored gateway auth secret
                        </label>
                      )}
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Gateway Extra Headers (Optional)</label>
                      <textarea
                        value={gatewayExtraHeadersJson}
                        onChange={(e) => setGatewayExtraHeadersJson(e.target.value)}
                        rows={4}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 font-mono text-sm"
                        placeholder={'{\n  "X-Custom-Tenant": "prod"\n}'}
                      />
                      <p className="mt-1 text-xs text-gray-500">
                        JSON object of additional HTTP headers sent with every gateway call. Auth header from above takes precedence if names collide.
                      </p>
                    </div>
                    </>
                  )}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      API Key{' '}
                      {isEditMode ? (
                        <span className="text-gray-500 font-normal">(leave empty to keep current)</span>
                      ) : showGatewayOptionalApiKeyUi ? (
                        aiProviderRequiresApiKey ? (
                          '*'
                        ) : (
                          <span className="text-gray-500 font-normal">
                            (optional — not needed for gateway routing)
                          </span>
                        )
                      ) : (
                        '*'
                      )}
                    </label>
                    <input
                      type="password"
                      required={!isEditMode && aiProviderRequiresApiKey}
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                      placeholder={
                        isEditMode
                          ? 'Enter new API key (optional)'
                          : showGatewayOptionalApiKeyUi
                            ? aiProviderRequiresApiKey
                              ? 'Enter API key'
                              : 'Leave blank when routing via Bifrost/gateway'
                            : 'Enter API key'
                      }
                    />
                    {showGatewayOptionalApiKeyUi ? (
                      <p className="mt-1 text-xs text-gray-500">
                        {credentialRoutingMode === 'direct'
                          ? 'Direct routing always requires a provider API key.'
                          : 'Gateway routing does not require a provider API key — Bifrost handles the model call. Add one only if you want to pass a provider secret through the gateway.'}
                      </p>
                    ) : (
                      <p className="mt-1 text-xs text-gray-500">
                        Your API key will be encrypted and stored securely
                      </p>
                    )}
                  </div>
                </>
              )}

              {aiProviderUsesModelsStep && aiProviderWizardStep === 2 && (selectedProvider || selectedAIProvider) && (
                <AIProviderEnabledModelsStep
                  provider={(selectedProvider || selectedAIProvider!.provider) as ModelProvider}
                  enabledModels={enabledModels}
                  onChange={setEnabledModels}
                  gatewayModel={gatewayModel}
                />
              )}

              {integrationType === 'telephony_provider' && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Provider *</label>
                    <div className="grid grid-cols-1 gap-2">
                      {Object.values(TelephonyProvider).map((tp) => {
                        const meta = TELEPHONY_PROVIDER_CONFIG[tp]
                        return (
                          <button key={tp} type="button" disabled={isEditMode} onClick={() => setSelectedTelephonyProvider(tp)}
                            className={`text-left rounded-lg border p-3 transition ${selectedTelephonyProvider === tp ? 'border-green-500 bg-green-50' : 'border-gray-200 hover:border-gray-300'} ${isEditMode ? 'opacity-75 cursor-not-allowed' : ''}`}>
                            <div className="flex items-center gap-2">
                              {meta?.logo ? (
                                <img src={meta.logo} alt={meta.label} className="w-5 h-5 object-contain" />
                              ) : (
                                <Phone className="h-4 w-4 text-green-600" />
                              )}
                              <span className="font-medium text-gray-900">{meta?.label || tp}</span>
                            </div>
                            <p className="text-xs text-gray-600 mt-1">{meta?.description}</p>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                  {selectedTelephonyProvider && (
                    <>
                      <div className="grid grid-cols-1 gap-4">
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">Name (Optional)</label>
                          <input
                            type="text"
                            value={telephonyName}
                            onChange={(e) => setTelephonyName(e.target.value)}
                            placeholder="Friendly name to distinguish multiple keys"
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500"
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            {selectedTelephonyProvider === TelephonyProvider.EXOTEL ? 'API Key' : 'Auth ID'} {isEditMode && <span className="text-gray-500 font-normal">(leave blank to keep current)</span>}
                          </label>
                          <input type="password" value={telephonyAuthId} onChange={(e) => setTelephonyAuthId(e.target.value)} required={!isEditMode}
                            placeholder={isEditMode ? 'Leave blank to keep current' : selectedTelephonyProvider === TelephonyProvider.EXOTEL ? 'Enter API Key' : 'Enter Auth ID'} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500" />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            {selectedTelephonyProvider === TelephonyProvider.EXOTEL ? 'API Token' : 'Auth Token'} {isEditMode && <span className="text-gray-500 font-normal">(leave blank to keep current)</span>}
                          </label>
                          <input type="password" value={telephonyAuthToken} onChange={(e) => setTelephonyAuthToken(e.target.value)} required={!isEditMode}
                            placeholder={isEditMode ? 'Leave blank to keep current' : selectedTelephonyProvider === TelephonyProvider.EXOTEL ? 'Enter API Token' : 'Enter Auth Token'} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500" />
                        </div>
                        {selectedTelephonyProvider === TelephonyProvider.EXOTEL && (
                          <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Account SID <span className="text-red-500">*</span></label>
                            <input type="text" value={telephonyVoiceAppId} onChange={(e) => setTelephonyVoiceAppId(e.target.value)}
                              required placeholder="Enter Exotel Account SID" className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500" />
                          </div>
                        )}
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">Verify App UUID <span className="text-gray-400 font-normal">(optional)</span></label>
                          <input type="text" value={telephonyVerifyAppUuid} onChange={(e) => setTelephonyVerifyAppUuid(e.target.value)}
                            placeholder="Optional: Verify App UUID" className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500" />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            {selectedTelephonyProvider === TelephonyProvider.EXOTEL ? 'API Host' : 'SIP Domain'} <span className="text-gray-400 font-normal">(optional)</span>
                          </label>
                          <input type="text" value={telephonySipDomain} onChange={(e) => setTelephonySipDomain(e.target.value)}
                            placeholder={selectedTelephonyProvider === TelephonyProvider.EXOTEL ? 'Optional: api.exotel.com or api.in.exotel.com' : 'Optional: SIP domain'} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500" />
                        </div>
                      </div>
                      <p className="text-xs text-gray-500">Credentials are encrypted and stored securely. Your browser never displays stored secrets.</p>
                    </>
                  )}
                </>
              )}

              {((integrationType === 'voice_platform' && (createIntegrationMutation.isError || updateIntegrationMutation.isError)) ||
                (integrationType === 'ai_provider' && (createAIProviderMutation.isError || updateAIProviderMutation.isError)) ||
                (integrationType === 'telephony_provider' && saveTelephonyConfigMutation.isError)) && (
                  <div className="rounded-md bg-red-50 p-4">
                    <div className="flex">
                      <AlertCircle className="h-5 w-5 text-red-400" />
                      <div className="ml-3">
                        <p className="text-sm text-red-800">
                          {integrationType === 'voice_platform'
                            ? ((createIntegrationMutation.error || updateIntegrationMutation.error as any)?.response?.data?.detail || (isEditMode ? 'Failed to update integration' : 'Failed to create integration'))
                            : integrationType === 'ai_provider'
                            ? ((createAIProviderMutation.error || updateAIProviderMutation.error as any)?.response?.data?.detail || (isEditMode ? 'Failed to update provider' : 'Failed to configure provider'))
                            : ((saveTelephonyConfigMutation.error as any)?.response?.data?.detail || (saveTelephonyConfigMutation.error as any)?.message || 'Failed to save telephony configuration')}
                        </p>
                      </div>
                    </div>
                  </div>
                )}

              <div className="flex gap-3 pt-4">
                <Button type="button" variant="outline" onClick={resetForm} className="flex-1">Cancel</Button>
                {aiProviderUsesModelsStep && aiProviderWizardStep === 2 ? (
                  <>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setAiProviderWizardStep(1)}
                      className="flex-1"
                    >
                      Back
                    </Button>
                    <Button
                      type="submit"
                      variant="primary"
                      isLoading={
                        isEditMode
                          ? updateAIProviderMutation.isPending
                          : createAIProviderMutation.isPending
                      }
                      className="flex-1"
                    >
                      {isEditMode ? 'Save provider' : 'Configure provider'}
                    </Button>
                  </>
                ) : isCustomAIProvider && integrationType === 'ai_provider' ? (
                  <Button
                    type="submit"
                    variant="primary"
                    isLoading={
                      isEditMode
                        ? updateAIProviderMutation.isPending
                        : createAIProviderMutation.isPending
                    }
                    className="flex-1"
                  >
                    {isEditMode ? 'Save provider' : 'Configure provider'}
                  </Button>
                ) : (
                  <Button
                    type="submit"
                    variant="primary"
                    isLoading={
                      integrationType === 'voice_platform'
                        ? isEditMode
                          ? updateIntegrationMutation.isPending
                          : createIntegrationMutation.isPending
                        : integrationType === 'ai_provider'
                          ? false
                          : integrationType === 'telephony_provider'
                            ? saveTelephonyConfigMutation.isPending
                            : false
                    }
                    disabled={!integrationType}
                    className="flex-1"
                  >
                    {integrationType === 'ai_provider'
                      ? 'Continue'
                      : isEditMode
                        ? integrationType === 'telephony_provider'
                          ? 'Update Telephony'
                          : 'Update Integration'
                        : integrationType === 'telephony_provider'
                          ? 'Configure Telephony'
                          : 'Add Integration'}
                  </Button>
                )}
              </div>
            </form>
          </div>
        </div>
      )}

      {showDeleteModal && integrationToDelete && renderModal(
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]" onClick={() => { setShowDeleteModal(false); setIntegrationToDelete(null); setDeleteDependencies(null) }}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Confirm Delete</h3>
              <button onClick={() => { setShowDeleteModal(false); setIntegrationToDelete(null); setDeleteDependencies(null) }} className="text-gray-400 hover:text-gray-600" disabled={deleteIntegrationMutation.isPending}><X className="h-5 w-5" /></button>
            </div>
            <div className="p-6">
              {deleteDependencies && (
                <div className="mb-4 p-4 bg-amber-50 border border-amber-200 rounded-lg">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <p className="text-sm font-medium text-amber-800 mb-2">This integration has dependent records</p>
                      <ul className="text-xs text-amber-700 space-y-1 mb-3">
                        {deleteDependencies.agents && <li>{deleteDependencies.agents} agent{deleteDependencies.agents !== 1 ? 's' : ''} (will be unlinked, not deleted)</li>}
                      </ul>
                      <p className="text-xs text-amber-700">Force deleting will remove the integration and unlink all agents using it.</p>
                    </div>
                  </div>
                </div>
              )}
              <div className="flex items-start gap-4 mb-6">
                <div className="flex-shrink-0"><div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center"><Trash2 className="h-6 w-6 text-red-600" /></div></div>
                <div className="flex-1">
                  <p className="text-sm text-gray-700 mb-2">Are you sure you want to delete this integration?</p>
                  <p className="text-sm font-semibold text-gray-900 mb-2">
                    {(() => { const pi = getPlatformInfo(integrationToDelete.platform); return pi?.name || integrationToDelete.platform })()}
                    {integrationToDelete.name && <span className="text-gray-500 font-normal ml-2">({integrationToDelete.name})</span>}
                  </p>
                  <p className="text-xs text-gray-500">This action cannot be undone. Any agents using this integration may stop working.</p>
                </div>
              </div>
              <div className="flex gap-3">
                <Button variant="outline" onClick={() => { setShowDeleteModal(false); setIntegrationToDelete(null); setDeleteDependencies(null) }} className="flex-1" disabled={deleteIntegrationMutation.isPending}>Cancel</Button>
                {deleteDependencies ? (
                  <Button variant="danger" onClick={() => confirmDeleteIntegration(true)} isLoading={deleteIntegrationMutation.isPending} leftIcon={!deleteIntegrationMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined} className="flex-1">Force Delete All</Button>
                ) : (
                  <Button variant="danger" onClick={() => confirmDeleteIntegration()} isLoading={deleteIntegrationMutation.isPending} leftIcon={!deleteIntegrationMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined} className="flex-1">Delete</Button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {showDeleteAIProviderModal && aiProviderToDelete && renderModal(
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]" onClick={() => { setShowDeleteAIProviderModal(false); setAIProviderToDelete(null) }}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Confirm Delete</h3>
              <button onClick={() => { setShowDeleteAIProviderModal(false); setAIProviderToDelete(null) }} className="text-gray-400 hover:text-gray-600" disabled={deleteAIProviderMutation.isPending}><X className="h-5 w-5" /></button>
            </div>
            <div className="p-6">
              <div className="flex items-start gap-4 mb-6">
                <div className="flex-shrink-0"><div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center"><Trash2 className="h-6 w-6 text-red-600" /></div></div>
                <div className="flex-1">
                  <p className="text-sm text-gray-700 mb-2">Are you sure you want to delete the <span className="font-semibold text-gray-900">{getProviderLabel(aiProviderToDelete.provider)}</span> configuration?</p>
                  {aiProviderToDelete.name && <p className="text-sm text-gray-600 mb-2">Name: <span className="font-medium">{aiProviderToDelete.name}</span></p>}
                  <p className="text-xs text-gray-500">This action cannot be undone. Any VoiceBundles using this provider may stop working.</p>
                </div>
              </div>
              <div className="flex gap-3">
                <Button variant="outline" onClick={() => { setShowDeleteAIProviderModal(false); setAIProviderToDelete(null) }} className="flex-1" disabled={deleteAIProviderMutation.isPending}>Cancel</Button>
                <Button variant="danger" onClick={confirmDeleteAIProvider} isLoading={deleteAIProviderMutation.isPending} leftIcon={!deleteAIProviderMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined} className="flex-1">Delete</Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showDeleteTelephonyModal && telephonyToDelete && renderModal(
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]" onClick={() => { setShowDeleteTelephonyModal(false); setTelephonyToDelete(null) }}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Confirm Delete</h3>
              <button onClick={() => { setShowDeleteTelephonyModal(false); setTelephonyToDelete(null) }} className="text-gray-400 hover:text-gray-600" disabled={deleteTelephonyMutation.isPending}><X className="h-5 w-5" /></button>
            </div>
            <div className="p-6">
              <div className="flex items-start gap-4 mb-6">
                <div className="flex-shrink-0"><div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center"><Trash2 className="h-6 w-6 text-red-600" /></div></div>
                <div className="flex-1">
                  <p className="text-sm text-gray-700 mb-2">Are you sure you want to delete the <span className="font-semibold text-gray-900">{getTelephonyProviderLabel(telephonyToDelete.provider as TelephonyProvider)}</span> configuration?</p>
                  {telephonyToDelete.name && <p className="text-sm text-gray-600 mb-2">Name: <span className="font-medium">{telephonyToDelete.name}</span></p>}
                  <p className="text-xs text-gray-500">This action cannot be undone. Phone numbers and agents linked to this credential may stop working.</p>
                </div>
              </div>
              <div className="flex gap-3">
                <Button variant="outline" onClick={() => { setShowDeleteTelephonyModal(false); setTelephonyToDelete(null) }} className="flex-1" disabled={deleteTelephonyMutation.isPending}>Cancel</Button>
                <Button variant="danger" onClick={confirmDeleteTelephony} isLoading={deleteTelephonyMutation.isPending} leftIcon={!deleteTelephonyMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined} className="flex-1">Delete</Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

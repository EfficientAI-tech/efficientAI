import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../lib/api'
import type { TelephonyPhoneNumberResponse } from '../../lib/api'
import { useState, useEffect, useRef, useMemo, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Plus, Trash2, X, AlertCircle, Plug, Edit, Brain, ChevronDown, Phone, RefreshCw, ShieldCheck, CheckCircle2 } from 'lucide-react'
import { IntegrationCreate, IntegrationPlatform, Integration, AIProvider, AIProviderCreate, ModelProvider, TelephonyProvider } from '../../types/api'
import Button from '../../components/Button'
import { useToast } from '../../hooks/useToast'
import {
  getProviderLabel,
  getProviderLogo,
  getProviderDescription,
  TELEPHONY_PROVIDER_CONFIG,
  getTelephonyProviderLabel,
  getTelephonyProviderDescription,
} from '../../config/providers'

type IntegrationType = 'voice_platform' | 'ai_provider' | 'telephony_provider' | null

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
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showDeleteAIProviderModal, setShowDeleteAIProviderModal] = useState(false)
  const [integrationToDelete, setIntegrationToDelete] = useState<Integration | null>(null)
  const [aiProviderToDelete, setAIProviderToDelete] = useState<AIProvider | null>(null)
  const [deleteDependencies, setDeleteDependencies] = useState<Record<string, number> | null>(null)
  const providerDropdownRef = useRef<HTMLDivElement>(null)
  const platformDropdownRef = useRef<HTMLDivElement>(null)

  // Telephony-specific state
  const [selectedTelephonyProvider, setSelectedTelephonyProvider] = useState<TelephonyProvider | null>(null)
  const [telephonyAuthId, setTelephonyAuthId] = useState('')
  const [telephonyAuthToken, setTelephonyAuthToken] = useState('')
  const [telephonyVerifyAppUuid, setTelephonyVerifyAppUuid] = useState('')
  const [telephonySipDomain, setTelephonySipDomain] = useState('')
  const [expandedTelephony, setExpandedTelephony] = useState<string | null>(null)

  const renderModal = (content: ReactNode) => {
    if (typeof document === 'undefined') return null
    return createPortal(content, document.body)
  }

  const { data: integrations = [] } = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
  })

  const { data: aiproviders = [] } = useQuery({
    queryKey: ['aiproviders'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const { data: telephonyConfig } = useQuery({
    queryKey: ['telephony-config'],
    queryFn: () => apiClient.getTelephonyConfig('plivo'),
    retry: false,
  })

  const { data: telephonyNumbers = [], isLoading: telephonyNumbersLoading } = useQuery({
    queryKey: ['telephony-numbers'],
    queryFn: () => apiClient.listTelephonyNumbers(),
    retry: false,
  })

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
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['aiproviders'] }); showToast('AI Provider configured successfully!', 'success'); resetForm() },
    onError: (error: any) => { showToast(`Failed to configure provider: ${error.response?.data?.detail || error.message}`, 'error') },
  })

  const updateAIProviderMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<AIProviderCreate> }) => apiClient.updateAIProvider(id, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['aiproviders'] }); showToast('AI Provider updated successfully!', 'success'); resetForm() },
    onError: (error: any) => { showToast(`Failed to update provider: ${error.response?.data?.detail || error.message}`, 'error') },
  })

  const deleteAIProviderMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteAIProvider(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['aiproviders'] }); showToast('AI Provider deleted successfully!', 'success'); setShowDeleteAIProviderModal(false); setAIProviderToDelete(null) },
    onError: (error: any) => { showToast(`Failed to delete provider: ${error.response?.data?.detail || error.message}`, 'error') },
  })

  const saveTelephonyConfigMutation = useMutation({
    mutationFn: async () => {
      const payload: Record<string, any> = { provider: selectedTelephonyProvider || 'plivo' }
      if (telephonyAuthId.trim()) payload.auth_id = telephonyAuthId.trim()
      if (telephonyAuthToken.trim()) payload.auth_token = telephonyAuthToken.trim()
      if (telephonyVerifyAppUuid.trim()) payload.verify_app_uuid = telephonyVerifyAppUuid.trim()
      if (telephonySipDomain.trim()) payload.sip_domain = telephonySipDomain.trim()
      if (telephonyConfig) return apiClient.updateTelephonyConfig(payload)
      if (!payload.auth_id || !payload.auth_token) throw new Error('Auth ID and Auth Token are required for first-time setup')
      return apiClient.createTelephonyConfig(payload as any)
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['telephony-config'] }); showToast('Telephony configuration saved successfully!', 'success'); resetForm() },
    onError: (error: any) => { showToast(error?.response?.data?.detail || error?.message || 'Failed to save telephony config', 'error') },
  })

  const testTelephonyMutation = useMutation({
    mutationFn: () => apiClient.testTelephonyConfig('plivo'),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['telephony-config'] }); showToast('Telephony connection test succeeded!', 'success') },
    onError: (error: any) => { showToast(error?.response?.data?.detail || error?.message || 'Connection test failed', 'error') },
  })

  const syncNumbersMutation = useMutation({
    mutationFn: () => apiClient.syncTelephonyNumbers(),
    onSuccess: (synced) => { queryClient.invalidateQueries({ queryKey: ['telephony-numbers'] }); showToast(`Synced ${synced.length} number(s) from provider.`, 'success') },
    onError: (error: any) => { showToast(error?.response?.data?.detail || error?.message || 'Failed to sync numbers', 'error') },
  })

  const updateNumberMutation = useMutation({
    mutationFn: ({ id, is_masking_pool }: { id: string; is_masking_pool: boolean }) => apiClient.updateTelephonyNumber(id, { is_masking_pool }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['telephony-numbers'] }); showToast('Number settings updated.', 'success') },
    onError: (error: any) => { showToast(error?.response?.data?.detail || error?.message || 'Failed to update number', 'error') },
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
    setApiKey(''); setPublicKey(''); setName('')
    setSelectedTelephonyProvider(null); setTelephonyAuthId(''); setTelephonyAuthToken(''); setTelephonyVerifyAppUuid(''); setTelephonySipDomain('')
  }

  const handleEdit = (integration: Integration) => {
    setIntegrationType('voice_platform')
    setSelectedIntegration(integration)
    setSelectedPlatform(integration.platform as 'retell' | 'vapi' | 'cartesia' | 'elevenlabs' | 'deepgram' | 'murf' | 'sarvam' | 'voicemaker' | 'smallest')
    setName(integration.name || '')
    setApiKey('') // Don't pre-fill API key for security
    setPublicKey(integration.public_key || '')
    setIsEditMode(true)
    setShowModal(true)
  }

  const handleEditAIProvider = (provider: AIProvider) => {
    setIntegrationType('ai_provider'); setSelectedAIProvider(provider); setSelectedProvider(provider.provider)
    setName(provider.name || ''); setApiKey(''); setShowProviderDropdown(false); setIsEditMode(true); setShowModal(true)
  }

  const handleEditTelephony = () => {
    setIntegrationType('telephony_provider'); setSelectedTelephonyProvider(TelephonyProvider.PLIVO)
    setTelephonyVerifyAppUuid(telephonyConfig?.verify_app_uuid || ''); setTelephonySipDomain(telephonyConfig?.sip_domain || '')
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
        if (Object.keys(updateData).length > 0) updateIntegrationMutation.mutate({ id: selectedIntegration.id, data: updateData })
        else resetForm()
      } else {
        if (!selectedPlatform || !apiKey) return
        createIntegrationMutation.mutate({ platform: selectedPlatform as IntegrationPlatform, api_key: apiKey, public_key: publicKey || undefined, name: name || undefined })
      }
    } else if (integrationType === 'ai_provider') {
      if (isEditMode && selectedAIProvider) {
        if (!apiKey.trim()) { showToast('Please enter an API key', 'error'); return }
        updateAIProviderMutation.mutate({ id: selectedAIProvider.id, data: { api_key: apiKey, name: name || null } })
      } else {
        if (!selectedProvider || !apiKey.trim()) { showToast('Please select a provider and enter an API key', 'error'); return }
        createAIProviderMutation.mutate({ provider: selectedProvider, api_key: apiKey, name: name || null })
      }
    } else if (integrationType === 'telephony_provider') {
      saveTelephonyConfigMutation.mutate()
    }
  }

  const handleDelete = (integration: Integration) => { setIntegrationToDelete(integration); setDeleteDependencies(null); setShowDeleteModal(true) }
  const handleDeleteAIProvider = (provider: AIProvider) => { setAIProviderToDelete(provider); setShowDeleteAIProviderModal(true) }
  const confirmDeleteIntegration = (force?: boolean) => { if (integrationToDelete) deleteIntegrationMutation.mutate({ id: integrationToDelete.id, force }) }
  const confirmDeleteAIProvider = () => { if (aiProviderToDelete) deleteAIProviderMutation.mutate(aiProviderToDelete.id) }

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
      description: 'Connect your Sarvam STT & TTS voice AI',
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

  const configuredPlatforms = new Set(integrations.map((i: Integration) => i.platform))
  const availablePlatforms = platforms.filter(p => !configuredPlatforms.has(p.id))
  const configuredProviders = new Set(aiproviders.map((p: AIProvider) => p.provider))
  const availableProviders = Object.values(ModelProvider).filter(p => !configuredProviders.has(p))
  const telephonyStatus = useMemo(() => { if (!telephonyConfig) return 'Not configured'; if (!telephonyConfig.is_active) return 'Configured (inactive)'; return 'Configured (active)' }, [telephonyConfig])
  const getPlatformInfo = (platformId: IntegrationPlatform) => platforms.find(p => p.id === platformId)
  const hasTelephony = !!telephonyConfig
  const totalConfigured = integrations.length + aiproviders.length + (hasTelephony ? 1 : 0)

  return (
    <div className="space-y-6">
      <ToastContainer />
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Integrations</h1>
          <p className="text-gray-600 mt-1">Connect with voice AI platforms, AI providers, and telephony providers</p>
        </div>
        <Button variant="primary" onClick={() => setShowModal(true)} leftIcon={<Plus className="h-5 w-5" />}>Add Integration</Button>
      </div>

      {totalConfigured > 0 && (
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
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-4 flex-1">
                            <div className="flex-shrink-0">
                              {platformInfo?.image ? (
                                <div className="w-12 h-12 bg-white rounded-lg flex items-center justify-center border border-gray-200 p-2"><img src={platformInfo.image} alt={platformInfo.name} className="w-full h-full object-contain" /></div>
                              ) : (
                                <div className="w-12 h-12 bg-gradient-to-br from-primary-100 to-primary-200 rounded-lg flex items-center justify-center"><Plug className="h-6 w-6 text-primary-600" /></div>
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                <h3 className="text-lg font-semibold text-gray-900">{platformInfo?.name || integration.platform}</h3>
                                <span className="px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 rounded-full">Voice Platform</span>
                                {integration.name && <span className="text-sm text-gray-500">({integration.name})</span>}
                                {!integration.is_active && <span className="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded">Inactive</span>}
                              </div>
                              <p className="text-sm text-gray-600 mt-1">{platformInfo?.description || 'Voice AI platform integration'}</p>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
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

            {aiproviders.length > 0 && (
              <div className="border-b border-gray-200">
                <div className="px-6 py-3 bg-purple-50 border-b border-purple-100">
                  <div className="flex items-center gap-2">
                    <Brain className="h-4 w-4 text-purple-600" />
                    <h3 className="text-sm font-semibold text-purple-900">AI Providers</h3>
                    <span className="px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-700 rounded-full">{aiproviders.length}</span>
                  </div>
                </div>
                <div className="divide-y divide-gray-200">
                  {aiproviders.map((provider: AIProvider) => (
                    <div key={provider.id} className="px-6 py-4 hover:bg-gray-50 transition-colors">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-4 flex-1">
                          <div className="flex-shrink-0">
                            {getProviderLogo(provider.provider) ? (
                              <div className="w-12 h-12 bg-white rounded-lg flex items-center justify-center border border-gray-200 p-2"><img src={getProviderLogo(provider.provider)!} alt={getProviderLabel(provider.provider)} className="w-full h-full object-contain" /></div>
                            ) : (
                              <div className="w-12 h-12 bg-gradient-to-br from-primary-100 to-primary-200 rounded-lg flex items-center justify-center"><Brain className="h-6 w-6 text-primary-600" /></div>
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <h3 className="text-lg font-semibold text-gray-900">{getProviderLabel(provider.provider)}</h3>
                              <span className="px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-700 rounded-full">AI Provider</span>
                              {provider.name && <span className="text-sm text-gray-500">({provider.name})</span>}
                              {!provider.is_active && <span className="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded">Inactive</span>}
                            </div>
                            <p className="text-sm text-gray-600 mt-1">{getProviderDescription(provider.provider)}</p>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
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
                  <div className="flex items-center gap-2">
                    <Phone className="h-4 w-4 text-green-600" />
                    <h3 className="text-sm font-semibold text-green-900">Telephony Providers</h3>
                    <span className="px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 rounded-full">1</span>
                  </div>
                </div>
                <div>
                  <div className="px-6 py-4 hover:bg-gray-50 transition-colors">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-4 flex-1">
                        <div className="flex-shrink-0">
                          <div className="w-12 h-12 bg-gradient-to-br from-green-100 to-green-200 rounded-lg flex items-center justify-center"><Phone className="h-6 w-6 text-green-600" /></div>
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <h3 className="text-lg font-semibold text-gray-900">{getTelephonyProviderLabel(telephonyConfig!.provider as TelephonyProvider)}</h3>
                            <span className="px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 rounded-full">Telephony</span>
                            <span className={`px-2 py-0.5 text-xs font-medium rounded ${telephonyConfig!.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}>{telephonyStatus}</span>
                          </div>
                          <p className="text-sm text-gray-600 mt-1">{getTelephonyProviderDescription(telephonyConfig!.provider as TelephonyProvider)}</p>
                          {telephonyConfig!.last_tested_at && (
                            <div className="flex items-center gap-1 mt-1 text-xs text-green-700"><CheckCircle2 className="h-3 w-3" />Last tested: {new Date(telephonyConfig!.last_tested_at).toLocaleString()}</div>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button variant="ghost" size="sm" onClick={() => testTelephonyMutation.mutate()} isLoading={testTelephonyMutation.isPending} leftIcon={!testTelephonyMutation.isPending ? <ShieldCheck className="h-4 w-4" /> : undefined}>Test</Button>
                        <Button variant="ghost" size="sm" onClick={() => setExpandedTelephony(expandedTelephony ? null : telephonyConfig!.id)} leftIcon={<Phone className="h-4 w-4" />}>Numbers</Button>
                        <Button variant="ghost" size="sm" onClick={handleEditTelephony} leftIcon={<Edit className="h-4 w-4" />}>Edit</Button>
                      </div>
                    </div>
                    {expandedTelephony === telephonyConfig!.id && (
                      <div className="mt-4 border-t border-gray-100 pt-4">
                        <div className="flex items-center justify-between mb-3">
                          <h4 className="text-sm font-semibold text-gray-800">Phone Numbers</h4>
                          <Button variant="secondary" size="sm" onClick={() => syncNumbersMutation.mutate()} isLoading={syncNumbersMutation.isPending} leftIcon={!syncNumbersMutation.isPending ? <RefreshCw className="h-4 w-4" /> : undefined}>Sync Numbers</Button>
                        </div>
                        {telephonyNumbersLoading ? (
                          <p className="text-sm text-gray-500">Loading numbers...</p>
                        ) : telephonyNumbers.length === 0 ? (
                          <p className="text-sm text-gray-500">No numbers synced yet. Click <strong>Sync Numbers</strong> to pull from your provider.</p>
                        ) : (
                          <div className="divide-y divide-gray-100 border border-gray-200 rounded-lg">
                            {telephonyNumbers.map((num: TelephonyPhoneNumberResponse) => (
                              <div key={num.id} className="px-4 py-3 flex items-center justify-between">
                                <div>
                                  <div className="text-sm font-semibold text-gray-900">{num.phone_number}</div>
                                  <div className="text-xs text-gray-500">{num.country_iso2 || 'N/A'} &bull; {num.region || 'Unknown'} &bull; {num.number_type || 'Unknown'}</div>
                                </div>
                                <label className="flex items-center gap-2 text-sm text-gray-700">
                                  <input type="checkbox" checked={num.is_masking_pool} onChange={(e) => updateNumberMutation.mutate({ id: num.id, is_masking_pool: e.target.checked })} />
                                  Masking Pool
                                </label>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {totalConfigured === 0 && (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <Plug className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No integrations configured</h3>
          <p className="text-gray-500">Get started by adding a voice platform, AI provider, or telephony provider</p>
        </div>
      )}

      {showModal && renderModal(
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[9999]">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4 max-h-[90vh] overflow-y-auto">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">{isEditMode ? (integrationType === 'ai_provider' ? 'Edit AI Provider' : integrationType === 'telephony_provider' ? 'Edit Telephony Provider' : 'Edit Integration') : 'Add Integration'}</h3>
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
                    <button type="button" onClick={() => { setIntegrationType('ai_provider'); setSelectedPlatform(null); setSelectedProvider(null); setSelectedTelephonyProvider(null) }}
                      className={`p-3 border-2 rounded-lg text-left transition-all ${integrationType === 'ai_provider' ? 'border-primary-500 bg-primary-50' : 'border-gray-200 hover:border-gray-300'}`}>
                      <div className="flex items-center gap-2"><Brain className="h-5 w-5 text-primary-600" /><span className="font-medium text-gray-900 text-sm">AI Provider</span></div>
                      <p className="text-xs text-gray-600 mt-1">OpenAI, Anthropic, etc.</p>
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

              {integrationType === 'ai_provider' && (
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
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">API Key *</label>
                    <input type="password" required value={apiKey} onChange={(e) => setApiKey(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                      placeholder={isEditMode ? "Enter new API key" : "Enter API key"} />
                    <p className="mt-1 text-xs text-gray-500">Your API key will be encrypted and stored securely</p>
                  </div>
                </>
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
                            <div className="flex items-center gap-2"><Phone className="h-4 w-4 text-green-600" /><span className="font-medium text-gray-900">{meta?.label || tp}</span></div>
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
                          <label className="block text-sm font-medium text-gray-700 mb-1">Auth ID {isEditMode && <span className="text-gray-500 font-normal">(leave blank to keep current)</span>}</label>
                          <input type="password" value={telephonyAuthId} onChange={(e) => setTelephonyAuthId(e.target.value)} required={!isEditMode}
                            placeholder={isEditMode ? 'Leave blank to keep current' : 'Enter Auth ID'} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500" />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">Auth Token {isEditMode && <span className="text-gray-500 font-normal">(leave blank to keep current)</span>}</label>
                          <input type="password" value={telephonyAuthToken} onChange={(e) => setTelephonyAuthToken(e.target.value)} required={!isEditMode}
                            placeholder={isEditMode ? 'Leave blank to keep current' : 'Enter Auth Token'} className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500" />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">Verify App UUID <span className="text-gray-400 font-normal">(optional)</span></label>
                          <input type="text" value={telephonyVerifyAppUuid} onChange={(e) => setTelephonyVerifyAppUuid(e.target.value)}
                            placeholder="Optional: Verify App UUID" className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500" />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">SIP Domain <span className="text-gray-400 font-normal">(optional)</span></label>
                          <input type="text" value={telephonySipDomain} onChange={(e) => setTelephonySipDomain(e.target.value)}
                            placeholder="Optional: SIP domain" className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500" />
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
                <Button type="submit" variant="primary"
                  isLoading={integrationType === 'voice_platform' ? (isEditMode ? updateIntegrationMutation.isPending : createIntegrationMutation.isPending) : integrationType === 'ai_provider' ? (isEditMode ? updateAIProviderMutation.isPending : createAIProviderMutation.isPending) : saveTelephonyConfigMutation.isPending}
                  disabled={!integrationType} className="flex-1">
                  {isEditMode ? (integrationType === 'ai_provider' ? 'Update Provider' : integrationType === 'telephony_provider' ? 'Update Telephony' : 'Update Integration') : (integrationType === 'ai_provider' ? 'Configure Provider' : integrationType === 'telephony_provider' ? 'Configure Telephony' : 'Add Integration')}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showDeleteModal && integrationToDelete && renderModal(
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[9999]" onClick={() => { setShowDeleteModal(false); setIntegrationToDelete(null); setDeleteDependencies(null) }}>
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
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[9999]" onClick={() => { setShowDeleteAIProviderModal(false); setAIProviderToDelete(null) }}>
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
    </div>
  )
}

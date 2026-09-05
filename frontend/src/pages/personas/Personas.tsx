import { useState, useMemo, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createPortal } from 'react-dom'
import {
  Users,
  Plus,
  Edit,
  Trash2,
  X,
  Loader2,
  UserPlus,
  ChevronDown,
  AlertCircle,
  Mic,
  PlusCircle,
  Upload,
  Volume2,
} from 'lucide-react'
import { apiClient } from '../../lib/api'
import { useToast } from '../../hooks/useToast'
import Button from '../../components/Button'
import ProviderLogo, { getProviderInfo } from '../../components/shared/ProviderLogo'
import WalkthroughToggleButton from '../../components/walkthrough/WalkthroughToggleButton'
import PersonaTile from './PersonaTile'
import PersonaEditModal from './PersonaEditModal'
import PersonaTabContent from './PersonaTabContent'
import AmbientNoiseLibraryPanel from './AmbientNoiseLibraryPanel'
import UploadAmbientNoiseModal from './UploadAmbientNoiseModal'
import {
  emptyPersonaFormData,
  personaPayload,
  personaUpdatePayload,
  type Persona,
  type PersonaFormData,
  type ProviderOption,
  PERSONA_TILE_TABS,
  type PersonaTileTab,
} from './personaTypes'

export default function Personas() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()

  // Tab state
  const [activeTab, setActiveTab] = useState<'personas' | 'custom-voices' | 'ambient-noises'>('personas')

  // Modal state
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [createTab, setCreateTab] = useState<PersonaTileTab>('prompt')
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showCustomVoiceModal, setShowCustomVoiceModal] = useState(false)
  const [showEditCustomVoiceModal, setShowEditCustomVoiceModal] = useState(false)
  const [deleteCustomVoiceConfirm, setDeleteCustomVoiceConfirm] = useState<{ id: string; name: string } | null>(null)
  const [editingCustomVoice, setEditingCustomVoice] = useState<any>(null)
  const [selectedPersona, setSelectedPersona] = useState<Persona | null>(null)
  const [editingPersona, setEditingPersona] = useState<Persona | null>(null)
  const [savingPersonaId, setSavingPersonaId] = useState<string | null>(null)
  const [deleteDependencies, setDeleteDependencies] = useState<Record<string, number> | null>(null)
  const [showAmbientUpload, setShowAmbientUpload] = useState(false)

  // Persona form (create modal only)
  const [formData, setFormData] = useState<PersonaFormData>(emptyPersonaFormData())

  // Custom voice form
  const [customVoiceForm, setCustomVoiceForm] = useState({
    provider: '',
    voice_id: '',
    name: '',
    gender: '',
    description: '',
  })

  const renderModal = (content: ReactNode) => {
    if (typeof document === 'undefined') return null
    return createPortal(content, document.body)
  }

  // Fetch personas
  const { data: personas = [], isLoading, error, isError } = useQuery({
    queryKey: ['personas'],
    queryFn: () => apiClient.listPersonas(),
    retry: 1,
  })

  // Fetch voice options
  const { data: voiceOptionsData } = useQuery({
    queryKey: ['persona-voice-options'],
    queryFn: () => apiClient.getPersonaVoiceOptions(),
    retry: 1,
  })

  // Fetch existing custom voices
  const { data: customVoices = [] } = useQuery({
    queryKey: ['persona-custom-voices'],
    queryFn: () => apiClient.listPersonaCustomVoices(),
    retry: 1,
  })

  const { data: ambientLibrary = [] } = useQuery({
    queryKey: ['ambient-library'],
    queryFn: () => apiClient.listAmbientLibrary(),
    retry: 1,
  })

  const providers: ProviderOption[] = useMemo(
    () => voiceOptionsData?.providers ?? [],
    [voiceOptionsData],
  )

  const userPersonas = useMemo(() => personas as Persona[], [personas])

  // Mutations
  const createMutation = useMutation({
    mutationFn: (data: PersonaFormData) => apiClient.createPersona(personaPayload(data)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['personas'] })
      showToast('Persona created successfully!', 'success')
      handleCloseCreateModal()
    },
    onError: (error: any) => {
      showToast(`Failed to create persona: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: ReturnType<typeof personaUpdatePayload> }) =>
      apiClient.updatePersona(id, payload),
    onMutate: ({ id }) => {
      setSavingPersonaId(id)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['personas'] })
      showToast('Persona saved', 'success')
      setEditingPersona(null)
    },
    onError: (error: any) => {
      showToast(`Failed to save persona: ${error.response?.data?.detail || error.message}`, 'error')
    },
    onSettled: () => {
      setSavingPersonaId(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: ({ id, force }: { id: string; force?: boolean }) => apiClient.deletePersona(id, force),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['personas'] })
      setShowDeleteModal(false)
      setSelectedPersona(null)
      setDeleteDependencies(null)
      showToast('Persona deleted successfully!', 'success')
    },
    onError: (error: any) => {
      const status = error.response?.status
      const detail = error.response?.data?.detail
      if (status === 409 && detail?.dependencies) {
        setDeleteDependencies(detail.dependencies)
        return
      }
      const errorMessage = typeof detail === 'string'
        ? detail
        : detail?.message || error.message || 'Failed to delete persona.'
      showToast(errorMessage, 'error')
    },
  })

  const createCustomVoiceMutation = useMutation({
    mutationFn: (data: typeof customVoiceForm) =>
      apiClient.createPersonaCustomVoice({
        provider: data.provider,
        voice_id: data.voice_id,
        name: data.name,
        gender: data.gender || undefined,
        description: data.description || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['persona-voice-options'] })
      queryClient.invalidateQueries({ queryKey: ['persona-custom-voices'] })
      showToast('Custom voice added successfully!', 'success')
      setShowCustomVoiceModal(false)
      resetCustomVoiceForm()
    },
    onError: (error: any) => {
      showToast(`Failed to add custom voice: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const deleteCustomVoiceMutation = useMutation({
    mutationFn: (customVoiceId: string) => apiClient.deletePersonaCustomVoice(customVoiceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['persona-custom-voices'] })
      queryClient.invalidateQueries({ queryKey: ['persona-voice-options'] })
      setDeleteCustomVoiceConfirm(null)
      showToast('Custom voice deleted', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to delete custom voice: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const updateCustomVoiceMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { voice_id?: string; name?: string; gender?: string; description?: string } }) =>
      apiClient.updatePersonaCustomVoice(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['persona-custom-voices'] })
      queryClient.invalidateQueries({ queryKey: ['persona-voice-options'] })
      setShowEditCustomVoiceModal(false)
      setEditingCustomVoice(null)
      resetCustomVoiceForm()
      showToast('Custom voice updated', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to update custom voice: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const resetForm = () => {
    setFormData(emptyPersonaFormData())
    setCreateTab('prompt')
  }

  const resetCustomVoiceForm = () => {
    setCustomVoiceForm({ provider: '', voice_id: '', name: '', gender: '', description: '' })
  }

  const openEditCustomVoiceModal = (cv: any) => {
    setEditingCustomVoice(cv)
    setCustomVoiceForm({
      provider: cv.provider,
      voice_id: cv.voice_id,
      name: cv.name,
      gender: cv.gender || '',
      description: cv.description || '',
    })
    setShowEditCustomVoiceModal(true)
  }

  const handleUpdateCustomVoice = (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingCustomVoice) return
    updateCustomVoiceMutation.mutate({
      id: editingCustomVoice.id,
      data: {
        voice_id: customVoiceForm.voice_id,
        name: customVoiceForm.name,
        gender: customVoiceForm.gender || undefined,
        description: customVoiceForm.description || undefined,
      },
    })
  }

  const openCreateModal = () => {
    resetForm()
    setSelectedPersona(null)
    setShowCreateModal(true)
  }

  const handleCloseCreateModal = () => {
    setShowCreateModal(false)
    resetForm()
  }

  const handleSavePersonaTile = (id: string, data: PersonaFormData) => {
    const existing = userPersonas.find((p) => p.id === id)
    const lockProvider = Boolean(existing?.tts_provider)
    updateMutation.mutate({ id, payload: personaUpdatePayload(data, lockProvider) })
  }

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    createMutation.mutate(formData)
  }

  const handleDelete = (persona: Persona) => {
    setSelectedPersona(persona)
    setDeleteDependencies(null)
    setShowDeleteModal(true)
  }

  const confirmDelete = (force?: boolean) => {
    if (selectedPersona) {
      deleteMutation.mutate({ id: selectedPersona.id, force })
    }
  }

  const handleCreateCustomVoice = (e: React.FormEvent) => {
    e.preventDefault()
    createCustomVoiceMutation.mutate(customVoiceForm)
  }

  const renderCreateTabContent = () => (
    <PersonaTabContent
      tab={createTab}
      draft={formData}
      onChange={setFormData}
      providers={providers}
      lockProvider={false}
      voiceFieldSize="md"
    />
  )

  // -- Loading / Error states --
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
        <span className="ml-3 text-gray-500">Loading personas...</span>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="bg-white rounded-lg shadow p-12 text-center">
        <div className="text-red-500 mb-4">
          <X className="h-12 w-12 mx-auto mb-2" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">Error loading personas</h3>
          <p className="text-gray-500 mb-4">
            {(error as any)?.response?.data?.detail || (error as any)?.message || 'Failed to load personas'}
          </p>
          <Button variant="ghost" onClick={() => queryClient.invalidateQueries({ queryKey: ['personas'] })}>
            Try again
          </Button>
        </div>
      </div>
    )
  }

  return (
    <>
      <ToastContainer />
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-3xl font-bold text-gray-900">Test Personas</h1>
            <p className="text-gray-600 mt-1">
              Configure test caller personas — prompt, voice, TTS, behavior, and environment
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2 pr-2">
            {activeTab === 'personas' ? (
              <Button
                variant="primary"
                onClick={openCreateModal}
                leftIcon={<Plus className="h-5 w-5" />}
              >
                Create Persona
              </Button>
            ) : activeTab === 'custom-voices' ? (
              <Button
                variant="primary"
                onClick={() => setShowCustomVoiceModal(true)}
                leftIcon={<PlusCircle className="h-5 w-5" />}
              >
                Add Custom Voice
              </Button>
            ) : (
              <Button
                variant="primary"
                onClick={() => setShowAmbientUpload(true)}
                leftIcon={<Upload className="h-5 w-5" />}
              >
                Upload Audio
              </Button>
            )}
            <WalkthroughToggleButton />
          </div>
        </div>

        {/* Tab Nav */}
        <div className="border-b border-gray-200">
          <nav className="-mb-px flex gap-6" aria-label="Tabs">
            <button
              onClick={() => setActiveTab('personas')}
              className={`flex items-center gap-2 whitespace-nowrap border-b-2 py-3 px-1 text-sm font-medium transition-colors ${
                activeTab === 'personas'
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
              }`}
            >
              <UserPlus className="h-4 w-4" />
              Personas
              {userPersonas.length > 0 && (
                <span className={`ml-1 rounded-full px-2 py-0.5 text-xs font-medium ${
                  activeTab === 'personas' ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600'
                }`}>
                  {userPersonas.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab('custom-voices')}
              className={`flex items-center gap-2 whitespace-nowrap border-b-2 py-3 px-1 text-sm font-medium transition-colors ${
                activeTab === 'custom-voices'
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
              }`}
            >
              <Mic className="h-4 w-4" />
              Custom Voices
              {customVoices.length > 0 && (
                <span className={`ml-1 rounded-full px-2 py-0.5 text-xs font-medium ${
                  activeTab === 'custom-voices' ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600'
                }`}>
                  {customVoices.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab('ambient-noises')}
              className={`flex items-center gap-2 whitespace-nowrap border-b-2 py-3 px-1 text-sm font-medium transition-colors ${
                activeTab === 'ambient-noises'
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
              }`}
            >
              <Volume2 className="h-4 w-4" />
              Background Noise
              {ambientLibrary.length > 0 && (
                <span className={`ml-1 rounded-full px-2 py-0.5 text-xs font-medium ${
                  activeTab === 'ambient-noises' ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600'
                }`}>
                  {ambientLibrary.length}
                </span>
              )}
            </button>
          </nav>
        </div>

        {/* ===================== PERSONAS TAB ===================== */}
        {activeTab === 'personas' && (
          <>
            {personas.length === 0 ? (
              <div className="bg-white rounded-lg shadow p-12 text-center">
                <Users className="w-12 h-12 text-gray-400 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-gray-900 mb-2">No personas yet</h3>
                <p className="text-gray-500 mb-4">Create your first voice persona to get started</p>
                <Button variant="ghost" onClick={openCreateModal}>
                  Create Persona
                </Button>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {userPersonas.map((persona) => (
                  <PersonaTile
                    key={persona.id}
                    persona={persona}
                    onClick={setEditingPersona}
                    onDelete={handleDelete}
                  />
                ))}
              </div>
            )}
          </>
        )}

        {/* ===================== CUSTOM VOICES TAB ===================== */}
        {activeTab === 'custom-voices' && (
          <>
            {customVoices.length === 0 ? (
              <div className="bg-white rounded-lg shadow p-12 text-center">
                <Mic className="w-12 h-12 text-gray-400 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-gray-900 mb-2">No custom voices yet</h3>
                <p className="text-gray-500 mb-4">
                  Register voice IDs from your TTS providers to use them when creating personas
                </p>
                <Button variant="ghost" onClick={() => setShowCustomVoiceModal(true)}>
                  Add Custom Voice
                </Button>
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {customVoices.map((cv: any) => {
                  const providerInfo = getProviderInfo(cv.provider)
                  return (
                    <div
                      key={cv.id}
                      className="bg-white rounded-xl border border-gray-200 shadow-sm hover:shadow-md transition-shadow overflow-hidden"
                    >
                      <div className="p-5">
                        <div className="flex items-start justify-between mb-4">
                          <div className="flex items-center gap-3 min-w-0">
                            <ProviderLogo provider={cv.provider} size="md" />
                            <div className="min-w-0">
                              <h3 className="text-sm font-semibold text-gray-900 truncate">{cv.name}</h3>
                              <span className="text-xs text-gray-500">{providerInfo.label}</span>
                            </div>
                          </div>
                          <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                            <button
                              onClick={() => openEditCustomVoiceModal(cv)}
                              className="p-1.5 text-gray-400 hover:text-blue-500 hover:bg-blue-50 rounded-lg transition-colors"
                              title="Edit custom voice"
                            >
                              <Edit className="h-4 w-4" />
                            </button>
                            <button
                              onClick={() => setDeleteCustomVoiceConfirm({ id: cv.id, name: cv.name })}
                              className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                              title="Delete custom voice"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        </div>

                        {cv.description && (
                          <p className="text-xs text-gray-500 mb-3 line-clamp-2">{cv.description}</p>
                        )}

                        <div className="space-y-2.5">
                          <div className="flex items-center justify-between">
                            <span className="text-xs text-gray-500">Voice ID</span>
                            <code className="text-[11px] bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded font-mono max-w-[160px] truncate" title={cv.voice_id}>
                              {cv.voice_id}
                            </code>
                          </div>

                          <div className="flex items-center justify-between">
                            <span className="text-xs text-gray-500">Gender</span>
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800 capitalize">
                              {cv.gender || 'Unknown'}
                            </span>
                          </div>

                          {cv.created_at && (
                            <div className="flex items-center justify-between pt-1 border-t border-gray-100">
                              <span className="text-xs text-gray-400">Added</span>
                              <span className="text-xs text-gray-400">
                                {new Date(cv.created_at).toLocaleDateString()}
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </>
        )}

        {/* ===================== BACKGROUND NOISE TAB ===================== */}
        {activeTab === 'ambient-noises' && <AmbientNoiseLibraryPanel />}

        {/* ===================== EDIT PERSONA MODAL ===================== */}
        {editingPersona && renderModal(
          <PersonaEditModal
            persona={editingPersona}
            providers={providers}
            isSaving={savingPersonaId === editingPersona.id && updateMutation.isPending}
            onSave={handleSavePersonaTile}
            onClose={() => setEditingPersona(null)}
          />,
        )}

        {/* ===================== CREATE PERSONA MODAL ===================== */}
        {showCreateModal && renderModal(
          <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
            <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-hidden flex flex-col">
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                <h3 className="text-lg font-semibold">Create Persona</h3>
                <button onClick={handleCloseCreateModal} className="text-gray-400 hover:text-gray-600">
                  <X className="h-5 w-5" />
                </button>
              </div>
              <form onSubmit={handleCreate} className="flex flex-col flex-1 min-h-0">
                <div className="px-6 pt-4">
                  <label className="block text-sm font-medium text-gray-700 mb-1">Name *</label>
                  <input
                    type="text"
                    required
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    placeholder="e.g. Friendly Customer"
                  />
                </div>
                <div className="px-6 pt-4 border-b border-gray-100">
                  <nav className="flex gap-1 overflow-x-auto" aria-label="Create persona sections">
                    {PERSONA_TILE_TABS.map((tab) => (
                      <button
                        key={tab.id}
                        type="button"
                        onClick={() => setCreateTab(tab.id)}
                        className={`whitespace-nowrap px-3 py-2 text-xs font-medium rounded-t-lg border-b-2 transition-colors ${
                          createTab === tab.id
                            ? 'border-primary-500 text-primary-700 bg-primary-50/60'
                            : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                        }`}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </nav>
                </div>
                <div className="p-6 overflow-y-auto flex-1 space-y-4 min-h-[280px]">
                  {renderCreateTabContent()}
                </div>
                <div className="px-6 pb-6 flex gap-3">
                  <Button type="button" variant="outline" onClick={handleCloseCreateModal} className="flex-1">
                    Cancel
                  </Button>
                  <Button type="submit" variant="primary" isLoading={createMutation.isPending} className="flex-1">
                    Create
                  </Button>
                </div>
              </form>
            </div>
          </div>,
        )}

        {/* ===================== DELETE MODAL ===================== */}
        {showDeleteModal && selectedPersona && renderModal(
          <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]" onClick={() => { setShowDeleteModal(false); setSelectedPersona(null); setDeleteDependencies(null) }}>
            <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                <h3 className="text-lg font-semibold text-gray-900">Delete Persona</h3>
                <button onClick={() => { setShowDeleteModal(false); setSelectedPersona(null); setDeleteDependencies(null) }} className="text-gray-400 hover:text-gray-600">
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-6">
                {deleteDependencies && (
                  <div className="mb-4 p-4 bg-amber-50 border border-amber-200 rounded-lg">
                    <div className="flex items-start gap-3">
                      <AlertCircle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
                      <div className="flex-1">
                        <p className="text-sm font-medium text-amber-800 mb-2">This persona has dependent records</p>
                        <ul className="text-xs text-amber-700 space-y-1 mb-3">
                          {deleteDependencies.evaluators && <li>{deleteDependencies.evaluators} evaluator{deleteDependencies.evaluators !== 1 ? 's' : ''}</li>}
                          {deleteDependencies.evaluator_results && <li>{deleteDependencies.evaluator_results} evaluator result{deleteDependencies.evaluator_results !== 1 ? 's' : ''}</li>}
                          {deleteDependencies.test_conversations && <li>{deleteDependencies.test_conversations} test conversation{deleteDependencies.test_conversations !== 1 ? 's' : ''}</li>}
                        </ul>
                        <p className="text-xs text-amber-700">Force deleting will remove the persona and all its dependent records.</p>
                      </div>
                    </div>
                  </div>
                )}
                <div className="flex items-start gap-4 mb-6">
                  <div className="flex-shrink-0">
                    <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
                      <Trash2 className="h-6 w-6 text-red-600" />
                    </div>
                  </div>
                  <div className="flex-1">
                    <p className="text-sm text-gray-700 mb-2">
                      Are you sure you want to delete <span className="font-semibold text-gray-900">"{selectedPersona.name}"</span>?
                    </p>
                    <p className="text-xs text-gray-500">This action cannot be undone.</p>
                  </div>
                </div>
                <div className="flex gap-3">
                  <Button variant="outline" onClick={() => { setShowDeleteModal(false); setSelectedPersona(null); setDeleteDependencies(null) }} className="flex-1">
                    Cancel
                  </Button>
                  {deleteDependencies ? (
                    <Button variant="danger" onClick={() => confirmDelete(true)} isLoading={deleteMutation.isPending} leftIcon={!deleteMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined} className="flex-1">
                      Force Delete All
                    </Button>
                  ) : (
                    <Button variant="danger" onClick={() => confirmDelete()} isLoading={deleteMutation.isPending} leftIcon={!deleteMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined} className="flex-1">
                      Delete
                    </Button>
                  )}
                </div>
              </div>
            </div>
          </div>,
        )}

        {/* ===================== ADD CUSTOM VOICE MODAL ===================== */}
        {showCustomVoiceModal && renderModal(
          <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
            <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                <h3 className="text-lg font-semibold">Add Custom Voice</h3>
                <button onClick={() => { setShowCustomVoiceModal(false); resetCustomVoiceForm() }} className="text-gray-400 hover:text-gray-600">
                  <X className="h-5 w-5" />
                </button>
              </div>
              <form onSubmit={handleCreateCustomVoice} className="p-6 space-y-4">
                <p className="text-sm text-gray-600">
                  Register a custom voice ID from your TTS provider. Once added, it will appear in the voice selector when creating personas.
                </p>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Provider *</label>
                  {providers.length === 0 ? (
                    <p className="text-sm text-gray-600">
                      No TTS providers are connected yet.{' '}
                      <Link
                        to="/integrations"
                        className="text-primary-600 hover:text-primary-700 underline font-medium"
                      >
                        Connect a provider in Integrations
                      </Link>{' '}
                      before registering custom voices.
                    </p>
                  ) : (
                  <div className="grid grid-cols-2 gap-2">
                    {providers.map((p) => {
                      const isSelected = customVoiceForm.provider === p.id
                      return (
                        <button
                          key={p.id}
                          type="button"
                          onClick={() => setCustomVoiceForm({ ...customVoiceForm, provider: isSelected ? '' : p.id })}
                          className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-left transition-all ${
                            isSelected
                              ? 'border-primary-400 bg-primary-50 ring-1 ring-primary-200'
                              : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
                          }`}
                        >
                          <ProviderLogo provider={p.id} size="sm" />
                          <span className={`text-sm font-medium truncate ${isSelected ? 'text-primary-700' : 'text-gray-700'}`}>
                            {p.name}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Voice ID *</label>
                  <input
                    type="text"
                    required
                    value={customVoiceForm.voice_id}
                    onChange={(e) => setCustomVoiceForm({ ...customVoiceForm, voice_id: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    placeholder="Provider-specific voice identifier"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Display Name *</label>
                  <input
                    type="text"
                    required
                    value={customVoiceForm.name}
                    onChange={(e) => setCustomVoiceForm({ ...customVoiceForm, name: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    placeholder="e.g. My Custom Voice"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Gender</label>
                  <div className="relative">
                    <select
                      value={customVoiceForm.gender}
                      onChange={(e) => setCustomVoiceForm({ ...customVoiceForm, gender: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent appearance-none bg-white pr-8"
                    >
                      <option value="">Not specified</option>
                      <option value="Male">Male</option>
                      <option value="Female">Female</option>
                      <option value="Neutral">Neutral</option>
                    </select>
                    <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                  <textarea
                    value={customVoiceForm.description}
                    onChange={(e) => setCustomVoiceForm({ ...customVoiceForm, description: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    rows={2}
                    placeholder="Optional description..."
                  />
                </div>
                <div className="flex gap-3 pt-4">
                  <Button type="button" variant="outline" onClick={() => { setShowCustomVoiceModal(false); resetCustomVoiceForm() }} className="flex-1">
                    Cancel
                  </Button>
                  <Button type="submit" variant="primary" isLoading={createCustomVoiceMutation.isPending} className="flex-1">
                    Add Voice
                  </Button>
                </div>
              </form>
            </div>
          </div>,
        )}

        {/* ===================== EDIT CUSTOM VOICE MODAL ===================== */}
        {showEditCustomVoiceModal && editingCustomVoice && renderModal(
          <div className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]">
            <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                <div className="flex items-center gap-3">
                  <ProviderLogo provider={editingCustomVoice.provider} size="sm" />
                  <h3 className="text-lg font-semibold">Edit Custom Voice</h3>
                </div>
                <button onClick={() => { setShowEditCustomVoiceModal(false); setEditingCustomVoice(null); resetCustomVoiceForm() }} className="text-gray-400 hover:text-gray-600">
                  <X className="h-5 w-5" />
                </button>
              </div>
              <form onSubmit={handleUpdateCustomVoice} className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Voice ID *</label>
                  <input
                    type="text"
                    required
                    value={customVoiceForm.voice_id}
                    onChange={(e) => setCustomVoiceForm({ ...customVoiceForm, voice_id: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    placeholder="Provider-specific voice identifier"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Display Name *</label>
                  <input
                    type="text"
                    required
                    value={customVoiceForm.name}
                    onChange={(e) => setCustomVoiceForm({ ...customVoiceForm, name: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Gender</label>
                  <div className="relative">
                    <select
                      value={customVoiceForm.gender}
                      onChange={(e) => setCustomVoiceForm({ ...customVoiceForm, gender: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent appearance-none bg-white pr-8"
                    >
                      <option value="">Not specified</option>
                      <option value="Male">Male</option>
                      <option value="Female">Female</option>
                      <option value="Neutral">Neutral</option>
                    </select>
                    <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                  <textarea
                    value={customVoiceForm.description}
                    onChange={(e) => setCustomVoiceForm({ ...customVoiceForm, description: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    rows={2}
                    placeholder="Optional description..."
                  />
                </div>
                <div className="flex gap-3 pt-4">
                  <Button type="button" variant="outline" onClick={() => { setShowEditCustomVoiceModal(false); setEditingCustomVoice(null); resetCustomVoiceForm() }} className="flex-1">
                    Cancel
                  </Button>
                  <Button type="submit" variant="primary" isLoading={updateCustomVoiceMutation.isPending} className="flex-1">
                    Save Changes
                  </Button>
                </div>
              </form>
            </div>
          </div>,
        )}

        {/* ===================== DELETE CUSTOM VOICE CONFIRMATION ===================== */}
        {deleteCustomVoiceConfirm && renderModal(
          <div
            className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center z-[9999]"
            onClick={() => setDeleteCustomVoiceConfirm(null)}
          >
            <div
              className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                <h3 className="text-lg font-semibold text-gray-900">Delete Custom Voice</h3>
                <button
                  onClick={() => setDeleteCustomVoiceConfirm(null)}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-6">
                <div className="flex items-start gap-4 mb-6">
                  <div className="flex-shrink-0">
                    <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
                      <Trash2 className="h-6 w-6 text-red-600" />
                    </div>
                  </div>
                  <div className="flex-1">
                    <p className="text-sm text-gray-700 mb-2">
                      Are you sure you want to delete <span className="font-semibold text-gray-900">"{deleteCustomVoiceConfirm.name}"</span>?
                    </p>
                    <p className="text-xs text-gray-500">
                      This voice will be removed and will no longer appear in the voice selector when creating personas.
                    </p>
                  </div>
                </div>
                <div className="flex gap-3">
                  <Button variant="outline" onClick={() => setDeleteCustomVoiceConfirm(null)} className="flex-1">
                    Cancel
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => deleteCustomVoiceMutation.mutate(deleteCustomVoiceConfirm.id)}
                    isLoading={deleteCustomVoiceMutation.isPending}
                    leftIcon={!deleteCustomVoiceMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
                    className="flex-1"
                  >
                    Delete
                  </Button>
                </div>
              </div>
            </div>
          </div>,
        )}
      </div>

      <UploadAmbientNoiseModal
        open={showAmbientUpload}
        onClose={() => setShowAmbientUpload(false)}
      />
    </>
  )
}

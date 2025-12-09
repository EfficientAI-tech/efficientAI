import { useState, useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Users,
  Plus,
  Edit,
  Trash2,
  Copy,
  X,
  Loader2,
  Sparkles,
  UserPlus,
  Languages,
  Globe,
  Volume2,
  VolumeX,
  Building2,
  Car,
  Coffee,
  Home,
  ChevronDown,
} from 'lucide-react'
// Use emoji flags with better styling - most reliable solution
// Emoji flags work everywhere and don't require additional dependencies
import { apiClient } from '../lib/api'
import { useToast } from '../hooks/useToast'
import Button from '../components/Button'

interface Persona {
  id: string
  name: string
  language: string
  accent: string
  gender: string
  background_noise: string
  created_at: string
  updated_at: string
  created_by?: string | null
}

// Known default persona names from seed data
const DEFAULT_PERSONA_NAMES = [
  'Grumpy Old Man',
  'Confused Senior',
  'Busy Professional',
  'Friendly Customer',
  'Angry Caller',
]

const genderIcons: Record<string, string> = {
  male: '👨',
  female: '👩',
  neutral: '🧑',
}

// Mapping accents to country codes for flags
const accentToCountry: Record<string, string> = {
  american: 'US',
  british: 'GB',
  australian: 'AU',
  indian: 'IN',
  chinese: 'CN',
  spanish: 'ES',
  french: 'FR',
  german: 'DE',
  neutral: '',
}

// Mapping languages to country codes for flags
const languageToCountry: Record<string, string> = {
  en: 'GB',
  es: 'ES',
  fr: 'FR',
  de: 'DE',
}

// Emoji flag mapping - reliable and works everywhere
const emojiFlags: Record<string, string> = {
  US: '🇺🇸',
  GB: '🇬🇧',
  AU: '🇦🇺',
  IN: '🇮🇳',
  CN: '🇨🇳',
  ES: '🇪🇸',
  FR: '🇫🇷',
  DE: '🇩🇪',
}

// Helper component to render flags using emoji
const FlagIcon = ({ code, className = 'w-5 h-4', title }: { code: string; className?: string; title?: string }) => {
  if (!code || !emojiFlags[code]) {
    return <Globe className={className} />
  }
  return (
    <span 
      className={`inline-block ${className}`}
      style={{ fontSize: '1.25rem', lineHeight: '1' }}
      title={title || code}
      role="img"
      aria-label={title || code}
    >
      {emojiFlags[code]}
    </span>
  )
}

const languages = ['en', 'es', 'fr', 'de']
const accents = ['american', 'british', 'australian', 'indian', 'chinese', 'spanish', 'french', 'german', 'neutral']
const genders = ['male', 'female', 'neutral']
const backgroundNoises = ['none', 'office', 'street', 'cafe', 'home']

// Language display config
const languageConfig: Record<string, { label: string; color: string; bgColor: string }> = {
  en: { label: 'English', color: 'text-blue-700', bgColor: 'bg-blue-100' },
  es: { label: 'Spanish', color: 'text-red-700', bgColor: 'bg-red-100' },
  fr: { label: 'French', color: 'text-indigo-700', bgColor: 'bg-indigo-100' },
  de: { label: 'German', color: 'text-yellow-700', bgColor: 'bg-yellow-100' },
}

// Accent display config
const accentConfig: Record<string, { label: string; color: string; bgColor: string }> = {
  american: { label: 'American', color: 'text-blue-700', bgColor: 'bg-blue-100' },
  british: { label: 'British', color: 'text-red-700', bgColor: 'bg-red-100' },
  australian: { label: 'Australian', color: 'text-green-700', bgColor: 'bg-green-100' },
  indian: { label: 'Indian', color: 'text-orange-700', bgColor: 'bg-orange-100' },
  chinese: { label: 'Chinese', color: 'text-red-600', bgColor: 'bg-red-50' },
  spanish: { label: 'Spanish', color: 'text-yellow-700', bgColor: 'bg-yellow-100' },
  french: { label: 'French', color: 'text-blue-600', bgColor: 'bg-blue-50' },
  german: { label: 'German', color: 'text-black', bgColor: 'bg-gray-200' },
  neutral: { label: 'Neutral', color: 'text-gray-700', bgColor: 'bg-gray-100' },
}

// Background noise display config
const noiseConfig: Record<string, { label: string; icon: any; color: string; bgColor: string }> = {
  none: { label: 'None', icon: VolumeX, color: 'text-gray-700', bgColor: 'bg-gray-100' },
  office: { label: 'Office', icon: Building2, color: 'text-blue-700', bgColor: 'bg-blue-100' },
  street: { label: 'Street', icon: Car, color: 'text-orange-700', bgColor: 'bg-orange-100' },
  cafe: { label: 'Cafe', icon: Coffee, color: 'text-amber-700', bgColor: 'bg-amber-100' },
  home: { label: 'Home', icon: Home, color: 'text-green-700', bgColor: 'bg-green-100' },
}

type CreateMode = 'default' | 'custom' | null

export default function Personas() {
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()
  const [showMainModal, setShowMainModal] = useState(false)
  const [createMode, setCreateMode] = useState<CreateMode>(null)
  const [showEditModal, setShowEditModal] = useState(false)
  const [showCloneModal, setShowCloneModal] = useState(false)
  const [showDetailsModal, setShowDetailsModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [selectedPersona, setSelectedPersona] = useState<Persona | null>(null)
  const [formData, setFormData] = useState({
    name: '',
    language: 'en',
    accent: 'american',
    gender: 'neutral',
    background_noise: 'none',
  })


  // Fetch personas
  const { data: personas = [], isLoading, error, isError } = useQuery({
    queryKey: ['personas'],
    queryFn: () => apiClient.listPersonas(),
    retry: 1,
  })

  // Separate personas into default and user-created
  const { defaultPersonas, userPersonas } = useMemo(() => {
    const defaults: Persona[] = []
    const userCreated: Persona[] = []
    
    // Track which default persona IDs we've seen to avoid duplicates
    const seenDefaultIds = new Set<string>()
    
    personas.forEach((persona: Persona) => {
      // Check if it's a default persona:
      // 1. Name exactly matches a default persona name
      // 2. created_by is null/empty (seeded personas)
      // 3. Name doesn't contain "(Copy)" or "(Clone)" (cloned personas)
      // 4. We haven't seen this ID before (to handle edge cases)
      const isExactDefaultName = DEFAULT_PERSONA_NAMES.includes(persona.name)
      const isCloned = persona.name.includes('(Copy)') || persona.name.includes('(Clone)')
      const isDefault = isExactDefaultName && !isCloned && !persona.created_by && !seenDefaultIds.has(persona.id)
      
      if (isDefault) {
        seenDefaultIds.add(persona.id)
        defaults.push(persona)
      } else {
        // All cloned personas, custom personas, and modified defaults go to user-created
        userCreated.push(persona)
      }
    })
    
    return { defaultPersonas: defaults, userPersonas: userCreated }
  }, [personas])

  // Create persona mutation
  const createMutation = useMutation({
    mutationFn: (data: typeof formData) => apiClient.createPersona(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['personas'] })
      showToast('Persona created successfully!', 'success')
      handleCloseMainModal()
    },
    onError: (error: any) => {
      showToast(`Failed to create persona: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  // Update persona mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<typeof formData> }) =>
      apiClient.updatePersona(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['personas'] })
      setShowEditModal(false)
      setSelectedPersona(null)
      resetForm()
      showToast('Persona updated successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to update persona: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  // Delete persona mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deletePersona(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['personas'] })
      showToast('Persona deleted successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to delete persona: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  // Clone persona mutation
  const cloneMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name?: string }) => apiClient.clonePersona(id, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['personas'] })
      setShowCloneModal(false)
      setSelectedPersona(null)
      resetForm()
      showToast('Persona cloned successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to clone persona: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  // Seed demo data mutation
  const seedMutation = useMutation({
    mutationFn: () => apiClient.seedDemoData(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['personas'] })
      showToast('Demo personas loaded successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(`Failed to load demo data: ${error.response?.data?.detail || error.message}`, 'error')
    },
  })

  const resetForm = () => {
    setFormData({
      name: '',
      language: 'en',
      accent: 'american',
      gender: 'neutral',
      background_noise: 'none',
    })
  }

  const openCreateModal = () => {
    resetForm()
    setSelectedPersona(null)
    setShowMainModal(true)
  }

  const handleCloseMainModal = () => {
    setShowMainModal(false)
    setCreateMode(null)
    resetForm()
    setSelectedPersona(null)
  }

  const handleSelectDefaultPersona = (persona: Persona) => {
    setSelectedPersona(persona)
    // Pre-populate form with default persona data
    setFormData({
      name: `${persona.name} (Copy)`,
      language: persona.language,
      accent: persona.accent,
      gender: persona.gender,
      background_noise: persona.background_noise,
    })
    // Switch to custom mode to show the full form
    setCreateMode('custom')
  }

  const openEditModal = (persona: Persona) => {
    setSelectedPersona(persona)
    setFormData({
      name: persona.name,
      language: persona.language,
      accent: persona.accent,
      gender: persona.gender,
      background_noise: persona.background_noise,
    })
    setShowEditModal(true)
  }

  const openCloneModal = (persona: Persona) => {
    setSelectedPersona(persona)
    setFormData({
      name: `${persona.name} (Copy)`,
      language: persona.language,
      accent: persona.accent,
      gender: persona.gender,
      background_noise: persona.background_noise,
    })
    setShowCloneModal(true)
  }

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    createMutation.mutate(formData)
  }

  const handleUpdate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedPersona) return
    updateMutation.mutate({ id: selectedPersona.id, data: formData })
  }

  const handleDelete = (persona: Persona) => {
    setSelectedPersona(persona)
    setShowDeleteModal(true)
  }

  const confirmDelete = () => {
    if (selectedPersona) {
      deleteMutation.mutate(selectedPersona.id)
      setShowDeleteModal(false)
      setSelectedPersona(null)
    }
  }

  const handleClone = (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedPersona) return
    cloneMutation.mutate({ id: selectedPersona.id, name: formData.name })
  }

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
          <Button
            variant="ghost"
            onClick={() => queryClient.invalidateQueries({ queryKey: ['personas'] })}
          >
            Try again →
          </Button>
        </div>
      </div>
    )
  }

  return (
    <>
      <ToastContainer />
      <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Test Personas</h1>
          <p className="text-gray-600 mt-1">Create and manage personas for testing voice AI agents</p>
        </div>
        <div className="flex gap-3">
          {personas.length === 0 && (
            <Button
              variant="secondary"
              onClick={() => seedMutation.mutate()}
              isLoading={seedMutation.isPending}
            >
              Load Demo Personas
            </Button>
          )}
          <Button
            variant="primary"
            onClick={openCreateModal}
            leftIcon={<Plus className="h-5 w-5" />}
          >
            Create Persona
          </Button>
        </div>
      </div>

      {personas.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <Users className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No personas yet</h3>
          <p className="text-gray-500 mb-4">Create your first persona or load demo personas to get started</p>
          <div className="flex gap-3 justify-center items-center">
            <Button
              variant="ghost"
              onClick={() => seedMutation.mutate()}
              isLoading={seedMutation.isPending}
            >
              Load demo personas →
            </Button>
            <span className="text-gray-400">or</span>
            <Button
              variant="ghost"
              onClick={openCreateModal}
            >
              Create Persona →
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-8">
          {/* User-Created Personas Section */}
          <div className="bg-white shadow rounded-lg overflow-hidden">
            <div className="px-6 py-4 bg-gradient-to-r from-green-50 to-emerald-50 border-b border-green-200">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <UserPlus className="h-5 w-5 text-green-600" />
                  <h2 className="text-lg font-semibold text-gray-900">Your Personas</h2>
                  <span className="px-2 py-1 text-xs font-medium text-green-700 bg-green-100 rounded-full">
                    {userPersonas.length}
                  </span>
                </div>
                <p className="text-sm text-gray-600">Personas you've created or cloned</p>
              </div>
            </div>
            {userPersonas.length === 0 ? (
              <div className="p-12 text-center">
                <UserPlus className="w-12 h-12 text-gray-300 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-gray-900 mb-2">No custom personas yet</h3>
                <p className="text-gray-500 mb-4">Create your first persona or clone a default persona to get started</p>
                <Button
                  variant="ghost"
                  onClick={openCreateModal}
                >
                  Create Persona →
                </Button>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Name
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Gender
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Language
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Accent
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Background Noise
                      </th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {userPersonas.map((persona) => {
                      const langConfig = languageConfig[persona.language] || { label: persona.language.toUpperCase(), color: 'text-gray-700', bgColor: 'bg-gray-100' }
                      const accConfig = accentConfig[persona.accent] || { label: persona.accent, color: 'text-gray-700', bgColor: 'bg-gray-100' }
                      const noiseInfo = noiseConfig[persona.background_noise] || { label: persona.background_noise, icon: Volume2, color: 'text-gray-700', bgColor: 'bg-gray-100' }
                      const NoiseIcon = noiseInfo.icon
                      
                      return (
                        <tr key={persona.id} className="hover:bg-gray-50">
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className="text-sm font-medium text-gray-900">{persona.name}</span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800 capitalize">
                              {persona.gender}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${langConfig.bgColor} ${langConfig.color}`}>
                              <Languages className="h-3.5 w-3.5" />
                              {langConfig.label}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${accConfig.bgColor} ${accConfig.color}`}>
                              <Globe className="h-3.5 w-3.5" />
                              {accConfig.label}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${noiseInfo.bgColor} ${noiseInfo.color}`}>
                              <NoiseIcon className="h-3.5 w-3.5" />
                              {noiseInfo.label}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                            <div className="flex items-center justify-end gap-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => openEditModal(persona)}
                              leftIcon={<Edit className="h-4 w-4" />}
                              title="Edit persona"
                            >
                              Edit
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => openCloneModal(persona)}
                              leftIcon={<Copy className="h-4 w-4" />}
                              title="Clone persona"
                              className="text-blue-600 hover:text-blue-700 hover:bg-blue-50"
                            >
                              Clone
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleDelete(persona)}
                              isLoading={deleteMutation.isPending}
                              leftIcon={!deleteMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
                              title="Delete persona"
                              className="text-red-600 hover:text-red-700 hover:bg-red-50"
                            >
                              Delete
                            </Button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Main Create Persona Modal */}
      {showMainModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full mx-4 max-h-[90vh] overflow-hidden flex flex-col">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Create Persona</h3>
              <button
                onClick={handleCloseMainModal}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {!createMode ? (
              // Mode Selection
              <div className="p-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Default Personas */}
                  <button
                    onClick={() => setCreateMode('default')}
                    className="group relative p-6 bg-gradient-to-br from-blue-50 to-indigo-50 border-2 border-blue-200 rounded-xl hover:border-blue-400 hover:shadow-lg transition-all text-left"
                  >
                    <div className="flex items-start gap-4">
                      <div className="flex-shrink-0">
                        <div className="w-12 h-12 bg-blue-500 rounded-lg flex items-center justify-center group-hover:bg-blue-600 transition-colors">
                          <Sparkles className="h-6 w-6 text-white" />
                        </div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-lg font-semibold text-gray-900 mb-2">Default Personas</h3>
                        <p className="text-sm text-gray-600 leading-relaxed">
                          Choose from pre-configured personas like Grumpy Old Man, Confused Senior, etc. and clone them.
                        </p>
                      </div>
                    </div>
                  </button>

                  {/* Create Custom Persona */}
                  <button
                    onClick={() => setCreateMode('custom')}
                    className="group relative p-6 bg-gradient-to-br from-orange-50 to-amber-50 border-2 border-orange-200 rounded-xl hover:border-orange-400 hover:shadow-lg transition-all text-left"
                  >
                    <div className="flex items-start gap-4">
                      <div className="flex-shrink-0">
                        <div className="w-12 h-12 bg-orange-500 rounded-lg flex items-center justify-center group-hover:bg-orange-600 transition-colors">
                          <Plus className="h-6 w-6 text-white" />
                        </div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-lg font-semibold text-gray-900 mb-2">Create Custom Persona</h3>
                        <p className="text-sm text-gray-600 leading-relaxed">
                          Manually create a custom persona with specific language, accent, gender, and background noise settings.
                        </p>
                      </div>
                    </div>
                  </button>
                </div>
              </div>
            ) : createMode === 'default' ? (
              // Default Personas Selection
              <div className="p-6 overflow-y-auto flex-1">
                <button
                  onClick={() => setCreateMode(null)}
                  className="mb-4 text-sm text-gray-600 hover:text-gray-900 flex items-center gap-2"
                >
                  <X className="h-4 w-4" />
                  Back
                </button>
                <h4 className="text-lg font-semibold text-gray-900 mb-4">Select a Default Persona</h4>
                {defaultPersonas.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">
                    <Sparkles className="h-12 w-12 mx-auto mb-4 text-gray-300" />
                    <p>No default personas available. Load demo data first.</p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {defaultPersonas.map((persona) => (
                      <div
                        key={persona.id}
                        onClick={() => handleSelectDefaultPersona(persona)}
                        className="p-4 bg-gradient-to-br from-blue-50 to-indigo-50 border-2 border-blue-200 rounded-xl hover:border-blue-400 hover:shadow-lg transition-all cursor-pointer"
                      >
                        <div className="flex items-center gap-3 mb-3">
                          <span className="text-3xl">{genderIcons[persona.gender] || '🧑'}</span>
                          <div className="flex-1 min-w-0">
                            <h5 className="font-semibold text-gray-900">{persona.name}</h5>
                            <p className="text-xs text-gray-500 capitalize">{persona.gender}</p>
                          </div>
                        </div>
                        <div className="space-y-1.5 text-xs">
                          <div className="flex items-center gap-2">
                            <span className="text-gray-500 w-16">Language:</span>
                            <div className="flex items-center gap-1">
                              <FlagIcon code={languageToCountry[persona.language] || ''} className="w-4 h-3" title={persona.language} />
                              <span className="font-medium text-gray-900 uppercase">{persona.language}</span>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-gray-500 w-16">Accent:</span>
                            <div className="flex items-center gap-1">
                              <FlagIcon code={accentToCountry[persona.accent] || ''} className="w-4 h-3" title={persona.accent} />
                              <span className="font-medium text-gray-900 capitalize">{persona.accent}</span>
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-gray-500 w-16">Noise:</span>
                            <span className="font-medium text-gray-900 capitalize">
                              {persona.background_noise === 'none' ? 'None' : persona.background_noise}
                            </span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : createMode === 'custom' ? (
              // Create Custom Persona
              <div className="p-6 overflow-y-auto flex-1">
                <button
                  onClick={() => setCreateMode(null)}
                  className="mb-4 text-sm text-gray-600 hover:text-gray-900 flex items-center gap-2"
                >
                  <X className="h-4 w-4" />
                  Back
                </button>
                <h4 className="text-lg font-semibold text-gray-900 mb-4">Create Custom Persona</h4>
                <form onSubmit={handleCreate} className="space-y-4">
                  <div>
                    <label htmlFor="create-name" className="block text-sm font-medium text-gray-700 mb-1">
                      Name *
                    </label>
                    <input
                      id="create-name"
                      type="text"
                      required
                      value={formData.name}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                      placeholder="e.g., Grumpy Old Man"
                    />
                  </div>
                  <div>
                    <label htmlFor="create-language" className="block text-sm font-medium text-gray-700 mb-1">
                      <span className="flex items-center gap-2">
                        <Languages className="h-4 w-4" />
                        Language
                      </span>
                    </label>
                    <div className="relative">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none z-10">
                        <FlagIcon code={languageToCountry[formData.language] || ''} className="w-5 h-4" title={formData.language.toUpperCase()} />
                      </span>
                      <select
                        id="create-language"
                        value={formData.language}
                        onChange={(e) => setFormData({ ...formData, language: e.target.value })}
                        className="w-full pl-10 pr-8 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent appearance-none bg-white"
                      >
                        {languages.map((lang) => (
                          <option key={lang} value={lang}>
                            {lang.toUpperCase()}
                          </option>
                        ))}
                      </select>
                      <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
                    </div>
                  </div>
                  <div>
                    <label htmlFor="create-accent" className="block text-sm font-medium text-gray-700 mb-1">
                      <span className="flex items-center gap-2">
                        <Globe className="h-4 w-4" />
                        Accent
                      </span>
                    </label>
                    <div className="relative">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none z-10">
                        <FlagIcon code={accentToCountry[formData.accent] || ''} className="w-5 h-4" title={formData.accent.charAt(0).toUpperCase() + formData.accent.slice(1)} />
                      </span>
                      <select
                        id="create-accent"
                        value={formData.accent}
                        onChange={(e) => setFormData({ ...formData, accent: e.target.value })}
                        className="w-full pl-10 pr-8 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent appearance-none bg-white"
                      >
                        {accents.map((accent) => (
                          <option key={accent} value={accent}>
                            {accent.charAt(0).toUpperCase() + accent.slice(1)}
                          </option>
                        ))}
                      </select>
                      <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
                    </div>
                  </div>
                  <div>
                    <label htmlFor="create-gender" className="block text-sm font-medium text-gray-700 mb-1">
                      Gender
                    </label>
                    <div className="relative">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-lg pointer-events-none z-10">
                        {genderIcons[formData.gender] || '🧑'}
                      </span>
                      <select
                        id="create-gender"
                        value={formData.gender}
                        onChange={(e) => setFormData({ ...formData, gender: e.target.value })}
                        className="w-full pl-10 pr-8 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent appearance-none bg-white"
                      >
                        {genders.map((gender) => (
                          <option key={gender} value={gender}>
                            {gender.charAt(0).toUpperCase() + gender.slice(1)}
                          </option>
                        ))}
                      </select>
                      <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
                    </div>
                  </div>
                  <div>
                    <label htmlFor="create-noise" className="block text-sm font-medium text-gray-700 mb-1">
                      Background Noise
                    </label>
                    <select
                      id="create-noise"
                      value={formData.background_noise}
                      onChange={(e) => setFormData({ ...formData, background_noise: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                    >
                      {backgroundNoises.map((noise) => (
                        <option key={noise} value={noise}>
                          {noise === 'none' ? 'None' : noise.charAt(0).toUpperCase() + noise.slice(1)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex gap-3 pt-4">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleCloseMainModal}
                      className="flex-1"
                    >
                      Cancel
                    </Button>
                    <Button
                      type="submit"
                      variant="primary"
                      isLoading={createMutation.isPending}
                      className="flex-1"
                    >
                      Create
                    </Button>
                  </div>
                </form>
              </div>
            ) : null}
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {showEditModal && selectedPersona && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Edit Persona</h3>
              <button
                onClick={() => {
                  setShowEditModal(false)
                  setSelectedPersona(null)
                  resetForm()
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleUpdate} className="p-6 space-y-4">
              <div>
                <label htmlFor="edit-name" className="block text-sm font-medium text-gray-700 mb-1">
                  Name *
                </label>
                <input
                  id="edit-name"
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                />
              </div>
              <div>
                <label htmlFor="edit-language" className="block text-sm font-medium text-gray-700 mb-1">
                  <span className="flex items-center gap-2">
                    <Languages className="h-4 w-4" />
                    Language
                  </span>
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none z-10">
                    <FlagIcon code={languageToCountry[formData.language] || ''} className="w-5 h-4" title={formData.language.toUpperCase()} />
                  </span>
                  <select
                    id="edit-language"
                    value={formData.language}
                    onChange={(e) => setFormData({ ...formData, language: e.target.value })}
                    className="w-full pl-10 pr-8 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent appearance-none bg-white"
                  >
                    {languages.map((lang) => (
                      <option key={lang} value={lang}>
                        {lang.toUpperCase()}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
                </div>
              </div>
              <div>
                <label htmlFor="edit-accent" className="block text-sm font-medium text-gray-700 mb-1">
                  <span className="flex items-center gap-2">
                    <Globe className="h-4 w-4" />
                    Accent
                  </span>
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none z-10">
                    <FlagIcon code={accentToCountry[formData.accent] || ''} className="w-5 h-4" title={formData.accent.charAt(0).toUpperCase() + formData.accent.slice(1)} />
                  </span>
                  <select
                    id="edit-accent"
                    value={formData.accent}
                    onChange={(e) => setFormData({ ...formData, accent: e.target.value })}
                    className="w-full pl-10 pr-8 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent appearance-none bg-white"
                  >
                    {accents.map((accent) => (
                      <option key={accent} value={accent}>
                        {accent.charAt(0).toUpperCase() + accent.slice(1)}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
                </div>
              </div>
              <div>
                <label htmlFor="edit-gender" className="block text-sm font-medium text-gray-700 mb-1">
                  Gender
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-lg pointer-events-none z-10">
                    {genderIcons[formData.gender] || '🧑'}
                  </span>
                  <select
                    id="edit-gender"
                    value={formData.gender}
                    onChange={(e) => setFormData({ ...formData, gender: e.target.value })}
                    className="w-full pl-10 pr-8 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent appearance-none bg-white"
                  >
                    {genders.map((gender) => (
                      <option key={gender} value={gender}>
                        {gender.charAt(0).toUpperCase() + gender.slice(1)}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
                </div>
              </div>
              <div>
                <label htmlFor="edit-noise" className="block text-sm font-medium text-gray-700 mb-1">
                  Background Noise
                </label>
                <select
                  id="edit-noise"
                  value={formData.background_noise}
                  onChange={(e) => setFormData({ ...formData, background_noise: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                >
                  {backgroundNoises.map((noise) => (
                    <option key={noise} value={noise}>
                      {noise === 'none' ? 'None' : noise.charAt(0).toUpperCase() + noise.slice(1)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setShowEditModal(false)
                    setSelectedPersona(null)
                    resetForm()
                  }}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  isLoading={updateMutation.isPending}
                  className="flex-1"
                >
                  Update
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Clone Modal */}
      {showCloneModal && selectedPersona && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Clone Persona</h3>
              <button
                onClick={() => {
                  setShowCloneModal(false)
                  setSelectedPersona(null)
                  resetForm()
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleClone} className="p-6 space-y-4">
              <p className="text-sm text-gray-600 mb-4">
                Create a copy of "{selectedPersona.name}" with a new name. All other attributes will be copied.
              </p>
              <div>
                <label htmlFor="clone-name" className="block text-sm font-medium text-gray-700 mb-1">
                  New Name *
                </label>
                <input
                  id="clone-name"
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                />
              </div>
              <div className="flex gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setShowCloneModal(false)
                    setSelectedPersona(null)
                    resetForm()
                  }}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  isLoading={cloneMutation.isPending}
                  className="flex-1"
                >
                  Clone
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Default Persona Details Modal */}
      {showDetailsModal && selectedPersona && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setShowDetailsModal(false)}>
          <div className="bg-white rounded-lg shadow-xl max-w-lg w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Persona Details</h3>
              <button
                onClick={() => {
                  setShowDetailsModal(false)
                  setSelectedPersona(null)
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6 space-y-6">
              {/* Header with icon and name */}
              <div className="flex items-center gap-4 pb-4 border-b border-gray-200">
                <span className="text-5xl">{genderIcons[selectedPersona.gender] || '🧑'}</span>
                <div>
                  <h3 className="text-xl font-semibold text-gray-900">{selectedPersona.name}</h3>
                  <p className="text-sm text-gray-500 capitalize mt-1">{selectedPersona.gender}</p>
                </div>
              </div>

              {/* Details Grid */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <p className="text-xs font-medium text-gray-500 uppercase">Language</p>
                  <div className="flex items-center gap-2">
                    <Languages className="h-4 w-4 text-gray-400" />
                    <FlagIcon code={languageToCountry[selectedPersona.language] || ''} className="w-5 h-4" title={selectedPersona.language} />
                    <span className="text-sm font-medium text-gray-900 uppercase">
                      {selectedPersona.language}
                    </span>
                  </div>
                </div>
                <div className="space-y-1">
                  <p className="text-xs font-medium text-gray-500 uppercase">Accent</p>
                  <div className="flex items-center gap-2">
                    <Globe className="h-4 w-4 text-gray-400" />
                    <FlagIcon code={accentToCountry[selectedPersona.accent] || ''} className="w-5 h-4" title={selectedPersona.accent} />
                    <span className="text-sm font-medium text-gray-900 capitalize">
                      {selectedPersona.accent}
                    </span>
                  </div>
                </div>
                <div className="space-y-1">
                  <p className="text-xs font-medium text-gray-500 uppercase">Background Noise</p>
                  <div className="flex items-center gap-2">
                    {(() => {
                      const noiseInfo = noiseConfig[selectedPersona.background_noise] || { icon: Volume2, label: selectedPersona.background_noise }
                      const NoiseIcon = noiseInfo.icon
                      return (
                        <>
                          <NoiseIcon className="h-4 w-4 text-gray-400" />
                          <span className="text-sm font-medium text-gray-900 capitalize">
                            {noiseInfo.label}
                          </span>
                        </>
                      )
                    })()}
                  </div>
                </div>
                <div className="space-y-1">
                  <p className="text-xs font-medium text-gray-500 uppercase">Gender</p>
                  <span className="text-sm font-medium text-gray-900 capitalize">
                    {selectedPersona.gender}
                  </span>
                </div>
              </div>

              {/* Action Button */}
              <div className="pt-4 border-t border-gray-200">
                <Button
                  variant="primary"
                  onClick={() => {
                    setShowDetailsModal(false)
                    openCloneModal(selectedPersona)
                  }}
                  leftIcon={<Copy className="h-5 w-5" />}
                  className="w-full"
                >
                  Clone Persona
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && selectedPersona && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setShowDeleteModal(false)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">Delete Persona</h3>
              <button
                onClick={() => {
                  setShowDeleteModal(false)
                  setSelectedPersona(null)
                }}
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
                    Are you sure you want to delete <span className="font-semibold text-gray-900">"{selectedPersona.name}"</span>?
                  </p>
                  <p className="text-xs text-gray-500">
                    This action cannot be undone. The persona will be permanently deleted.
                  </p>
                </div>
              </div>
              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowDeleteModal(false)
                    setSelectedPersona(null)
                  }}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  variant="danger"
                  onClick={confirmDelete}
                  isLoading={deleteMutation.isPending}
                  leftIcon={!deleteMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
                  className="flex-1"
                >
                  Delete
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
      </div>
    </>
  )
}


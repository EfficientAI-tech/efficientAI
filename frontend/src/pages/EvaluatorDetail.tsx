import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import { apiClient } from '../lib/api'
import { ModelProvider, AIProvider, Integration, IntegrationPlatform } from '../types/api'
import Button from '../components/Button'
import { ArrowLeft, Edit, Save, X, Phone, Globe, Sparkles, Trash2, AlertCircle, Brain, ChevronDown } from 'lucide-react'
import { useToast } from '../hooks/useToast'

const PROVIDER_LABELS: Record<ModelProvider, string> = {
  [ModelProvider.OPENAI]: 'OpenAI',
  [ModelProvider.ANTHROPIC]: 'Anthropic',
  [ModelProvider.GOOGLE]: 'Google',
  [ModelProvider.AZURE]: 'Azure',
  [ModelProvider.AWS]: 'AWS',
  [ModelProvider.DEEPGRAM]: 'Deepgram',
  [ModelProvider.CARTESIA]: 'Cartesia',
  [ModelProvider.ELEVENLABS]: 'ElevenLabs',
  [ModelProvider.CUSTOM]: 'Custom',
}

const PROVIDER_LOGOS: Record<ModelProvider, string | null> = {
  [ModelProvider.OPENAI]: '/openai-logo.png',
  [ModelProvider.ANTHROPIC]: '/anthropic.png',
  [ModelProvider.GOOGLE]: '/geminiai.png',
  [ModelProvider.AZURE]: '/azureai.png',
  [ModelProvider.AWS]: '/AWS_logo.png',
  [ModelProvider.DEEPGRAM]: '/deepgram.png',
  [ModelProvider.CARTESIA]: '/cartesia.jpg',
  [ModelProvider.ELEVENLABS]: '/elevenlabs.jpg',
  [ModelProvider.CUSTOM]: null,
}

interface Evaluator {
  id: string
  evaluator_id: string
  name?: string | null
  agent_id?: string | null
  persona_id?: string | null
  scenario_id?: string | null
  custom_prompt?: string | null
  llm_provider?: string | null
  llm_model?: string | null
  tags?: string[]
  created_at: string
  updated_at: string
}

const markdownComponents = {
  h1: ({ children }: any) => <h1 className="text-xl font-bold text-gray-900 mt-5 mb-2 first:mt-0 border-b border-gray-200 pb-1">{children}</h1>,
  h2: ({ children }: any) => <h2 className="text-lg font-semibold text-gray-800 mt-4 mb-2 first:mt-0">{children}</h2>,
  h3: ({ children }: any) => <h3 className="text-base font-semibold text-gray-800 mt-3 mb-1 first:mt-0">{children}</h3>,
  h4: ({ children }: any) => <h4 className="text-sm font-semibold text-gray-800 mt-2 mb-1 first:mt-0">{children}</h4>,
  p: ({ children }: any) => <p className="text-sm text-gray-700 mb-2 leading-relaxed">{children}</p>,
  ul: ({ children }: any) => <ul className="list-disc list-inside text-sm text-gray-700 mb-2 space-y-1 ml-2">{children}</ul>,
  ol: ({ children }: any) => <ol className="list-decimal list-inside text-sm text-gray-700 mb-2 space-y-1 ml-2">{children}</ol>,
  li: ({ children }: any) => <li className="text-sm text-gray-700">{children}</li>,
  strong: ({ children }: any) => <strong className="font-semibold text-gray-900">{children}</strong>,
  em: ({ children }: any) => <em className="italic text-gray-600">{children}</em>,
  code: ({ children }: any) => <code className="bg-gray-100 text-pink-600 text-xs px-1.5 py-0.5 rounded font-mono">{children}</code>,
  pre: ({ children }: any) => <pre className="bg-gray-900 text-gray-100 text-xs p-3 rounded-md overflow-x-auto mb-2 font-mono">{children}</pre>,
  blockquote: ({ children }: any) => <blockquote className="border-l-4 border-gray-300 pl-3 italic text-gray-600 text-sm my-2">{children}</blockquote>,
  hr: () => <hr className="my-3 border-gray-200" />,
  a: ({ children, href }: any) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">{children}</a>,
  table: ({ children }: any) => <table className="w-full border-collapse text-sm mb-2">{children}</table>,
  th: ({ children }: any) => <th className="border border-gray-300 px-2 py-1 bg-gray-50 text-left font-semibold text-gray-800">{children}</th>,
  td: ({ children }: any) => <td className="border border-gray-300 px-2 py-1 text-gray-700">{children}</td>,
}

export default function EvaluatorDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast, ToastContainer } = useToast()

  const [isEditing, setIsEditing] = useState(false)
  const [editData, setEditData] = useState<Evaluator | null>(null)
  const [editTagInput, setEditTagInput] = useState('')
  const [isFormattingPrompt, setIsFormattingPrompt] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [deleteDependencies, setDeleteDependencies] = useState<Record<string, number> | null>(null)
  const [showLlmDropdown, setShowLlmDropdown] = useState(false)
  const llmDropdownRef = useRef<HTMLDivElement>(null)

  const { data: evaluator, isLoading } = useQuery<Evaluator>({
    queryKey: ['evaluator', id],
    queryFn: () => apiClient.getEvaluator(id!),
    enabled: !!id,
  })

  const isCustom = !!evaluator?.custom_prompt

  const { data: details, isLoading: loadingDetails } = useQuery({
    queryKey: ['evaluator-details', id],
    queryFn: async () => {
      if (!evaluator) return null
      if (isCustom) {
        return { agent: null, persona: null, scenario: null, isCustom: true }
      }
      const [agent, persona, scenario] = await Promise.all([
        evaluator.agent_id ? apiClient.getAgent(evaluator.agent_id) : null,
        evaluator.persona_id ? apiClient.getPersona(evaluator.persona_id) : null,
        evaluator.scenario_id ? apiClient.getScenario(evaluator.scenario_id) : null,
      ])
      return { agent, persona, scenario, isCustom: false }
    },
    enabled: !!evaluator,
  })

  const { data: aiproviders = [] } = useQuery({
    queryKey: ['aiproviders'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const { data: integrations = [] } = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
  })

  const { data: modelConfigs = {} } = useQuery({
    queryKey: ['model-configs'],
    queryFn: async () => {
      const providers = Object.values(ModelProvider)
      const configs: Record<string, { stt: string[]; llm: string[]; tts: string[]; s2s: string[] }> = {}
      for (const provider of providers) {
        try {
          const options = await apiClient.getModelOptions(provider)
          configs[provider] = { stt: options.stt || [], llm: options.llm || [], tts: options.tts || [], s2s: options.s2s || [] }
        } catch {
          configs[provider] = { stt: [], llm: [], tts: [], s2s: [] }
        }
      }
      return configs
    },
    staleTime: 5 * 60 * 1000,
  })

  const mapIntegrationToProvider = (platform: IntegrationPlatform | string): ModelProvider | null => {
    const platformLower = (typeof platform === 'string' ? platform : String(platform)).toLowerCase()
    switch (platformLower) {
      case 'deepgram': return ModelProvider.DEEPGRAM
      case 'cartesia': return ModelProvider.CARTESIA
      case 'elevenlabs': return ModelProvider.ELEVENLABS
      default: return null
    }
  }

  const configuredProviders = Array.from(
    new Set([
      ...(aiproviders.filter((p: AIProvider) => p.is_active).map((p: AIProvider) => p.provider as ModelProvider)),
      ...(integrations.filter((i: Integration) => i.is_active).map((i: Integration) => mapIntegrationToProvider(i.platform)).filter((p): p is ModelProvider => Boolean(p))),
    ])
  )

  const llmProviders = configuredProviders.filter(p => {
    const opts = modelConfigs[p]
    return opts && opts.llm && opts.llm.length > 0
  })

  const getModelOptions = (provider: ModelProvider): { stt: string[]; llm: string[]; tts: string[]; s2s: string[] } => {
    return modelConfigs[provider] || { stt: [], llm: [], tts: [], s2s: [] }
  }

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (llmDropdownRef.current && !llmDropdownRef.current.contains(event.target as Node)) {
        setShowLlmDropdown(false)
      }
    }
    if (showLlmDropdown) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showLlmDropdown])

  const updateMutation = useMutation({
    mutationFn: ({ evalId, data }: { evalId: string; data: any }) => apiClient.updateEvaluator(evalId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluator', id] })
      queryClient.invalidateQueries({ queryKey: ['evaluator-details', id] })
      queryClient.invalidateQueries({ queryKey: ['evaluators'] })
      setIsEditing(false)
      setEditData(null)
      showToast('Evaluator updated successfully!', 'success')
    },
    onError: (error: any) => {
      showToast(error.response?.data?.detail || 'Failed to update evaluator', 'error')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: ({ evalId, force }: { evalId: string; force?: boolean }) => apiClient.deleteEvaluator(evalId, force),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evaluators'] })
      showToast('Evaluator deleted successfully!', 'success')
      navigate('/evaluate-test-agents')
    },
    onError: (error: any) => {
      const status = error.response?.status
      const detail = error.response?.data?.detail
      if (status === 409 && detail?.dependencies) {
        setDeleteDependencies(detail.dependencies)
        return
      }
      const errorMessage = typeof detail === 'string' ? detail : detail?.message || error.message || 'Failed to delete evaluator.'
      showToast(errorMessage, 'error')
    },
  })

  const startEditing = () => {
    if (!evaluator) return
    setEditData({ ...evaluator })
    setIsEditing(true)
    setEditTagInput('')
  }

  const cancelEditing = () => {
    setIsEditing(false)
    setEditData(null)
    setEditTagInput('')
  }

  const handleSave = () => {
    if (!editData || !evaluator) return
    const data: any = { tags: editData.tags || [] }
    if (isCustom) {
      data.name = editData.name || ''
      data.custom_prompt = editData.custom_prompt || ''
    }
    if (editData.llm_provider) data.llm_provider = editData.llm_provider
    if (editData.llm_model) data.llm_model = editData.llm_model
    updateMutation.mutate({ evalId: evaluator.id, data })
  }

  const handleFormatPrompt = async () => {
    if (!editData?.custom_prompt?.trim()) return
    setIsFormattingPrompt(true)
    try {
      const { formatted_prompt } = await apiClient.formatCustomPrompt(editData.custom_prompt)
      setEditData({ ...editData, custom_prompt: formatted_prompt })
    } catch (error: any) {
      const msg = error.response?.data?.detail || error.message || 'Formatting failed'
      showToast(`Failed to format prompt: ${msg}`, 'error')
    } finally {
      setIsFormattingPrompt(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="text-gray-500">Loading evaluator...</div>
      </div>
    )
  }

  if (!evaluator) {
    return (
      <div className="space-y-6">
        <button onClick={() => navigate('/evaluate-test-agents')} className="flex items-center gap-2 text-gray-600 hover:text-gray-900 transition-colors">
          <ArrowLeft className="w-4 h-4" />
          <span className="text-sm font-medium">Back to Evaluators</span>
        </button>
        <div className="text-center py-12 text-gray-500">Evaluator not found.</div>
      </div>
    )
  }

  return (
    <>
      <ToastContainer />
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/evaluate-test-agents')}
              className="flex items-center gap-2 text-gray-600 hover:text-gray-900 transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              <span className="text-sm font-medium">Back</span>
            </button>
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-2xl font-bold text-gray-900 font-mono">
                  #{evaluator.evaluator_id}
                </h1>
                {isCustom && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800">
                    Custom
                  </span>
                )}
              </div>
              {isCustom && evaluator.name && (
                <p className="text-sm text-gray-600 mt-0.5">{evaluator.name}</p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {isEditing ? (
              <>
                <Button variant="ghost" onClick={cancelEditing}>
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  onClick={handleSave}
                  isLoading={updateMutation.isPending}
                  leftIcon={<Save className="w-4 h-4" />}
                >
                  Save Changes
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="primary"
                  onClick={startEditing}
                  leftIcon={<Edit className="w-4 h-4" />}
                >
                  Edit
                </Button>
                <Button
                  variant="danger"
                  onClick={() => {
                    setDeleteDependencies(null)
                    setShowDeleteModal(true)
                  }}
                  leftIcon={<Trash2 className="w-4 h-4" />}
                >
                  Delete
                </Button>
              </>
            )}
          </div>
        </div>

        {/* Main Content */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left column: main details */}
          <div className="lg:col-span-2 space-y-6">
            {isCustom ? (
              <>
                {/* Custom evaluator name (editable) */}
                {isEditing && editData ? (
                  <div className="bg-white shadow rounded-lg p-6">
                    <label className="block text-sm font-semibold text-gray-700 mb-2">Evaluator Name</label>
                    <input
                      type="text"
                      value={editData.name || ''}
                      onChange={(e) => setEditData({ ...editData, name: e.target.value })}
                      placeholder="e.g. Customer Support Bot v2"
                      className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                    />
                  </div>
                ) : null}

                {/* Custom Prompt */}
                <div className="bg-white shadow rounded-lg overflow-hidden">
                  <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
                    <h2 className="text-lg font-semibold text-gray-900">Agent Prompt / Instructions</h2>
                    {isEditing && editData && (
                      <button
                        type="button"
                        disabled={!(editData.custom_prompt || '').trim() || isFormattingPrompt}
                        onClick={handleFormatPrompt}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md bg-violet-50 text-violet-700 border border-violet-200 hover:bg-violet-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                      >
                        <Sparkles className={`h-3.5 w-3.5 ${isFormattingPrompt ? 'animate-spin' : ''}`} />
                        {isFormattingPrompt ? 'Formatting...' : 'Format with AI'}
                      </button>
                    )}
                  </div>
                  <div className="p-6">
                    {isEditing && editData ? (
                      <textarea
                        value={editData.custom_prompt || ''}
                        onChange={(e) => setEditData({ ...editData, custom_prompt: e.target.value })}
                        rows={16}
                        placeholder="Paste the full system prompt or description of what the agent is supposed to do..."
                        className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500 text-sm font-mono"
                      />
                    ) : (
                      <div className="max-h-[600px] overflow-y-auto">
                        <ReactMarkdown components={markdownComponents}>
                          {evaluator.custom_prompt || ''}
                        </ReactMarkdown>
                      </div>
                    )}
                  </div>
                </div>
              </>
            ) : (
              <>
                {/* Standard evaluator details */}
                {loadingDetails ? (
                  <div className="bg-white shadow rounded-lg p-6 text-center text-gray-500">
                    Loading details...
                  </div>
                ) : details ? (
                  <>
                    {/* Agent */}
                    {details.agent && (
                      <div className="bg-white shadow rounded-lg overflow-hidden">
                        <div className="px-6 py-4 border-b border-gray-200">
                          <h2 className="text-lg font-semibold text-gray-900">Agent</h2>
                        </div>
                        <div className="p-6 space-y-3">
                          <p className="text-base font-medium text-gray-900">{details.agent.name}</p>
                          {details.agent.description && (
                            <p className="text-sm text-gray-600">{details.agent.description}</p>
                          )}
                          <div className="flex items-center gap-2">
                            {details.agent.call_medium === 'web_call' ? (
                              <span className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 border border-gray-300">
                                <Globe className="w-3.5 h-3.5 mr-1.5" />
                                Web Call
                              </span>
                            ) : details.agent.phone_number ? (
                              <span className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-teal-100 text-teal-800 border border-teal-300">
                                <Phone className="w-3.5 h-3.5 mr-1.5" />
                                {details.agent.phone_number}
                              </span>
                            ) : (
                              <span className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 border border-gray-300">
                                No phone number
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Persona */}
                    {details.persona && (
                      <div className="bg-white shadow rounded-lg overflow-hidden">
                        <div className="px-6 py-4 border-b border-purple-100 bg-purple-50">
                          <h2 className="text-lg font-semibold text-purple-900">Persona</h2>
                        </div>
                        <div className="p-6 space-y-3">
                          <p className="text-base font-medium text-gray-900">{details.persona.name}</p>
                          <div className="flex flex-wrap gap-2">
                            <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-purple-50 text-purple-800 border border-purple-200">
                              Language: {details.persona.language}
                            </span>
                            <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-purple-50 text-purple-800 border border-purple-200">
                              Accent: {details.persona.accent}
                            </span>
                            <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-purple-50 text-purple-800 border border-purple-200">
                              Gender: {details.persona.gender}
                            </span>
                            {details.persona.background_noise && (
                              <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-purple-50 text-purple-800 border border-purple-200">
                                Noise: {details.persona.background_noise}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Scenario */}
                    {details.scenario && (
                      <div className="bg-white shadow rounded-lg overflow-hidden">
                        <div className="px-6 py-4 border-b border-blue-100 bg-blue-50">
                          <h2 className="text-lg font-semibold text-blue-900">Scenario</h2>
                        </div>
                        <div className="p-6 space-y-3">
                          <p className="text-base font-medium text-gray-900">{details.scenario.name}</p>
                          {details.scenario.description && (
                            <p className="text-sm text-gray-600">{details.scenario.description}</p>
                          )}
                          {details.scenario.required_info && Object.keys(details.scenario.required_info).length > 0 && (
                            <div>
                              <p className="text-xs font-medium text-blue-700 mb-2">Required Information:</p>
                              <div className="bg-blue-50 rounded border border-blue-200 p-3">
                                <dl className="space-y-1">
                                  {Object.entries(details.scenario.required_info).map(([key, value]) => (
                                    <div key={key} className="flex">
                                      <dt className="text-xs font-medium text-gray-500 w-32">{key}:</dt>
                                      <dd className="text-xs text-gray-700">{String(value)}</dd>
                                    </div>
                                  ))}
                                </dl>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="bg-white shadow rounded-lg p-6 text-center text-gray-500">
                    Failed to load details.
                  </div>
                )}
              </>
            )}
          </div>

          {/* Right column: sidebar */}
          <div className="space-y-6">
            {/* Tags */}
            <div className="bg-white shadow rounded-lg overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200">
                <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Tags</h2>
              </div>
              <div className="p-6">
                {isEditing && editData ? (
                  <div className="space-y-3">
                    <div className="flex flex-wrap gap-2 min-h-[36px]">
                      {editData.tags && editData.tags.length > 0 ? (
                        editData.tags.map((tag, idx) => (
                          <span key={idx} className="inline-flex items-center px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded">
                            {tag}
                            <button
                              onClick={() => {
                                const newTags = editData.tags?.filter(t => t !== tag) || []
                                setEditData({ ...editData, tags: newTags })
                              }}
                              className="ml-1 text-blue-600 hover:text-blue-800"
                            >
                              <X className="w-3 h-3" />
                            </button>
                          </span>
                        ))
                      ) : (
                        <span className="text-sm text-gray-400">No tags</span>
                      )}
                    </div>
                    <div className="flex space-x-2">
                      <input
                        type="text"
                        value={editTagInput}
                        onChange={(e) => setEditTagInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            if (editTagInput.trim() && !editData.tags?.includes(editTagInput.trim())) {
                              setEditData({ ...editData, tags: [...(editData.tags || []), editTagInput.trim()] })
                              setEditTagInput('')
                            }
                          }
                        }}
                        placeholder="Add tag..."
                        className="flex-1 px-2 py-1.5 text-xs border border-gray-300 rounded-md focus:outline-none focus:ring-primary-500 focus:border-primary-500"
                      />
                      <Button
                        size="sm"
                        onClick={() => {
                          if (editTagInput.trim() && !editData.tags?.includes(editTagInput.trim())) {
                            setEditData({ ...editData, tags: [...(editData.tags || []), editTagInput.trim()] })
                            setEditTagInput('')
                          }
                        }}
                      >
                        Add
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {evaluator.tags && evaluator.tags.length > 0 ? (
                      evaluator.tags.map((tag, idx) => (
                        <span key={idx} className="px-3 py-1 text-sm bg-blue-100 text-blue-800 rounded-full">
                          {tag}
                        </span>
                      ))
                    ) : (
                      <span className="text-sm text-gray-400">No tags</span>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Evaluation Model */}
            <div className="bg-white shadow rounded-lg overflow-hidden">
              <div className="px-6 py-4 border-b border-purple-100 bg-purple-50">
                <div className="flex items-center gap-2">
                  <Brain className="h-4 w-4 text-purple-600" />
                  <h2 className="text-sm font-semibold text-purple-900 uppercase tracking-wide">Evaluation Model</h2>
                </div>
              </div>
              <div className="p-6">
                {isEditing && editData ? (
                  <div className="space-y-3">
                    {llmProviders.length === 0 ? (
                      <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
                        No AI providers with LLM models configured. Default (gpt-4o) will be used.
                      </div>
                    ) : (
                      <>
                        <div>
                          <label className="block text-xs font-medium text-gray-700 mb-1">Provider</label>
                          <div className="relative" ref={llmDropdownRef}>
                            <button
                              type="button"
                              onClick={() => setShowLlmDropdown(!showLlmDropdown)}
                              className="w-full px-3 py-2 border border-gray-300 rounded-md bg-white text-left flex items-center justify-between text-sm"
                            >
                              <div className="flex items-center gap-2">
                                {editData.llm_provider && PROVIDER_LOGOS[editData.llm_provider as ModelProvider] ? (
                                  <img src={PROVIDER_LOGOS[editData.llm_provider as ModelProvider]!} alt="" className="w-4 h-4 object-contain" />
                                ) : (
                                  <Brain className="h-4 w-4 text-gray-400" />
                                )}
                                <span className={editData.llm_provider ? 'text-gray-900' : 'text-gray-400'}>
                                  {editData.llm_provider ? PROVIDER_LABELS[editData.llm_provider as ModelProvider] || editData.llm_provider : 'Select provider'}
                                </span>
                              </div>
                              <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${showLlmDropdown ? 'rotate-180' : ''}`} />
                            </button>
                            {showLlmDropdown && (
                              <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-md shadow-lg max-h-48 overflow-auto">
                                {llmProviders.map((provider) => (
                                  <button
                                    key={provider}
                                    type="button"
                                    onClick={() => {
                                      const models = getModelOptions(provider).llm
                                      setEditData({ ...editData, llm_provider: provider, llm_model: models.length > 0 ? models[0] : '' })
                                      setShowLlmDropdown(false)
                                    }}
                                    className="w-full px-3 py-2 text-left hover:bg-gray-50 flex items-center gap-2 text-sm"
                                  >
                                    {PROVIDER_LOGOS[provider] ? (
                                      <img src={PROVIDER_LOGOS[provider]!} alt="" className="w-4 h-4 object-contain" />
                                    ) : (
                                      <Brain className="h-4 w-4 text-purple-600" />
                                    )}
                                    <span>{PROVIDER_LABELS[provider]}</span>
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-gray-700 mb-1">Model</label>
                          <select
                            value={editData.llm_model || ''}
                            onChange={(e) => setEditData({ ...editData, llm_model: e.target.value })}
                            disabled={!editData.llm_provider}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500 disabled:bg-gray-50 disabled:text-gray-400"
                          >
                            {editData.llm_provider ? (
                              getModelOptions(editData.llm_provider as ModelProvider).llm.map((model) => (
                                <option key={model} value={model}>{model}</option>
                              ))
                            ) : (
                              <option value="">Select provider first</option>
                            )}
                          </select>
                        </div>
                      </>
                    )}
                  </div>
                ) : (
                  <div className="space-y-2">
                    {evaluator.llm_provider && evaluator.llm_model ? (
                      <>
                        <div className="flex items-center gap-2">
                          {PROVIDER_LOGOS[evaluator.llm_provider as ModelProvider] && (
                            <img src={PROVIDER_LOGOS[evaluator.llm_provider as ModelProvider]!} alt="" className="w-5 h-5 object-contain" />
                          )}
                          <span className="text-sm font-medium text-gray-900">
                            {PROVIDER_LABELS[evaluator.llm_provider as ModelProvider] || evaluator.llm_provider}
                          </span>
                        </div>
                        <p className="text-sm text-purple-700 font-mono">{evaluator.llm_model}</p>
                      </>
                    ) : (
                      <p className="text-sm text-gray-400">Default (gpt-4o)</p>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Metadata */}
            <div className="bg-white shadow rounded-lg overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200">
                <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Details</h2>
              </div>
              <div className="p-6 space-y-3">
                <div>
                  <p className="text-xs text-gray-500 uppercase tracking-wide">Evaluator ID</p>
                  <p className="text-sm font-mono font-medium text-gray-900">{evaluator.evaluator_id}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 uppercase tracking-wide">Type</p>
                  <p className="text-sm font-medium text-gray-900">{isCustom ? 'Custom Prompt' : 'Standard (Agent + Persona + Scenario)'}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 uppercase tracking-wide">Created</p>
                  <p className="text-sm text-gray-700">{new Date(evaluator.created_at).toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 uppercase tracking-wide">Last Updated</p>
                  <p className="text-sm text-gray-700">{new Date(evaluator.updated_at).toLocaleString()}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Delete Modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-center justify-center p-4">
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
              onClick={() => { setShowDeleteModal(false); setDeleteDependencies(null) }}
            />
            <div className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-gray-900">Delete Evaluator</h3>
                <button
                  onClick={() => { setShowDeleteModal(false); setDeleteDependencies(null) }}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {deleteDependencies && (
                <div className="mb-4 p-4 bg-amber-50 border border-amber-200 rounded-lg">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <p className="text-sm font-medium text-amber-800 mb-2">This evaluator has dependent records</p>
                      <ul className="text-xs text-amber-700 space-y-1 mb-3">
                        {deleteDependencies.evaluator_results && (
                          <li>{deleteDependencies.evaluator_results} evaluator result{deleteDependencies.evaluator_results !== 1 ? 's' : ''}</li>
                        )}
                      </ul>
                      <p className="text-xs text-amber-700">Force deleting will remove the evaluator and all its results.</p>
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
                    Are you sure you want to delete evaluator <span className="font-semibold text-gray-900">#{evaluator.evaluator_id}</span>?
                  </p>
                  <p className="text-xs text-gray-500">This action cannot be undone.</p>
                </div>
              </div>

              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={() => { setShowDeleteModal(false); setDeleteDependencies(null) }}
                  className="flex-1"
                >
                  Cancel
                </Button>
                {deleteDependencies ? (
                  <Button
                    variant="danger"
                    onClick={() => deleteMutation.mutate({ evalId: evaluator.id, force: true })}
                    isLoading={deleteMutation.isPending}
                    leftIcon={!deleteMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
                    className="flex-1"
                  >
                    Force Delete All
                  </Button>
                ) : (
                  <Button
                    variant="danger"
                    onClick={() => deleteMutation.mutate({ evalId: evaluator.id })}
                    isLoading={deleteMutation.isPending}
                    leftIcon={!deleteMutation.isPending ? <Trash2 className="h-4 w-4" /> : undefined}
                    className="flex-1"
                  >
                    Delete
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/api'
import ReactMarkdown from 'react-markdown'
import {
  Plus,
  Search,
  Edit3,
  Trash2,
  Copy,
  History,
  RotateCcw,
  X,
  ChevronRight,
  FileText,
  Eye,
  Code,
  Tag,
  Clock,
  Save,
  Sparkles,
  Loader2,
  Wand2,
  Bot,
} from 'lucide-react'
import { format } from 'date-fns'

interface AIProvider {
  id: string
  provider: string
  name: string | null
  is_active: boolean
}

interface PromptPartial {
  id: string
  organization_id: string
  name: string
  description: string | null
  content: string
  tags: string[] | null
  current_version: number
  created_at: string
  updated_at: string
  created_by: string | null
}

interface PromptPartialVersion {
  id: string
  prompt_partial_id: string
  version: number
  content: string
  change_summary: string | null
  created_at: string
  created_by: string | null
}

interface PromptPartialDetail extends PromptPartial {
  versions: PromptPartialVersion[]
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  deepseek: 'DeepSeek',
  groq: 'Groq',
}

function LLMProviderSelector({
  selectedProvider,
  selectedModel,
  onProviderChange,
  onModelChange,
}: {
  selectedProvider: string
  selectedModel: string
  onProviderChange: (provider: string) => void
  onModelChange: (model: string) => void
}) {
  const { data: aiProviders = [] } = useQuery<AIProvider[]>({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const activeProviders = aiProviders.filter((p) => p.is_active)

  const { data: modelOptions } = useQuery({
    queryKey: ['model-options', selectedProvider],
    queryFn: () => apiClient.getModelOptions(selectedProvider),
    enabled: !!selectedProvider,
  })

  const llmModels = modelOptions?.llm || []

  useEffect(() => {
    if (selectedProvider && llmModels.length > 0 && !llmModels.includes(selectedModel)) {
      onModelChange(llmModels[0])
    }
  }, [selectedProvider, llmModels, selectedModel, onModelChange])

  return (
    <div className="flex gap-3">
      <div className="flex-1">
        <label className="block text-xs font-medium text-gray-600 mb-1">
          <Bot className="w-3 h-3 inline mr-1" />
          LLM Provider
        </label>
        <select
          value={selectedProvider}
          onChange={(e) => {
            onProviderChange(e.target.value)
            onModelChange('')
          }}
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
        >
          <option value="">Auto-detect (use first available)</option>
          {activeProviders.map((p) => (
            <option key={p.id} value={p.provider}>
              {PROVIDER_LABELS[p.provider] || p.provider}
              {p.name ? ` — ${p.name}` : ''}
            </option>
          ))}
        </select>
        {activeProviders.length === 0 && (
          <p className="mt-1 text-xs text-amber-600">
            No AI providers configured. Add one in AI Providers settings.
          </p>
        )}
      </div>
      <div className="flex-1">
        <label className="block text-xs font-medium text-gray-600 mb-1">Model</label>
        <select
          value={selectedModel}
          onChange={(e) => onModelChange(e.target.value)}
          disabled={!selectedProvider}
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white disabled:bg-gray-50 disabled:text-gray-400"
        >
          {!selectedProvider ? (
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
  )
}

export default function PromptPartials() {
  const queryClient = useQueryClient()
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedPartial, setSelectedPartial] = useState<PromptPartialDetail | null>(null)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(false)
  const [showVersionHistory, setShowVersionHistory] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null)
  const [previewMode, setPreviewMode] = useState<'preview' | 'raw'>('preview')
  const [compareVersion, setCompareVersion] = useState<PromptPartialVersion | null>(null)
  const [showAIGenerateModal, setShowAIGenerateModal] = useState(false)

  const { data: partials = [], isLoading } = useQuery({
    queryKey: ['prompt-partials', searchQuery],
    queryFn: () => apiClient.listPromptPartials(0, 100, searchQuery || undefined),
  })

  const { data: partialDetail, isLoading: isDetailLoading } = useQuery({
    queryKey: ['prompt-partial', selectedPartial?.id],
    queryFn: () => apiClient.getPromptPartial(selectedPartial!.id),
    enabled: !!selectedPartial?.id,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deletePromptPartial(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompt-partials'] })
      if (selectedPartial && showDeleteConfirm === selectedPartial.id) {
        setSelectedPartial(null)
      }
      setShowDeleteConfirm(null)
    },
  })

  const cloneMutation = useMutation({
    mutationFn: (id: string) => apiClient.clonePromptPartial(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompt-partials'] })
    },
  })

  const revertMutation = useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      apiClient.revertPromptPartial(id, version),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompt-partials'] })
      queryClient.invalidateQueries({ queryKey: ['prompt-partial'] })
      setCompareVersion(null)
    },
  })

  const handleSelectPartial = (partial: PromptPartial) => {
    setSelectedPartial(partial as PromptPartialDetail)
    setShowVersionHistory(false)
    setCompareVersion(null)
  }

  return (
    <div className="h-[calc(100vh-7rem)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Prompt Partials</h1>
          <p className="mt-1 text-sm text-gray-500">
            Create, manage, and version reusable prompt templates
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowAIGenerateModal(true)}
            className="inline-flex items-center gap-2 px-4 py-2 bg-amber-50 text-amber-700 text-sm font-medium rounded-lg border border-amber-300 hover:bg-amber-100 transition-colors"
          >
            <Sparkles className="h-4 w-4" />
            AI Generate
          </button>
          <button
            onClick={() => setShowCreateModal(true)}
            className="inline-flex items-center gap-2 px-4 py-2 bg-gray-900 text-white text-sm font-medium rounded-lg hover:bg-gray-800 transition-colors"
          >
            <Plus className="h-4 w-4" />
            New Prompt
          </button>
        </div>
      </div>

      {/* Main Content - Split View */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* Left Panel - List */}
        <div className="w-80 flex-shrink-0 flex flex-col bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          {/* Search */}
          <div className="p-3 border-b border-gray-200">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
              <input
                type="text"
                placeholder="Search prompts..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
              />
            </div>
          </div>

          {/* List */}
          <div className="flex-1 overflow-y-auto">
            {isLoading ? (
              <div className="flex items-center justify-center h-32">
                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-900" />
              </div>
            ) : partials.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-48 px-4 text-center">
                <FileText className="h-10 w-10 text-gray-300 mb-3" />
                <p className="text-sm text-gray-500">
                  {searchQuery ? 'No prompts match your search' : 'No prompt partials yet'}
                </p>
                {!searchQuery && (
                  <button
                    onClick={() => setShowCreateModal(true)}
                    className="mt-3 text-sm text-gray-700 font-medium hover:text-gray-900"
                  >
                    Create your first prompt
                  </button>
                )}
              </div>
            ) : (
              partials.map((partial: PromptPartial) => (
                <button
                  key={partial.id}
                  onClick={() => handleSelectPartial(partial)}
                  className={`w-full text-left px-4 py-3 border-b border-gray-100 hover:bg-gray-50 transition-colors ${
                    selectedPartial?.id === partial.id ? 'bg-gray-50 border-l-4 border-l-gray-900' : 'border-l-4 border-l-transparent'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-gray-900 truncate">{partial.name}</p>
                      {partial.description && (
                        <p className="text-xs text-gray-500 mt-0.5 truncate">{partial.description}</p>
                      )}
                      <div className="flex items-center gap-2 mt-1.5">
                        <span className="inline-flex items-center gap-1 text-xs text-gray-400">
                          <History className="h-3 w-3" />
                          v{partial.current_version}
                        </span>
                        <span className="text-xs text-gray-400">
                          {format(new Date(partial.updated_at), 'MMM d, yyyy')}
                        </span>
                      </div>
                    </div>
                    <ChevronRight className="h-4 w-4 text-gray-400 flex-shrink-0 mt-0.5" />
                  </div>
                  {partial.tags && partial.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      {partial.tags.slice(0, 3).map((tag) => (
                        <span
                          key={tag}
                          className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-gray-100 text-gray-600"
                        >
                          {tag}
                        </span>
                      ))}
                      {partial.tags.length > 3 && (
                        <span className="text-xs text-gray-400">+{partial.tags.length - 3}</span>
                      )}
                    </div>
                  )}
                </button>
              ))
            )}
          </div>
        </div>

        {/* Right Panel - Detail / Preview */}
        <div className="flex-1 flex flex-col bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          {selectedPartial ? (
            <>
              {/* Detail Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
                <div className="min-w-0 flex-1">
                  <h2 className="text-lg font-semibold text-gray-900 truncate">
                    {partialDetail?.name || selectedPartial.name}
                  </h2>
                  {(partialDetail?.description || selectedPartial.description) && (
                    <p className="text-sm text-gray-500 mt-0.5">
                      {partialDetail?.description || selectedPartial.description}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2 ml-4 flex-shrink-0">
                  {/* Preview / Raw toggle */}
                  <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
                    <button
                      onClick={() => setPreviewMode('preview')}
                      className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                        previewMode === 'preview'
                          ? 'bg-white text-gray-900 shadow-sm'
                          : 'text-gray-500 hover:text-gray-700'
                      }`}
                    >
                      <Eye className="h-3.5 w-3.5" />
                      Preview
                    </button>
                    <button
                      onClick={() => setPreviewMode('raw')}
                      className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                        previewMode === 'raw'
                          ? 'bg-white text-gray-900 shadow-sm'
                          : 'text-gray-500 hover:text-gray-700'
                      }`}
                    >
                      <Code className="h-3.5 w-3.5" />
                      Raw
                    </button>
                  </div>

                  <button
                    onClick={() => setShowVersionHistory(!showVersionHistory)}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                      showVersionHistory
                        ? 'bg-gray-900 text-white border-gray-900'
                        : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <History className="h-3.5 w-3.5" />
                    Versions ({partialDetail?.current_version || selectedPartial.current_version})
                  </button>
                  <button
                    onClick={() => setShowEditModal(true)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 transition-colors"
                  >
                    <Edit3 className="h-3.5 w-3.5" />
                    Edit
                  </button>
                  <button
                    onClick={() => cloneMutation.mutate(selectedPartial.id)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 transition-colors"
                    title="Clone"
                  >
                    <Copy className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => setShowDeleteConfirm(selectedPartial.id)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-red-200 bg-white text-red-600 hover:bg-red-50 transition-colors"
                    title="Delete"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              {/* Tags */}
              {(partialDetail?.tags || selectedPartial.tags) && (
                <div className="flex items-center gap-2 px-6 py-2 border-b border-gray-100 bg-gray-50/50">
                  <Tag className="h-3.5 w-3.5 text-gray-400" />
                  <div className="flex flex-wrap gap-1">
                    {(partialDetail?.tags || selectedPartial.tags || []).map((tag: string) => (
                      <span
                        key={tag}
                        className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-200 text-gray-700"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Content Area */}
              <div className="flex-1 flex min-h-0">
                {/* Main content */}
                <div className={`flex-1 overflow-y-auto ${showVersionHistory ? 'border-r border-gray-200' : ''}`}>
                  {compareVersion ? (
                    <div className="p-6">
                      <div className="flex items-center justify-between mb-4">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-gray-900">
                            Comparing: Current (v{partialDetail?.current_version || selectedPartial.current_version})
                            vs v{compareVersion.version}
                          </span>
                        </div>
                        <button
                          onClick={() => setCompareVersion(null)}
                          className="text-xs text-gray-500 hover:text-gray-700"
                        >
                          Close comparison
                        </button>
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <div className="text-xs font-medium text-gray-500 mb-2 flex items-center gap-1">
                            <span className="inline-block w-2 h-2 rounded-full bg-green-500" />
                            Current (v{partialDetail?.current_version || selectedPartial.current_version})
                          </div>
                          <div className="bg-green-50 border border-green-200 rounded-lg p-4 prose prose-sm max-w-none">
                            <ReactMarkdown>{partialDetail?.content || selectedPartial.content}</ReactMarkdown>
                          </div>
                        </div>
                        <div>
                          <div className="text-xs font-medium text-gray-500 mb-2 flex items-center gap-1">
                            <span className="inline-block w-2 h-2 rounded-full bg-blue-500" />
                            Version {compareVersion.version}
                          </div>
                          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 prose prose-sm max-w-none">
                            <ReactMarkdown>{compareVersion.content}</ReactMarkdown>
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : isDetailLoading ? (
                    <div className="flex items-center justify-center h-32">
                      <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-900" />
                    </div>
                  ) : previewMode === 'preview' ? (
                    <div className="p-6 prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-code:text-gray-800 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100">
                      <ReactMarkdown>
                        {partialDetail?.content || selectedPartial.content}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <div className="p-6">
                      <pre className="whitespace-pre-wrap text-sm text-gray-800 font-mono bg-gray-50 rounded-lg p-4 border border-gray-200">
                        {partialDetail?.content || selectedPartial.content}
                      </pre>
                    </div>
                  )}
                </div>

                {/* Version History Sidebar */}
                {showVersionHistory && (
                  <div className="w-72 flex-shrink-0 flex flex-col overflow-hidden">
                    <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
                      <h3 className="text-sm font-semibold text-gray-900">Version History</h3>
                    </div>
                    <div className="flex-1 overflow-y-auto">
                      {(partialDetail?.versions || []).map((version: PromptPartialVersion) => (
                        <div
                          key={version.id}
                          className={`px-4 py-3 border-b border-gray-100 hover:bg-gray-50 ${
                            version.version === (partialDetail?.current_version || selectedPartial.current_version)
                              ? 'bg-gray-50'
                              : ''
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-gray-900">
                                v{version.version}
                              </span>
                              {version.version === (partialDetail?.current_version || selectedPartial.current_version) && (
                                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700">
                                  Current
                                </span>
                              )}
                            </div>
                          </div>
                          {version.change_summary && (
                            <p className="text-xs text-gray-500 mt-1">{version.change_summary}</p>
                          )}
                          <div className="flex items-center gap-1 mt-1 text-xs text-gray-400">
                            <Clock className="h-3 w-3" />
                            {format(new Date(version.created_at), 'MMM d, yyyy HH:mm')}
                          </div>
                          <div className="flex items-center gap-2 mt-2">
                            <button
                              onClick={() => setCompareVersion(version)}
                              className="text-xs text-gray-600 hover:text-gray-900 font-medium"
                            >
                              Compare
                            </button>
                            {version.version !== (partialDetail?.current_version || selectedPartial.current_version) && (
                              <button
                                onClick={() =>
                                  revertMutation.mutate({
                                    id: selectedPartial.id,
                                    version: version.version,
                                  })
                                }
                                className="inline-flex items-center gap-1 text-xs text-amber-600 hover:text-amber-800 font-medium"
                              >
                                <RotateCcw className="h-3 w-3" />
                                Revert
                              </button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
              <FileText className="h-16 w-16 text-gray-200 mb-4" />
              <h3 className="text-lg font-medium text-gray-900 mb-1">Select a prompt</h3>
              <p className="text-sm text-gray-500 max-w-sm">
                Choose a prompt partial from the list to view its content, version history, and manage it.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <PromptPartialModal
          onClose={() => setShowCreateModal(false)}
          onSaved={() => {
            setShowCreateModal(false)
            queryClient.invalidateQueries({ queryKey: ['prompt-partials'] })
          }}
        />
      )}

      {/* Edit Modal */}
      {showEditModal && selectedPartial && (
        <PromptPartialModal
          partial={partialDetail || selectedPartial}
          onClose={() => setShowEditModal(false)}
          onSaved={() => {
            setShowEditModal(false)
            queryClient.invalidateQueries({ queryKey: ['prompt-partials'] })
            queryClient.invalidateQueries({ queryKey: ['prompt-partial'] })
          }}
        />
      )}

      {/* AI Generate Modal */}
      {showAIGenerateModal && (
        <AIGenerateModal
          onClose={() => setShowAIGenerateModal(false)}
          onCreated={() => {
            setShowAIGenerateModal(false)
            queryClient.invalidateQueries({ queryKey: ['prompt-partials'] })
          }}
        />
      )}

      {/* Delete Confirmation */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-xl shadow-xl p-6 max-w-sm w-full mx-4">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Delete Prompt Partial</h3>
            <p className="text-sm text-gray-500 mb-6">
              This will permanently delete this prompt partial and all its version history. This action cannot be undone.
            </p>
            <div className="flex items-center gap-3 justify-end">
              <button
                onClick={() => setShowDeleteConfirm(null)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={() => deleteMutation.mutate(showDeleteConfirm)}
                disabled={deleteMutation.isPending}
                className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


function PromptPartialModal({
  partial,
  onClose,
  onSaved,
}: {
  partial?: PromptPartialDetail | PromptPartial
  onClose: () => void
  onSaved: () => void
}) {
  const isEditing = !!partial
  const [name, setName] = useState(partial?.name || '')
  const [description, setDescription] = useState(partial?.description || '')
  const [content, setContent] = useState(partial?.content || '')
  const [tagsInput, setTagsInput] = useState((partial?.tags || []).join(', '))
  const [changeSummary, setChangeSummary] = useState('')
  const [editorMode, setEditorMode] = useState<'write' | 'preview'>('write')
  const [error, setError] = useState('')
  const [showImprovePanel, setShowImprovePanel] = useState(false)
  const [improveInstructions, setImproveInstructions] = useState('')
  const [improveProvider, setImproveProvider] = useState('')
  const [improveModel, setImproveModel] = useState('')

  const improveMutation = useMutation({
    mutationFn: (data: { content: string; instructions?: string; provider?: string; model?: string }) =>
      apiClient.improvePromptWithAI(data),
    onSuccess: (data) => {
      setContent(data.content)
      setShowImprovePanel(false)
      setImproveInstructions('')
      setEditorMode('preview')
    },
    onError: (err: any) => {
      setError(err?.response?.data?.detail || 'Failed to improve prompt with AI')
    },
  })

  const createMutation = useMutation({
    mutationFn: (data: { name: string; description?: string; content: string; tags?: string[] }) =>
      apiClient.createPromptPartial(data),
    onSuccess: () => onSaved(),
    onError: (err: any) => {
      setError(err?.response?.data?.detail || 'Failed to create prompt partial')
    },
  })

  const updateMutation = useMutation({
    mutationFn: (data: {
      name?: string
      description?: string
      content?: string
      tags?: string[]
      change_summary?: string
    }) => apiClient.updatePromptPartial(partial!.id, data),
    onSuccess: () => onSaved(),
    onError: (err: any) => {
      setError(err?.response?.data?.detail || 'Failed to update prompt partial')
    },
  })

  const handleSubmit = () => {
    setError('')
    if (!name.trim()) {
      setError('Name is required')
      return
    }
    if (!content.trim()) {
      setError('Content is required')
      return
    }

    const tags = tagsInput
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)

    if (isEditing) {
      updateMutation.mutate({
        name: name.trim(),
        description: description.trim() || undefined,
        content: content,
        tags: tags.length > 0 ? tags : undefined,
        change_summary: changeSummary.trim() || undefined,
      })
    } else {
      createMutation.mutate({
        name: name.trim(),
        description: description.trim() || undefined,
        content: content,
        tags: tags.length > 0 ? tags : undefined,
      })
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl mx-4 max-h-[90vh] flex flex-col">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">
            {isEditing ? 'Edit Prompt Partial' : 'Create Prompt Partial'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-500">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {error && (
            <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">
              {error}
            </div>
          )}

          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., System Prompt - Customer Support"
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Description <span className="text-gray-400">(optional)</span>
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Brief description of what this prompt does"
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
            />
          </div>

          {/* Tags */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Tags <span className="text-gray-400">(comma-separated, optional)</span>
            </label>
            <input
              type="text"
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              placeholder="e.g., system, support, v2"
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
            />
          </div>

          {/* Content */}
          <div className="flex-1">
            <div className="flex items-center justify-between mb-1">
              <label className="block text-sm font-medium text-gray-700">Content</label>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    if (!content.trim()) {
                      setError('Write some content first before improving with AI')
                      return
                    }
                    setShowImprovePanel(!showImprovePanel)
                  }}
                  disabled={improveMutation.isPending}
                  className={`inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-lg border transition-colors ${
                    showImprovePanel
                      ? 'bg-amber-100 text-amber-800 border-amber-300'
                      : 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100'
                  }`}
                >
                  {improveMutation.isPending ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Wand2 className="h-3 w-3" />
                  )}
                  {improveMutation.isPending ? 'Improving...' : 'Improve with AI'}
                </button>
                <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
                  <button
                    onClick={() => setEditorMode('write')}
                    className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                      editorMode === 'write'
                        ? 'bg-white text-gray-900 shadow-sm'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    <Code className="h-3 w-3" />
                    Write
                  </button>
                  <button
                    onClick={() => setEditorMode('preview')}
                    className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                      editorMode === 'preview'
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

            {/* AI Improve Panel */}
            {showImprovePanel && (
              <div className="mb-2 p-3 bg-amber-50 rounded-lg border border-amber-200">
                <div className="flex items-center gap-2 mb-2">
                  <Sparkles className="h-4 w-4 text-amber-600" />
                  <span className="text-sm font-medium text-amber-900">Improve with AI</span>
                </div>
                <p className="text-xs text-amber-700 mb-3">
                  AI will restructure your content into well-formatted markdown, improving clarity and organization.
                </p>
                <div className="mb-3">
                  <LLMProviderSelector
                    selectedProvider={improveProvider}
                    selectedModel={improveModel}
                    onProviderChange={setImproveProvider}
                    onModelChange={setImproveModel}
                  />
                </div>
                <input
                  type="text"
                  value={improveInstructions}
                  onChange={(e) => setImproveInstructions(e.target.value)}
                  placeholder="Optional: specific instructions (e.g., 'make it more concise', 'add examples')"
                  className="w-full px-3 py-2 text-sm border border-amber-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white mb-2"
                />
                <div className="flex items-center gap-2 justify-end">
                  <button
                    onClick={() => setShowImprovePanel(false)}
                    className="px-3 py-1.5 text-xs font-medium text-gray-600 hover:text-gray-800"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() =>
                      improveMutation.mutate({
                        content,
                        instructions: improveInstructions || undefined,
                        ...(improveProvider ? { provider: improveProvider } : {}),
                        ...(improveModel ? { model: improveModel } : {}),
                      })
                    }
                    disabled={improveMutation.isPending || !content.trim()}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50"
                  >
                    {improveMutation.isPending ? (
                      <><Loader2 className="h-3 w-3 animate-spin" /> Improving...</>
                    ) : (
                      <><Wand2 className="h-3 w-3" /> Improve Now</>
                    )}
                  </button>
                </div>
              </div>
            )}

            {editorMode === 'write' ? (
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="Write your prompt content here... Markdown is supported."
                rows={12}
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent font-mono resize-y"
              />
            ) : (
              <div className="min-h-[240px] max-h-[400px] overflow-y-auto border border-gray-300 rounded-lg p-4 prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-code:text-gray-800 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100">
                {content ? (
                  <ReactMarkdown>{content}</ReactMarkdown>
                ) : (
                  <p className="text-gray-400 italic">Nothing to preview yet...</p>
                )}
              </div>
            )}
          </div>

          {/* Change Summary (only for edits) */}
          {isEditing && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Change Summary <span className="text-gray-400">(optional)</span>
              </label>
              <input
                type="text"
                value={changeSummary}
                onChange={(e) => setChangeSummary(e.target.value)}
                placeholder="Briefly describe what changed"
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
              />
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={isPending}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-lg hover:bg-gray-800 disabled:opacity-50 transition-colors"
          >
            <Save className="h-4 w-4" />
            {isPending ? 'Saving...' : isEditing ? 'Save Changes' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  )
}


function AIGenerateModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: () => void
}) {
  const [aiDescription, setAiDescription] = useState('')
  const [aiTone, setAiTone] = useState('professional')
  const [aiFormat, setAiFormat] = useState('structured')
  const [aiProvider, setAiProvider] = useState('')
  const [aiModel, setAiModel] = useState('')
  const [generatedContent, setGeneratedContent] = useState('')
  const [promptName, setPromptName] = useState('')
  const [promptDescription, setPromptDescription] = useState('')
  const [tagsInput, setTagsInput] = useState('')
  const [step, setStep] = useState<'generate' | 'review'>('generate')
  const [error, setError] = useState('')

  const generateMutation = useMutation({
    mutationFn: (data: { description: string; tone?: string; format_style?: string; provider?: string; model?: string }) =>
      apiClient.generatePromptWithAI(data),
    onSuccess: (data) => {
      setGeneratedContent(data.content)
      setStep('review')
      setError('')
    },
    onError: (err: any) => {
      setError(err?.response?.data?.detail || 'Failed to generate prompt with AI')
    },
  })

  const saveMutation = useMutation({
    mutationFn: (data: { name: string; description?: string; content: string; tags?: string[] }) =>
      apiClient.createPromptPartial(data),
    onSuccess: () => onCreated(),
    onError: (err: any) => {
      setError(err?.response?.data?.detail || 'Failed to save prompt')
    },
  })

  const handleGenerate = () => {
    setError('')
    if (!aiDescription.trim()) {
      setError('Please describe what kind of prompt you need')
      return
    }
    generateMutation.mutate({
      description: aiDescription,
      tone: aiTone,
      format_style: aiFormat,
      ...(aiProvider ? { provider: aiProvider } : {}),
      ...(aiModel ? { model: aiModel } : {}),
    })
  }

  const handleSave = () => {
    setError('')
    if (!promptName.trim()) {
      setError('Please provide a name for this prompt')
      return
    }
    const tags = tagsInput
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
    saveMutation.mutate({
      name: promptName.trim(),
      description: promptDescription.trim() || undefined,
      content: generatedContent,
      tags: tags.length > 0 ? tags : undefined,
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl mx-4 max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-amber-500" />
            <h2 className="text-lg font-semibold text-gray-900">
              {step === 'generate' ? 'Generate Prompt with AI' : 'Review & Save'}
            </h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-500">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {error && (
            <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">
              {error}
            </div>
          )}

          {step === 'generate' ? (
            <>
              {/* Description */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  What kind of prompt do you need?
                </label>
                <textarea
                  value={aiDescription}
                  onChange={(e) => setAiDescription(e.target.value)}
                  placeholder="e.g., A system prompt for a customer support chatbot that handles refund requests, tracks order status, and escalates complex issues to human agents..."
                  rows={4}
                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent resize-y"
                />
              </div>

              {/* Tone & Format */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Tone</label>
                  <select
                    value={aiTone}
                    onChange={(e) => setAiTone(e.target.value)}
                    className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
                  >
                    <option value="professional">Professional</option>
                    <option value="casual">Casual / Friendly</option>
                    <option value="technical">Technical</option>
                    <option value="concise">Concise / Direct</option>
                    <option value="detailed">Detailed / Thorough</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Format Style</label>
                  <select
                    value={aiFormat}
                    onChange={(e) => setAiFormat(e.target.value)}
                    className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
                  >
                    <option value="structured">Structured (sections & bullet points)</option>
                    <option value="narrative">Narrative (flowing text)</option>
                    <option value="template">Template (with placeholders)</option>
                    <option value="step-by-step">Step-by-step Instructions</option>
                  </select>
                </div>
              </div>

              {/* LLM Provider / Model selector */}
              <LLMProviderSelector
                selectedProvider={aiProvider}
                selectedModel={aiModel}
                onProviderChange={setAiProvider}
                onModelChange={setAiModel}
              />

              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
                <div className="flex items-start gap-2">
                  <Sparkles className="h-4 w-4 text-amber-600 mt-0.5 flex-shrink-0" />
                  <p className="text-xs text-amber-800">
                    {aiProvider
                      ? `Using ${PROVIDER_LABELS[aiProvider] || aiProvider}${aiModel ? ` / ${aiModel}` : ''} to generate your prompt.`
                      : 'Auto-detect will use the first available AI provider from your configuration.'}
                    {' '}You can review and edit before saving.
                  </p>
                </div>
              </div>
            </>
          ) : (
            <>
              {/* Review step - name and save options */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                  <input
                    type="text"
                    value={promptName}
                    onChange={(e) => setPromptName(e.target.value)}
                    placeholder="e.g., Customer Support System Prompt"
                    className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Tags <span className="text-gray-400">(optional)</span>
                  </label>
                  <input
                    type="text"
                    value={tagsInput}
                    onChange={(e) => setTagsInput(e.target.value)}
                    placeholder="e.g., ai-generated, support"
                    className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Description <span className="text-gray-400">(optional)</span>
                </label>
                <input
                  type="text"
                  value={promptDescription}
                  onChange={(e) => setPromptDescription(e.target.value)}
                  placeholder="Brief description"
                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent"
                />
              </div>

              {/* Generated content preview + edit */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-sm font-medium text-gray-700">Generated Content</label>
                  <span className="text-xs text-gray-400">You can edit this before saving</span>
                </div>
                <textarea
                  value={generatedContent}
                  onChange={(e) => setGeneratedContent(e.target.value)}
                  rows={8}
                  className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent font-mono resize-y"
                />
              </div>

              {/* Markdown preview */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Preview</label>
                <div className="max-h-[300px] overflow-y-auto border border-gray-200 rounded-lg p-4 bg-gray-50 prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-code:text-gray-800 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100">
                  <ReactMarkdown>{generatedContent}</ReactMarkdown>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200">
          <div>
            {step === 'review' && (
              <button
                onClick={() => {
                  setStep('generate')
                  setError('')
                }}
                className="text-sm text-gray-500 hover:text-gray-700 font-medium"
              >
                Back to description
              </button>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
            >
              Cancel
            </button>
            {step === 'generate' ? (
              <button
                onClick={handleGenerate}
                disabled={generateMutation.isPending || !aiDescription.trim()}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-amber-600 rounded-lg hover:bg-amber-700 disabled:opacity-50 transition-colors"
              >
                {generateMutation.isPending ? (
                  <><Loader2 className="h-4 w-4 animate-spin" /> Generating...</>
                ) : (
                  <><Sparkles className="h-4 w-4" /> Generate</>
                )}
              </button>
            ) : (
              <>
                <button
                  onClick={handleGenerate}
                  disabled={generateMutation.isPending}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-amber-700 bg-amber-50 border border-amber-300 rounded-lg hover:bg-amber-100 disabled:opacity-50 transition-colors"
                >
                  {generateMutation.isPending ? (
                    <><Loader2 className="h-4 w-4 animate-spin" /> Regenerating...</>
                  ) : (
                    <><Sparkles className="h-4 w-4" /> Regenerate</>
                  )}
                </button>
                <button
                  onClick={handleSave}
                  disabled={saveMutation.isPending || !promptName.trim()}
                  className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-lg hover:bg-gray-800 disabled:opacity-50 transition-colors"
                >
                  <Save className="h-4 w-4" />
                  {saveMutation.isPending ? 'Saving...' : 'Save Prompt'}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

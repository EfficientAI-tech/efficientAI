import { useEffect, useState, type ReactNode } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { FileText, Sparkles, Bot, Loader2, X, Pencil, Check, Save } from 'lucide-react'
import { createPortal } from 'react-dom'
import { getProviderInfo } from '../../../../components/shared/ProviderLogo'
import { apiClient } from '../../../../lib/api'
import { useToast } from '../../../../hooks/useToast'
import { AIProvider } from '../../../../types/api'
import { useVoicePlayground } from '../context'
import { DEFAULT_SAMPLE_TEXTS } from '../types'

interface PromptPartial {
  id: string
  name: string
  description?: string | null
  content?: string
  tags?: string[] | null
}

export default function SampleTextsPanel() {
  const {
    sampleTexts,
    setSampleTexts,
    customText,
    setCustomText,
    showAiGenerate,
    setShowAiGenerate,
    aiScenario,
    setAiScenario,
    aiSampleCount,
    setAiSampleCount,
    aiSampleLength,
    setAiSampleLength,
    generateSamplesMutation,
  } = useVoicePlayground()

  const [selectedTranscript, setSelectedTranscript] = useState(0)
  const [editingIdx, setEditingIdx] = useState<number | null>(null)
  const [editingText, setEditingText] = useState('')
  const [showSaveModal, setShowSaveModal] = useState(false)
  const [savingSampleText, setSavingSampleText] = useState('')
  const [savingSampleIndex, setSavingSampleIndex] = useState<number | null>(null)
  const [partialName, setPartialName] = useState('')
  const [partialDescription, setPartialDescription] = useState('')
  const [partialTagsInput, setPartialTagsInput] = useState('voice-playground, tts-sample')
  const [showSaveAllModal, setShowSaveAllModal] = useState(false)
  const [saveAllNamePrefix, setSaveAllNamePrefix] = useState('Voice Playground Sample')
  const [saveAllDescription, setSaveAllDescription] = useState('Saved from Voice Playground sample transcripts')
  const [saveAllTagsInput, setSaveAllTagsInput] = useState('voice-playground, tts-sample')
  const [showUseSavedModal, setShowUseSavedModal] = useState(false)
  const [savedPromptSearch, setSavedPromptSearch] = useState('')
  const [selectedSavedPromptIds, setSelectedSavedPromptIds] = useState<Set<string>>(new Set())
  const [aiGeneratedSamples, setAiGeneratedSamples] = useState<Set<string>>(new Set())

  const [selectedLlmProvider, setSelectedLlmProvider] = useState('')
  const [selectedLlmModel, setSelectedLlmModel] = useState('')
  const { showToast, ToastContainer } = useToast()

  const { data: aiProviders = [] } = useQuery<AIProvider[]>({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const { data: modelOptions } = useQuery({
    queryKey: ['model-options', selectedLlmProvider],
    queryFn: () => apiClient.getModelOptions(selectedLlmProvider),
    enabled: !!selectedLlmProvider,
  })
  const { data: savedPromptPartials = [], isLoading: isLoadingSavedPromptPartials } = useQuery<PromptPartial[]>({
    queryKey: ['voice-playground-prompt-partials', savedPromptSearch],
    queryFn: () => apiClient.listPromptPartials(0, 100, savedPromptSearch.trim() || undefined),
    enabled: showUseSavedModal,
  })

  const llmModels = modelOptions?.llm || []

  const renderModal = (content: ReactNode) => {
    if (typeof document === 'undefined') return null
    return createPortal(content, document.body)
  }

  useEffect(() => {
    if (selectedLlmProvider && llmModels.length > 0 && !llmModels.includes(selectedLlmModel)) {
      setSelectedLlmModel(llmModels[0])
    }
  }, [selectedLlmProvider, llmModels, selectedLlmModel])

  useEffect(() => {
    const newSamples = generateSamplesMutation.data?.samples || []
    if (newSamples.length === 0) return
    setAiGeneratedSamples((prev) => {
      const next = new Set(prev)
      newSamples.forEach((sample) => {
        const normalized = sample.trim()
        if (normalized) next.add(normalized)
      })
      return next
    })
  }, [generateSamplesMutation.data])

  const resetSavePromptModal = () => {
    setShowSaveModal(false)
    setSavingSampleText('')
    setSavingSampleIndex(null)
    setPartialName('')
    setPartialDescription('')
    setPartialTagsInput('voice-playground, tts-sample')
  }

  const savePromptPartialMutation = useMutation({
    mutationFn: (data: { name: string; description?: string; content: string; tags?: string[] }) =>
      apiClient.createPromptPartial(data),
    onSuccess: () => {
      showToast('Saved to Prompt Partials', 'success')
      resetSavePromptModal()
    },
    onError: (err: any) => {
      showToast(err?.response?.data?.detail || 'Failed to save prompt partial', 'error')
    },
  })

  const openSavePromptModal = (sampleText: string, sampleIndex: number) => {
    setSavingSampleText(sampleText)
    setSavingSampleIndex(sampleIndex)
    setPartialName(`Voice Playground Sample ${sampleIndex + 1}`)
    setPartialDescription('Saved from Voice Playground sample transcript')
    setPartialTagsInput('voice-playground, tts-sample')
    setShowSaveModal(true)
  }

  const resetSaveAllPromptModal = () => {
    setShowSaveAllModal(false)
    setSaveAllNamePrefix('Voice Playground Sample')
    setSaveAllDescription('Saved from Voice Playground sample transcripts')
    setSaveAllTagsInput('voice-playground, tts-sample')
  }

  const resetUseSavedPromptModal = () => {
    setShowUseSavedModal(false)
    setSavedPromptSearch('')
    setSelectedSavedPromptIds(new Set())
  }

  const handleSavePromptPartial = () => {
    if (!partialName.trim()) {
      showToast('Prompt partial name is required', 'error')
      return
    }
    if (!savingSampleText.trim()) {
      showToast('Sample text is empty', 'error')
      return
    }

    const tags = partialTagsInput
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean)

    savePromptPartialMutation.mutate({
      name: partialName.trim(),
      description: partialDescription.trim() || undefined,
      content: savingSampleText.trim(),
      tags: tags.length > 0 ? tags : undefined,
    })
  }

  const saveAllPromptPartialsMutation = useMutation({
    mutationFn: async (data: { namePrefix: string; description?: string; tags?: string[] }) => {
      const baseName = data.namePrefix.trim()
      const createRequests = sampleTexts
        .map((sample, idx) => ({ sample: sample.trim(), idx }))
        .filter((item) => item.sample.length > 0)
        .map((item) =>
          apiClient.createPromptPartial({
            name: `${baseName} ${item.idx + 1}`,
            description: data.description,
            content: item.sample,
            tags: data.tags,
          })
        )

      return Promise.allSettled(createRequests)
    },
    onSuccess: (results) => {
      const createdCount = results.filter((r) => r.status === 'fulfilled').length
      const failedCount = results.length - createdCount
      if (createdCount > 0) {
        showToast(`Saved ${createdCount} prompt partial${createdCount > 1 ? 's' : ''}`, 'success')
      }
      if (failedCount > 0) {
        showToast(`${failedCount} prompt partial${failedCount > 1 ? 's' : ''} failed to save`, 'error')
      }
      if (failedCount === 0) {
        resetSaveAllPromptModal()
      }
    },
    onError: () => {
      showToast('Failed to save prompt partials', 'error')
    },
  })

  const handleSaveAllPromptPartials = () => {
    if (!saveAllNamePrefix.trim()) {
      showToast('Name prefix is required', 'error')
      return
    }
    if (sampleTexts.length === 0) {
      showToast('No sample texts to save', 'error')
      return
    }

    const tags = saveAllTagsInput
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean)

    saveAllPromptPartialsMutation.mutate({
      namePrefix: saveAllNamePrefix.trim(),
      description: saveAllDescription.trim() || undefined,
      tags: tags.length > 0 ? tags : undefined,
    })
  }

  const toggleSavedPromptSelection = (promptId: string) => {
    setSelectedSavedPromptIds((prev) => {
      const next = new Set(prev)
      if (next.has(promptId)) {
        next.delete(promptId)
      } else {
        next.add(promptId)
      }
      return next
    })
  }

  const useSavedPromptsMutation = useMutation({
    mutationFn: async (partialIds: string[]) => {
      const details = await Promise.all(partialIds.map((id) => apiClient.getPromptPartial(id)))
      return details
        .map((detail) => (detail?.content || '').trim())
        .filter((content): content is string => content.length > 0)
    },
    onSuccess: (contents) => {
      const existing = new Set(sampleTexts.map((text) => text.trim()).filter(Boolean))
      const toAdd = contents.filter((content) => !existing.has(content))
      if (toAdd.length === 0) {
        showToast('No new prompts to add', 'error')
        return
      }
      setSampleTexts([...sampleTexts, ...toAdd])
      showToast(`Added ${toAdd.length} saved prompt${toAdd.length > 1 ? 's' : ''}`, 'success')
      resetUseSavedPromptModal()
    },
    onError: () => {
      showToast('Failed to load selected prompt partials', 'error')
    },
  })

  const handleAddSelectedSavedPrompts = () => {
    if (selectedSavedPromptIds.size === 0) {
      showToast('Select at least one saved prompt', 'error')
      return
    }
    useSavedPromptsMutation.mutate([...selectedSavedPromptIds])
  }

  const hasAiGeneratedSamplesInList = sampleTexts.some((text) => aiGeneratedSamples.has(text.trim()))

  return (
    <>
      <div className="bg-gradient-to-r from-indigo-50 to-violet-50 rounded-xl p-4 border border-indigo-100">
        <div className="flex items-center gap-2 mb-3">
          <FileText className="w-5 h-5 text-indigo-600" />
          <h3 className="font-semibold text-indigo-900">Sample Transcripts</h3>
        </div>
        <div className="flex gap-2 flex-wrap mb-3">
          {DEFAULT_SAMPLE_TEXTS.map((t, idx) => {
            const isActive = sampleTexts.includes(t)
            return (
              <button
                key={idx}
                onClick={() => {
                  if (isActive) {
                    setSampleTexts(sampleTexts.filter((s) => s !== t))
                  } else {
                    setSampleTexts([...sampleTexts, t])
                  }
                  setSelectedTranscript(idx)
                }}
                className={`px-3 py-2 text-xs rounded-lg transition-all ${
                  isActive
                    ? 'bg-indigo-600 text-white'
                    : 'bg-white text-gray-600 hover:bg-indigo-100 border border-indigo-200'
                }`}
              >
                Sample {idx + 1}
              </button>
            )
          })}
        </div>
        <p className="p-3 bg-white rounded-lg text-sm text-gray-700 italic border border-indigo-100">
          &ldquo;{DEFAULT_SAMPLE_TEXTS[selectedTranscript]}&rdquo;
        </p>

        {/* Custom text + AI generate */}
        <div className="mt-3 flex gap-2">
          <input
            type="text"
            value={customText}
            onChange={(e) => setCustomText(e.target.value)}
            placeholder="Add custom text..."
            className="flex-1 px-3 py-2 text-sm border border-indigo-200 rounded-lg focus:ring-2 focus:ring-indigo-500"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && customText.trim()) {
                setSampleTexts([...sampleTexts, customText.trim()])
                setCustomText('')
              }
            }}
          />
          <button
            onClick={() => {
              if (customText.trim()) {
                setSampleTexts([...sampleTexts, customText.trim()])
                setCustomText('')
              }
            }}
            disabled={!customText.trim()}
            className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
          >
            Add
          </button>
          <button
            onClick={() => setShowAiGenerate(!showAiGenerate)}
            className={`px-4 py-2 text-sm rounded-lg flex items-center gap-1.5 transition-all ${
              showAiGenerate
                ? 'bg-primary-600 text-white'
                : 'bg-primary-100 text-primary-700 hover:bg-primary-200 border border-primary-400'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            AI Generate
          </button>
          <button
            onClick={() => setShowUseSavedModal(true)}
            className="px-4 py-2 text-sm rounded-lg flex items-center gap-1.5 bg-white text-indigo-700 hover:bg-indigo-50 border border-indigo-300 transition-all"
          >
            <FileText className="w-3.5 h-3.5" />
            Use Saved
          </button>
        </div>

        {/* AI Generate panel */}
        {showAiGenerate && (
          <div className="mt-3 p-4 bg-primary-50 rounded-lg border border-primary-300">
            <div className="flex items-center gap-2 mb-2">
              <Sparkles className="w-4 h-4 text-primary-600" />
              <span className="text-sm font-medium text-primary-900">Generate samples with AI</span>
            </div>
            <p className="text-xs text-primary-700 mb-3">
              Pick an LLM provider, describe a scenario, and generate realistic TTS sample texts.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3">
              <div>
                <label className="block text-xs font-medium text-primary-800 mb-1">
                  <Bot className="w-3.5 h-3.5 inline mr-1" />
                  LLM Provider
                </label>
                <select
                  value={selectedLlmProvider}
                  onChange={(e) => {
                    setSelectedLlmProvider(e.target.value)
                    setSelectedLlmModel('')
                  }}
                  className="w-full px-3 py-2 text-sm border border-primary-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white"
                >
                  <option value="">Select LLM provider...</option>
                  {aiProviders.filter((p) => p.is_active).map((p) => (
                    <option key={p.id} value={p.provider}>
                      {getProviderInfo(p.provider).label}
                      {p.name ? ` — ${p.name}` : ''}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-primary-800 mb-1">Model</label>
                <select
                  value={selectedLlmModel}
                  onChange={(e) => setSelectedLlmModel(e.target.value)}
                  disabled={!selectedLlmProvider}
                  className="w-full px-3 py-2 text-sm border border-primary-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white disabled:bg-gray-50 disabled:text-gray-400"
                >
                  {!selectedLlmProvider ? (
                    <option value="">Select provider first</option>
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
              {aiProviders.filter((p) => p.is_active).length === 0 && (
                <p className="md:col-span-2 mt-1 text-xs text-primary-600">
                  No active AI providers configured. Add one in Integrations first.
                </p>
              )}
            </div>

            <div className="flex gap-2 mb-3">
              <input
                type="text"
                value={aiScenario}
                onChange={(e) => setAiScenario(e.target.value)}
                placeholder="e.g. Healthcare appointment reminders, Bank customer support..."
                className="flex-1 px-3 py-2 text-sm border border-primary-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white"
              />
              <div className="flex items-center gap-1">
                <label className="text-xs text-primary-800 whitespace-nowrap">Length:</label>
                <select
                  value={aiSampleLength}
                  onChange={(e) => setAiSampleLength(e.target.value as any)}
                  className="px-2 py-2 text-sm border border-primary-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white"
                >
                  <option value="short">Short (1 sentence)</option>
                  <option value="medium">Medium (2-3 sentences)</option>
                  <option value="long">Long (4-6 sentences)</option>
                  <option value="paragraph">Paragraph (7-10 sentences)</option>
                </select>
              </div>
              <div className="flex items-center gap-1">
                <label className="text-xs text-primary-800 whitespace-nowrap">Count:</label>
                <select
                  value={aiSampleCount}
                  onChange={(e) => setAiSampleCount(Number(e.target.value))}
                  className="px-2 py-2 text-sm border border-primary-300 rounded-lg focus:ring-2 focus:ring-primary-500 bg-white"
                >
                  {[3, 5, 8, 10].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="flex justify-end">
              <button
                onClick={() =>
                  generateSamplesMutation.mutate({
                    provider: selectedLlmProvider || undefined,
                    model: selectedLlmModel || undefined,
                    scenario: aiScenario || undefined,
                    count: aiSampleCount,
                    length: aiSampleLength,
                  })
                }
                disabled={generateSamplesMutation.isPending || !selectedLlmProvider || !selectedLlmModel}
                className="px-4 py-2 text-sm bg-primary-100 text-primary-700 border border-primary-400 rounded-lg hover:bg-primary-200 disabled:opacity-60 flex items-center gap-1.5"
              >
                {generateSamplesMutation.isPending ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> Generating...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-3.5 h-3.5" /> Generate Samples
                  </>
                )}
              </button>
            </div>

            {generateSamplesMutation.isError && (
              <p className="mt-2 text-xs text-red-600">
                {(generateSamplesMutation.error as any)?.response?.data?.detail ||
                  'Failed to generate samples'}
              </p>
            )}
          </div>
        )}

        {/* Active sample texts — editable list */}
        {sampleTexts.length > 0 && (
          <div className="mt-3 space-y-1.5">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs text-indigo-700">
                {sampleTexts.length} sample text{sampleTexts.length > 1 ? 's' : ''} selected
              </p>
              {hasAiGeneratedSamplesInList && (
                <button
                  onClick={() => setShowSaveAllModal(true)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-100"
                >
                  <Save className="h-3.5 w-3.5" />
                  Save All
                </button>
              )}
            </div>
            {sampleTexts.map((t, idx) => (
              <div
                key={idx}
                className="group flex items-start gap-2 bg-white rounded-lg border border-indigo-200 px-3 py-2"
              >
                <span className="flex-shrink-0 w-5 h-5 rounded bg-indigo-100 text-indigo-600 flex items-center justify-center text-[10px] font-bold mt-0.5">
                  {idx + 1}
                </span>
                {editingIdx === idx ? (
                  <textarea
                    autoFocus
                    value={editingText}
                    onChange={(e) => setEditingText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        if (editingText.trim()) {
                          setSampleTexts(
                            sampleTexts.map((s, i) => (i === idx ? editingText.trim() : s))
                          )
                        }
                        setEditingIdx(null)
                      }
                      if (e.key === 'Escape') {
                        setEditingIdx(null)
                      }
                    }}
                    className="flex-1 text-sm text-gray-800 bg-indigo-50 border border-indigo-300 rounded px-2 py-1 focus:ring-2 focus:ring-indigo-500 focus:outline-none resize-none min-h-[2.25rem]"
                    rows={2}
                  />
                ) : (
                  <span className="flex-1 text-sm text-gray-700 leading-snug pt-0.5">{t}</span>
                )}
                <div className="flex items-center gap-0.5 flex-shrink-0 mt-0.5">
                  {editingIdx === idx ? (
                    <button
                      onClick={() => {
                        if (editingText.trim()) {
                          setSampleTexts(
                            sampleTexts.map((s, i) => (i === idx ? editingText.trim() : s))
                          )
                        }
                        setEditingIdx(null)
                      }}
                      className="p-1 rounded hover:bg-green-100 text-green-600 transition-colors"
                      title="Save"
                    >
                      <Check className="w-3.5 h-3.5" />
                    </button>
                  ) : (
                    <>
                      <button
                        onClick={() => openSavePromptModal(t, idx)}
                        className="p-1 rounded hover:bg-emerald-100 text-gray-400 hover:text-emerald-600 transition-colors opacity-0 group-hover:opacity-100"
                        title="Save to Prompt Partials"
                      >
                        <Save className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => {
                          setEditingIdx(idx)
                          setEditingText(t)
                        }}
                        className="p-1 rounded hover:bg-indigo-100 text-gray-400 hover:text-indigo-600 transition-colors opacity-0 group-hover:opacity-100"
                        title="Edit"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                    </>
                  )}
                  <button
                    onClick={() => {
                      setSampleTexts(sampleTexts.filter((_, i) => i !== idx))
                      if (editingIdx === idx) setEditingIdx(null)
                    }}
                    className="p-1 rounded hover:bg-red-100 text-gray-400 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100"
                    title="Remove"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      {showSaveModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-2xl rounded-xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
              <h3 className="text-lg font-semibold text-gray-900">Save to Prompt Partials</h3>
              <button
                onClick={resetSavePromptModal}
                className="text-gray-400 hover:text-gray-600"
                aria-label="Close save prompt modal"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4 px-5 py-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Name</label>
                <input
                  type="text"
                  value={partialName}
                  onChange={(e) => setPartialName(e.target.value)}
                  placeholder="Prompt partial name"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  Description <span className="text-gray-400">(optional)</span>
                </label>
                <input
                  type="text"
                  value={partialDescription}
                  onChange={(e) => setPartialDescription(e.target.value)}
                  placeholder="Brief description"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  Tags <span className="text-gray-400">(comma-separated, optional)</span>
                </label>
                <input
                  type="text"
                  value={partialTagsInput}
                  onChange={(e) => setPartialTagsInput(e.target.value)}
                  placeholder="voice-playground, tts-sample"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  Content {savingSampleIndex !== null ? `(Sample ${savingSampleIndex + 1})` : ''}
                </label>
                <textarea
                  value={savingSampleText}
                  onChange={(e) => setSavingSampleText(e.target.value)}
                  rows={5}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 border-t border-gray-200 px-5 py-4">
              <button
                onClick={resetSavePromptModal}
                className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSavePromptPartial}
                disabled={savePromptPartialMutation.isPending || !partialName.trim() || !savingSampleText.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-60"
              >
                {savePromptPartialMutation.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <Save className="h-4 w-4" />
                    Save Prompt
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {showSaveAllModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-xl rounded-xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
              <h3 className="text-lg font-semibold text-gray-900">Save All to Prompt Partials</h3>
              <button
                onClick={resetSaveAllPromptModal}
                className="text-gray-400 hover:text-gray-600"
                aria-label="Close save all prompt modal"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="space-y-4 px-5 py-4">
              <p className="text-sm text-gray-600">
                This will create one prompt partial per sample using incremental names.
              </p>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Name Prefix</label>
                <input
                  type="text"
                  value={saveAllNamePrefix}
                  onChange={(e) => setSaveAllNamePrefix(e.target.value)}
                  placeholder="Voice Playground Sample"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  Description <span className="text-gray-400">(optional)</span>
                </label>
                <input
                  type="text"
                  value={saveAllDescription}
                  onChange={(e) => setSaveAllDescription(e.target.value)}
                  placeholder="Brief description for all saved prompts"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  Tags <span className="text-gray-400">(comma-separated, optional)</span>
                </label>
                <input
                  type="text"
                  value={saveAllTagsInput}
                  onChange={(e) => setSaveAllTagsInput(e.target.value)}
                  placeholder="voice-playground, tts-sample"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>
            </div>
            <div className="flex items-center justify-end gap-3 border-t border-gray-200 px-5 py-4">
              <button
                onClick={resetSaveAllPromptModal}
                className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveAllPromptPartials}
                disabled={saveAllPromptPartialsMutation.isPending || !saveAllNamePrefix.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-60"
              >
                {saveAllPromptPartialsMutation.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Saving All...
                  </>
                ) : (
                  <>
                    <Save className="h-4 w-4" />
                    Save All
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {showUseSavedModal && renderModal(
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[9999] p-4">
          <div className="w-full max-w-3xl rounded-xl bg-white shadow-xl max-h-[90vh] overflow-hidden flex flex-col">
            <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
              <h3 className="text-lg font-semibold text-gray-900">Use Saved Prompt Partials</h3>
              <button
                onClick={resetUseSavedPromptModal}
                className="text-gray-400 hover:text-gray-600"
                aria-label="Close use saved prompt modal"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="space-y-4 px-5 py-4 overflow-y-auto flex-1">
              <input
                type="text"
                value={savedPromptSearch}
                onChange={(e) => setSavedPromptSearch(e.target.value)}
                placeholder="Search saved prompts..."
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
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
                <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
                  {savedPromptPartials.map((partial) => {
                    const isSelected = selectedSavedPromptIds.has(partial.id)
                    return (
                      <label
                        key={partial.id}
                        className={`block cursor-pointer rounded-lg border p-3 transition-colors ${
                          isSelected ? 'border-primary-300 bg-primary-50' : 'border-gray-200 hover:bg-gray-50'
                        }`}
                      >
                        <div className="flex items-start gap-3">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSavedPromptSelection(partial.id)}
                            className="mt-1 h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                          />
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-semibold text-gray-900">{partial.name}</p>
                            {partial.description && (
                              <p className="mt-0.5 text-xs text-gray-500">{partial.description}</p>
                            )}
                            <p className="mt-1 line-clamp-2 text-xs text-gray-600">
                              {partial.content || 'Click Add Selected to load and use this prompt.'}
                            </p>
                          </div>
                        </div>
                      </label>
                    )
                  })}
                </div>
              )}
            </div>
            <div className="flex items-center justify-between border-t border-gray-200 px-5 py-4">
              <p className="text-xs text-gray-500">
                Selected: {selectedSavedPromptIds.size}
              </p>
              <div className="flex items-center gap-3">
                <button
                  onClick={resetUseSavedPromptModal}
                  className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleAddSelectedSavedPrompts}
                  disabled={selectedSavedPromptIds.size === 0 || useSavedPromptsMutation.isPending}
                  className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-60"
                >
                  {useSavedPromptsMutation.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Adding...
                    </>
                  ) : (
                    'Add Selected'
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <ToastContainer />
    </>
  )
}

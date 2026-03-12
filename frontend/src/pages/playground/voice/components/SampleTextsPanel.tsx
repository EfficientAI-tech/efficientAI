import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileText, Sparkles, Bot, Loader2, X, Pencil, Check } from 'lucide-react'
import { getProviderInfo } from '../../../../components/shared/ProviderLogo'
import { apiClient } from '../../../../lib/api'
import { AIProvider } from '../../../../types/api'
import { useVoicePlayground } from '../context'
import { DEFAULT_SAMPLE_TEXTS } from '../types'

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

  const [selectedLlmProvider, setSelectedLlmProvider] = useState('')
  const [selectedLlmModel, setSelectedLlmModel] = useState('')

  const { data: aiProviders = [] } = useQuery<AIProvider[]>({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const { data: modelOptions } = useQuery({
    queryKey: ['model-options', selectedLlmProvider],
    queryFn: () => apiClient.getModelOptions(selectedLlmProvider),
    enabled: !!selectedLlmProvider,
  })

  const llmModels = modelOptions?.llm || []

  useEffect(() => {
    if (selectedLlmProvider && llmModels.length > 0 && !llmModels.includes(selectedLlmModel)) {
      setSelectedLlmModel(llmModels[0])
    }
  }, [selectedLlmProvider, llmModels, selectedLlmModel])

  return (
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
              <p className="mt-1 text-xs text-primary-600">
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
  )
}

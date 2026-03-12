import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Sparkles, Loader2, Bot, ChevronDown } from 'lucide-react'
import { apiClient } from '../../lib/api'
import { getProviderLabel, getProviderLogo } from '../../config/providers'
import { ModelProvider } from '../../types/api'

interface AIProvider {
  id: string
  provider: string
  name: string | null
  is_active: boolean
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  deepseek: 'DeepSeek',
  groq: 'Groq',
}

interface AIGeneratePanelProps {
  onGenerate: (content: string) => void
  onCancel: () => void
  generateFn: (params: {
    description: string
    tone?: string
    format_style?: string
    provider?: string
    model?: string
  }) => Promise<{ content: string }>
  title?: string
  placeholder?: string
  showToneAndFormat?: boolean
}

export default function AIGeneratePanel({
  onGenerate,
  onCancel,
  generateFn,
  title = 'Generate with AI',
  placeholder = 'Describe what you want to generate...',
  showToneAndFormat = true,
}: AIGeneratePanelProps) {
  const [description, setDescription] = useState('')
  const [tone, setTone] = useState('professional')
  const [format, setFormat] = useState('structured')
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [showProviderDropdown, setShowProviderDropdown] = useState(false)
  const providerDropdownRef = useRef<HTMLDivElement>(null)

  const { data: aiProviders = [] } = useQuery<AIProvider[]>({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const { data: modelOptions } = useQuery({
    queryKey: ['model-options', provider],
    queryFn: () => apiClient.getModelOptions(provider),
    enabled: !!provider,
  })

  const llmModels = modelOptions?.llm || []

  useEffect(() => {
    if (provider && llmModels.length > 0 && !llmModels.includes(model)) {
      setModel(llmModels[0])
    }
  }, [provider, llmModels, model])

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (providerDropdownRef.current && !providerDropdownRef.current.contains(event.target as Node)) {
        setShowProviderDropdown(false)
      }
    }

    if (showProviderDropdown) {
      document.addEventListener('mousedown', handleClickOutside)
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [showProviderDropdown])

  const generateMutation = useMutation({
    mutationFn: generateFn,
    onSuccess: (data) => {
      onGenerate(data.content)
    },
  })

  const handleGenerate = () => {
    generateMutation.mutate({
      description,
      tone: showToneAndFormat ? tone : undefined,
      format_style: showToneAndFormat ? format : undefined,
      ...(provider ? { provider } : {}),
      ...(model ? { model } : {}),
    })
  }

  return (
    <div className="p-3 bg-amber-50 rounded-lg border border-amber-200">
      <div className="flex items-center gap-2 mb-2">
        <Sparkles className="h-4 w-4 text-amber-600" />
        <span className="text-sm font-medium text-amber-900">{title}</span>
      </div>
      <p className="text-xs text-amber-700 mb-3">
        Describe what you want and AI will generate content for you.
      </p>
      
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder={placeholder}
        rows={3}
        className="w-full px-3 py-2 text-sm border border-amber-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white mb-2"
      />
      
      {showToneAndFormat && (
        <div className="grid grid-cols-2 gap-3 mb-2">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Tone</label>
            <select
              value={tone}
              onChange={(e) => setTone(e.target.value)}
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
              value={format}
              onChange={(e) => setFormat(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
            >
              <option value="structured">Structured (sections & bullet points)</option>
              <option value="narrative">Narrative (flowing text)</option>
              <option value="template">Template (with placeholders)</option>
              <option value="step-by-step">Step-by-step Instructions</option>
            </select>
          </div>
        </div>
      )}
      
      <div className="flex gap-3 mb-2">
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            <Bot className="w-3 h-3 inline mr-1" />
            LLM Provider
          </label>
          <div className="relative" ref={providerDropdownRef}>
            <button
              type="button"
              onClick={() => setShowProviderDropdown(!showProviderDropdown)}
              className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white text-left flex items-center justify-between"
            >
              <div className="flex items-center gap-2 min-w-0">
                {provider && getProviderLogo(provider as ModelProvider) ? (
                  <img
                    src={getProviderLogo(provider as ModelProvider)!}
                    alt={getProviderLabel(provider as ModelProvider)}
                    className="w-4 h-4 object-contain"
                  />
                ) : null}
                <span className="truncate">
                  {provider
                    ? `${getProviderLabel(provider as ModelProvider)}${aiProviders.find((p) => p.provider === provider)?.name ? ` — ${aiProviders.find((p) => p.provider === provider)?.name}` : ''}`
                    : 'Auto-detect (use first available)'}
                </span>
              </div>
              <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${showProviderDropdown ? 'transform rotate-180' : ''}`} />
            </button>
            {showProviderDropdown && (
              <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-auto">
                <button
                  type="button"
                  onClick={() => {
                    setProvider('')
                    setModel('')
                    setShowProviderDropdown(false)
                  }}
                  className="w-full px-3 py-2 text-left hover:bg-gray-50 transition-colors text-sm text-gray-700"
                >
                  Auto-detect (use first available)
                </button>
                {aiProviders.filter((p) => p.is_active).map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => {
                      setProvider(p.provider)
                      setModel('')
                      setShowProviderDropdown(false)
                    }}
                    className="w-full px-3 py-2 text-left hover:bg-gray-50 transition-colors flex items-center gap-2 text-sm"
                  >
                    {getProviderLogo(p.provider as ModelProvider) ? (
                      <img
                        src={getProviderLogo(p.provider as ModelProvider)!}
                        alt={getProviderLabel(p.provider as ModelProvider)}
                        className="w-4 h-4 object-contain"
                      />
                    ) : null}
                    <span>
                      {getProviderLabel(p.provider as ModelProvider) || PROVIDER_LABELS[p.provider] || p.provider}
                      {p.name ? ` — ${p.name}` : ''}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">Model</label>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={!provider}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white disabled:bg-gray-50 disabled:text-gray-400"
          >
            {!provider ? (
              <option value="">Select a provider first</option>
            ) : llmModels.length === 0 ? (
              <option value="">Loading models...</option>
            ) : (
              llmModels.map((m: string) => (
                <option key={m} value={m}>{m}</option>
              ))
            )}
          </select>
        </div>
      </div>
      
      <div className="flex items-center gap-2 justify-end">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 text-xs font-medium text-gray-600 hover:text-gray-800"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleGenerate}
          disabled={generateMutation.isPending || !description.trim()}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50"
        >
          {generateMutation.isPending ? (
            <><Loader2 className="h-3 w-3 animate-spin" /> Generating...</>
          ) : (
            <><Sparkles className="h-3 w-3" /> Generate</>
          )}
        </button>
      </div>
      
      {generateMutation.isError && (
        <p className="mt-2 text-xs text-red-600">
          {(generateMutation.error as any)?.response?.data?.detail || 'Failed to generate'}
        </p>
      )}
    </div>
  )
}

import { useRef, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import { ModelProvider, AIProvider, Integration, IntegrationPlatform } from '../../../types/api'
import { Brain, ChevronDown } from 'lucide-react'
import { getProviderLabel, getProviderLogo } from '../../../config/providers'

interface Props {
  llmProvider: ModelProvider | null
  llmModel: string
  onProviderChange: (provider: ModelProvider | null) => void
  onModelChange: (model: string) => void
}

export default function EvaluatorLlmPicker({
  llmProvider,
  llmModel,
  onProviderChange,
  onModelChange,
}: Props) {
  const [showDropdown, setShowDropdown] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

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
          configs[provider] = {
            stt: options.stt || [],
            llm: options.llm || [],
            tts: options.tts || [],
            s2s: options.s2s || [],
          }
        } catch {
          configs[provider] = { stt: [], llm: [], tts: [], s2s: [] }
        }
      }
      return configs
    },
    staleTime: 5 * 60 * 1000,
  })

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setShowDropdown(false)
      }
    }
    if (showDropdown) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showDropdown])

  const mapIntegrationToProvider = (platform: IntegrationPlatform | string): ModelProvider | null => {
    const p = (typeof platform === 'string' ? platform : String(platform)).toLowerCase()
    switch (p) {
      case 'deepgram': return ModelProvider.DEEPGRAM
      case 'cartesia': return ModelProvider.CARTESIA
      case 'elevenlabs': return ModelProvider.ELEVENLABS
      case 'murf': return ModelProvider.MURF
      case 'sarvam': return ModelProvider.SARVAM
      case 'voicemaker': return ModelProvider.VOICEMAKER
      default: return null
    }
  }

  const configuredProviders = Array.from(
    new Set([
      ...(aiproviders.filter((p: AIProvider) => p.is_active).map((p: AIProvider) => p.provider as ModelProvider)),
      ...(integrations
        .filter((i: Integration) => i.is_active)
        .map((i: Integration) => mapIntegrationToProvider(i.platform))
        .filter((p): p is ModelProvider => Boolean(p))),
    ]),
  )

  const llmProviders = configuredProviders.filter((p) => {
    const opts = modelConfigs[p]
    return opts && opts.llm && opts.llm.length > 0
  })

  const getModelOptions = (provider: ModelProvider) =>
    modelConfigs[provider] || { stt: [], llm: [], tts: [], s2s: [] }

  return (
    <div className="space-y-3 p-4 bg-purple-50 rounded-lg border border-purple-200">
      <div className="flex items-center gap-2">
        <Brain className="h-4 w-4 text-purple-600" />
        <h4 className="text-sm font-semibold text-gray-900">Evaluation LLM</h4>
      </div>
      <p className="text-xs text-gray-500">
        Model used for post-call transcript evaluation. Defaults to gpt-4o if unset.
      </p>
      {llmProviders.length === 0 ? (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
          No AI providers with LLM models configured. Add one in Integrations.
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Provider</label>
            <div className="relative" ref={dropdownRef}>
              <button
                type="button"
                onClick={() => setShowDropdown(!showDropdown)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md bg-white text-left flex items-center justify-between text-sm"
              >
                <div className="flex items-center gap-2">
                  {llmProvider && getProviderLogo(llmProvider) ? (
                    <img src={getProviderLogo(llmProvider)!} alt="" className="w-5 h-5 object-contain rounded" />
                  ) : (
                    <Brain className="h-4 w-4 text-gray-400" />
                  )}
                  <span className={llmProvider ? 'text-gray-900' : 'text-gray-400'}>
                    {llmProvider ? getProviderLabel(llmProvider) : 'Default (OpenAI)'}
                  </span>
                </div>
                <ChevronDown className={`h-4 w-4 text-gray-400 transition-transform ${showDropdown ? 'rotate-180' : ''}`} />
              </button>
              {showDropdown && (
                <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-md shadow-lg max-h-48 overflow-auto">
                  <button
                    type="button"
                    onClick={() => {
                      onProviderChange(null)
                      onModelChange('')
                      setShowDropdown(false)
                    }}
                    className="w-full px-3 py-2 text-left hover:bg-gray-50 text-sm text-gray-500"
                  >
                    Default (OpenAI)
                  </button>
                  {llmProviders.map((provider) => (
                    <button
                      key={provider}
                      type="button"
                      onClick={() => {
                        onProviderChange(provider)
                        const models = getModelOptions(provider).llm
                        onModelChange(models.length > 0 ? models[0] : '')
                        setShowDropdown(false)
                      }}
                      className="w-full px-3 py-2 text-left hover:bg-gray-50 flex items-center gap-2 text-sm"
                    >
                      {getProviderLogo(provider) ? (
                        <img src={getProviderLogo(provider)!} alt="" className="w-5 h-5 object-contain rounded" />
                      ) : (
                        <Brain className="h-4 w-4 text-purple-600" />
                      )}
                      <span>{getProviderLabel(provider)}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Model</label>
            <select
              value={llmModel}
              onChange={(e) => onModelChange(e.target.value)}
              disabled={!llmProvider}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-primary-500 focus:border-primary-500 disabled:bg-gray-50 disabled:text-gray-400"
            >
              {!llmProvider ? (
                <option value="">Using default model</option>
              ) : (
                getModelOptions(llmProvider).llm.map((model) => (
                  <option key={model} value={model}>{model}</option>
                ))
              )}
            </select>
          </div>
        </div>
      )}
    </div>
  )
}

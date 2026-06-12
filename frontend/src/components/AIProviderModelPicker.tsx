import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bot } from 'lucide-react'
import { apiClient } from '../lib/api'
import LLMAdvancedOptionsPanel from './providers/LLMAdvancedOptionsPanel'
import type { LLMGenerationConfig } from '../config/llmGenerationParams'

interface AIProviderRow {
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

/**
 * Inline two-up provider + model dropdown shared by every AI-generate
 * surface (Prompt Partials, Visualizations TLDR, etc.).
 *
 * Empty string for ``provider`` means "auto-detect" -- the backend
 * resolver will pick the org's first active OpenAI/Anthropic/Google
 * credential. When ``provider`` is set we surface that provider's
 * available LLM models from ``apiClient.getModelOptions``.
 *
 * The component is fully controlled: the parent owns ``provider`` /
 * ``model`` state and reacts to ``onProviderChange`` / ``onModelChange``
 * so it can persist or seed the picker between mounts (e.g. seed to
 * the previously-used provider on Regenerate).
 */
export default function AIProviderModelPicker({
  provider,
  model,
  onProviderChange,
  onModelChange,
  llm_config,
  onLLMConfigChange,
  disabled = false,
  size = 'md',
  showAdvancedOptions = true,
}: {
  provider: string
  model: string
  onProviderChange: (next: string) => void
  onModelChange: (next: string) => void
  llm_config?: LLMGenerationConfig | null
  onLLMConfigChange?: (next: LLMGenerationConfig | null) => void
  disabled?: boolean
  size?: 'sm' | 'md'
  showAdvancedOptions?: boolean
}) {
  const { data: aiProviders = [] } = useQuery<AIProviderRow[]>({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const activeProviders = aiProviders.filter((p) => p.is_active)

  const { data: modelOptions } = useQuery({
    queryKey: ['model-options', provider],
    queryFn: () => apiClient.getModelOptions(provider),
    enabled: !!provider,
  })

  const llmModels: string[] = modelOptions?.llm ?? []

  // When the provider switches, snap the model selection to that
  // provider's first available LLM so the parent never holds a model
  // that doesn't belong to the active provider.
  useEffect(() => {
    if (provider && llmModels.length > 0 && !llmModels.includes(model)) {
      onModelChange(llmModels[0])
    }
  }, [provider, llmModels, model, onModelChange])

  const inputClass =
    size === 'sm'
      ? 'w-full px-2.5 py-1.5 text-xs border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white disabled:bg-gray-50 disabled:text-gray-400'
      : 'w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white disabled:bg-gray-50 disabled:text-gray-400'

  const labelClass =
    size === 'sm'
      ? 'block text-[10px] font-medium text-gray-600 mb-1'
      : 'block text-xs font-medium text-gray-600 mb-1'

  return (
    <div className="space-y-2 w-full">
      <div className="flex gap-2 w-full">
      <div className="flex-1 min-w-0">
        <label className={labelClass}>
          <Bot className="w-3 h-3 inline mr-1" />
          LLM Provider
        </label>
        <select
          value={provider}
          onChange={(e) => {
            onProviderChange(e.target.value)
            onModelChange('')
          }}
          disabled={disabled}
          className={inputClass}
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
          <p className="mt-1 text-[10px] text-amber-600">
            No AI providers configured. Add one in AI Providers settings.
          </p>
        )}
      </div>
      <div className="flex-1 min-w-0">
        <label className={labelClass}>Model</label>
        <select
          value={model}
          onChange={(e) => onModelChange(e.target.value)}
          disabled={disabled || !provider}
          className={inputClass}
        >
          {!provider ? (
            <option value="">Auto</option>
          ) : llmModels.length === 0 ? (
            <option value="">Loading models…</option>
          ) : (
            llmModels.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))
          )}
        </select>
      </div>
      </div>
      {showAdvancedOptions && provider && onLLMConfigChange && (
        <LLMAdvancedOptionsPanel
          provider={provider}
          value={llm_config ?? null}
          disabled={disabled}
          onChange={onLLMConfigChange}
        />
      )}
    </div>
  )
}

import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bot } from 'lucide-react'
import { apiClient } from '../lib/api'
import LLMAdvancedOptionsPanel from './providers/LLMAdvancedOptionsPanel'
import type { LLMGenerationConfig } from '../config/llmGenerationParams'
import type { AIProvider } from '../types/api'
import {
  resolveActiveAIProvider,
  usesGatewayDirectModel,
} from '../lib/gatewayRouting'

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  deepseek: 'DeepSeek',
  groq: 'Groq',
  custom: 'Custom',
}

/**
 * Inline provider + model dropdown shared by AI-generate surfaces.
 * Each credential row is selectable by id so multiple integrations
 * for the same provider (e.g. several custom Bifrost models) resolve
 * to the intended gateway_model.
 */
export default function AIProviderModelPicker({
  provider,
  model,
  credentialId,
  onProviderChange,
  onModelChange,
  onCredentialIdChange,
  llm_config,
  onLLMConfigChange,
  disabled = false,
  size = 'md',
  showAdvancedOptions = true,
}: {
  provider: string
  model: string
  credentialId?: string
  onProviderChange: (next: string) => void
  onModelChange: (next: string) => void
  onCredentialIdChange?: (next: string) => void
  llm_config?: LLMGenerationConfig | null
  onLLMConfigChange?: (next: LLMGenerationConfig | null) => void
  disabled?: boolean
  size?: 'sm' | 'md'
  showAdvancedOptions?: boolean
}) {
  const { data: aiProviders = [] } = useQuery<AIProvider[]>({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const activeProviders = aiProviders.filter((p) => p.is_active)

  const selectedCredential = useMemo(() => {
    if (credentialId) {
      return activeProviders.find((p) => p.id === credentialId)
    }
    if (provider) {
      return resolveActiveAIProvider(aiProviders, provider)
    }
    return undefined
  }, [activeProviders, aiProviders, credentialId, provider])

  const selectedCredentialId =
    credentialId || selectedCredential?.id || ''

  const gatewayDirectModel = usesGatewayDirectModel(selectedCredential)
    ? selectedCredential?.gateway_model?.trim()
    : null

  const resolvedProvider = selectedCredential?.provider || provider

  const { data: modelOptions } = useQuery({
    queryKey: ['model-options', resolvedProvider],
    queryFn: () => apiClient.getModelOptions(resolvedProvider),
    enabled: !!resolvedProvider && !gatewayDirectModel,
  })

  const llmModels: string[] = modelOptions?.llm ?? []

  useEffect(() => {
    if (gatewayDirectModel) {
      if (model) onModelChange('')
      return
    }
    if (resolvedProvider && llmModels.length > 0 && !llmModels.includes(model)) {
      onModelChange(llmModels[0])
    }
  }, [resolvedProvider, llmModels, model, onModelChange, gatewayDirectModel])

  const inputClass =
    size === 'sm'
      ? 'w-full px-2.5 py-1.5 text-xs border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white disabled:bg-gray-50 disabled:text-gray-400'
      : 'w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white disabled:bg-gray-50 disabled:text-gray-400'

  const labelClass =
    size === 'sm'
      ? 'block text-[10px] font-medium text-gray-600 mb-1'
      : 'block text-xs font-medium text-gray-600 mb-1'

  const handleCredentialChange = (nextId: string) => {
    if (!nextId) {
      onCredentialIdChange?.('')
      onProviderChange('')
      onModelChange('')
      return
    }
    const row = activeProviders.find((p) => p.id === nextId)
    if (!row) return
    onCredentialIdChange?.(row.id)
    onProviderChange(row.provider)
    onModelChange('')
  }

  return (
    <div className="space-y-2 w-full">
      <div className="flex gap-2 w-full">
        <div className="flex-1 min-w-0">
          <label className={labelClass}>
            <Bot className="w-3 h-3 inline mr-1" />
            LLM Provider
          </label>
          <select
            value={selectedCredentialId}
            onChange={(e) => handleCredentialChange(e.target.value)}
            disabled={disabled}
            className={inputClass}
          >
            <option value="">Auto-detect (use first available)</option>
            {activeProviders.map((p) => (
              <option key={p.id} value={p.id}>
                {PROVIDER_LABELS[p.provider] || p.provider}
                {p.name ? ` — ${p.name}` : ''}
                {p.is_default ? ' (default)' : ''}
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
          {gatewayDirectModel ? (
            <>
              <label className={labelClass}>Gateway model</label>
              <div
                className={`${inputClass} bg-gray-50 text-gray-700 truncate`}
                title={gatewayDirectModel}
              >
                {gatewayDirectModel}
              </div>
              <p className="mt-1 text-[10px] text-gray-500">
                Model is fixed on the integration — Bifrost gateway routing applies.
              </p>
            </>
          ) : (
            <>
              <label className={labelClass}>Model</label>
              <select
                value={model}
                onChange={(e) => onModelChange(e.target.value)}
                disabled={disabled || !resolvedProvider}
                className={inputClass}
              >
                {!resolvedProvider ? (
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
            </>
          )}
        </div>
      </div>
      {showAdvancedOptions && resolvedProvider && !gatewayDirectModel && onLLMConfigChange && (
        <LLMAdvancedOptionsPanel
          provider={resolvedProvider}
          value={llm_config ?? null}
          disabled={disabled}
          onChange={onLLMConfigChange}
        />
      )}
    </div>
  )
}

import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bot } from 'lucide-react'
import { apiClient } from '../lib/api'
import LLMAdvancedOptionsPanel from './providers/LLMAdvancedOptionsPanel'
import type { LLMGenerationConfig } from '../config/llmGenerationParams'
import type { AIProvider, Integration } from '../types/api'
import { INTEGRATION_LLM_PLATFORMS } from '../lib/integrationLlmPlatforms'
import { resolveActiveAIProvider } from '../lib/gatewayRouting'
import {
  formatGatewayCredentialLabel,
  resolveLLMModelsForCredential,
} from '../lib/llmModelOptions'

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  deepseek: 'DeepSeek',
  groq: 'Groq',
  custom: 'Custom',
  sarvam: 'Sarvam',
}

type CredentialRow = {
  id: string
  provider: string
  is_active: boolean
  is_default: boolean
  name: string | null
  source: 'aiprovider' | 'integration'
  gateway_model?: string | null
  routing_mode?: string | null
  effective_routing?: string | null
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
  onSelectionChange,
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
  /** Fires once with the full selection when the credential dropdown changes. */
  onSelectionChange?: (next: {
    provider: string
    model: string
    credentialId: string
  }) => void
  disabled?: boolean
  size?: 'sm' | 'md'
  showAdvancedOptions?: boolean
}) {
  const { data: aiProviders = [] } = useQuery<AIProvider[]>({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })
  const { data: integrations = [] } = useQuery<Integration[]>({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
  })

  const allCredentials: CredentialRow[] = useMemo(() => {
    const integrationRows: CredentialRow[] = integrations
      .filter((i) =>
        INTEGRATION_LLM_PLATFORMS.has((i.platform || '').toLowerCase()),
      )
      .map((i) => ({
        id: i.id,
        provider: (i.platform || '').toLowerCase(),
        is_active: i.is_active,
        is_default: i.is_default ?? false,
        name: i.name ?? null,
        source: 'integration' as const,
      }))
    const aiRows: CredentialRow[] = aiProviders.map((p) => ({
      id: p.id,
      provider: (p.provider || '').toLowerCase(),
      is_active: p.is_active,
      is_default: p.is_default ?? false,
      name: p.name ?? null,
      source: 'aiprovider' as const,
      gateway_model: p.gateway_model ?? null,
      routing_mode: p.routing_mode ?? null,
      effective_routing: p.effective_routing ?? null,
    }))
    return [...aiRows, ...integrationRows]
  }, [aiProviders, integrations])

  const activeCredentials = allCredentials.filter((p) => p.is_active)

  const selectedCredential = useMemo(() => {
    if (credentialId) {
      return activeCredentials.find((p) => p.id === credentialId)
    }
    if (provider) {
      const aiMatch = resolveActiveAIProvider(aiProviders, provider)
      if (aiMatch) {
        return activeCredentials.find(
          (p) => p.source === 'aiprovider' && p.id === aiMatch.id,
        )
      }
      return activeCredentials.find(
        (p) => p.source === 'integration' && p.provider === provider.toLowerCase(),
      )
    }
    return undefined
  }, [activeCredentials, aiProviders, credentialId, provider])

  const selectedCredentialId =
    credentialId || selectedCredential?.id || ''

  const selectedAiProvider =
    selectedCredential?.source === 'aiprovider'
      ? aiProviders.find((p) => p.id === selectedCredential.id)
      : undefined

  const gatewayCredential: AIProvider | undefined = useMemo(() => {
    if (selectedAiProvider) return selectedAiProvider
    if (
      selectedCredential?.source === 'aiprovider' &&
      selectedCredential.gateway_model?.trim()
    ) {
      return {
        id: selectedCredential.id,
        provider: selectedCredential.provider as AIProvider['provider'],
        gateway_model: selectedCredential.gateway_model,
        routing_mode: (selectedCredential.routing_mode as AIProvider['routing_mode']) ?? 'gateway',
        effective_routing: selectedCredential.effective_routing as AIProvider['effective_routing'],
        is_active: true,
        created_at: '',
        updated_at: '',
      }
    }
    return undefined
  }, [selectedAiProvider, selectedCredential])

  const resolvedProvider = selectedCredential?.provider || provider

  const { data: modelOptions } = useQuery({
    queryKey: ['model-options', resolvedProvider],
    queryFn: () => apiClient.getModelOptions(resolvedProvider),
    enabled: !!resolvedProvider && !gatewayCredential?.gateway_model?.trim(),
  })

  const rawCatalogModels: string[] = modelOptions?.llm ?? []

  const modelResolution = gatewayCredential
    ? resolveLLMModelsForCredential(gatewayCredential, rawCatalogModels)
    : { mode: 'catalog' as const, models: rawCatalogModels }

  const gatewayDirectModel =
    modelResolution.mode === 'gateway_direct' ? modelResolution.model : null

  const llmModels =
    modelResolution.mode === 'catalog' ? modelResolution.models : []

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
      if (onSelectionChange) {
        onSelectionChange({ provider: '', model: '', credentialId: '' })
        return
      }
      onCredentialIdChange?.('')
      onProviderChange('')
      onModelChange('')
      return
    }
    const row = activeCredentials.find((p) => p.id === nextId)
    if (!row) return
    if (onSelectionChange) {
      onSelectionChange({
        provider: row.provider,
        model: '',
        credentialId: row.id,
      })
      return
    }
    onCredentialIdChange?.(row.id)
    onProviderChange(row.provider)
    onModelChange('')
  }

  const credentialLabel = (row: CredentialRow) => {
    if (row.source === 'aiprovider') {
      const aiRow = aiProviders.find((p) => p.id === row.id)
      if (aiRow) {
        return formatGatewayCredentialLabel(aiRow, PROVIDER_LABELS)
      }
    }
    const base = PROVIDER_LABELS[row.provider] || row.provider
    const named = row.name ? ` — ${row.name}` : ''
    const defaultTag = row.is_default ? ' (default)' : ''
    const sourceTag =
      row.source === 'integration' ? ' [Integration]' : ''
    return `${base}${named}${defaultTag}${sourceTag}`
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
            {activeCredentials.map((p) => (
              <option key={`${p.source}-${p.id}`} value={p.id}>
                {credentialLabel(p)}
              </option>
            ))}
          </select>
          {activeCredentials.length === 0 && (
            <p className="mt-1 text-[10px] text-amber-600">
              No LLM credentials configured. Add one in AI Providers or
              Integrations settings.
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

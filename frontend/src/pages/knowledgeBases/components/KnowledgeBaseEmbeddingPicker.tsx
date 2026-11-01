import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'

export interface KnowledgeBaseEmbeddingValue {
  provider: string
  model: string
  credential_id: string | null
}

type EmbeddingConfigProvider = {
  id: string
  label?: string
  suggested_models?: Array<{ id: string; label: string }>
}

type AIProviderRow = {
  id: string
  provider?: string
  is_active?: boolean
  name?: string | null
}

export const DEFAULT_KB_EMBEDDING: KnowledgeBaseEmbeddingValue = {
  provider: 'openai',
  model: 'text-embedding-3-small',
  credential_id: null,
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  openrouter: 'OpenRouter',
  anthropic: 'Anthropic',
  google: 'Google',
  fireworks: 'Fireworks AI',
  cohere: 'Cohere',
  mistral: 'Mistral',
  together: 'Together',
  azure: 'Azure',
  aws: 'AWS',
}

function connectedProviderKeys(aiProviders: AIProviderRow[]): Set<string> {
  return new Set(
    aiProviders
      .filter((row) => row.is_active !== false)
      .map((row) => (row.provider || '').toLowerCase())
      .filter(Boolean),
  )
}

export function eligibleEmbeddingProviders(
  configProviders: EmbeddingConfigProvider[] | undefined,
  aiProviders: AIProviderRow[],
): EmbeddingConfigProvider[] {
  const connected = connectedProviderKeys(aiProviders)
  return (configProviders ?? []).filter(
    (p) =>
      (p.suggested_models?.length ?? 0) > 0 && connected.has(p.id.toLowerCase()),
  )
}

export function resolveDefaultKnowledgeBaseEmbedding(
  configProviders: EmbeddingConfigProvider[] | undefined,
  aiProviders: AIProviderRow[],
): KnowledgeBaseEmbeddingValue | null {
  const eligible = eligibleEmbeddingProviders(configProviders, aiProviders)
  const first = eligible[0]
  const firstModel = first?.suggested_models?.[0]?.id
  if (!first || !firstModel) return null
  return {
    provider: first.id,
    model: firstModel,
    credential_id: null,
  }
}

interface KnowledgeBaseEmbeddingPickerProps {
  value: KnowledgeBaseEmbeddingValue
  onChange: (value: KnowledgeBaseEmbeddingValue) => void
  disabled?: boolean
}

export default function KnowledgeBaseEmbeddingPicker({
  value,
  onChange,
  disabled,
}: KnowledgeBaseEmbeddingPickerProps) {
  const { data: config } = useQuery({
    queryKey: ['knowledge-base-embedding-config'],
    queryFn: () => apiClient.getKnowledgeBaseEmbeddingConfig(),
  })

  const { data: aiProviders = [] } = useQuery({
    queryKey: ['aiproviders'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const eligibleProviders = useMemo(
    () => eligibleEmbeddingProviders(config?.providers, aiProviders as AIProviderRow[]),
    [config?.providers, aiProviders],
  )

  const providerOptions = useMemo(() => {
    const ids = eligibleProviders.map((p) => p.id)
    if (value.provider && !ids.includes(value.provider)) {
      return [value.provider, ...ids]
    }
    return ids
  }, [eligibleProviders, value.provider])

  const modelOptions = useMemo(() => {
    const match = config?.providers?.find((p) => p.id === value.provider)
    const fromCatalog = match?.suggested_models ?? []
    if (value.model && !fromCatalog.some((m) => m.id === value.model)) {
      return [{ id: value.model, label: `${value.model} (saved)` }, ...fromCatalog]
    }
    return fromCatalog
  }, [config?.providers, value.provider, value.model])

  const credentialsForProvider = useMemo(() => {
    const key = value.provider.toLowerCase()
    return (aiProviders as AIProviderRow[]).filter(
      (row) => (row.provider || '').toLowerCase() === key && row.is_active !== false,
    )
  }, [aiProviders, value.provider])

  const requiredDims = config?.required_dimensions ?? 1536
  const hasEligible = eligibleProviders.length > 0

  const handleProviderChange = (providerId: string) => {
    const match = config?.providers?.find((p) => p.id === providerId)
    const firstModel = match?.suggested_models?.[0]?.id ?? value.model
    onChange({
      provider: providerId,
      model: firstModel,
      credential_id: null,
    })
  }

  return (
    <div className="space-y-3">
      {!hasEligible ? (
        <p className="text-sm text-amber-800 bg-amber-50 border border-amber-100 rounded-lg p-3">
          No connected AI provider has a {requiredDims}-dimension embedding model. Add OpenAI,
          OpenRouter, or Azure under{' '}
          <Link to="/integrations" className="font-medium text-primary-700 hover:underline">
            Configurations → AI Providers
          </Link>
          .
        </p>
      ) : (
        <p className="text-xs text-gray-500">
          Choose an embedding model from your integrated providers. Vectors must be {requiredDims}{' '}
          dimensions to match pgvector.
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Provider</label>
          <select
            disabled={disabled || !hasEligible}
            value={value.provider}
            onChange={(e) => handleProviderChange(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
          >
            {providerOptions.map((id) => (
              <option key={id} value={id}>
                {PROVIDER_LABELS[id] ??
                  config?.providers?.find((p) => p.id === id)?.label ??
                  id}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Credential (optional)
          </label>
          <select
            disabled={disabled || !hasEligible}
            value={value.credential_id ?? ''}
            onChange={(e) =>
              onChange({
                ...value,
                credential_id: e.target.value || null,
              })
            }
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
          >
            <option value="">Default org credential</option>
            {credentialsForProvider.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name || row.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Model</label>
        <select
          disabled={disabled || !hasEligible || modelOptions.length === 0}
          value={value.model}
          onChange={(e) => onChange({ ...value, model: e.target.value })}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono"
        >
          {modelOptions.map((opt) => (
            <option key={opt.id} value={opt.id}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}

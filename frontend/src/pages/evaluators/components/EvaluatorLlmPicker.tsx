import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../lib/api'
import { ModelProvider, type AIProvider } from '../../../types/api'
import { Brain } from 'lucide-react'
import { getProviderLabel } from '../../../config/providers'
import AnchoredSelect from '../../../components/shared/AnchoredSelect'
import { INTEGRATION_LLM_PLATFORMS } from '../../../lib/integrationLlmPlatforms'
import { buildLLMProviderKeys, resolveLLMModelsForCredential } from '../../../lib/llmModelOptions'
import { resolveActiveAIProvider } from '../../../lib/gatewayRouting'

interface Props {
  llmProvider: ModelProvider | null
  llmModel: string
  onProviderChange: (provider: ModelProvider | null) => void
  onModelChange: (model: string) => void
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  openrouter: 'OpenRouter',
  xai: 'xAI',
  fireworks: 'Fireworks AI',
  google: 'Google',
  cohere: 'Cohere',
  mistral: 'Mistral',
  sarvam: 'Sarvam',
  custom: 'Custom',
}

function providerDisplayLabel(key: string): string {
  const enumVal = Object.values(ModelProvider).find((p) => p === key)
  if (enumVal) return getProviderLabel(enumVal)
  return PROVIDER_LABELS[key] || key
}

export default function EvaluatorLlmPicker({
  llmProvider,
  llmModel,
  onProviderChange,
  onModelChange,
}: Props) {
  const { data: aiProviders = [], isLoading: aiLoading } = useQuery<AIProvider[]>({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
    staleTime: 60_000,
  })

  const { data: integrations = [], isLoading: integrationsLoading } = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiClient.listIntegrations(),
    staleTime: 60_000,
  })

  const credentialsLoading = aiLoading || integrationsLoading

  const configuredProviderKeys = useMemo(() => {
    const integrationKeys = integrations
      .filter(
        (i) => i.is_active && INTEGRATION_LLM_PLATFORMS.has((i.platform || '').toLowerCase()),
      )
      .map((i) => (i.platform || '').toLowerCase())
    return buildLLMProviderKeys(aiProviders, integrationKeys)
  }, [aiProviders, integrations])

  const providerKey = llmProvider?.toLowerCase() ?? ''

  const { data: modelOptions, isFetching: modelsLoading } = useQuery({
    queryKey: ['model-options', providerKey],
    queryFn: () => apiClient.getModelOptions(providerKey),
    enabled: Boolean(providerKey),
    staleTime: 5 * 60 * 1000,
  })

  const activeCredential = useMemo(() => {
    if (!llmProvider) return undefined
    return resolveActiveAIProvider(aiProviders, llmProvider, null)
  }, [aiProviders, llmProvider])

  const resolvedModels = useMemo(() => {
    if (!llmProvider) return []
    const catalog = modelOptions?.llm ?? []
    const resolved = resolveLLMModelsForCredential(activeCredential, catalog)
    if (resolved.mode === 'gateway_direct') return [resolved.model]
    return resolved.models
  }, [llmProvider, modelOptions?.llm, activeCredential])

  const providerOptions = useMemo(
    () => [
      { value: '', label: 'Default (OpenAI)' },
      ...configuredProviderKeys.map((key) => ({
        value: key,
        label: providerDisplayLabel(key),
      })),
    ],
    [configuredProviderKeys],
  )

  const modelOptionsList = useMemo(() => {
    if (!llmProvider) {
      return [{ value: '', label: 'Using default model' }]
    }
    if (modelsLoading && resolvedModels.length === 0) {
      return [{ value: '', label: 'Loading models…' }]
    }
    if (resolvedModels.length === 0) {
      return [{ value: '', label: 'No models for this credential' }]
    }
    return resolvedModels.map((model) => ({ value: model, label: model }))
  }, [llmProvider, modelsLoading, resolvedModels])

  useEffect(() => {
    if (!llmProvider || resolvedModels.length === 0) return
    if (llmModel && resolvedModels.includes(llmModel)) return
    onModelChange(resolvedModels[0])
  }, [llmProvider, resolvedModels, llmModel, onModelChange])

  const handleProviderSelect = (value: string) => {
    if (!value) {
      onProviderChange(null)
      onModelChange('')
      return
    }
    const provider = value as ModelProvider
    onProviderChange(provider)
    onModelChange('')
  }

  return (
    <div className="space-y-3 p-4 bg-purple-50 rounded-lg border border-purple-200">
      <div className="flex items-center gap-2">
        <Brain className="h-4 w-4 text-purple-600" />
        <h4 className="text-sm font-semibold text-gray-900">Evaluation LLM</h4>
      </div>
      <p className="text-xs text-gray-500">
        Model used for post-call transcript evaluation. Defaults to gpt-4o if unset.
      </p>

      {credentialsLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4" aria-busy="true">
          <div className="space-y-1.5">
            <div className="h-3 w-16 rounded bg-purple-100" />
            <div className="h-10 rounded-lg bg-white/80 border border-purple-100 animate-pulse" />
          </div>
          <div className="space-y-1.5">
            <div className="h-3 w-12 rounded bg-purple-100" />
            <div className="h-10 rounded-lg bg-white/80 border border-purple-100 animate-pulse" />
          </div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <AnchoredSelect
              label="Provider"
              value={llmProvider ?? ''}
              options={providerOptions}
              onChange={handleProviderSelect}
              placeholder="Default (OpenAI)"
            />
            <AnchoredSelect
              label="Model"
              value={llmModel}
              options={modelOptionsList}
              onChange={onModelChange}
              disabled={!llmProvider || (modelsLoading && resolvedModels.length === 0)}
              placeholder="Using default model"
              maxMenuHeight={320}
            />
          </div>
          {configuredProviderKeys.length === 0 ? (
            <p className="text-xs text-gray-600">
              Only the platform default is available until you add an LLM under{' '}
              <span className="font-medium">Configurations → Integrations</span>.
            </p>
          ) : null}
        </>
      )}
    </div>
  )
}

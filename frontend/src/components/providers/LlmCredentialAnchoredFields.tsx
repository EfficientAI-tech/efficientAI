import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../lib/api'
import AnchoredSelect from '../shared/AnchoredSelect'
import { logoUrlForProviderKey } from '../../lib/providerVisuals'
import { formatGatewayCredentialLabel, resolveLLMModelsForCredential } from '../../lib/llmModelOptions'
import type { AIProvider, ModelProvider } from '../../types/api'

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  custom: 'Custom',
  sarvam: 'Sarvam',
  fireworks: 'Fireworks AI',
}

type Props = {
  credentialId: string
  model: string
  activeProviders: AIProvider[]
  onCredentialChange: (credentialId: string, provider: string) => void
  onModelChange: (model: string) => void
  credentialLabel?: string
  modelLabel?: string
}

export default function LlmCredentialAnchoredFields({
  credentialId,
  model,
  activeProviders,
  onCredentialChange,
  onModelChange,
  credentialLabel = 'Credential',
  modelLabel = 'Model',
}: Props) {
  const credential = useMemo(
    () => activeProviders.find((p) => p.id === credentialId),
    [activeProviders, credentialId],
  )
  const providerKey = credential?.provider || ''
  const providerEnum = providerKey as ModelProvider
  const providerIcon = logoUrlForProviderKey(providerKey)

  const { data: modelOptions } = useQuery({
    queryKey: ['model-options', providerEnum, credentialId],
    queryFn: () => apiClient.getModelOptions(providerEnum),
    enabled: !!providerKey,
  })

  const resolution = credential
    ? resolveLLMModelsForCredential(credential, modelOptions?.llm || [])
    : { mode: 'catalog' as const, models: modelOptions?.llm || [] }
  const gatewayModel = resolution.mode === 'gateway_direct' ? resolution.model : null
  const selectable = resolution.mode === 'catalog' ? resolution.models : []

  const credentialOptions = useMemo(
    () =>
      activeProviders.map((p) => ({
        value: p.id,
        label: formatGatewayCredentialLabel(p, PROVIDER_LABELS),
        iconUrl: logoUrlForProviderKey(p.provider),
      })),
    [activeProviders],
  )

  const modelOptionsList = useMemo(
    () =>
      selectable.map((m) => ({
        value: m,
        label: m,
        iconUrl: providerIcon,
      })),
    [selectable, providerIcon],
  )

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <AnchoredSelect
        label={credentialLabel}
        value={credentialId}
        options={credentialOptions}
        placeholder="Select credential"
        onChange={(id) => {
          const row = activeProviders.find((p) => p.id === id)
          onCredentialChange(id, row?.provider || '')
          onModelChange('')
        }}
      />
      {gatewayModel ? (
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1.5">{modelLabel}</label>
          <div className="flex items-center gap-2 px-3 py-2 text-sm border border-gray-300 rounded-lg bg-gray-50 text-gray-700">
            {providerIcon ? (
              <img src={providerIcon} alt="" className="h-4 w-4 object-contain shrink-0" />
            ) : null}
            <span className="truncate">{gatewayModel}</span>
          </div>
        </div>
      ) : (
        <AnchoredSelect
          label={modelLabel}
          value={model}
          options={modelOptionsList}
          placeholder={credentialId ? 'Select model' : 'Select credential first'}
          disabled={!credentialId || modelOptionsList.length === 0}
          onChange={onModelChange}
          maxMenuHeight={320}
        />
      )}
    </div>
  )
}

import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../../lib/api'
import { AIProvider, ModelProvider } from '../../../../types/api'
import { MODERN_SELECT_CLASS } from '../../../evaluators/components/evaluatorUi'
import { resolveLLMModelsForCredential } from '../../../../lib/llmModelOptions'

export type ChatConnectionType =
  | 'internal_llm'
  | 'provider_chat'
  | 'customer_api'
  | 'messaging_channels'

export type ChatConnectionForm = {
  connectionType: ChatConnectionType
  mainLlmProvider: string
  mainLlmCredentialId: string
  mainLlmModel: string
  useSeparateTestLlm: boolean
  testLlmProvider: string
  testLlmCredentialId: string
  testLlmModel: string
}

export type ChatEvalMode = 'pre_prod_sim' | 'post_prod_live' | 'post_prod_import'

interface ChatConnectionStepProps {
  value: ChatConnectionForm
  onChange: (patch: Partial<ChatConnectionForm>) => void
  variant?: 'create' | 'compact'
  chatEvalMode?: ChatEvalMode
  onChatEvalModeChange?: (mode: ChatEvalMode) => void
}

export function validateChatConnection(value: ChatConnectionForm): boolean {
  const testOk = Boolean(value.testLlmProvider && value.testLlmModel.trim())
  if (value.connectionType === 'internal_llm') {
    return Boolean(value.mainLlmProvider && value.mainLlmModel.trim() && testOk)
  }
  return testOk
}

function LlmCredentialModelFields({
  title,
  hint,
  credentialId,
  model,
  onCredentialChange,
  onModelChange,
  activeProviders,
}: {
  title: string
  hint?: string
  credentialId: string
  model: string
  onCredentialChange: (credentialId: string, provider: string) => void
  onModelChange: (model: string) => void
  activeProviders: AIProvider[]
}) {
  const credential = useMemo(
    () => activeProviders.find((p) => p.id === credentialId),
    [activeProviders, credentialId],
  )
  const providerEnum = (credential?.provider || '') as ModelProvider
  const { data: modelOptions } = useQuery({
    queryKey: ['model-options', providerEnum, title],
    queryFn: () => apiClient.getModelOptions(providerEnum),
    enabled: !!providerEnum,
  })
  const resolution = credential
    ? resolveLLMModelsForCredential(credential, modelOptions?.llm || [])
    : { mode: 'catalog' as const, models: modelOptions?.llm || [] }
  const selectable = resolution.mode === 'catalog' ? resolution.models : []

  useEffect(() => {
    if (selectable.length && !selectable.includes(model)) {
      onModelChange(selectable[0])
    }
  }, [selectable, model, onModelChange])

  return (
    <div className="border border-gray-200 rounded-lg p-3 space-y-2.5 bg-white">
      <div>
        <h4 className="text-xs font-semibold text-gray-900">{title}</h4>
        {hint ? <p className="text-xs text-gray-500 mt-0.5">{hint}</p> : null}
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Credential</label>
        <select
          className={MODERN_SELECT_CLASS}
          value={credentialId}
          onChange={(e) => {
            const row = activeProviders.find((p) => p.id === e.target.value)
            onCredentialChange(e.target.value, row?.provider || '')
          }}
        >
          <option value="">Select API credential</option>
          {activeProviders.map((p: AIProvider) => (
            <option key={p.id} value={p.id}>
              {p.name || p.provider} ({p.provider})
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Model</label>
        <select
          className={MODERN_SELECT_CLASS}
          value={model}
          onChange={(e) => onModelChange(e.target.value)}
          disabled={!selectable.length}
        >
          <option value="">Select model</option>
          {selectable.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}

export default function ChatConnectionStep({
  value,
  onChange,
  variant: _variant = 'create',
}: ChatConnectionStepProps) {
  const { data: aiProviders = [] } = useQuery({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const activeProviders = aiProviders.filter((p: AIProvider) => p.is_active)
  const isLlmConnection = value.connectionType === 'internal_llm'

  useEffect(() => {
    if (activeProviders.length !== 1) return
    const p = activeProviders[0]
    const patch: Partial<ChatConnectionForm> = {}
    if (!value.mainLlmCredentialId && isLlmConnection) {
      patch.mainLlmCredentialId = p.id
      patch.mainLlmProvider = p.provider
    }
    if (!value.testLlmCredentialId) {
      patch.testLlmCredentialId = p.id
      patch.testLlmProvider = p.provider
    }
    if (Object.keys(patch).length) onChange(patch)
  }, [activeProviders, isLlmConnection, value.mainLlmCredentialId, value.testLlmCredentialId, onChange])

  return (
    <div className="w-full space-y-4">
      {isLlmConnection ? (
        <p className="text-sm text-gray-600 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 leading-relaxed">
          LLM-to-LLM: the <span className="font-medium text-gray-900">production prompt</span> runs on
          production LLM; the <span className="font-medium text-gray-900">test agent</span> uses the test
          agent LLM (same roles as voice evals).
        </p>
      ) : (
        <p className="text-sm text-gray-600 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
          Production replies come from your{' '}
          {value.connectionType === 'customer_api'
            ? 'HTTP API'
            : value.connectionType === 'provider_chat'
              ? 'existing platform'
              : 'messaging channel'}
          . Choose the test agent LLM that plays the customer in evals.
        </p>
      )}

      {isLlmConnection ? (
        <LlmCredentialModelFields
          title="Production LLM"
          hint="Runs your production prompt each turn."
          credentialId={value.mainLlmCredentialId}
          model={value.mainLlmModel}
          activeProviders={activeProviders}
          onCredentialChange={(id, provider) =>
            onChange({ mainLlmCredentialId: id, mainLlmProvider: provider, mainLlmModel: '' })
          }
          onModelChange={(m) => onChange({ mainLlmModel: m })}
        />
      ) : null}

      <LlmCredentialModelFields
        title="Test agent LLM"
        hint={
          isLlmConnection
            ? 'Simulates the customer / user side in evals.'
            : 'Required — simulates the customer side while production uses your live connection.'
        }
        credentialId={value.testLlmCredentialId}
        model={value.testLlmModel}
        activeProviders={activeProviders}
        onCredentialChange={(id, provider) =>
          onChange({ testLlmCredentialId: id, testLlmProvider: provider, testLlmModel: '' })
        }
        onModelChange={(m) => onChange({ testLlmModel: m })}
      />
    </div>
  )
}

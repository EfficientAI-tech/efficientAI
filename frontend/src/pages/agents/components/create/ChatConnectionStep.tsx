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
  if (value.connectionType === 'internal_llm') {
    if (!value.mainLlmProvider || !value.mainLlmModel.trim()) return false
    if (value.useSeparateTestLlm && (!value.testLlmProvider || !value.testLlmModel.trim())) {
      return false
    }
    return true
  }

  return Boolean(value.testLlmProvider && value.testLlmModel.trim())
}

export default function ChatConnectionStep({
  value,
  onChange,
  variant = 'create',
  chatEvalMode = 'pre_prod_sim',
  onChatEvalModeChange,
}: ChatConnectionStepProps) {
  const { data: aiProviders = [] } = useQuery({
    queryKey: ['ai-providers'],
    queryFn: () => apiClient.listAIProviders(),
  })

  const activeProviders = aiProviders.filter((p: AIProvider) => p.is_active)

  const mainCredential = useMemo(
    () => activeProviders.find((p) => p.id === value.mainLlmCredentialId),
    [activeProviders, value.mainLlmCredentialId],
  )
  const mainProviderEnum = (mainCredential?.provider || value.mainLlmProvider || '') as ModelProvider

  const { data: mainModelOptions } = useQuery({
    queryKey: ['model-options', mainProviderEnum],
    queryFn: () => apiClient.getModelOptions(mainProviderEnum),
    enabled: !!mainProviderEnum,
  })

  const mainResolution = mainCredential
    ? resolveLLMModelsForCredential(mainCredential, mainModelOptions?.llm || [])
    : { mode: 'catalog' as const, models: mainModelOptions?.llm || [] }
  const mainSelectable =
    mainResolution.mode === 'catalog' ? mainResolution.models : []

  useEffect(() => {
    if (!value.mainLlmCredentialId && activeProviders.length === 1) {
      const p = activeProviders[0]
      onChange({
        mainLlmCredentialId: p.id,
        mainLlmProvider: p.provider,
      })
    }
  }, [activeProviders, value.mainLlmCredentialId, onChange])

  useEffect(() => {
    if (mainSelectable.length && !mainSelectable.includes(value.mainLlmModel)) {
      onChange({ mainLlmModel: mainSelectable[0] })
    }
  }, [mainSelectable, value.mainLlmModel, onChange])

  const testCredential = useMemo(
    () => activeProviders.find((p) => p.id === value.testLlmCredentialId),
    [activeProviders, value.testLlmCredentialId],
  )
  const testProviderEnum = (testCredential?.provider || value.testLlmProvider || '') as ModelProvider
  const { data: testModelOptions } = useQuery({
    queryKey: ['model-options', testProviderEnum, 'test'],
    queryFn: () => apiClient.getModelOptions(testProviderEnum),
    enabled: value.useSeparateTestLlm && !!testProviderEnum,
  })
  const testResolution = testCredential
    ? resolveLLMModelsForCredential(testCredential, testModelOptions?.llm || [])
    : { mode: 'catalog' as const, models: testModelOptions?.llm || [] }
  const testSelectable = testResolution.mode === 'catalog' ? testResolution.models : []

  const showMainLlm = value.connectionType === 'internal_llm'

  const compact = variant === 'compact'

  return (
    <div className="w-full space-y-4">
      {!compact ? (
        <p className="text-sm font-medium text-gray-900">Evaluation models</p>
      ) : null}

      {!compact && onChatEvalModeChange ? (
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Eval mode</label>
          <select
            className={MODERN_SELECT_CLASS}
            value={chatEvalMode}
            onChange={(e) => onChatEvalModeChange(e.target.value as ChatEvalMode)}
          >
            <option value="pre_prod_sim">Pre-prod simulation</option>
            <option value="post_prod_live">Post-prod live (platform / API / webhook)</option>
            <option value="post_prod_import">Post-prod import only</option>
          </select>
        </div>
      ) : null}

      {showMainLlm ? (
      <div className="border border-gray-200 rounded-lg p-3 space-y-2.5 bg-white">
        <h4 className="text-xs font-semibold text-gray-900">Main agent LLM</h4>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Credential</label>
          <select
            className={MODERN_SELECT_CLASS}
            value={value.mainLlmCredentialId}
            onChange={(e) => {
              const row = activeProviders.find((p) => p.id === e.target.value)
              onChange({
                mainLlmCredentialId: e.target.value,
                mainLlmProvider: row?.provider || '',
                mainLlmModel: '',
              })
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
            value={value.mainLlmModel}
            onChange={(e) => onChange({ mainLlmModel: e.target.value })}
            disabled={!mainSelectable.length}
          >
            <option value="">Select model</option>
            {mainSelectable.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
      </div>
      ) : (
        <p className="text-sm text-gray-600 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
          Production replies use your{' '}
          {value.connectionType === 'customer_api'
            ? 'HTTP API'
            : value.connectionType === 'provider_chat'
              ? 'voice platform agent'
              : 'messaging channel config'}
          . Configure the simulated customer LLM below.
        </p>
      )}

      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input
          type="checkbox"
          checked={value.useSeparateTestLlm}
          onChange={(e) => onChange({ useSeparateTestLlm: e.target.checked })}
        />
        {showMainLlm
          ? 'Use a different LLM for the simulated customer (testing agent)'
          : 'Simulated customer LLM (required for pre-prod evals)'}
      </label>

      {!showMainLlm && !value.useSeparateTestLlm ? (
        <p className="text-xs text-gray-500 -mt-2">
          Main production LLM fields are hidden — we use this LLM for the persona side of the conversation.
        </p>
      ) : null}

      {value.useSeparateTestLlm || !showMainLlm ? (
        <div className="border border-gray-200 rounded-lg p-3 space-y-2.5 bg-white">
          <h4 className="text-xs font-semibold text-gray-900">
            {showMainLlm ? 'Testing agent LLM' : 'Simulated customer LLM'}
          </h4>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Credential</label>
            <select
              className={MODERN_SELECT_CLASS}
              value={value.testLlmCredentialId}
              onChange={(e) => {
                const row = activeProviders.find((p) => p.id === e.target.value)
                onChange({
                  testLlmCredentialId: e.target.value,
                  testLlmProvider: row?.provider || '',
                  testLlmModel: '',
                })
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
              value={value.testLlmModel}
              onChange={(e) => onChange({ testLlmModel: e.target.value })}
              disabled={!testSelectable.length}
            >
              <option value="">Select model</option>
              {testSelectable.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        </div>
      ) : null}
    </div>
  )
}

import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../../lib/api'
import { AIProvider, ModelProvider } from '../../../../types/api'
import { MODERN_SELECT_CLASS } from '../../../evaluators/components/evaluatorUi'
import { resolveLLMModelsForCredential } from '../../../../lib/llmModelOptions'

export type ChatConnectionForm = {
  mainLlmProvider: string
  mainLlmCredentialId: string
  mainLlmModel: string
  useSeparateTestLlm: boolean
  testLlmProvider: string
  testLlmCredentialId: string
  testLlmModel: string
}

interface ChatConnectionStepProps {
  value: ChatConnectionForm
  onChange: (patch: Partial<ChatConnectionForm>) => void
}

export function validateChatConnection(value: ChatConnectionForm): boolean {
  if (!value.mainLlmProvider || !value.mainLlmModel.trim()) return false
  if (value.useSeparateTestLlm && (!value.testLlmProvider || !value.testLlmModel.trim())) {
    return false
  }
  return true
}

export default function ChatConnectionStep({ value, onChange }: ChatConnectionStepProps) {
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

  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-900">
        <p className="font-medium">Connection layer (like Cekura)</p>
        <p className="mt-1 text-violet-800">
          <strong>Internal LLM</strong> — we run your production prompt on the Main LLM and the
          simulated customer on the Testing LLM. Provider chat and customer API hooks come next.
        </p>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-gray-700">Connection type</legend>
        <label className="flex items-center gap-2 text-sm">
          <input type="radio" checked readOnly className="text-primary-600" />
          Internal LLM (platform simulation)
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-400">
          <input type="radio" disabled />
          Provider native chat (Vapi / Retell) — coming soon
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-400">
          <input type="radio" disabled />
          Customer API (you drive agent turns) — coming soon
        </label>
      </fieldset>

      <div className="border border-gray-200 rounded-lg p-4 space-y-3 bg-white">
        <h4 className="text-sm font-semibold text-gray-900">Main agent LLM (production)</h4>
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

      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input
          type="checkbox"
          checked={value.useSeparateTestLlm}
          onChange={(e) => onChange({ useSeparateTestLlm: e.target.checked })}
        />
        Use a different LLM for the simulated customer (testing agent)
      </label>

      {value.useSeparateTestLlm ? (
        <div className="border border-gray-200 rounded-lg p-4 space-y-3 bg-white">
          <h4 className="text-sm font-semibold text-gray-900">Testing agent LLM</h4>
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

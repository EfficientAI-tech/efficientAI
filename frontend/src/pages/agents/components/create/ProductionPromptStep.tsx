import { Sparkles, Loader2 } from 'lucide-react'
import { AIProvider } from '../../../../types/api'
import { formatGatewayCredentialLabel } from '../../../../lib/llmModelOptions'
import TestAgentTemplateEditor from '../TestAgentTemplateEditor'
import {
  TestAgentTemplateDraft,
  assembleTestAgentPrompt,
  isTemplateFilled,
} from '../agentTestSetupConstants'

interface ProductionPromptStepProps {
  agentName: string
  language: string
  callType: string
  productionPrompt: string
  onProductionPromptChange: (value: string) => void
  productionPromptReadOnly?: boolean
  isFetchingProductionPrompt?: boolean
  fetchError?: string | null
  testAgentTemplate: TestAgentTemplateDraft
  onTestAgentTemplateChange: (value: TestAgentTemplateDraft) => void
  additionalContext: string
  onAdditionalContextChange: (value: string) => void
  aiProviders: AIProvider[]
  aiCredentialId: string
  onAiCredentialIdChange: (value: string) => void
  aiModel: string
  onAiModelChange: (value: string) => void
  selectableModels: string[]
  gatewayDirectModel: string | null
  aiProvider: string
  onGenerateTestPrompt: () => void
  isGenerating: boolean
  canGenerate: boolean
}

export default function ProductionPromptStep({
  productionPrompt,
  onProductionPromptChange,
  productionPromptReadOnly = false,
  isFetchingProductionPrompt = false,
  fetchError = null,
  testAgentTemplate,
  onTestAgentTemplateChange,
  additionalContext,
  onAdditionalContextChange,
  aiProviders,
  aiCredentialId,
  onAiCredentialIdChange,
  aiModel,
  onAiModelChange,
  selectableModels,
  gatewayDirectModel,
  aiProvider,
  onGenerateTestPrompt,
  isGenerating,
  canGenerate,
}: ProductionPromptStepProps) {
  const assembledPrompt = assembleTestAgentPrompt(testAgentTemplate.sections)
  const wordCount = assembledPrompt.trim().split(/\s+/).filter(Boolean).length

  const productionProse =
    'prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-code:text-gray-800 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-ul:text-gray-700 prose-ol:text-gray-700'

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium text-gray-700">
            Production Agent Prompt *
          </label>
        </div>
        {isFetchingProductionPrompt ? (
          <div className="flex items-center gap-2 text-sm text-gray-500 py-8 justify-center border border-gray-200 rounded-lg bg-gray-50">
            <Loader2 className="h-4 w-4 animate-spin" />
            Fetching production prompt from provider…
          </div>
        ) : productionPromptReadOnly ? (
          <div className="min-h-[200px] max-h-[400px] overflow-y-auto border border-gray-300 rounded-lg p-4 bg-gray-50">
            {productionPrompt.trim() ? (
              <div className={productionProse}>
                <p className="whitespace-pre-wrap text-sm text-gray-700">{productionPrompt}</p>
              </div>
            ) : (
              <p className="text-sm text-gray-400 italic">
                Production prompt will appear here after connecting your platform…
              </p>
            )}
          </div>
        ) : (
          <textarea
            value={productionPrompt}
            onChange={(e) => onProductionPromptChange(e.target.value)}
            rows={8}
            placeholder="Paste the production system prompt from your voice platform…"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent font-mono text-sm"
          />
        )}
        {fetchError && <p className="mt-1 text-xs text-red-600">{fetchError}</p>}
      </div>

      <div className="p-3 bg-gray-50 rounded-lg border border-gray-200 space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">AI Provider</label>
            <select
              value={aiCredentialId}
              onChange={(e) => {
                onAiCredentialIdChange(e.target.value)
                onAiModelChange('')
              }}
              className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-white"
            >
              <option value="">Auto-detect</option>
              {aiProviders.filter((p) => p.is_active).map((p) => (
                <option key={p.id} value={p.id}>
                  {formatGatewayCredentialLabel(p, {
                    custom: 'Custom',
                    openai: 'OpenAI',
                    anthropic: 'Anthropic',
                    google: 'Google',
                  })}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Model</label>
            <select
              value={aiModel}
              onChange={(e) => onAiModelChange(e.target.value)}
              disabled={!aiProvider || !!gatewayDirectModel}
              className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-white disabled:bg-gray-100"
            >
              {gatewayDirectModel ? (
                <option value="">{gatewayDirectModel}</option>
              ) : (
                selectableModels.map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))
              )}
            </select>
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Additional context (optional)</label>
          <textarea
            value={additionalContext}
            onChange={(e) => onAdditionalContextChange(e.target.value)}
            rows={2}
            placeholder="Industry, compliance notes, or test priorities…"
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-white"
          />
        </div>
        <button
          type="button"
          onClick={onGenerateTestPrompt}
          disabled={isGenerating || !canGenerate}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50"
        >
          {isGenerating ? (
            <>
              <Loader2 className="h-3 w-3 animate-spin" />
              Generating test template…
            </>
          ) : (
            <>
              <Sparkles className="h-3 w-3" />
              Generate from production
            </>
          )}
        </button>
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium text-gray-700">Test Agent Template *</label>
        </div>
        <TestAgentTemplateEditor
          template={testAgentTemplate}
          onChange={onTestAgentTemplateChange}
        />
        <p className={`mt-2 text-xs ${wordCount >= 10 ? 'text-green-600' : 'text-gray-500'}`}>
          {wordCount}/10 words minimum in assembled prompt
        </p>
      </div>
    </div>
  )
}

export function isPromptStepValid(
  productionPrompt: string,
  testAgentTemplate: TestAgentTemplateDraft,
): boolean {
  if (!productionPrompt.trim()) return false
  return isTemplateFilled(testAgentTemplate)
}

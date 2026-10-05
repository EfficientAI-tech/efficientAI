import { Sparkles, Loader2, RefreshCw } from 'lucide-react'
import { AIProvider } from '../../../../types/api'
import LlmCredentialAnchoredFields from '../../../../components/providers/LlmCredentialAnchoredFields'
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
  onGenerateTestPrompt: () => void
  isGenerating: boolean
  canGenerate: boolean
  importFromProvider?: {
    onClick: () => void
    isPending: boolean
    disabled?: boolean
  }
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
  selectableModels: _selectableModels,
  gatewayDirectModel: _gatewayDirectModel,
  onGenerateTestPrompt,
  isGenerating,
  canGenerate,
  importFromProvider,
}: ProductionPromptStepProps) {
  const assembledPrompt = assembleTestAgentPrompt(testAgentTemplate.sections)
  const wordCount = assembledPrompt.trim().split(/\s+/).filter(Boolean).length

  const productionProse =
    'prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-code:text-gray-800 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-ul:text-gray-700 prose-ol:text-gray-700'

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center justify-between gap-2 mb-2">
          <label className="block text-sm font-medium text-gray-700">Production prompt *</label>
          {importFromProvider ? (
            <button
              type="button"
              disabled={importFromProvider.isPending || importFromProvider.disabled}
              onClick={importFromProvider.onClick}
              className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50"
            >
              {importFromProvider.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              Import from provider
            </button>
          ) : null}
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
        <LlmCredentialAnchoredFields
          credentialId={aiCredentialId}
          model={aiModel}
          activeProviders={aiProviders.filter((p) => p.is_active)}
          onCredentialChange={(id) => {
            onAiCredentialIdChange(id)
            onAiModelChange('')
          }}
          onModelChange={onAiModelChange}
          credentialLabel="AI Provider"
        />
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
        <p
          className={`mt-2 text-xs ${
            testAgentTemplate.generated_from_production && wordCount >= 10
              ? 'text-green-600'
              : 'text-gray-500'
          }`}
        >
          {testAgentTemplate.generated_from_production
            ? `${wordCount} words in assembled prompt`
            : 'Generate from production above — manual edits alone cannot complete this step.'}
        </p>
      </div>
    </div>
  )
}

export type PromptStepValidationOptions = {
  requireGeneratedFromProduction?: boolean
}

export function isPromptStepValid(
  productionPrompt: string,
  testAgentTemplate: TestAgentTemplateDraft,
  options?: PromptStepValidationOptions,
): boolean {
  if (!productionPrompt.trim()) return false
  if (!isTemplateFilled(testAgentTemplate)) return false
  if (options?.requireGeneratedFromProduction && !testAgentTemplate.generated_from_production) {
    return false
  }
  return true
}

export function promptStepValidationMessage(
  productionPrompt: string,
  testAgentTemplate: TestAgentTemplateDraft,
  options?: PromptStepValidationOptions,
): string {
  if (!productionPrompt.trim()) return 'Production prompt is required.'
  if (!isTemplateFilled(testAgentTemplate)) {
    return 'Test agent prompt must be at least 10 words.'
  }
  if (options?.requireGeneratedFromProduction && !testAgentTemplate.generated_from_production) {
    return 'Use “Generate from production” to create the test agent prompt before continuing.'
  }
  return 'Complete the prompt step.'
}

import { useState } from 'react'
import { Sparkles, Loader2, Eye, Code } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { AIProvider } from '../../../../types/api'
import { formatGatewayCredentialLabel } from '../../../../lib/llmModelOptions'

interface ProductionPromptStepProps {
  agentName: string
  language: string
  callType: string
  productionPrompt: string
  onProductionPromptChange: (value: string) => void
  productionPromptReadOnly?: boolean
  isFetchingProductionPrompt?: boolean
  fetchError?: string | null
  testAgentPrompt: string
  onTestAgentPromptChange: (value: string) => void
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
  testAgentPrompt,
  onTestAgentPromptChange,
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
  const [productionPromptView, setProductionPromptView] = useState<'write' | 'preview'>(
    productionPromptReadOnly ? 'preview' : 'write',
  )
  const [testPromptView, setTestPromptView] = useState<'write' | 'preview'>('write')
  const wordCount = testAgentPrompt.trim().split(/\s+/).filter(Boolean).length

  const productionProse =
    'prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-code:text-gray-800 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-ul:text-gray-700 prose-ol:text-gray-700'

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium text-gray-700">
            Production Agent Prompt *
          </label>
          {!isFetchingProductionPrompt && (
            <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
              <button
                type="button"
                onClick={() => setProductionPromptView('write')}
                disabled={productionPromptReadOnly}
                className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                  productionPromptView === 'write'
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                } disabled:opacity-40 disabled:cursor-not-allowed`}
              >
                <Code className="h-3 w-3" />
                Write
              </button>
              <button
                type="button"
                onClick={() => setProductionPromptView('preview')}
                className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                  productionPromptView === 'preview'
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                <Eye className="h-3 w-3" />
                Preview
              </button>
            </div>
          )}
        </div>
        {isFetchingProductionPrompt ? (
          <div className="flex items-center gap-2 text-sm text-gray-500 py-8 justify-center border border-gray-200 rounded-lg bg-gray-50">
            <Loader2 className="h-4 w-4 animate-spin" />
            Fetching production prompt from provider…
          </div>
        ) : productionPromptView === 'write' && !productionPromptReadOnly ? (
          <textarea
            value={productionPrompt}
            onChange={(e) => onProductionPromptChange(e.target.value)}
            rows={8}
            placeholder="Paste the production system prompt from your voice platform…"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent font-mono text-sm"
          />
        ) : (
          <div className="min-h-[200px] max-h-[400px] overflow-y-auto border border-gray-300 rounded-lg p-4 bg-gray-50">
            {productionPrompt.trim() ? (
              <div className={productionProse}>
                <ReactMarkdown>{productionPrompt}</ReactMarkdown>
              </div>
            ) : (
              <p className="text-sm text-gray-400 italic">
                {productionPromptReadOnly
                  ? 'Production prompt will appear here after connecting your platform…'
                  : 'Nothing to preview yet…'}
              </p>
            )}
          </div>
        )}
        {fetchError && (
          <p className="mt-1 text-xs text-red-600">{fetchError}</p>
        )}
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
                  <option key={model} value={model}>{model}</option>
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
              Generating test prompt…
            </>
          ) : (
            <>
              <Sparkles className="h-3 w-3" />
              Generate test prompt
            </>
          )}
        </button>
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium text-gray-700">Test Agent Prompt *</label>
          <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
            <button
              type="button"
              onClick={() => setTestPromptView('write')}
              className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                testPromptView === 'write'
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <Code className="h-3 w-3" />
              Write
            </button>
            <button
              type="button"
              onClick={() => setTestPromptView('preview')}
              className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                testPromptView === 'preview'
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <Eye className="h-3 w-3" />
              Preview
            </button>
          </div>
        </div>

        {testPromptView === 'write' ? (
          <textarea
            value={testAgentPrompt}
            onChange={(e) => onTestAgentPromptChange(e.target.value)}
            className="w-full min-h-[280px] px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent font-mono text-sm resize-y"
            rows={12}
            placeholder="Generate a test prompt from your production prompt, or edit manually…"
          />
        ) : (
          <div className="min-h-[280px] max-h-[480px] overflow-y-auto border border-gray-300 rounded-lg p-4 prose prose-sm max-w-none">
            {testAgentPrompt ? (
              <ReactMarkdown>{testAgentPrompt}</ReactMarkdown>
            ) : (
              <p className="text-gray-400 italic">Nothing to preview yet…</p>
            )}
          </div>
        )}
        <p className={`mt-1 text-xs ${wordCount >= 10 ? 'text-green-600' : 'text-gray-500'}`}>
          {wordCount}/10 words minimum
        </p>
      </div>
    </div>
  )
}

export function isPromptStepValid(productionPrompt: string, testAgentPrompt: string): boolean {
  if (!productionPrompt.trim()) return false
  const words = testAgentPrompt.trim().split(/\s+/).filter(Boolean)
  return words.length >= 10
}

import { Loader2, Save, Sparkles } from 'lucide-react'
import type { UseMutationResult } from '@tanstack/react-query'
import { AIProvider } from '../../../types/api'
import { formatGatewayCredentialLabel } from '../../../lib/llmModelOptions'
import TestAgentTemplateEditor from './TestAgentTemplateEditor'
import {
  TestAgentTemplateDraft,
  assembleTestAgentPrompt,
  isTemplateFilled,
} from './agentTestSetupConstants'

export type TestAgentPromptFormSlice = {
  name: string
  language: string
  call_type: string
  description: string
  provider_prompt: string
  test_agent_template: TestAgentTemplateDraft
  prompt_variables: Record<string, string>
}

interface TestAgentPromptEditPanelProps {
  medium: 'chat' | 'voice'
  formData: TestAgentPromptFormSlice
  onChange: (patch: Partial<TestAgentPromptFormSlice>) => void
  showLegacy: boolean
  onSaveSystemPrompt: () => void
  showGeneratePanel: boolean
  onToggleGeneratePanel: () => void
  setupAdditionalContext: string
  onSetupAdditionalContextChange: (value: string) => void
  aiProviders: AIProvider[]
  aiCredentialId: string
  onAiCredentialIdChange: (id: string) => void
  aiModel: string
  onAiModelChange: (model: string) => void
  gatewayDirectModel: string | null
  selectableModels: string[]
  generateMutation: UseMutationResult<unknown, unknown, void, unknown>
}

export default function TestAgentPromptEditPanel({
  medium,
  formData,
  onChange,
  showLegacy,
  onSaveSystemPrompt,
  showGeneratePanel,
  onToggleGeneratePanel,
  setupAdditionalContext,
  onSetupAdditionalContextChange,
  aiProviders,
  aiCredentialId,
  onAiCredentialIdChange,
  aiModel,
  onAiModelChange,
  gatewayDirectModel,
  selectableModels,
  generateMutation,
}: TestAgentPromptEditPanelProps) {
  const productionTabLabel = medium === 'chat' ? 'Chat Agent' : 'Voice Agent'
  const generateHint =
    medium === 'chat'
      ? `Uses the production prompt from the ${productionTabLabel} tab to generate customer persona sections.`
      : `Uses the production agent prompt from the ${productionTabLabel} tab to generate complementary caller sections and first-message settings.`

  return (
    <div className="border border-gray-200 rounded-lg p-4 bg-white space-y-4">
      <div className="flex items-center justify-between mb-1 gap-3 flex-wrap">
        <label className="block text-sm font-medium text-gray-700">EfficientAI Test Agent Template</label>
        <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onToggleGeneratePanel}
          disabled={generateMutation.isPending}
          className={`inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-lg border transition-colors ${
              showGeneratePanel
                ? 'bg-amber-100 text-amber-800 border-amber-300'
                : 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100'
            }`}
          >
            {generateMutation.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Sparkles className="h-3 w-3" />
            )}
            {generateMutation.isPending ? 'Generating...' : 'Generate from production'}
          </button>
          <button
            type="button"
            onClick={onSaveSystemPrompt}
            disabled={!isTemplateFilled(formData.test_agent_template)}
            className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
          >
            <Save className="h-3 w-3" />
            Save Prompt
          </button>
        </div>
      </div>

      {showGeneratePanel && (
        <div className="p-3 bg-amber-50 rounded-lg border border-amber-200 space-y-3">
          <p className="text-xs text-amber-700">{generateHint}</p>
          {!formData.provider_prompt?.trim() ? (
            <p className="text-xs text-red-600">
              Add a production prompt on the {productionTabLabel} tab first.
            </p>
          ) : null}
          <textarea
            value={setupAdditionalContext}
            onChange={(e) => onSetupAdditionalContextChange(e.target.value)}
            rows={2}
            placeholder="Additional context (optional)…"
            className="w-full px-3 py-2 text-sm border border-amber-200 rounded-lg bg-white"
          />
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">LLM Provider</label>
              <select
                value={aiCredentialId}
                onChange={(e) => {
                  onAiCredentialIdChange(e.target.value)
                  onAiModelChange('')
                }}
                className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-white"
              >
                <option value="">Select credential</option>
                {aiProviders
                  .filter((p) => p.is_active)
                  .map((p) => (
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
                disabled={!aiCredentialId || !!gatewayDirectModel}
                className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-white disabled:bg-gray-100"
              >
                {!aiCredentialId ? <option value="">Select credential first</option> : null}
                {gatewayDirectModel ? (
                  <option value="">{gatewayDirectModel}</option>
                ) : (
                  selectableModels.map((m: string) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))
                )}
              </select>
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onToggleGeneratePanel}
              className="px-3 py-1.5 text-xs font-medium text-gray-600"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => generateMutation.mutate()}
              disabled={
                generateMutation.isPending ||
                !formData.provider_prompt?.trim() ||
                !aiCredentialId ||
                !(aiModel.trim() || gatewayDirectModel)
              }
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-amber-600 text-white rounded-lg disabled:opacity-50"
            >
              {generateMutation.isPending ? (
                <>
                  <Loader2 className="h-3 w-3 animate-spin" /> Generating...
                </>
              ) : (
                <>
                  <Sparkles className="h-3 w-3" /> Generate
                </>
              )}
            </button>
          </div>
        </div>
      )}

      <TestAgentTemplateEditor
        template={formData.test_agent_template}
        onChange={(test_agent_template) =>
          onChange({
            test_agent_template,
            description: assembleTestAgentPrompt(test_agent_template.sections),
          })
        }
        legacyDescription={formData.description}
        showLegacy={showLegacy}
        variant="workspace"
        simulationMedium={medium}
      />

      <div className="rounded-lg border border-gray-200 bg-white p-3">
        <div className="flex items-center justify-between gap-2 mb-2">
          <label className="text-sm font-medium text-gray-700">Custom prompt variables</label>
          <button
            type="button"
            className="text-xs font-medium text-primary-600 hover:text-primary-800"
            onClick={() => {
              const base = { ...(formData.prompt_variables || {}) }
              let n = 1
              let key = 'custom_var'
              while (base[key]) {
                n += 1
                key = `custom_var_${n}`
              }
              base[key] = ''
              onChange({ prompt_variables: base })
            }}
          >
            + Add variable
          </button>
        </div>
        <p className="text-xs text-gray-500 mb-2">
          Define keys you can insert with <code className="text-gray-700">{'{'}</code> or{' '}
          <code className="text-gray-700">@</code>. Values are optional descriptions for your team.
        </p>
        {Object.keys(formData.prompt_variables || {}).length === 0 ? (
          <p className="text-xs text-gray-400 italic">No custom variables yet.</p>
        ) : (
          <div className="space-y-2">
            {Object.entries(formData.prompt_variables || {}).map(([key, desc]) => (
              <div key={key} className="flex flex-wrap items-center gap-2">
                <input
                  type="text"
                  value={key}
                  onChange={(e) => {
                    const nextKey = e.target.value.replace(/\s+/g, '_')
                    const vars = { ...(formData.prompt_variables || {}) }
                    delete vars[key]
                    if (nextKey) vars[nextKey] = desc
                    onChange({ prompt_variables: vars })
                  }}
                  className="w-36 px-2 py-1.5 text-xs font-mono border border-gray-300 rounded-md"
                  placeholder="variable_key"
                />
                <input
                  type="text"
                  value={desc}
                  onChange={(e) =>
                    onChange({
                      prompt_variables: {
                        ...(formData.prompt_variables || {}),
                        [key]: e.target.value,
                      },
                    })
                  }
                  className="flex-1 min-w-[120px] px-2 py-1.5 text-xs border border-gray-300 rounded-md"
                  placeholder="Description (optional)"
                />
                <button
                  type="button"
                  className="text-xs text-red-600 hover:text-red-800"
                  onClick={() => {
                    const vars = { ...(formData.prompt_variables || {}) }
                    delete vars[key]
                    onChange({ prompt_variables: vars })
                  }}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
